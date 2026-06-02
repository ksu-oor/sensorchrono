"""EXP-00 / EXP-01 analyzer: load an XDF and print pass/fail metrics.

Pass criteria (from outputs/lsl_sync_experiment_plan.md, EXP-00 + EXP-01):
  - effective rate within +/- 1% of nominal (256 Hz for ECG)
  - no gaps > 100 ms in LSL timestamps
  - timestamps monotonic
  - tick counter increments at the expected rate (32768 Hz)
  - markers present (session_started, recording_started, recording_stopped)

Also computes diagnostics for EXP-01:
  - inter-sample interval (ISI) stats in LSL time
  - ISI stats in device time
  - cumulative drift: cumulative_samples - nominal_rate * elapsed
  - mapper.offset proxy: per-sample (lsl_t - device_t / 32768)
"""
import sys
import os
import json
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pyxdf


def fmt(x, unit=""):
    if isinstance(x, float):
        return f"{x:.4f}{unit}"
    return f"{x}{unit}"


def load_xdf(path):
    streams, header = pyxdf.load_xdf(str(path), dejitter_timestamps=False)
    return streams, header


def summarize_stream(stream):
    info = stream["info"]
    name = info["name"][0]
    stype = info["type"][0]
    nominal = float(info["nominal_srate"][0])
    n_chans = int(info["channel_count"][0])
    ts = np.asarray(stream["time_stamps"])
    data = np.asarray(stream["time_series"])
    return dict(name=name, type=stype, nominal=nominal, n_chans=n_chans, ts=ts, data=data)


def check_ecg(stream, expected_seconds=300.0, expected_rate=256.0):
    s = summarize_stream(stream)
    ts = s["ts"]
    data = s["data"]

    results = {}
    n = len(ts)
    results["n_samples"] = n
    results["expected_min"] = int(expected_rate * expected_seconds * 0.99)
    results["expected_max"] = int(expected_rate * expected_seconds * 1.01)
    results["sample_count_ok"] = results["expected_min"] <= n <= results["expected_max"]

    if n < 10:
        results["error"] = "too few samples"
        return s, results

    elapsed = ts[-1] - ts[0]
    eff_rate = (n - 1) / elapsed if elapsed > 0 else 0.0
    results["elapsed_s"] = elapsed
    results["effective_rate_hz"] = eff_rate
    results["rate_dev_pct"] = 100.0 * (eff_rate - expected_rate) / expected_rate
    results["rate_ok"] = abs(results["rate_dev_pct"]) < 1.0

    # Monotonicity
    diffs = np.diff(ts)
    results["monotonic"] = bool(np.all(diffs > 0))
    results["isi_mean_ms"] = float(np.mean(diffs) * 1000.0)
    results["isi_std_ms"] = float(np.std(diffs) * 1000.0)
    results["isi_min_ms"] = float(np.min(diffs) * 1000.0)
    results["isi_max_ms"] = float(np.max(diffs) * 1000.0)
    results["isi_p99_ms"] = float(np.percentile(diffs, 99) * 1000.0)
    results["max_gap_ms"] = results["isi_max_ms"]
    results["gap_ok"] = results["max_gap_ms"] < 100.0
    results["n_gaps_over_50ms"] = int(np.sum(diffs > 0.050))

    # Device-tick channel is data[:, 0] (ts_sec column from the bridge)
    if data.ndim == 2 and data.shape[1] >= 1:
        dev_t = data[:, 0]
        # Unwrap any 24-bit ticks->seconds wrap (each wrap = 512 s)
        WRAP = (1 << 24) / 32768.0  # 512 s
        unwrapped = dev_t.copy()
        for i in range(1, len(unwrapped)):
            if unwrapped[i] < unwrapped[i - 1] - WRAP / 2:
                unwrapped[i:] += WRAP
        dev_diffs = np.diff(unwrapped)
        results["dev_isi_mean_ms"] = float(np.mean(dev_diffs) * 1000.0)
        results["dev_isi_std_ms"] = float(np.std(dev_diffs) * 1000.0)
        results["dev_isi_max_ms"] = float(np.max(dev_diffs) * 1000.0)
        results["n_dev_wraps"] = int(round((unwrapped[-1] - dev_t[-1]) / WRAP))

        # Per-sample offset = lsl_t - device_t (relative to first)
        offset = ts - unwrapped
        offset_rel = offset - offset[0]
        results["offset_drift_ms_total"] = float(offset_rel[-1] * 1000.0)
        results["offset_drift_ppm"] = (
            float(1e6 * offset_rel[-1] / elapsed) if elapsed > 0 else 0.0
        )
        results["offset_std_ms"] = float(np.std(offset_rel) * 1000.0)

    return s, results


def check_markers(stream):
    s = summarize_stream(stream)
    msgs = [str(x[0]) if hasattr(x, "__len__") else str(x) for x in s["data"]]
    events = []
    for m in msgs:
        try:
            events.append(json.loads(m).get("event", m))
        except Exception:
            events.append(m)
    required = {"session_started", "recording_armed", "recording_started", "recording_stopped"}
    present = required & set(events)
    return s, {
        "n_markers": len(events),
        "events": events,
        "required_present": sorted(present),
        "required_missing": sorted(required - present),
        "ok": required.issubset(set(events)),
    }


def plot_diagnostics(ecg_summary, ecg_results, outdir):
    ts = ecg_summary["ts"]
    data = ecg_summary["data"]
    rel = ts - ts[0]
    diffs = np.diff(ts) * 1000.0  # ms

    fig, axes = plt.subplots(3, 1, figsize=(12, 9))

    # 1. Inter-sample interval over time
    axes[0].plot(rel[1:], diffs, ",", alpha=0.5)
    axes[0].axhline(1000.0 / ecg_summary["nominal"], color="r", linestyle="--", label="nominal")
    axes[0].set_ylabel("ISI (ms)")
    axes[0].set_title(f"{ecg_summary['name']} inter-sample interval (LSL time)")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    # 2. ISI histogram (log scale)
    axes[1].hist(diffs, bins=200)
    axes[1].set_yscale("log")
    axes[1].set_xlabel("ISI (ms)")
    axes[1].set_ylabel("count (log)")
    axes[1].set_title("ISI histogram")
    axes[1].grid(True, alpha=0.3)

    # 3. Offset drift vs time (lsl_t - device_t, relative)
    if data.ndim == 2 and data.shape[1] >= 1:
        dev_t = data[:, 0]
        WRAP = (1 << 24) / 32768.0
        unwrapped = dev_t.copy()
        for i in range(1, len(unwrapped)):
            if unwrapped[i] < unwrapped[i - 1] - WRAP / 2:
                unwrapped[i:] += WRAP
        offset_rel = (ts - unwrapped) - (ts[0] - unwrapped[0])
        axes[2].plot(rel, offset_rel * 1000.0, linewidth=0.5)
        axes[2].set_xlabel("time (s)")
        axes[2].set_ylabel("LSL - device offset (ms, relative)")
        axes[2].set_title(
            f"clock-mapper residual; total drift = {ecg_results.get('offset_drift_ms_total', 0):.2f} ms "
            f"({ecg_results.get('offset_drift_ppm', 0):.1f} ppm)"
        )
        axes[2].grid(True, alpha=0.3)

    fig.tight_layout()
    path = Path(outdir) / "exp00_diagnostics.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def report(xdf_path, outdir=None):
    xdf_path = Path(xdf_path)
    outdir = Path(outdir) if outdir else xdf_path.parent
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"Loading {xdf_path}")
    streams, _ = load_xdf(xdf_path)
    print(f"Found {len(streams)} streams:")
    for s in streams:
        info = s["info"]
        print(f"  - {info['name'][0]} ({info['type'][0]}, "
              f"{info['channel_count'][0]} ch, nominal {info['nominal_srate'][0]} Hz, "
              f"{len(s['time_stamps'])} samples)")

    ecg_stream = next((s for s in streams if s["info"]["name"][0] == "ShimmerECG"), None)
    marker_stream = next((s for s in streams if s["info"]["name"][0] == "ShimmerMarkers"), None)

    if ecg_stream is None:
        print("FAIL: ShimmerECG stream not found in XDF.")
        return 1

    ecg_summary, ecg_results = check_ecg(ecg_stream)
    print("\n=== ShimmerECG diagnostics ===")
    for k, v in ecg_results.items():
        if not isinstance(v, (list, dict)):
            print(f"  {k:30s} {fmt(v)}")

    marker_results = {"ok": False}
    if marker_stream is not None:
        _, marker_results = check_markers(marker_stream)
        print("\n=== ShimmerMarkers ===")
        print(f"  n_markers          {marker_results['n_markers']}")
        print(f"  events             {marker_results['events']}")
        print(f"  required_missing   {marker_results['required_missing']}")
    else:
        print("\nWARN: ShimmerMarkers stream missing.")

    plot_path = plot_diagnostics(ecg_summary, ecg_results, outdir)
    print(f"\nDiagnostic plot: {plot_path}")

    # PASS / FAIL summary
    checks = {
        "sample count within +/- 1%": ecg_results.get("sample_count_ok", False),
        "effective rate within +/- 1%": ecg_results.get("rate_ok", False),
        "timestamps monotonic": ecg_results.get("monotonic", False),
        "no gaps > 100 ms": ecg_results.get("gap_ok", False),
        "markers present": marker_results.get("ok", False),
    }
    print("\n=== EXP-00 PASS / FAIL ===")
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    all_ok = all(checks.values())
    print(f"\n>>> EXP-00 OVERALL: {'PASS' if all_ok else 'FAIL'} <<<")
    return 0 if all_ok else 2


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python exp00_analyze.py <path/to/recording.xdf> [outdir]")
        sys.exit(1)
    xdf = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    sys.exit(report(xdf, out))
