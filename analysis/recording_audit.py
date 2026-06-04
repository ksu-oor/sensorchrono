"""Per-recording quality audit. One command, one report.

Runs the full per-recording quality check and produces a single
human-readable + JSON report covering:

  - Stream completeness (which expected streams are in the XDF, at what rates)
  - Stream continuity (gaps, packet loss)
  - Shimmer crystal drift fit + verdict
  - In-situ lag calibration (audio, video, ECG-BT-min)
  - Overall recording PASS / WARN / FAIL

CLI
---
    python -m analysis.recording_audit path/to/recording.xdf
    python -m analysis.recording_audit path/to/recording.xdf --out-dir AUDIT/
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Sequence

import numpy as np
import pyxdf

from analysis.shimmer_clock_model import fit_from_xdf, ClockModel
from analysis.insitu_lag_calibration import calibrate_xdf, LagCalibration


# Expected streams for a "fully instrumented" calibrated recording.
# Streams marked optional are nice-to-have; missing them downgrades but
# does not fail the audit.
EXPECTED_STREAMS = {
    "ShimmerECG":              {"type": "ECG",         "nominal_sr": 256, "required": True},
    "ShimmerMarkers":          {"type": "Markers",     "nominal_sr": 0,   "required": False},
    "ShimmerDiagnostics_ECG":  {"type": "Diagnostics", "nominal_sr": 1,   "required": True},
    "Audio":                   {"type": "Audio",       "nominal_sr": 48000, "required": True},
    "VideoFrames":             {"type": "Video",       "nominal_sr": 30,  "required": True},
    "KeyboardFiducial":        {"type": "Markers",     "nominal_sr": 0,   "required": True},
}


@dataclass
class StreamStatus:
    name: str
    present: bool
    n_samples: int
    duration_s: float
    effective_rate: float
    nominal_rate: float
    rate_deviation_pct: float
    max_gap_ms: float
    required: bool

    def issues(self) -> list[str]:
        out = []
        if not self.present:
            if self.required:
                out.append(f"MISSING (required)")
            else:
                out.append("missing (optional)")
            return out
        if self.nominal_rate > 0:
            if abs(self.rate_deviation_pct) > 1.0:
                out.append(f"effective rate {self.effective_rate:.2f} vs nominal "
                           f"{self.nominal_rate} ({self.rate_deviation_pct:+.2f}%)")
            if self.max_gap_ms > 500.0:
                out.append(f"max gap {self.max_gap_ms:.0f} ms")
        return out


@dataclass
class AuditReport:
    xdf_path: str
    duration_s: float
    streams: list           # list[StreamStatus]
    clock_model: dict       # ClockModel.to_dict() or {"error": "..."}
    lag_calibration: dict   # LagCalibration.to_dict() or {"error": "..."}
    overall_verdict: str    # PASS / WARN / FAIL
    summary_issues: list    # list[str]

    def to_dict(self) -> dict:
        return {
            "xdf_path": self.xdf_path,
            "duration_s": self.duration_s,
            "streams": [asdict(s) for s in self.streams],
            "clock_model": self.clock_model,
            "lag_calibration": self.lag_calibration,
            "overall_verdict": self.overall_verdict,
            "summary_issues": self.summary_issues,
        }


def _stream_status(streams_by_name: dict, name: str, spec: dict) -> StreamStatus:
    if name not in streams_by_name:
        return StreamStatus(
            name=name, present=False, n_samples=0, duration_s=0.0,
            effective_rate=0.0, nominal_rate=spec["nominal_sr"],
            rate_deviation_pct=0.0, max_gap_ms=0.0, required=spec["required"],
        )
    s = streams_by_name[name]
    ts = np.asarray(s["time_stamps"])
    n = len(ts)
    if n < 2:
        return StreamStatus(
            name=name, present=True, n_samples=n, duration_s=0.0,
            effective_rate=0.0, nominal_rate=spec["nominal_sr"],
            rate_deviation_pct=0.0, max_gap_ms=0.0, required=spec["required"],
        )
    duration = float(ts[-1] - ts[0])
    eff_rate = n / duration if duration > 0 else 0.0
    nom = spec["nominal_sr"]
    dev_pct = 100 * (eff_rate - nom) / nom if nom > 0 else 0.0
    gaps_ms = np.diff(ts) * 1000.0
    return StreamStatus(
        name=name, present=True, n_samples=n, duration_s=duration,
        effective_rate=float(eff_rate), nominal_rate=float(nom),
        rate_deviation_pct=float(dev_pct),
        max_gap_ms=float(gaps_ms.max()),
        required=spec["required"],
    )


def audit(xdf_path: Path) -> AuditReport:
    streams, _ = pyxdf.load_xdf(str(xdf_path))
    by_name = {s["info"]["name"][0]: s for s in streams}

    # Per-stream status
    statuses = [_stream_status(by_name, n, spec) for n, spec in EXPECTED_STREAMS.items()]

    # Recording duration = max(end) - min(start) over present streams
    all_starts, all_ends = [], []
    for s in by_name.values():
        ts = np.asarray(s["time_stamps"])
        if len(ts) > 0:
            all_starts.append(ts[0]); all_ends.append(ts[-1])
    duration = float(max(all_ends) - min(all_starts)) if all_starts else 0.0

    # Clock model
    try:
        cm = fit_from_xdf(xdf_path)
        cm_dict = cm.to_dict()
    except Exception as exc:
        cm_dict = {"error": str(exc)}

    # Lag calibration
    try:
        cal = calibrate_xdf(xdf_path)
        cal_dict = cal.to_dict()
    except Exception as exc:
        cal_dict = {"error": str(exc)}

    # Roll up issues
    issues = []
    for ss in statuses:
        for i in ss.issues():
            issues.append(f"[{ss.name}] {i}")
    if isinstance(cm_dict, dict) and cm_dict.get("verdict") in ("WARN", "ANOMALY", "FAIL"):
        v = cm_dict.get("verdict")
        issues.append(f"[clock_model] verdict {v}")
        for a in cm_dict.get("anomalies", ()):
            issues.append(f"[clock_model] anomaly: {a}")
    if "error" in cm_dict:
        issues.append(f"[clock_model] could not fit: {cm_dict['error']}")
    if isinstance(cal_dict, dict) and cal_dict.get("verdict") not in ("PASS", "unknown", None):
        issues.append(f"[lag_calibration] verdict {cal_dict.get('verdict')}")
    if "error" in cal_dict:
        issues.append(f"[lag_calibration] could not compute: {cal_dict['error']}")

    # Overall verdict
    has_missing_required = any(
        (not ss.present and ss.required) for ss in statuses
    )
    has_clock_fail = isinstance(cm_dict, dict) and cm_dict.get("verdict") == "FAIL"
    has_clock_anomaly = isinstance(cm_dict, dict) and cm_dict.get("verdict") == "ANOMALY"
    has_drift_warn = isinstance(cm_dict, dict) and cm_dict.get("verdict") == "WARN"
    has_stream_warn = any(
        ss.present and ss.nominal_rate > 0 and abs(ss.rate_deviation_pct) > 5.0
        for ss in statuses
    )
    if has_missing_required or has_clock_fail:
        verdict = "FAIL"
    elif has_clock_anomaly or has_drift_warn or has_stream_warn:
        verdict = "WARN"
    else:
        verdict = "PASS"

    return AuditReport(
        xdf_path=str(xdf_path.resolve()),
        duration_s=duration,
        streams=statuses,
        clock_model=cm_dict,
        lag_calibration=cal_dict,
        overall_verdict=verdict,
        summary_issues=issues,
    )


def _print_human(report: AuditReport) -> None:
    print(f"Recording audit")
    print(f"  xdf:      {report.xdf_path}")
    print(f"  duration: {report.duration_s:.1f} s")
    print()
    print(f"  Streams:")
    print(f"    {'name':<28} {'present':>8} {'n':>10} {'eff Hz':>10} {'dev%':>7} {'max gap':>10}")
    for ss in report.streams:
        present = "YES" if ss.present else ("NO!" if ss.required else "no")
        print(f"    {ss.name:<28} {present:>8} {ss.n_samples:>10d} "
              f"{ss.effective_rate:>10.2f} {ss.rate_deviation_pct:>+7.2f} "
              f"{ss.max_gap_ms:>10.1f} ms")
    print()
    cm = report.clock_model
    print(f"  Clock model:")
    if "error" in cm:
        print(f"    ERROR: {cm['error']}")
    else:
        print(f"    drift     : {cm['b_ppm']:+.3f} ppm   "
              f"(residual {cm['residual_std_ms']:.2f} ms)")
        print(f"    verdict   : {cm['verdict']}")
        for a in cm.get("anomalies", []):
            print(f"      ! {a}")
    print()
    cal = report.lag_calibration
    print(f"  Lag calibration:")
    if "error" in cal:
        print(f"    ERROR: {cal['error']}")
    else:
        for k in ("audio", "video"):
            m = cal.get(k)
            if m:
                print(f"    {k:6s}   : median {m['median_ms']:+.2f} ms  "
                      f"95%CI [{m['ci95_low_ms']:+.2f}, {m['ci95_high_ms']:+.2f}]  "
                      f"n={m['n_events']}  detect {100*m['detection_rate']:.0f}%")
            else:
                print(f"    {k:6s}   : -- (not measurable)")
        if cal.get("shimmer_ecg_min_bt_lag_ms") is not None:
            print(f"    shimmer ecg: BT min one-way ~{cal['shimmer_ecg_min_bt_lag_ms']:+.2f} ms "
                  f"({cal.get('shimmer_ecg_note','')})")
    print()
    print(f"  Overall verdict: {report.overall_verdict}")
    if report.summary_issues:
        print(f"  Issues:")
        for i in report.summary_issues:
            print(f"    - {i}")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Per-recording quality audit.")
    ap.add_argument("xdf", type=Path)
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="If set, write {xdf.stem}_audit.json and .md into this dir.")
    ap.add_argument("--json", action="store_true",
                    help="Print JSON instead of human format.")
    args = ap.parse_args(argv)
    if not args.xdf.exists():
        print(f"ERROR: {args.xdf} not found", file=sys.stderr)
        return 2
    report = audit(args.xdf)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_human(report)
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        base = args.xdf.stem
        (args.out_dir / f"{base}_audit.json").write_text(
            json.dumps(report.to_dict(), indent=2)
        )
        # Markdown rendering
        import io
        buf = io.StringIO()
        import contextlib
        with contextlib.redirect_stdout(buf):
            _print_human(report)
        (args.out_dir / f"{base}_audit.md").write_text("```\n" + buf.getvalue() + "\n```\n")
        print(f"\nwrote {args.out_dir}/{base}_audit.{{json,md}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
