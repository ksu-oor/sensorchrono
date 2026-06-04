"""EXP-03c quicklook.

Goal: with only ShimmerECG in the XDF (Audio + AudioPulseSchedule were not
ticked in LabRecorder), demonstrate that the red+green-on-driver electrode
placement couples to the audio pulses by looking for ~34 burst events at
~10 s intervals on the three signal channels.

Outputs (LSL_data/EXP03c_quicklook/):
  ecg_raw.png      - raw + high-pass filtered traces over the full run
  ecg_burst_zoom.png - zoom around the strongest candidate bursts
  pulse_intervals.csv - detected burst times and inter-burst intervals
"""
from pathlib import Path
import numpy as np
import pyxdf
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt

XDF = r"C:\Users\ngoldbla\Documents\CurrentStudy\sub-P001\ses-S001\eeg\sub-P001_ses-S001_task-Default_run-001_eeg.xdf"
OUT = Path(r"C:\Users\ngoldbla\Desktop\LSL_data\EXP03c_quicklook")
OUT.mkdir(parents=True, exist_ok=True)

streams, _ = pyxdf.load_xdf(XDF)
ecg = next(s for s in streams if s["info"]["name"][0] == "ShimmerECG")
ts = np.asarray(ecg["time_stamps"])
X = np.asarray(ecg["time_series"])  # cols: [device_ts/32768, lead1, lead2, lead2-lead1]
fs = float(ecg["info"]["nominal_srate"][0])
t0 = ts[0]
t = ts - t0
print(f"loaded {len(t)} samples over {t[-1]:.1f}s @ {fs} Hz nominal")

# High-pass at 30 Hz to suppress ECG/EMG biological signals; the 1 kHz audio
# pulse will alias into low frequencies on a 256 Hz channel, but the pulse
# ONSET (driver step) is broadband and should survive any HP cutoff.
def hp(x, fc=30.0, order=4):
    b, a = butter(order, fc / (fs / 2), btype="high")
    return filtfilt(b, a, x)

labels = ["lead1 (LA-RA)", "lead2 (LL-RA)", "lead2-lead1 (LL-LA)"]
sigs_raw = [X[:, 1], X[:, 2], X[:, 3]]
sigs_hp = [hp(s) for s in sigs_raw]

# Raw channel stats (helps diagnose flatline/clipping)
print(f"\n{'channel':<22} {'min':>12} {'max':>12} {'std':>12} {'p95-p5':>12}")
print("-" * 70)
for name, s in zip(labels, sigs_raw):
    print(f"{name:<22} {np.min(s):>12.4g} {np.max(s):>12.4g} {np.std(s):>12.4g} {np.percentile(s,95)-np.percentile(s,5):>12.4g}")

# --- detection ---
# Use HP signal envelope; threshold at ~6 sigma of robust noise; refractory 5s.
def detect_bursts(s, refractory_s=5.0, k_sigma=4.0):
    env = np.abs(s)
    # robust sigma via MAD
    mad = np.median(np.abs(env - np.median(env))) + 1e-12
    sigma = 1.4826 * mad
    thr = k_sigma * sigma
    refr = int(refractory_s * fs)
    above = np.where(env > thr)[0]
    if above.size == 0:
        return np.array([], dtype=int), thr
    peaks = []
    last = -refr
    for i in above:
        if i - last < refr:
            # update if higher
            if env[i] > env[peaks[-1]]:
                peaks[-1] = i
            continue
        peaks.append(i)
        last = i
    return np.asarray(peaks, dtype=int), thr

print(f"\n{'channel':<22} {'thr':>10} {'n_bursts':>9} {'median ISI':>12} {'ISI std':>10}")
print("-" * 70)
best_ch = None
best_peaks = None
best_score = -1
for name, s_hp in zip(labels, sigs_hp):
    peaks, thr = detect_bursts(s_hp)
    if len(peaks) >= 2:
        isis = np.diff(t[peaks])
        med = float(np.median(isis))
        std = float(np.std(isis))
    else:
        med = std = float("nan")
    print(f"{name:<22} {thr:>10.4g} {len(peaks):>9d} {med:>12.3f} {std:>10.3f}")
    # score: peaks closest to 34 and ISI std small
    score = -abs(len(peaks) - 34) - (std if not np.isnan(std) else 100)
    if score > best_score:
        best_score = score; best_ch = name; best_peaks = peaks; best_sig = s_hp

# --- overview plot ---
fig, axes = plt.subplots(3, 1, figsize=(14, 8), sharex=True)
for ax, name, raw, hp_s in zip(axes, labels, sigs_raw, sigs_hp):
    ax.plot(t, raw - np.median(raw), lw=0.4, alpha=0.5, label="raw (dc-removed)")
    ax.plot(t, hp_s, lw=0.4, label="HP > 30 Hz", color="tab:red")
    pk, _ = detect_bursts(hp_s)
    ax.plot(t[pk], hp_s[pk], "kx", ms=8, label=f"detected ({len(pk)})")
    ax.set_ylabel(name, fontsize=9)
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.3)
# Overlay expected schedule (pulses at ~1.0, 11.0, 21.0 ... since pulse bridge fires first at +1s)
# But the bridge started at some unknown offset relative to LabRecorder Start; we just draw a grid.
for i in range(35):
    for ax in axes:
        ax.axvline(i * 10.0 + 1.0, color="gray", ls=":", lw=0.5, alpha=0.4)
axes[-1].set_xlabel("time since recording start (s)")
fig.suptitle(f"EXP-03c quicklook — ECG raw + HP, best channel: {best_ch}")
fig.tight_layout()
fig.savefig(OUT / "ecg_raw.png", dpi=130)
print(f"\nsaved {OUT/'ecg_raw.png'}")

# --- zoom plot around best channel ---
if best_peaks is not None and len(best_peaks) >= 1:
    fig2, axes2 = plt.subplots(1, min(6, len(best_peaks)), figsize=(16, 3), sharey=True)
    if len(best_peaks) == 1:
        axes2 = [axes2]
    for ax, idx in zip(axes2, best_peaks[:6]):
        w = int(0.3 * fs)  # +- 300 ms
        a = max(0, idx - w); b = min(len(t), idx + w)
        ax.plot(t[a:b] - t[idx], best_sig[a:b], lw=0.6)
        ax.axvline(0, color="r", lw=0.5)
        ax.set_title(f"t={t[idx]:.2f}s", fontsize=9)
        ax.grid(alpha=0.3)
    fig2.suptitle(f"EXP-03c zoom on first 6 detected bursts ({best_ch})")
    fig2.tight_layout()
    fig2.savefig(OUT / "ecg_burst_zoom.png", dpi=130)
    print(f"saved {OUT/'ecg_burst_zoom.png'}")

# --- intervals CSV ---
if best_peaks is not None and len(best_peaks) >= 2:
    import csv
    with open(OUT / "pulse_intervals.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["idx", "t_since_start_s", "isi_s_from_prev"])
        for i, p in enumerate(best_peaks):
            isi = "" if i == 0 else f"{t[best_peaks[i]] - t[best_peaks[i-1]]:.4f}"
            w.writerow([i, f"{t[p]:.4f}", isi])
    print(f"saved {OUT/'pulse_intervals.csv'}")

# --- verdict ---
print(f"\nBest channel: {best_ch}")
print(f"Detected bursts: {len(best_peaks) if best_peaks is not None else 0} (expected ~34)")
if best_peaks is not None and len(best_peaks) >= 5:
    isis = np.diff(t[best_peaks])
    print(f"ISI median {np.median(isis):.3f}s (expected 10.0s)  std {np.std(isis):.4f}s")
    if abs(np.median(isis) - 10.0) < 0.5 and np.std(isis) < 0.1:
        print("VERDICT: COUPLING DETECTED — electrode placement works.")
    elif len(best_peaks) >= 10:
        print("VERDICT: PARTIAL — many candidates but not the right cadence. Inspect plot.")
    else:
        print("VERDICT: WEAK / UNCLEAR. Inspect plot.")
else:
    print("VERDICT: NO COUPLING DETECTED on any channel.")
