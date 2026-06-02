"""EXP-03 analyzer v2 — matched filtering on audio.

Uses cross-correlation of the audio with the known pulse waveform.
Much more selective than envelope detection; rejects typing/clicks.

Also fixes per-sample LSL timestamp reconstruction in the audio stream.
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


def make_pulse_template(freq=PULSE_FREQ_HZ, dur_ms=PULSE_DUR_MS, fs=AUDIO_FS):
    n = int(fs * dur_ms / 1000.0)
    t = np.arange(n) / fs
    sig = np.sin(2 * np.pi * freq * t).astype(np.float32)
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
    """Reconstruct per-sample LSL timestamps for a chunked audio stream.

    The Audio LSL stream gets one timestamp per chunk (block of N samples).
    pyxdf returns time_stamps with one entry per chunk; time_series has one
    row per sample. We expand the per-chunk timestamps using the nominal
    sample rate and the chunk boundaries.
    """
    ts = np.asarray(stream["time_stamps"])
    data = np.asarray(stream["time_series"]).flatten()
    fs = float(stream["info"]["nominal_srate"][0])
    n_samples = len(data)
    n_chunks = len(ts)
    if n_chunks == n_samples:
        return ts, data  # already per-sample
    # Block size = total samples / chunks
    block = n_samples // n_chunks
    per_sample = np.empty(n_samples)
    for i, t in enumerate(ts):
        # Each chunk's timestamp is the time of the LAST sample (we pushed it as such)
        # so the samples within the chunk are at t - (block-1-j)/fs for j in 0..block-1
        start = i * block
        end = start + block
        if end > n_samples:
            end = n_samples
        for j, k in enumerate(range(start, end)):
            per_sample[k] = t - ((block - 1) - j) / fs
    # any tail
    if end < n_samples:
        per_sample[end:] = ts[-1] + np.arange(1, n_samples - end + 1) / fs
    return per_sample, data


def matched_filter_pulses(audio, fs, template, n_expected,
                          min_gap_s=5.0, fraction_of_max=0.3):
    """Cross-correlate audio with the pulse template; peaks above threshold
    are pulse onsets.

    Returns array of sample indices where pulses begin.
    """
    # Bandpass audio to clean band around pulse freq
    sos = butter(4, [500, 2000], btype="band", fs=fs, output="sos")
    audio_bp = sosfiltfilt(sos, audio)
    # Normalize template
    tmpl = template - np.mean(template)
    tmpl = tmpl / (np.linalg.norm(tmpl) + 1e-9)
    # Compute normalized cross-correlation by sliding dot product
    # (simple and accurate enough for our purposes)
    corr = correlate(audio_bp, tmpl, mode="valid")
    # corr[i] is the correlation when template starts at sample i
    # Find peaks
    threshold = fraction_of_max * np.max(np.abs(corr))
    above = np.abs(corr) > threshold
    # Group consecutive above-threshold runs into single peaks
    onsets = []
    in_peak = False
    peak_start = 0
    peak_val = 0
    peak_idx = 0
    min_gap_samples = int(min_gap_s * fs)
    for i in range(len(above)):
        if above[i]:
            if not in_peak:
                in_peak = True
                peak_start = i
                peak_val = abs(corr[i])
                peak_idx = i
            elif abs(corr[i]) > peak_val:
                peak_val = abs(corr[i])
                peak_idx = i
        else:
            if in_peak:
                in_peak = False
                if not onsets or peak_idx - onsets[-1] > min_gap_samples:
                    onsets.append(peak_idx)
    if in_peak and (not onsets or peak_idx - onsets[-1] > min_gap_samples):
        onsets.append(peak_idx)
    return np.array(onsets), corr


def accel_onsets(ts, z_g, threshold_sd=5.0, refractory_s=2.0, hp_hz=20.0):
    fs = 1.0 / np.median(np.diff(ts))
    sos = butter(4, hp_hz, btype="high", fs=fs, output="sos")
    hp = sosfiltfilt(sos, z_g)
    env = np.abs(hp)
    base = np.median(env)
    mad = np.median(np.abs(env - base))
    thresh = base + threshold_sd * mad * 1.4826
    above = env > thresh
    edges = np.where(np.diff(above.astype(int)) == 1)[0] + 1
    if len(edges) == 0:
        return np.array([]), env, thresh
    keep = [edges[0]]
    refrac = int(refractory_s * fs)
    for o in edges[1:]:
        if o - keep[-1] > refrac:
            keep.append(o)
    return ts[np.array(keep)], env, thresh


def match(reference, detected, tolerance_s):
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


def report(xdf_path, outdir, t_window=None):
    xdf_path = Path(xdf_path)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"Loading {xdf_path}")
    streams, _ = pyxdf.load_xdf(str(xdf_path), dejitter_timestamps=False)
    pulse_s = find_stream(streams, "AudioPulseSchedule")
    accel_s = find_stream(streams, "ShimmerAccel")
    audio_s = find_stream(streams, "Audio")
    if not (pulse_s and accel_s and audio_s):
        print("Missing required streams.")
        return 1

    pulse_ts = np.asarray(pulse_s["time_stamps"])
    print(f"Scheduled pulses: {len(pulse_ts)}, mean interval "
          f"{np.mean(np.diff(pulse_ts)):.3f}s std {np.std(np.diff(pulse_ts))*1000:.2f}ms")

    audio_ts, audio_data = per_sample_timestamps(audio_s)
    print(f"Audio: {len(audio_data)} samples, span "
          f"{audio_ts[0]:.2f} to {audio_ts[-1]:.2f} ({audio_ts[-1]-audio_ts[0]:.1f}s)")

    # Optional restrict to early window where coupling was good
    if t_window is not None:
        t_lo = audio_ts[0] + t_window[0]
        t_hi = audio_ts[0] + t_window[1]
        mask = (audio_ts >= t_lo) & (audio_ts <= t_hi)
        audio_ts = audio_ts[mask]
        audio_data = audio_data[mask]
        print(f"Restricted audio to window {t_window}: {len(audio_data)} samples")

    template = make_pulse_template()
    print(f"Matched-filtering with {len(template)}-sample template...")
    onsets_idx, corr = matched_filter_pulses(audio_data, AUDIO_FS, template,
                                             n_expected=len(pulse_ts),
                                             fraction_of_max=0.3, min_gap_s=5.0)
    audio_onset_t = audio_ts[onsets_idx]
    print(f"Matched-filter pulse onsets in audio: {len(audio_onset_t)}")

    matched_audio = match(pulse_ts, audio_onset_t, tolerance_s=2.0)
    if matched_audio:
        d_aud = np.array([d for _, _, d in matched_audio]) * 1000
        print(f"Audio onsets matched to schedule:")
        print(f"  n: {len(matched_audio)} / {len(pulse_ts)} scheduled pulses")
        print(f"  delta (ms): mean={np.mean(d_aud):.2f}, std={np.std(d_aud):.2f}, "
              f"median={np.median(d_aud):.2f}")
        print(f"  -> WASAPI playback latency ~ {np.median(d_aud):.0f} ms")
        true_fiducial_t = np.array([t for _, t, _ in matched_audio])
    else:
        true_fiducial_t = np.array([])

    accel_ts = np.asarray(accel_s["time_stamps"])
    accel_data = np.asarray(accel_s["time_series"])
    az = accel_data[:, 3]
    accel_onset_t, env, thresh = accel_onsets(accel_ts, az, threshold_sd=6.0,
                                              refractory_s=3.0, hp_hz=10.0)
    print(f"Accel vibration onsets: {len(accel_onset_t)}")

    if len(true_fiducial_t) > 0:
        matched_accel = match(true_fiducial_t, accel_onset_t, tolerance_s=0.3)
        if matched_accel:
            d_acc = np.array([d for _, _, d in matched_accel]) * 1000
            print(f"\nAccel matched to audio-detected fiducial:")
            print(f"  n: {len(matched_accel)}")
            print(f"  delta (ms): mean={np.mean(d_acc):.2f}, std={np.std(d_acc):.2f}, "
                  f"median={np.median(d_acc):.2f}, max={np.max(np.abs(d_acc)):.2f}")
            print(f"\n>>> CALIBRATION: lag_ms.ShimmerAccel = "
                  f"{np.median(d_acc):.2f} ms  (vs audio onset, n={len(matched_accel)})")

    # Plot
    fig, axes = plt.subplots(3, 1, figsize=(12, 9))
    t0 = audio_ts[0]
    # Decimate audio for plotting
    decim = max(1, len(audio_data) // 8000)
    axes[0].plot(audio_ts[::decim] - t0, audio_data[::decim], linewidth=0.4, color="C0")
    for pt in pulse_ts - t0:
        axes[0].axvline(pt, color="green", linestyle=":", linewidth=0.6, alpha=0.7)
    for at in audio_onset_t - t0:
        axes[0].axvline(at, color="red", linestyle="-", linewidth=0.6, alpha=0.7)
    axes[0].set_ylabel("audio")
    axes[0].set_title(f"audio (green dotted={len(pulse_ts)} scheduled, "
                      f"red={len(audio_onset_t)} matched-filter detections)")
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(accel_ts - t0, az, linewidth=0.5)
    for at in accel_onset_t - t0:
        axes[1].axvline(at, color="orange", linewidth=0.6, alpha=0.7)
    axes[1].set_ylabel("accel z (g)")
    axes[1].set_title("Shimmer accel z-axis (orange=onsets)")
    axes[1].grid(True, alpha=0.3)

    if len(true_fiducial_t) > 0 and matched_audio and 'd_acc' in dir():
        axes[2].hist(d_acc, bins=20)
        axes[2].axvline(0, color="red", linestyle="--")
        axes[2].set_xlabel("delta (ms): accel onset - audio onset")
        axes[2].set_title(f"calibration: median={np.median(d_acc):.2f} ms, "
                          f"std={np.std(d_acc):.2f} ms")
        axes[2].grid(True, alpha=0.3)

    fig.tight_layout()
    plot_path = outdir / "exp03_v2_diagnostics.png"
    fig.savefig(plot_path, dpi=120)
    plt.close(fig)
    print(f"\nPlot: {plot_path}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python exp03_analyze_v2.py <path/to/xdf> [outdir] [t_lo t_hi]")
        sys.exit(1)
    outdir = sys.argv[2] if len(sys.argv) > 2 else None
    t_window = None
    if len(sys.argv) >= 5:
        t_window = (float(sys.argv[3]), float(sys.argv[4]))
    sys.exit(report(sys.argv[1], outdir or Path(sys.argv[1]).parent, t_window))
