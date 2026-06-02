"""EXP-03 analyzer: audio pulses + Shimmer accel + audio capture.

For each scheduled audio pulse:
  - Find the pulse onset in the audio capture (rising-edge envelope detector)
  - Find the corresponding vibration onset in the Shimmer accel (z-axis high-pass)
  - Compute per-modality lag relative to the SCHEDULE marker (for sanity)
  - Compute per-modality lag relative to the AUDIO-DETECTED onset (the true fiducial time)

Outputs:
  - Distribution stats per modality
  - Calibration constants suitable for profiles/*.yaml
  - Plot
"""
import sys
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import butter, sosfiltfilt
import pyxdf


def find_stream(streams, name):
    for s in streams:
        if s["info"]["name"][0] == name:
            return s
    return None


def audio_envelope_onsets(audio_ts, audio_samples, fs, expected_n,
                          bandpass=(2000, 8000), threshold_sd=4.0,
                          refractory_s=0.5):
    """Detect short pulse onsets in audio.

    Returns array of timestamps (LSL clock) where pulses start.
    """
    # Bandpass to 2-8 kHz (our pulse is 4 kHz)
    sos = butter(4, bandpass, btype="band", fs=fs, output="sos")
    filt = sosfiltfilt(sos, audio_samples)
    env = np.abs(filt)
    # Smooth with a 2 ms moving average
    win = max(1, int(0.002 * fs))
    env_smooth = np.convolve(env, np.ones(win) / win, mode="same")
    # Threshold
    base = np.median(env_smooth)
    mad = np.median(np.abs(env_smooth - base))
    thresh = base + threshold_sd * mad * 1.4826
    # Detect rising edges
    above = env_smooth > thresh
    onsets = np.where(np.diff(above.astype(int)) == 1)[0] + 1
    # Apply refractory
    if len(onsets) == 0:
        return np.array([])
    keep = [onsets[0]]
    refrac_samp = int(refractory_s * fs)
    for o in onsets[1:]:
        if o - keep[-1] > refrac_samp:
            keep.append(o)
    onsets = np.array(keep)
    # Convert sample indices to LSL timestamps (audio_ts has one per sample if
    # we treat it as cumulative; but with chunk-based streaming, audio_ts
    # has one entry per push_chunk timestamp. We use linear interpolation.)
    if len(audio_ts) >= 2:
        # Assume audio samples are evenly spaced between audio_ts entries
        sample_idx = np.arange(len(audio_samples))
        # Build a per-sample timestamp by linearly interpolating audio_ts
        # over the sample indices
        block_size = len(audio_samples) // len(audio_ts) or 1
        block_centers = np.arange(len(audio_ts)) * block_size + block_size / 2
        per_sample_ts = np.interp(sample_idx, block_centers, audio_ts)
    else:
        per_sample_ts = np.zeros(len(audio_samples))
    onset_times = per_sample_ts[onsets]
    return onset_times


def accel_onsets(ts, z_g, threshold_sd=5.0, refractory_s=0.5, hp_hz=20.0):
    """Detect impulse onsets in accelerometer z-axis (vibrations)."""
    fs = 1.0 / np.median(np.diff(ts))
    sos = butter(4, hp_hz, btype="high", fs=fs, output="sos")
    hp = sosfiltfilt(sos, z_g)
    env = np.abs(hp)
    base = np.median(env)
    mad = np.median(np.abs(env - base))
    thresh = base + threshold_sd * mad * 1.4826
    above = env > thresh
    onsets = np.where(np.diff(above.astype(int)) == 1)[0] + 1
    if len(onsets) == 0:
        return np.array([])
    keep = [onsets[0]]
    refrac = int(refractory_s * fs)
    for o in onsets[1:]:
        if o - keep[-1] > refrac:
            keep.append(o)
    return ts[np.array(keep)]


def match(reference, detected, tolerance_s=0.5):
    """For each reference time, find the nearest detected time within tolerance."""
    matches = []
    for r in reference:
        idx = np.searchsorted(detected, r)
        cands = []
        if idx > 0: cands.append((idx - 1, detected[idx - 1]))
        if idx < len(detected): cands.append((idx, detected[idx]))
        if not cands: continue
        best_i, best_t = min(cands, key=lambda x: abs(x[1] - r))
        if abs(best_t - r) <= tolerance_s:
            matches.append((r, best_t, best_t - r))
    return matches


def report(xdf_path, outdir):
    xdf_path = Path(xdf_path)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"Loading {xdf_path}")
    streams, _ = pyxdf.load_xdf(str(xdf_path), dejitter_timestamps=False)
    print(f"Streams: {len(streams)}")
    for s in streams:
        info = s["info"]
        print(f"  - {info['name'][0]:30s} {info['type'][0]:12s} "
              f"{info['channel_count'][0]}ch  {len(s['time_stamps'])} samples")

    pulse_s = find_stream(streams, "AudioPulseSchedule")
    accel_s = find_stream(streams, "ShimmerAccel")
    audio_s = find_stream(streams, "Audio")

    checks = {}
    checks["AudioPulseSchedule present"] = pulse_s is not None
    checks["ShimmerAccel present"] = accel_s is not None
    checks["Audio present"] = audio_s is not None

    if not all(checks.values()):
        for k, v in checks.items():
            print(f"  [{'PASS' if v else 'FAIL'}] {k}")
        print("Cannot proceed without all three streams.")
        return 2

    # Schedule markers (when player asked for pulse to play)
    pulse_ts = np.asarray(pulse_s["time_stamps"])
    pulse_events = [json.loads(x[0]) for x in pulse_s["time_series"]]
    print(f"\n=== Scheduled pulses: {len(pulse_ts)} ===")
    if len(pulse_ts) >= 2:
        intervals = np.diff(pulse_ts)
        print(f"  interval mean: {np.mean(intervals):.3f} s  std: {np.std(intervals)*1000:.1f} ms")

    # Audio capture
    audio_ts = np.asarray(audio_s["time_stamps"])
    audio_data = np.asarray(audio_s["time_series"]).flatten()
    audio_fs = float(audio_s["info"]["nominal_srate"][0])
    print(f"\n=== Audio: {len(audio_data)} samples at {audio_fs} Hz ===")
    audio_onset_times = audio_envelope_onsets(audio_ts, audio_data, audio_fs,
                                              expected_n=len(pulse_ts))
    print(f"  detected pulse onsets in audio: {len(audio_onset_times)}")
    checks["Audio onset count within +/- 20% of scheduled"] = (
        0.8 * len(pulse_ts) <= len(audio_onset_times) <= 1.2 * len(pulse_ts)
    )

    # Match audio onsets to schedule
    matched_audio = match(pulse_ts, audio_onset_times, tolerance_s=0.5)
    if matched_audio:
        deltas_audio = np.array([d for _, _, d in matched_audio]) * 1000
        print(f"\n=== Audio onset vs schedule ===")
        print(f"  n matched: {len(matched_audio)}")
        print(f"  delta (ms): mean={np.mean(deltas_audio):.2f}, "
              f"std={np.std(deltas_audio):.2f}, max={np.max(np.abs(deltas_audio)):.2f}")
        print(f"  -> WASAPI playback latency = mean delta")
        # The audio onset IS the fiducial time for downstream comparisons
        true_fiducial_times = np.array([t for _, t, _ in matched_audio])
    else:
        print("FAIL: no audio onsets matched to schedule.")
        true_fiducial_times = np.array([])

    # Accel
    accel_ts = np.asarray(accel_s["time_stamps"])
    accel_data = np.asarray(accel_s["time_series"])
    # data: [ts_sec, ax, ay, az]
    az = accel_data[:, 3]
    accel_onset_times = accel_onsets(accel_ts, az, threshold_sd=5.0, refractory_s=0.5)
    print(f"\n=== Shimmer accel: {len(accel_data)} samples ===")
    print(f"  detected vibration onsets in accel z-axis: {len(accel_onset_times)}")

    # Match accel to TRUE fiducial (audio onset)
    if len(true_fiducial_times) > 0:
        matched_accel = match(true_fiducial_times, accel_onset_times, tolerance_s=0.3)
        if matched_accel:
            deltas_accel = np.array([d for _, _, d in matched_accel]) * 1000
            print(f"\n=== Accel onset vs audio-detected fiducial ===")
            print(f"  n matched: {len(matched_accel)}")
            print(f"  delta (ms): mean={np.mean(deltas_accel):.2f}, "
                  f"std={np.std(deltas_accel):.2f}, "
                  f"median={np.median(deltas_accel):.2f}, "
                  f"max={np.max(np.abs(deltas_accel)):.2f}")
            print(f"\n>>> CALIBRATION CONSTANT: lag_ms.ShimmerAccel = "
                  f"{np.median(deltas_accel):.2f} ms (n={len(matched_accel)})")
            checks["Accel detection >= 50% of pulses"] = (
                len(matched_accel) >= 0.5 * len(true_fiducial_times)
            )
            checks["Accel-to-audio delta std < 10 ms"] = (
                np.std(deltas_accel) < 10.0
            )
        else:
            print("WARN: no accel onsets matched within tolerance.")
            print("      Likely the earbud was not in firm enough contact with the Shimmer case.")

    # Plot
    fig, axes = plt.subplots(3, 1, figsize=(12, 9))
    t0 = pulse_ts[0]

    # 1) Audio waveform + detected onsets + schedule marks
    audio_sec = (audio_ts.repeat(len(audio_data)//len(audio_ts) or 1)[:len(audio_data)] - t0)
    # Resample audio for plotting (decimate to ~5000 points)
    decim = max(1, len(audio_data) // 5000)
    axes[0].plot(np.arange(0, len(audio_data), decim)/audio_fs, audio_data[::decim],
                 linewidth=0.3, alpha=0.6, color="C0")
    for pt in pulse_ts - t0:
        axes[0].axvline(pt, color="green", linestyle=":", linewidth=0.8, alpha=0.5)
    for at in audio_onset_times - t0:
        axes[0].axvline(at, color="red", linestyle="-", linewidth=0.5, alpha=0.5)
    axes[0].set_ylabel("audio")
    axes[0].set_title("audio (green dotted=scheduled, red=detected onset)")
    axes[0].grid(True, alpha=0.3)

    # 2) Accel z-axis
    axes[1].plot(accel_ts - t0, az, linewidth=0.5)
    for at in accel_onset_times - t0:
        axes[1].axvline(at, color="orange", linestyle="-", linewidth=0.5, alpha=0.7)
    axes[1].set_ylabel("accel z (g)")
    axes[1].set_title("Shimmer accel z-axis (orange=detected vibration onset)")
    axes[1].grid(True, alpha=0.3)

    # 3) Delta histogram (accel - audio_onset)
    if len(true_fiducial_times) > 0 and matched_accel:
        deltas = np.array([d for _, _, d in matched_accel]) * 1000
        axes[2].hist(deltas, bins=30)
        axes[2].axvline(0, color="red", linestyle="--")
        axes[2].set_xlabel("delta (ms): accel onset - audio onset")
        axes[2].set_title(f"calibration: median={np.median(deltas):.2f} ms, "
                          f"std={np.std(deltas):.2f} ms")
        axes[2].grid(True, alpha=0.3)

    fig.tight_layout()
    plot_path = outdir / "exp03_diagnostics.png"
    fig.savefig(plot_path, dpi=120)
    plt.close(fig)
    print(f"\nPlot: {plot_path}")

    print("\n=== EXP-03 PASS / FAIL ===")
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    all_ok = all(checks.values())
    print(f"\n>>> EXP-03 OVERALL: {'PASS' if all_ok else 'FAIL'} <<<")
    return 0 if all_ok else 2


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python exp03_analyze.py <path/to/xdf> [outdir]")
        sys.exit(1)
    sys.exit(report(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else Path(sys.argv[1]).parent))
