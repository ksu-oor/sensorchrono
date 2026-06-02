"""EXP-03 v3 — schedule-aware matched filtering.

Strategy: for each scheduled pulse time T_schedule, search the audio in a
narrow window [T_schedule - 50ms, T_schedule + 250ms] for the matched-filter
peak. The peak location relative to T_schedule gives the WASAPI playback
latency. The peak's absolute time is the TRUE fiducial time (when the pulse
arrived at the mic).

This eliminates 99% of false positives by exploiting the schedule prior.

For the accel: same approach. Around each TRUE fiducial time, search the
accel z-axis for a peak in a [TRUE - 50ms, TRUE + 250ms] window.
"""
import sys
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import butter, sosfiltfilt, correlate
import pyxdf

PULSE_FREQ_HZ = 1000.0
PULSE_DUR_MS = 20.0
AUDIO_FS = 48000.0
ACCEL_FS = 256.0
SEARCH_WINDOW_S = (-0.05, 0.30)  # search 50ms before to 300ms after schedule
ACCEL_SEARCH_S = (-0.05, 0.30)


def make_template(fs=AUDIO_FS):
    n = int(fs * PULSE_DUR_MS / 1000.0)
    t = np.arange(n) / fs
    sig = np.sin(2 * np.pi * PULSE_FREQ_HZ * t).astype(np.float32)
    fade_n = max(1, int(fs * 0.2 / 1000.0))
    if fade_n * 2 < n:
        w = 0.5 * (1 - np.cos(np.pi * np.arange(fade_n) / fade_n))
        sig[:fade_n] *= w
        sig[-fade_n:] *= w[::-1]
    return sig


def find_stream(streams, name):
    for s in streams:
        if s["info"]["name"][0] == name:
            return s
    return None


def per_sample_timestamps(stream):
    ts = np.asarray(stream["time_stamps"])
    data = np.asarray(stream["time_series"]).flatten()
    fs = float(stream["info"]["nominal_srate"][0])
    n_samples = len(data)
    n_chunks = len(ts)
    block = max(1, n_samples // n_chunks)
    per_sample = np.empty(n_samples)
    for i, t in enumerate(ts):
        start = i * block
        end = min(start + block, n_samples)
        for j, k in enumerate(range(start, end)):
            per_sample[k] = t - ((block - 1) - j) / fs
    if end < n_samples:
        per_sample[end:] = ts[-1] + np.arange(1, n_samples - end + 1) / fs
    return per_sample, data


def find_pulse_in_window(audio_ts, audio, fs, template, t_center, window_s,
                         min_snr=2.0):
    """Find the matched-filter peak in a window around t_center.
    Returns (peak_time, peak_amplitude, snr) or (None, None, None) if no peak above threshold.
    """
    i_lo = np.searchsorted(audio_ts, t_center + window_s[0])
    i_hi = np.searchsorted(audio_ts, t_center + window_s[1])
    if i_hi - i_lo < len(template):
        return None, None, None
    seg = audio[i_lo:i_hi]
    seg_ts = audio_ts[i_lo:i_hi]
    # Bandpass
    sos = butter(4, [500, 2000], btype="band", fs=fs, output="sos")
    seg_bp = sosfiltfilt(sos, seg)
    # Template (zero-mean, unit-norm)
    tmpl = template - np.mean(template)
    tmpl = tmpl / (np.linalg.norm(tmpl) + 1e-9)
    corr = correlate(seg_bp, tmpl, mode="valid")
    # Find absolute peak
    peak_idx = np.argmax(np.abs(corr))
    peak_val = abs(corr[peak_idx])
    # SNR = peak / median of |corr| outside the peak region
    mask = np.ones_like(corr, dtype=bool)
    mask[max(0, peak_idx - int(0.05 * fs)):peak_idx + int(0.05 * fs) + 1] = False
    if mask.sum() > 10:
        noise = np.median(np.abs(corr[mask]))
    else:
        noise = np.median(np.abs(corr))
    snr = peak_val / (noise + 1e-12)
    if snr < min_snr:
        return None, peak_val, snr
    # Peak location in original ts: peak_idx is the start of the template match
    if peak_idx < len(seg_ts):
        return seg_ts[peak_idx], peak_val, snr
    return None, peak_val, snr


def find_accel_in_window(accel_ts, az, t_center, window_s, hp_hz=10.0,
                         min_snr=3.0):
    """Find the accel impulse peak in a window around t_center."""
    i_lo = np.searchsorted(accel_ts, t_center + window_s[0])
    i_hi = np.searchsorted(accel_ts, t_center + window_s[1])
    if i_hi - i_lo < 10:
        return None, None, None
    seg = az[i_lo:i_hi]
    seg_ts = accel_ts[i_lo:i_hi]
    # High-pass
    fs = 1.0 / np.median(np.diff(accel_ts))
    sos = butter(4, hp_hz, btype="high", fs=fs, output="sos")
    seg_hp = sosfiltfilt(sos, seg)
    env = np.abs(seg_hp)
    peak_idx = np.argmax(env)
    peak_val = env[peak_idx]
    # SNR
    mask = np.ones_like(env, dtype=bool)
    mask[max(0, peak_idx - 5):peak_idx + 5 + 1] = False
    noise = np.median(env[mask]) if mask.sum() > 5 else np.median(env)
    snr = peak_val / (noise + 1e-12)
    if snr < min_snr:
        return None, peak_val, snr
    return seg_ts[peak_idx], peak_val, snr


def report(xdf_path, outdir):
    xdf_path = Path(xdf_path)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"Loading {xdf_path}")
    streams, _ = pyxdf.load_xdf(str(xdf_path), dejitter_timestamps=False)
    pulse_s = find_stream(streams, "AudioPulseSchedule")
    accel_s = find_stream(streams, "ShimmerAccel")
    audio_s = find_stream(streams, "Audio")

    pulse_ts = np.asarray(pulse_s["time_stamps"])
    print(f"Scheduled pulses: {len(pulse_ts)}")

    audio_ts, audio = per_sample_timestamps(audio_s)
    print(f"Audio span: {audio_ts[-1] - audio_ts[0]:.1f}s, {len(audio)} samples")
    template = make_template()

    accel_ts = np.asarray(accel_s["time_stamps"])
    az = np.asarray(accel_s["time_series"])[:, 3]
    print(f"Accel span: {accel_ts[-1] - accel_ts[0]:.1f}s, {len(az)} samples")

    rows = []
    for i, pt in enumerate(pulse_ts):
        a_t, a_v, a_snr = find_pulse_in_window(audio_ts, audio, AUDIO_FS, template,
                                               pt, SEARCH_WINDOW_S, min_snr=2.0)
        ac_t, ac_v, ac_snr = (None, None, None)
        if a_t is not None:
            ac_t, ac_v, ac_snr = find_accel_in_window(accel_ts, az, a_t,
                                                     ACCEL_SEARCH_S, min_snr=2.5)
        a_d = (a_t - pt) * 1000 if a_t is not None else None
        ac_d = (ac_t - a_t) * 1000 if ac_t is not None else None
        rows.append((pt, a_t, a_d, a_snr, ac_t, ac_d, ac_snr))
    print()
    print(f"{'#':>3s} {'sched':>8s} {'a_d_ms':>10s} {'a_snr':>7s} {'ac_d_ms':>10s} {'ac_snr':>7s}")
    audio_deltas = []
    accel_deltas = []
    for i, (pt, a_t, a_d, a_snr, ac_t, ac_d, ac_snr) in enumerate(rows, 1):
        ad = f"{a_d:10.2f}" if a_d is not None else f"{'-':>10s}"
        asnr = f"{a_snr:7.1f}" if a_snr is not None else f"{'-':>7s}"
        acd = f"{ac_d:10.2f}" if ac_d is not None else f"{'-':>10s}"
        acsnr = f"{ac_snr:7.1f}" if ac_snr is not None else f"{'-':>7s}"
        print(f"{i:3d} {pt - pulse_ts[0]:8.2f} {ad} {asnr} {acd} {acsnr}")
        if a_d is not None:
            audio_deltas.append(a_d)
        if ac_d is not None:
            accel_deltas.append(ac_d)

    print(f"\nAudio onsets detected: {len(audio_deltas)} / {len(pulse_ts)}")
    if audio_deltas:
        ad = np.array(audio_deltas)
        print(f"  audio_delta (ms vs schedule): "
              f"median={np.median(ad):.2f}, std={np.std(ad):.2f}, "
              f"min={np.min(ad):.2f}, max={np.max(ad):.2f}")
        print(f"  -> WASAPI playback latency = {np.median(ad):.1f} +/- {np.std(ad):.1f} ms")

    print(f"\nAccel onsets detected (only on pulses with audio detected): {len(accel_deltas)}")
    if accel_deltas:
        acd = np.array(accel_deltas)
        print(f"  accel_delta (ms vs audio fiducial): "
              f"median={np.median(acd):.2f}, std={np.std(acd):.2f}, "
              f"min={np.min(acd):.2f}, max={np.max(acd):.2f}")
        print(f"\n>>> CALIBRATION CONSTANT: lag_ms.ShimmerAccel = "
              f"{np.median(acd):.2f} ms (n={len(accel_deltas)})")

    # Plot
    fig, axes = plt.subplots(3, 1, figsize=(12, 9))
    t0 = pulse_ts[0]

    # Audio waveform + schedule lines + detected
    decim = max(1, len(audio) // 8000)
    axes[0].plot(audio_ts[::decim] - t0, audio[::decim], linewidth=0.4)
    for pt in pulse_ts:
        axes[0].axvline(pt - t0, color="green", linestyle=":", linewidth=0.5, alpha=0.5)
    for pt, a_t, *_ in rows:
        if a_t is not None:
            axes[0].axvline(a_t - t0, color="red", linewidth=0.5, alpha=0.8)
    axes[0].set_ylabel("audio")
    axes[0].set_title(f"audio (green=schedule, red={len(audio_deltas)} matched)")
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(accel_ts - t0, az, linewidth=0.5)
    for pt, a_t, _, _, ac_t, *_ in rows:
        if ac_t is not None:
            axes[1].axvline(ac_t - t0, color="orange", linewidth=0.5, alpha=0.8)
    axes[1].set_ylabel("accel z (g)")
    axes[1].set_title(f"accel (orange={len(accel_deltas)} detected near audio fiducials)")
    axes[1].grid(True, alpha=0.3)

    if audio_deltas:
        axes[2].hist(audio_deltas, bins=20, alpha=0.5, label="audio - schedule (WASAPI lag)")
    if accel_deltas:
        axes[2].hist(accel_deltas, bins=20, alpha=0.5, label="accel - audio (Shimmer lag)")
    axes[2].axvline(0, color="red", linestyle="--")
    axes[2].set_xlabel("delta (ms)")
    axes[2].legend()
    axes[2].set_title("delta distributions")
    axes[2].grid(True, alpha=0.3)

    fig.tight_layout()
    plot_path = outdir / "exp03_v3_diagnostics.png"
    fig.savefig(plot_path, dpi=120)
    plt.close(fig)
    print(f"\nPlot: {plot_path}")
    return 0 if accel_deltas else 2


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python exp03_analyze_v3.py <path/to/xdf> [outdir]")
        sys.exit(1)
    sys.exit(report(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else Path(sys.argv[1]).parent))
