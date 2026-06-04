"""Reanalyze the quicktest data with the right sample-rate handling.

Loads the .npz from the previous quicktest, uses device-tick-based sample rate
instead of perf_counter (which had BT-burst variance). Plots RAW accel too,
not just HP-filtered.
"""
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import butter, sosfiltfilt
from pathlib import Path


def main():
    npz_path = Path(r"C:\Users\ngoldbla\Desktop\LSL_data\quicktest\quicktest.npz")
    d = np.load(npz_path)
    accel_t = d["accel_t"]       # perf_counter timestamps per packet arrival
    az = d["az"]                 # raw accel z in g (nominal scale)
    audio = d["audio"]
    audio_t = d["audio_t"]
    schedule = d["schedule"]

    print(f"loaded {len(az)} accel samples over {accel_t[-1]-accel_t[0]:.1f}s")
    print(f"audio: {len(audio)} samples over {audio_t[-1]-audio_t[0]:.1f}s")
    print(f"schedule: {len(schedule)} pulses at {schedule[0]:.2f}..{schedule[-1]:.2f}")

    # Re-derive sample rate from ACCEL COUNT (samples/elapsed_time)
    # because perf_counter deltas are BT-burst-dominated
    fs_effective = len(az) / (accel_t[-1] - accel_t[0])
    print(f"effective accel fs (samples/elapsed): {fs_effective:.2f} Hz")

    # Replace accel_t with a regular grid at effective fs starting at accel_t[0]
    # (this is what device-tick dejittering would give us)
    accel_t_regular = accel_t[0] + np.arange(len(az)) / fs_effective

    # Look at raw, then mean-subtracted, then HP-filtered (with correct fs)
    az_mean_removed = az - np.mean(az)
    sos_hp20 = butter(4, 20.0, btype="high", fs=fs_effective, output="sos")
    az_hp20 = sosfiltfilt(sos_hp20, az_mean_removed)
    sos_hp5 = butter(4, 5.0, btype="high", fs=fs_effective, output="sos")
    az_hp5 = sosfiltfilt(sos_hp5, az_mean_removed)
    sos_bp = butter(4, [50.0, 120.0], btype="band", fs=fs_effective, output="sos")
    az_bp = sosfiltfilt(sos_bp, az_mean_removed)

    print(f"\nAccel signal stats (mg):")
    print(f"  raw range:    {np.min(az)*1000:.2f} .. {np.max(az)*1000:.2f}")
    print(f"  raw std:      {np.std(az)*1000:.3f}")
    print(f"  after mean removal: range {np.min(az_mean_removed)*1000:.2f} .. {np.max(az_mean_removed)*1000:.2f}")
    print(f"  HP 20 Hz std: {np.std(az_hp20)*1000:.3f}")
    print(f"  HP 5 Hz std:  {np.std(az_hp5)*1000:.3f}")
    print(f"  BP 50-120 Hz std (200 Hz pulse band): {np.std(az_bp)*1000:.3f}")

    # In the 200 Hz pulse band, look for peaks within +/-150 ms of each schedule
    print(f"\nLooking for pulses in BP 50-120 Hz signal:")
    deltas, snrs = [], []
    for k, st in enumerate(schedule, 1):
        i_lo = np.searchsorted(accel_t_regular, st - 0.05)
        i_hi = np.searchsorted(accel_t_regular, st + 0.30)
        if i_hi - i_lo < 5: continue
        seg = az_bp[i_lo:i_hi]
        seg_ts = accel_t_regular[i_lo:i_hi]
        peak_i = np.argmax(np.abs(seg))
        peak_val = abs(seg[peak_i])
        mask = np.ones_like(seg, dtype=bool); mask[max(0, peak_i-3):peak_i+4] = False
        noise = np.median(np.abs(seg[mask])) if mask.sum() > 5 else np.median(np.abs(seg))
        snr = peak_val / (noise + 1e-12)
        deltas.append((seg_ts[peak_i] - st) * 1000)
        snrs.append(snr)
        print(f"  pulse #{k:2d}: peak={peak_val*1000:7.3f} mg  noise={noise*1000:7.3f} mg  SNR={snr:5.2f}  delta={deltas[-1]:7.2f} ms")

    # Plot all 4 variants of the accel signal
    fig, axes = plt.subplots(5, 1, figsize=(13, 14))

    # 1. RAW accel
    axes[0].plot(accel_t_regular, az * 1000, linewidth=0.4)
    for st in schedule:
        axes[0].axvline(st, color="green", linestyle=":", alpha=0.6)
    axes[0].set_ylabel("raw (mg)")
    axes[0].set_title("Shimmer accel z RAW (linear drift = real DC bias, not signal)")
    axes[0].grid(True, alpha=0.3)

    # 2. mean-removed
    axes[1].plot(accel_t_regular, az_mean_removed * 1000, linewidth=0.4)
    for st in schedule:
        axes[1].axvline(st, color="green", linestyle=":", alpha=0.6)
    axes[1].set_ylabel("mean-removed (mg)")
    axes[1].set_title("after mean removal")
    axes[1].grid(True, alpha=0.3)

    # 3. HP 20 Hz
    axes[2].plot(accel_t_regular, az_hp20 * 1000, linewidth=0.4)
    for st in schedule:
        axes[2].axvline(st, color="green", linestyle=":", alpha=0.6)
    axes[2].set_ylabel("HP 20 Hz (mg)")
    axes[2].set_title("HP 20 Hz - should remove drift completely")
    axes[2].grid(True, alpha=0.3)

    # 4. BP for 200 Hz pulse band
    axes[3].plot(accel_t_regular, az_bp * 1000, linewidth=0.4)
    for st in schedule:
        axes[3].axvline(st, color="green", linestyle=":", alpha=0.6)
    axes[3].set_ylabel("BP 50-120 Hz (mg)")
    axes[3].set_title("BP 50-120 Hz - this is where 200 Hz pulse energy should appear")
    axes[3].grid(True, alpha=0.3)

    # 5. Audio for reference
    decim = max(1, len(audio) // 8000)
    axes[4].plot(audio_t[::decim], audio[::decim], linewidth=0.4)
    for st in schedule:
        axes[4].axvline(st, color="green", linestyle=":", alpha=0.6)
    axes[4].set_ylabel("audio")
    axes[4].set_xlabel("time (s)")
    axes[4].set_title("audio mic capture (green dotted = pulse schedule)")
    axes[4].grid(True, alpha=0.3)

    fig.tight_layout()
    plot_path = npz_path.parent / "quicktest_v2.png"
    fig.savefig(plot_path, dpi=120)
    plt.close(fig)
    print(f"\nPlot: {plot_path}")


if __name__ == "__main__":
    main()
