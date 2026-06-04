"""EXP-06 quicklook: 5-min dataset (recording stopped early).

Three questions:
  1. Do keystrokes show up as audio clicks in the BRIO mic? (Should — audio
     is loud and unambiguous.)
  2. Do the SAME keystrokes show up as ECG transients via aluminum-chassis
     vibration coupling? Use audio-confirmed keystroke times as the gold
     fiducial since they're tighter than HID timestamps (~0.5 ms vs ~1-2 ms).
  3. What's the keystroke -> audio and keystroke -> ECG latency distribution?
     This is the early read on whether either modality can drift-track over
     an hour.
"""
from pathlib import Path
import numpy as np
import pyxdf
from scipy.signal import butter, filtfilt, hilbert
import matplotlib.pyplot as plt

XDF = r"C:\Users\ngoldbla\Documents\CurrentStudy\sub-P001\ses-S001\eeg\sub-P001_ses-S001_task-Default_run-001_eeg.xdf"
OUT = Path(r"C:\Users\ngoldbla\Desktop\LSL_data\EXP06_quicklook")
OUT.mkdir(parents=True, exist_ok=True)

print(f"loading {XDF}")
streams, _ = pyxdf.load_xdf(XDF)
by = {s['info']['name'][0]: s for s in streams}

# Keyboard press events (ignore releases)
kb = by['KeyboardFiducial']
kb_ts = np.asarray(kb['time_stamps'])
kb_ev = [v[0] for v in kb['time_series']]
press_ts = np.array([t for t, e in zip(kb_ts, kb_ev) if 'press' in e])
print(f"  {len(press_ts)} key presses")

# Audio
audio = by['Audio']
a_ts = np.asarray(audio['time_stamps'])
a_v = np.asarray([v[0] for v in audio['time_series']], dtype=np.float32)
a_fs = float(audio['info']['nominal_srate'][0])
print(f"  audio {len(a_v)} samples @ {a_fs:.0f} Hz, range {a_v.min():.4f}..{a_v.max():.4f}")

# ECG lead2
ecg = by['ShimmerECG']
e_ts = np.asarray(ecg['time_stamps'])
e_v = np.asarray([v[2] for v in ecg['time_series']], dtype=np.float64)  # lead2
e_fs = float(ecg['info']['nominal_srate'][0])
print(f"  ecg lead2 {len(e_v)} samples @ {e_fs:.0f} Hz, std={e_v.std():.2f}")

# --- Audio click detection per keystroke ---
# Bandpass 1-6 kHz where keyclicks have energy; envelope; find peak in
# +- 80 ms window around each press.
def bp(x, lo, hi, fs, order=4):
    b, a = butter(order, [lo/(fs/2), hi/(fs/2)], btype='band')
    return filtfilt(b, a, x)

print("\nfiltering audio (1-6 kHz)...")
a_bp = bp(a_v, 1000, 6000, a_fs)
a_env = np.abs(hilbert(a_bp))

print("scanning per-keystroke audio windows...")
press_audio_dt = []   # audio click time - press time, per keystroke
press_audio_snr = []
for tp in press_ts:
    # window [tp-30ms, tp+150ms]
    mask = (a_ts >= tp - 0.03) & (a_ts <= tp + 0.15)
    if mask.sum() < 100:
        continue
    seg = a_env[mask]
    seg_t = a_ts[mask]
    # baseline = first 20 ms of window
    base_n = int(0.02 * a_fs)
    base = seg[:base_n]
    base_med = float(np.median(base))
    base_mad = float(np.median(np.abs(base - base_med))) + 1e-9
    j = int(np.argmax(seg))
    peak = float(seg[j])
    snr = (peak - base_med) / (1.4826 * base_mad)
    if snr < 6:  # noise floor of detection
        continue
    press_audio_dt.append(seg_t[j] - tp)
    press_audio_snr.append(snr)
press_audio_dt = np.array(press_audio_dt)
press_audio_snr = np.array(press_audio_snr)
print(f"  AUDIO: detected click for {len(press_audio_dt)}/{len(press_ts)} keystrokes "
      f"({100*len(press_audio_dt)/len(press_ts):.0f}%)")
if len(press_audio_dt):
    print(f"  AUDIO delta median {1000*np.median(press_audio_dt):.2f} ms, "
          f"std {1000*np.std(press_audio_dt):.2f} ms, "
          f"median SNR {np.median(press_audio_snr):.1f}")

# --- ECG vibration detection per keystroke ---
# Use audio-confirmed press times as the precise fiducial. Bandpass ECG
# 30-120 Hz to keep impulse energy and drop mains hum + slow drift.
print("\nfiltering ECG lead2 (30-120 Hz)...")
e_bp = bp(e_v, 30, 120, e_fs)

# Compute robust per-keystroke metric: peak |e_bp| in [tp, tp+50ms] vs
# stddev of |e_bp| in [tp-200ms, tp-50ms].
print("scanning per-keystroke ECG windows...")
ecg_metrics = []  # (latency_ms, snr_ratio, peak_value, pre_std)
for tp in press_ts:
    pre_mask = (e_ts >= tp - 0.2) & (e_ts < tp - 0.05)
    post_mask = (e_ts >= tp - 0.01) & (e_ts < tp + 0.05)
    if pre_mask.sum() < 20 or post_mask.sum() < 5:
        continue
    pre = e_bp[pre_mask]
    post = e_bp[post_mask]
    pre_std = float(np.std(pre))
    post_abs = np.abs(post)
    j = int(np.argmax(post_abs))
    peak = float(post[j])
    t_peak = e_ts[post_mask][j]
    snr = abs(peak) / (pre_std + 1e-9)
    ecg_metrics.append((1000*(t_peak - tp), snr, peak, pre_std))
ecg_metrics = np.array(ecg_metrics)
print(f"  total keystrokes analyzed: {len(ecg_metrics)}")
if len(ecg_metrics):
    snrs = ecg_metrics[:, 1]
    print(f"  ECG SNR distribution:")
    for q in [10, 25, 50, 75, 90, 95, 99]:
        print(f"    {q}th percentile: {np.percentile(snrs, q):.2f}")
    above_3 = (snrs > 3.0).sum()
    above_4 = (snrs > 4.0).sum()
    print(f"  SNR > 3.0: {above_3} / {len(ecg_metrics)} ({100*above_3/len(ecg_metrics):.0f}%)")
    print(f"  SNR > 4.0: {above_4} / {len(ecg_metrics)} ({100*above_4/len(ecg_metrics):.0f}%)")
    # latency distribution for the HIT events
    hits = ecg_metrics[snrs > 3.0]
    if len(hits):
        print(f"  Among SNR>3 hits: latency median {np.median(hits[:,0]):.2f} ms, "
              f"std {np.std(hits[:,0]):.2f} ms")

# --- Plots ---
fig, axes = plt.subplots(3, 1, figsize=(14, 9))
# Audio + key markers, first 20 s
t0 = a_ts[0]
mask = (a_ts - t0) < 20
axes[0].plot(a_ts[mask] - t0, a_v[mask], lw=0.3, alpha=0.6)
axes[0].plot(a_ts[mask] - t0, a_env[mask], lw=0.4, color='tab:orange', label='envelope')
for tp in press_ts:
    if tp - t0 < 20:
        axes[0].axvline(tp - t0, color='red', lw=0.5, alpha=0.5)
axes[0].set_title(f"Audio (BRIO mic) + keystroke markers (red), first 20 s")
axes[0].set_ylabel("amplitude")
axes[0].legend(fontsize=8)
axes[0].grid(alpha=0.3)

# ECG bandpassed + key markers, first 20 s
mask = (e_ts - t0) < 20
axes[1].plot(e_ts[mask] - t0, e_bp[mask], lw=0.5)
for tp in press_ts:
    if tp - t0 < 20:
        axes[1].axvline(tp - t0, color='red', lw=0.5, alpha=0.5)
axes[1].set_title(f"ECG lead2 (30-120 Hz BP) + keystroke markers, first 20 s")
axes[1].set_ylabel("counts")
axes[1].grid(alpha=0.3)
axes[1].set_xlabel("time since recording start (s)")

# SNR histogram for ECG events
if len(ecg_metrics):
    axes[2].hist(ecg_metrics[:, 1], bins=40, range=(0, 12), edgecolor='black')
    axes[2].axvline(3.0, color='orange', ls='--', label='3σ')
    axes[2].axvline(4.0, color='red', ls='--', label='4σ')
    axes[2].set_xlabel("ECG impulse SNR (|peak| / pre_std)")
    axes[2].set_ylabel("count")
    axes[2].set_title("Per-keystroke ECG vibration SNR distribution")
    axes[2].legend()
    axes[2].grid(alpha=0.3)

fig.tight_layout()
fig.savefig(OUT / "quicklook.png", dpi=130)
print(f"\nsaved {OUT/'quicklook.png'}")

# --- audio-vs-keyboard drift (5 min slice) ---
if len(press_audio_dt) >= 30:
    # press_ts vs press_audio_dt; fit linear
    t = press_ts[:len(press_audio_dt)] - press_ts[0]
    p = np.polyfit(t, press_audio_dt, 1)
    ppm = p[0] * 1e6
    pred = np.polyval(p, t)
    resid = press_audio_dt - pred
    print(f"\nAudio drift fit over 5 min: {ppm:+.2f} ppm; "
          f"residual std {1000*resid.std():.3f} ms; "
          f"raw std {1000*press_audio_dt.std():.3f} ms")

print("\nDone.")
