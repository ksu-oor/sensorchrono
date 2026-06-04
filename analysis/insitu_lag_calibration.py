"""In-situ absolute-lag calibration from a recorded XDF.

Uses keystrokes as a *triple* multimodal fiducial:
  - Keyboard HID timestamp (system clock, sub-ms precision) is the reference
  - Audio click in mic (typically tens of ms after HID)
  - Nearest video frame timestamp (frame-rate quantized)

For each press event at LSL time t_kb, we find:
  - t_aud  = click peak time in the BRIO mic (band-pass envelope)
  - t_vid  = LSL timestamp of the frame nearest to t_kb
  - delta_aud = t_aud - t_kb
  - delta_vid = t_vid - t_kb

The MEDIAN of these per-event deltas across the recording is the
estimated `lag_ms` for that modality, with confidence intervals via
bootstrap.

Library
-------
    from analysis.insitu_lag_calibration import calibrate_xdf
    cal = calibrate_xdf("recording.xdf")
    # cal.audio_lag_ms, cal.video_lag_ms, ...

CLI
---
    python -m analysis.insitu_lag_calibration recording.xdf
    python -m analysis.insitu_lag_calibration recording.xdf --out-json cal.json

Recording protocol
------------------
Every session that wants in-situ lag calibration MUST include a quiet
calibration block. At the start of the session (or any uncluttered
30-second window during it):

  1. Sit quietly. No talking, no background noise.
  2. Type 10-20 distinct keystrokes spaced ~2 seconds apart.
  3. Each keystroke should be a single firm tap on a key whose click is
     audible (the spacebar is loud and consistent on most keyboards).
  4. Make sure your hands are visible in the camera frame so the strike
     could be detected in video (not strictly required for the current
     analysis, which only uses the frame timestamps).

The bridges needed to capture this are exactly what `launch_calibrated_recording.bat`
opens.

Notes on what this measures
---------------------------
- `audio_lag_ms` includes: acoustic propagation (~3 ms / m), mic ADC,
  USB transport, sounddevice callback latency, and our pylsl timestamp
  in the audio bridge. For a BRIO mic ~30 cm away, typical values are
  ~40-60 ms.
- `video_lag_ms` is half-frame-quantized. For 30 fps it's bounded by
  +/- 16.5 ms, but the *median* is a useful estimate. Typical UVC
  cameras show +30 to +60 ms steady offset (exposure time + USB
  transport).
- For ShimmerECG, this analyzer does NOT attempt to measure lag from
  keystroke fiducials: EXG signal chain rejects mechanical impulses
  (see CHANGELOG EXP-03c/EXP-06). For ECG lag, see the related
  diagnostics-based bound in `recording_audit.py`.
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
from scipy.signal import butter, filtfilt, hilbert


# ---------- data ----------

@dataclass
class ModalityLag:
    median_ms: float
    mean_ms: float
    std_ms: float
    ci95_low_ms: float
    ci95_high_ms: float
    n_events: int
    detection_rate: float    # n_events / n_keystrokes
    notes: str = ""


@dataclass
class LagCalibration:
    n_keystrokes: int
    duration_s: float
    audio: ModalityLag | None
    video: ModalityLag | None
    shimmer_ecg_min_bt_lag_ms: float | None    # lower-bound on ECG lag from diagnostics OWD-min
    shimmer_ecg_note: str = ""
    method: str = "keystroke multimodal fiducial"
    verdict: str = "unknown"

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ---------- helpers ----------

def _bandpass(x: np.ndarray, lo: float, hi: float, fs: float, order: int = 4) -> np.ndarray:
    b, a = butter(order, [lo / (fs / 2), hi / (fs / 2)], btype="band")
    return filtfilt(b, a, x)


def _bootstrap_ci(values: np.ndarray, fn, n_iter: int = 200, ci: tuple = (2.5, 97.5),
                  rng_seed: int = 7) -> tuple[float, float]:
    rng = np.random.default_rng(rng_seed)
    stats = []
    for _ in range(n_iter):
        idx = rng.integers(0, len(values), size=len(values))
        stats.append(fn(values[idx]))
    lo, hi = np.percentile(stats, ci)
    return float(lo), float(hi)


# ---------- modality detectors ----------

def detect_audio_lag(press_ts: np.ndarray,
                     audio_ts: np.ndarray, audio_v: np.ndarray, audio_fs: float,
                     min_snr: float = 10.0,
                     band: tuple = (1000.0, 6000.0),
                     window_pre_s: float = 0.030,
                     window_post_s: float = 0.150) -> ModalityLag | None:
    """For each keystroke, detect the click peak in the mic envelope."""
    if len(press_ts) == 0 or len(audio_ts) == 0:
        return None
    a_bp = _bandpass(audio_v, band[0], band[1], audio_fs)
    a_env = np.abs(hilbert(a_bp))
    deltas = []
    snrs = []
    for tp in press_ts:
        mask = (audio_ts >= tp - window_pre_s) & (audio_ts <= tp + window_post_s)
        if mask.sum() < 100:
            continue
        seg = a_env[mask]
        seg_t = audio_ts[mask]
        # baseline = first 20 ms (assumed quieter than peak window)
        base = seg[:int(0.02 * audio_fs)]
        base_med = float(np.median(base))
        base_mad = float(np.median(np.abs(base - base_med))) + 1e-9
        j = int(np.argmax(seg))
        peak = float(seg[j])
        snr = (peak - base_med) / (1.4826 * base_mad)
        if snr < min_snr:
            continue
        deltas.append(seg_t[j] - tp)
        snrs.append(snr)
    if not deltas:
        return None
    d = np.array(deltas) * 1000.0
    lo, hi = _bootstrap_ci(d, np.median)
    return ModalityLag(
        median_ms=float(np.median(d)),
        mean_ms=float(d.mean()),
        std_ms=float(d.std()),
        ci95_low_ms=lo,
        ci95_high_ms=hi,
        n_events=int(len(d)),
        detection_rate=float(len(d) / len(press_ts)),
        notes=f"band-pass {int(band[0])}-{int(band[1])} Hz, min_snr={min_snr}, "
              f"median click SNR {np.median(snrs):.0f}",
    )


def detect_video_lag(press_ts: np.ndarray,
                     video_ts: np.ndarray) -> ModalityLag | None:
    """For each keystroke, find the time to the nearest video frame."""
    if len(press_ts) == 0 or len(video_ts) == 0:
        return None
    nearest_dt = []
    for tp in press_ts:
        idx = int(np.searchsorted(video_ts, tp))
        candidates = []
        if idx > 0:
            candidates.append(video_ts[idx - 1] - tp)
        if idx < len(video_ts):
            candidates.append(video_ts[idx] - tp)
        if not candidates:
            continue
        j = int(np.argmin([abs(c) for c in candidates]))
        nearest_dt.append(candidates[j])
    if not nearest_dt:
        return None
    d = np.array(nearest_dt) * 1000.0
    lo, hi = _bootstrap_ci(d, np.median)
    return ModalityLag(
        median_ms=float(np.median(d)),
        mean_ms=float(d.mean()),
        std_ms=float(d.std()),
        ci95_low_ms=lo,
        ci95_high_ms=hi,
        n_events=int(len(d)),
        detection_rate=float(len(d) / len(press_ts)),
        notes="nearest-frame timestamp, half-frame quantized (~16.5ms at 30fps)",
    )


def estimate_shimmer_min_bt_lag(diagnostics_stream: dict,
                                ecg_dev_ts: np.ndarray,
                                clock_model_b: float, clock_model_a: float) -> tuple[float, str]:
    """Return a lower-bound estimate on ShimmerECG lag (ms) from BT one-way delay.

    Logic: after applying the clock model to dev_ts, the smallest residual
    between a packet's BT-arrival lsl_time and the model's predicted lsl_time
    gives the floor of the BT transport latency. This is an UNDERESTIMATE
    of ECG lag because it doesn't include the Shimmer's internal ADC and
    filter-chain delay (datasheet says ~few ms).
    """
    d_ts = np.asarray(diagnostics_stream["time_stamps"])
    last_obs = np.asarray([v[1] for v in diagnostics_stream["time_series"]])
    if len(d_ts) < 5:
        return float("nan"), "diagnostics too short"
    # last_observed_s = lsl_time - dev_ts at packet arrival
    # The MIN of that, over the recording (after detrending the linear drift),
    # is the minimum BT one-way delay -> a floor on the ECG lag.
    t_rel = d_ts - d_ts[0]
    dev_at_diag = d_ts - last_obs
    pred_lsl = clock_model_a + clock_model_b * dev_at_diag
    residual_lsl_minus_pred = d_ts - pred_lsl
    # The minimum (residual) is what we want: cleanest packets
    # are closest to zero residual.
    min_resid_ms = float(np.min(residual_lsl_minus_pred) * 1000.0)
    return min_resid_ms, "lower bound only; excludes Shimmer ADC + filter-chain delay"


# ---------- top-level ----------

def calibrate_xdf(xdf_path: str | Path,
                  *,
                  keyboard_stream: str = "KeyboardFiducial",
                  audio_stream: str = "Audio",
                  video_stream: str = "VideoFrames",
                  diagnostics_stream: str = "ShimmerDiagnostics_ECG",
                  ecg_stream: str = "ShimmerECG") -> LagCalibration:
    streams, _ = pyxdf.load_xdf(str(xdf_path))
    by = {s["info"]["name"][0]: s for s in streams}

    if keyboard_stream not in by:
        raise ValueError(
            f"No '{keyboard_stream}' stream in XDF; can't perform in-situ "
            f"lag calibration. Available: {sorted(by)}"
        )
    kb = by[keyboard_stream]
    kb_ts = np.asarray(kb["time_stamps"])
    kb_ev = [v[0] for v in kb["time_series"]]
    press_ts = np.array([t for t, e in zip(kb_ts, kb_ev) if "press" in e])
    if len(press_ts) < 5:
        raise ValueError(
            f"Only {len(press_ts)} keystroke presses in recording; need >= 5 "
            f"to estimate lag. Did the operator do the calibration block?"
        )
    duration_s = float(kb_ts[-1] - kb_ts[0])

    audio_lag = None
    if audio_stream in by:
        audio = by[audio_stream]
        a_ts = np.asarray(audio["time_stamps"])
        a_v = np.asarray([v[0] for v in audio["time_series"]], dtype=np.float32)
        a_fs = float(audio["info"]["nominal_srate"][0])
        audio_lag = detect_audio_lag(press_ts, a_ts, a_v, a_fs)

    video_lag = None
    if video_stream in by:
        v_ts = np.asarray(by[video_stream]["time_stamps"])
        video_lag = detect_video_lag(press_ts, v_ts)

    # ECG lower bound (requires clock model fit + ECG stream)
    ecg_min_lag = None
    ecg_note = ""
    if diagnostics_stream in by and ecg_stream in by:
        try:
            from analysis.shimmer_clock_model import fit_from_diagnostics
            d = by[diagnostics_stream]
            model = fit_from_diagnostics(
                np.asarray(d["time_stamps"]),
                np.asarray([v[1] for v in d["time_series"]]),
                stream_name=diagnostics_stream,
            )
            ecg_min_lag, ecg_note = estimate_shimmer_min_bt_lag(
                d, np.asarray([]), model.b, model.a,
            )
        except Exception as exc:
            ecg_note = f"could not compute: {exc}"

    # Verdict
    verdict = "PASS"
    if not audio_lag or audio_lag.detection_rate < 0.7:
        verdict = "INCOMPLETE"
    if audio_lag and audio_lag.ci95_high_ms - audio_lag.ci95_low_ms > 50.0:
        verdict = "WIDE_CI"

    return LagCalibration(
        n_keystrokes=int(len(press_ts)),
        duration_s=duration_s,
        audio=audio_lag,
        video=video_lag,
        shimmer_ecg_min_bt_lag_ms=ecg_min_lag,
        shimmer_ecg_note=ecg_note,
        verdict=verdict,
    )


# ---------- CLI ----------

def _print_human(cal: LagCalibration) -> None:
    print(f"In-situ lag calibration")
    print(f"  duration_s    : {cal.duration_s:.1f}")
    print(f"  n_keystrokes  : {cal.n_keystrokes}")
    print(f"  verdict       : {cal.verdict}")
    for name, m in [("audio", cal.audio), ("video", cal.video)]:
        if m is None:
            print(f"  {name:10s}: -- (stream missing or no detections)")
            continue
        print(f"  {name:10s}: median {m.median_ms:+.2f} ms  "
              f"95%CI [{m.ci95_low_ms:+.2f}, {m.ci95_high_ms:+.2f}]  "
              f"std {m.std_ms:.2f} ms  n={m.n_events}  "
              f"detect {100*m.detection_rate:.0f}%")
        if m.notes:
            print(f"               {m.notes}")
    if cal.shimmer_ecg_min_bt_lag_ms is not None:
        print(f"  shimmer_ecg: BT min one-way ~{cal.shimmer_ecg_min_bt_lag_ms:+.2f} ms "
              f"({cal.shimmer_ecg_note})")
    else:
        print(f"  shimmer_ecg: not computed ({cal.shimmer_ecg_note})")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="In-situ absolute-lag calibration from XDF")
    ap.add_argument("xdf", type=Path)
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not args.xdf.exists():
        print(f"ERROR: {args.xdf} not found", file=sys.stderr)
        return 2
    try:
        cal = calibrate_xdf(args.xdf)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps({**cal.to_dict(), "xdf": str(args.xdf.resolve())}, indent=2))
    else:
        _print_human(cal)
    if args.out_json:
        args.out_json.write_text(
            json.dumps({**cal.to_dict(), "xdf": str(args.xdf.resolve())}, indent=2)
        )
        print(f"\nwrote {args.out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
