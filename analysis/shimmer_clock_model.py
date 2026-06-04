"""Post-hoc clock disciplining for ShimmerECG recordings.

Library
-------
    from analysis.shimmer_clock_model import fit_from_xdf, apply, ClockModel

    model = fit_from_xdf("path/to/recording.xdf")
    # model.a, model.b, model.b_ppm, model.residual_std_ms, ...
    corrected_lsl_ts = apply(model, ecg_dev_ts)

CLI
---
    python -m analysis.shimmer_clock_model path/to/recording.xdf
    python -m analysis.shimmer_clock_model path/to/recording.xdf --out-json model.json

Method
------
The Shimmer bridge already emits a 1 Hz `ShimmerDiagnostics_ECG` stream
whose channel 1 (`last_observed_s`) is the raw per-packet offset
`lsl_time - dev_ts`. Bluetooth transport jitter makes that signal noisy
(bimodal), but the underlying clock-drift trajectory is a clean linear
function of time. We extract it with One-Way-Delay minimum filtering:

  1. Bin the diagnostic samples into fixed `window_s` (default 10 s) windows.
  2. Per window, keep only the minimum observed offset (lowest-latency
     packet -> cleanest dev_ts -> lsl_time pair).
  3. Theil-Sen line fit on the resulting (dev_ts, lsl_time) bin pairs.

The fitted slope `b` should be close to 1.0; `(b - 1) * 1e6` is the
crystal drift in ppm relative to the LSL clock. Intercept `a` is the
LSL time at `dev_ts = 0`.

Result is a `ClockModel` dataclass; `apply(model, dev_ts) = a + b * dev_ts`
gives drift-corrected LSL timestamps deterministically reproducible from
the diagnostics stream alone, with no external fiducial required.

Validated across three independent runs (EXP-00, EXP-01, EXP-06) where
drift values agreed to within 6 ppm (31.1 / 37.4 / 35.8); see the
CHANGELOG 2026-06-03 entry for the drift-fit validation.
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


# ---------- data ----------

# Plausible-drift envelope for a 32.768 kHz crystal at room temperature.
# Anything outside this is either a different device, a bridge bug, or
# an in-recording state reset.
PLAUSIBLE_PPM_BAND = (-100.0, 100.0)
# Verdict thresholds on the bin-level residual std (ms).
RESIDUAL_PASS_MS = 5.0     # linear model is sufficient
RESIDUAL_WARN_MS = 20.0    # linear OK but non-linear structure present


@dataclass
class ClockModel:
    a: float                 # intercept (LSL seconds)
    b: float                 # slope ~1.0
    b_ppm: float             # (b - 1) * 1e6, the drift in parts per million
    n_bins: int              # number of OWD-min bins used in fit
    n_raw_samples: int       # number of diagnostic samples read
    duration_s: float        # recording duration covered
    residual_std_ms: float   # bin-level residual stddev after fit
    window_s: float          # binning window used
    fit_method: str
    diagnostics_stream: str
    verdict: str = "unknown"      # PASS | WARN | FAIL | ANOMALY
    anomalies: tuple = ()         # tuple[str, ...] of detected issues
    notes: str = ""

    def apply_to(self, dev_ts: np.ndarray) -> np.ndarray:
        """Apply this model to map device timestamps to corrected LSL time."""
        return apply(self, dev_ts)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- core ----------

def _theil_sen(x: np.ndarray, y: np.ndarray, *, rng_seed: int = 0,
               max_pairs: int = 4000) -> tuple[float, float]:
    """Median-of-pairwise-slopes line fit. O(n^2) naive, subsampled if large."""
    n = len(x)
    if n < 2:
        return 0.0, float(y.mean() if n else 0.0)
    if n * (n - 1) // 2 > max_pairs:
        rng = np.random.default_rng(rng_seed)
        idx_a = rng.integers(0, n, size=max_pairs)
        idx_b = rng.integers(0, n, size=max_pairs)
        keep = idx_a != idx_b
        ia, ib = idx_a[keep], idx_b[keep]
        dx = x[ib] - x[ia]
        dy = y[ib] - y[ia]
        nz = dx != 0
        slopes = dy[nz] / dx[nz]
    else:
        slopes = []
        for i in range(n):
            dx = x[i + 1:] - x[i]
            dy = y[i + 1:] - y[i]
            nz = dx != 0
            slopes.append(dy[nz] / dx[nz])
        slopes = np.concatenate(slopes) if slopes else np.array([])
    if slopes.size == 0:
        return 0.0, float(np.median(y))
    slope = float(np.median(slopes))
    intercept = float(np.median(y - slope * x))
    return slope, intercept


def fit_from_diagnostics(
    diag_time_stamps: np.ndarray,
    diag_last_observed_s: np.ndarray,
    *,
    window_s: float = 10.0,
    stream_name: str = "ShimmerDiagnostics_ECG",
) -> ClockModel:
    """Fit a ClockModel from raw diagnostics arrays. Use this if you have
    the stream in memory already and don't want to re-load the XDF."""
    t_lsl = np.asarray(diag_time_stamps, dtype=np.float64)
    obs = np.asarray(diag_last_observed_s, dtype=np.float64)
    if len(t_lsl) < 5:
        raise ValueError(
            f"Diagnostics stream has only {len(t_lsl)} samples; "
            f"need >= 5 for a meaningful fit."
        )

    t_rel = t_lsl - t_lsl[0]
    bin_idx = np.floor(t_rel / window_s).astype(int)
    unique_bins = np.unique(bin_idx)

    t_bin_lsl = np.array([t_lsl[bin_idx == b].mean() for b in unique_bins])
    obs_bin = np.array([obs[bin_idx == b].min() for b in unique_bins])
    # dev_ts at each bin = lsl_time - observed_offset
    dev_ts_bin = t_bin_lsl - obs_bin

    slope, intercept = _theil_sen(dev_ts_bin, t_bin_lsl)
    b_ppm = (slope - 1.0) * 1e6
    pred = intercept + slope * dev_ts_bin
    resid = t_bin_lsl - pred
    residual_std_ms = float(1000.0 * resid.std())

    # ---- anomaly detection ----
    anomalies = []
    # Exactly-zero drift is statistically impossible for a real crystal; it
    # almost always means the bridge reset its diagnostics state mid-
    # recording and `last_observed_s` was held at one constant value.
    if abs(b_ppm) < 1e-6:
        anomalies.append("b_ppm_exact_zero (likely bridge state reset)")
    # Outside the plausible band points to either a different device, a
    # bridge bug, or a bimodal cluster of one-way-delays that the binning
    # didn't separate. Investigate before trusting.
    if not (PLAUSIBLE_PPM_BAND[0] <= b_ppm <= PLAUSIBLE_PPM_BAND[1]):
        anomalies.append(
            f"b_ppm out of plausible band {PLAUSIBLE_PPM_BAND}: got {b_ppm:+.2f}"
        )
    # Very short recordings have too few bins for the slope to be trusted.
    if len(unique_bins) < 5:
        anomalies.append(
            f"only {len(unique_bins)} OWD-min bins; slope SE is large"
        )
    # If the bin-level residual std is way above one BT-frame (~7 ms),
    # the underlying clock signal is non-linear or the recording had
    # major BT congestion / disconnects.
    if residual_std_ms > RESIDUAL_WARN_MS:
        anomalies.append(
            f"residual {residual_std_ms:.1f} ms >> linear-fit floor"
        )

    # ---- verdict ----
    if anomalies:
        verdict = "FAIL" if residual_std_ms > RESIDUAL_WARN_MS else "ANOMALY"
    elif residual_std_ms < RESIDUAL_PASS_MS:
        verdict = "PASS"
    elif residual_std_ms < RESIDUAL_WARN_MS:
        verdict = "WARN"
    else:
        verdict = "FAIL"

    return ClockModel(
        a=float(intercept),
        b=float(slope),
        b_ppm=float(b_ppm),
        n_bins=int(len(unique_bins)),
        n_raw_samples=int(len(t_lsl)),
        duration_s=float(t_rel[-1]),
        residual_std_ms=residual_std_ms,
        window_s=float(window_s),
        fit_method="Theil-Sen on OWD-min binned (lsl_time vs dev_ts)",
        diagnostics_stream=stream_name,
        verdict=verdict,
        anomalies=tuple(anomalies),
        notes=(
            "Positive b_ppm = LSL clock faster than Shimmer crystal. "
            "Apply with: corrected_lsl_ts = a + b * dev_ts. "
            "dev_ts comes from ShimmerECG channel 0 (device_ts/32768)."
        ),
    )


def fit_from_xdf(
    xdf_path: str | Path,
    *,
    window_s: float = 10.0,
    diagnostics_name: str = "ShimmerDiagnostics_ECG",
) -> ClockModel:
    """Load an XDF and fit a ClockModel from its diagnostics stream."""
    streams, _ = pyxdf.load_xdf(str(xdf_path))
    by_name = {s["info"]["name"][0]: s for s in streams}
    if diagnostics_name not in by_name:
        raise ValueError(
            f"Stream '{diagnostics_name}' not present in {xdf_path}. "
            f"Available streams: {sorted(by_name)}"
        )
    diag = by_name[diagnostics_name]
    ts = np.asarray(diag["time_stamps"])
    series = np.asarray(diag["time_series"])
    # ShimmerDiagnostics layout: [offset, last_observed, min_observed, residual_ms, samples]
    last_obs = series[:, 1]
    model = fit_from_diagnostics(
        ts, last_obs, window_s=window_s, stream_name=diagnostics_name
    )
    return model


def apply(model: ClockModel, dev_ts: Sequence[float] | np.ndarray) -> np.ndarray:
    """Map device timestamps to drift-corrected LSL timestamps."""
    return model.a + model.b * np.asarray(dev_ts, dtype=np.float64)


# ---------- CLI ----------

def _print_human(model: ClockModel, xdf: Path) -> None:
    print(f"ShimmerClockModel fit  ({xdf.name})")
    print(f"  duration        : {model.duration_s:7.1f} s")
    print(f"  raw samples     : {model.n_raw_samples}")
    print(f"  OWD-min bins    : {model.n_bins}  (window {model.window_s}s)")
    print(f"  slope b         : {model.b:.12f}")
    print(f"  drift           : {model.b_ppm:+7.3f} ppm")
    print(f"  intercept a     : {model.a:.6f} s")
    print(f"  residual std    : {model.residual_std_ms:.3f} ms (bin-level)")
    print(f"  verdict         : {model.verdict}")
    if model.anomalies:
        print("  anomalies:")
        for a in model.anomalies:
            print(f"    - {a}")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Fit a post-hoc clock model for a Shimmer recording."
    )
    ap.add_argument("xdf", type=Path, help="Path to recorded XDF")
    ap.add_argument("--window-s", type=float, default=10.0,
                    help="OWD-min binning window (default 10 s)")
    ap.add_argument("--stream", default="ShimmerDiagnostics_ECG",
                    help="Diagnostics stream name (default ShimmerDiagnostics_ECG)")
    ap.add_argument("--out-json", type=Path, default=None,
                    help="Optional: write model JSON to this path")
    ap.add_argument("--json", action="store_true",
                    help="Print JSON instead of human format")
    args = ap.parse_args(argv)

    if not args.xdf.exists():
        print(f"ERROR: {args.xdf} not found", file=sys.stderr)
        return 2
    try:
        model = fit_from_xdf(args.xdf, window_s=args.window_s,
                             diagnostics_name=args.stream)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps({**model.to_dict(), "xdf": str(args.xdf.resolve())},
                         indent=2))
    else:
        _print_human(model, args.xdf)

    if args.out_json:
        args.out_json.write_text(
            json.dumps({**model.to_dict(), "xdf": str(args.xdf.resolve())}, indent=2)
        )
        print(f"\nwrote {args.out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
