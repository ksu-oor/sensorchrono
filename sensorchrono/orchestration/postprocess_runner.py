"""Run the analysis post-processing pipeline as an isolated subprocess.

This module is *both* the library wrapper the app calls and the subprocess
entry point it spawns (``python -m sensorchrono.orchestration.postprocess_runner``).
Running it as its own entry — rather than ``python -m analysis.postprocess`` —
lets us pass ``profile_lag_ms`` (the calibration fallback) through, which the
analysis CLI deliberately doesn't expose, **without modifying analysis/**.
Subprocess isolation also means a heavy/old XDF that crashes the pipeline can't
take the GUI down with it.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# repo root: sensorchrono/orchestration/postprocess_runner.py -> parents[2]
REPO_ROOT = Path(__file__).resolve().parents[2]

_EXIT_BY_STATUS = {"ok": 0, "warn": 1, "error": 2}


class PostprocessError(RuntimeError):
    pass


@dataclass
class PostprocessResult:
    """Parsed view of ``pipeline_report.json``."""

    overall_status: str  # ok | warn | error
    audit_verdict: str  # PASS | WARN | FAIL
    stages: list[dict] = field(default_factory=list)
    out_dir: str = ""
    report_json: str | None = None
    report_md: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.overall_status == "ok"

    @property
    def failed(self) -> bool:
        return self.overall_status == "error"

    def stage(self, name: str) -> dict | None:
        return next((s for s in self.stages if s.get("name") == name), None)

    def summary(self) -> str:
        bits = [f"overall={self.overall_status}", f"audit={self.audit_verdict}"]
        for s in self.stages:
            bits.append(f"{s.get('name')}={s.get('status')}")
        return ", ".join(bits)


def build_command(
    xdf: Path | str,
    out_dir: Path | str,
    *,
    mp4: Path | str | None = None,
    profile_lag_ms: dict | None = None,
    skip_parquet: bool = False,
    python: str = sys.executable,
) -> list[str]:
    """Construct the subprocess argv (pure — unit-testable)."""
    argv = [python, "-m", "sensorchrono.orchestration.postprocess_runner",
            "--xdf", str(xdf), "--out-dir", str(out_dir)]
    if mp4 is not None:
        argv += ["--mp4", str(mp4)]
    if profile_lag_ms:
        argv += ["--profile-lag-json", json.dumps(profile_lag_ms)]
    if skip_parquet:
        argv += ["--skip-parquet"]
    return argv


def parse_report(out_dir: Path | str) -> PostprocessResult:
    """Read ``pipeline_report.json`` from ``out_dir`` into a result object."""
    out_dir = Path(out_dir)
    jpath = out_dir / "pipeline_report.json"
    if not jpath.exists():
        raise PostprocessError(f"no pipeline_report.json in {out_dir}")
    data = json.loads(jpath.read_text(encoding="utf-8"))
    md = out_dir / "pipeline_report.md"
    return PostprocessResult(
        overall_status=data.get("overall_status", "error"),
        audit_verdict=data.get("audit_verdict", ""),
        stages=data.get("stages", []),
        out_dir=data.get("out_dir", str(out_dir)),
        report_json=str(jpath),
        report_md=str(md) if md.exists() else None,
        raw=data,
    )


def run_postprocess(
    xdf: Path | str,
    out_dir: Path | str,
    *,
    mp4: Path | str | None = None,
    profile_lag_ms: dict | None = None,
    skip_parquet: bool = False,
    python: str = sys.executable,
    timeout_s: float = 900.0,
) -> PostprocessResult:
    """Spawn the pipeline, wait, and parse its report. Raises
    :class:`PostprocessError` if it produced no report."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    argv = build_command(xdf, out_dir, mp4=mp4, profile_lag_ms=profile_lag_ms,
                         skip_parquet=skip_parquet, python=python)
    proc = subprocess.run(
        argv, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout_s,
    )
    report_path = out_dir / "pipeline_report.json"
    if not report_path.exists():
        tail = (proc.stderr or proc.stdout or "")[-800:]
        raise PostprocessError(
            f"post-processing produced no report (rc={proc.returncode}):\n{tail}"
        )
    return parse_report(out_dir)


# ---------- subprocess entry ----------
def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="sensorchrono postprocess subprocess entry")
    ap.add_argument("--xdf", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--mp4", type=Path, default=None)
    ap.add_argument("--profile-lag-json", default=None,
                    help="JSON dict of canonical-stream -> fallback lag ms")
    ap.add_argument("--skip-parquet", action="store_true")
    args = ap.parse_args(argv)

    if not args.xdf.exists():
        print(f"ERROR: {args.xdf} not found", file=sys.stderr)
        return 2

    # Heavy deps (pyxdf/scipy) imported here so the library wrapper stays light.
    from analysis.postprocess import run

    profile_lag = json.loads(args.profile_lag_json) if args.profile_lag_json else None
    report = run(
        args.xdf, mp4_path=args.mp4, out_dir=args.out_dir,
        profile_lag_ms=profile_lag, skip_parquet=args.skip_parquet,
    )
    return _EXIT_BY_STATUS.get(report.overall_status, 2)


if __name__ == "__main__":
    raise SystemExit(_main())
