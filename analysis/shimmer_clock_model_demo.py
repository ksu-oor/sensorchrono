"""End-to-end demo: fit the clock model, then apply it to ShimmerECG.

Loads the most recent XDF, fits a ClockModel from the diagnostics stream,
then applies the (a, b) mapping to the ShimmerECG device-timestamp column
to produce drift-corrected LSL timestamps. Compares the corrected
timestamps against the bridge-emitted (online-EMA-corrected) ones to
quantify how much the offline fit differs from the online estimate.
"""
from pathlib import Path
import numpy as np
import pyxdf
import matplotlib.pyplot as plt

from analysis.shimmer_clock_model import fit_from_xdf, apply

XDF = Path(r"C:\Users\ngoldbla\Documents\CurrentStudy\sub-P001\ses-S001\eeg\sub-P001_ses-S001_task-Default_run-001_eeg.xdf")
OUT = Path(r"C:\Users\ngoldbla\Desktop\LSL_data\EXP06_quicklook")

print(f"loading {XDF.name} and fitting clock model...")
model = fit_from_xdf(XDF)
print(f"  fit: {model.b_ppm:+.3f} ppm (residual {model.residual_std_ms:.2f} ms)")

streams, _ = pyxdf.load_xdf(str(XDF))
ecg = next(s for s in streams if s["info"]["name"][0] == "ShimmerECG")
ecg_lsl_bridge = np.asarray(ecg["time_stamps"])             # bridge-emitted, online EMA
ecg_dev_ts = np.asarray([v[0] for v in ecg["time_series"]]) # device ticks / 32768 from ch0
print(f"  loaded ShimmerECG: {len(ecg_lsl_bridge)} samples")

# Apply the offline model
ecg_lsl_corrected = apply(model, ecg_dev_ts)

# Compare: per-sample diff between online and offline timestamps
diff = (ecg_lsl_corrected - ecg_lsl_bridge) * 1000.0  # ms
t_rel = ecg_lsl_bridge - ecg_lsl_bridge[0]

print()
print(f"corrected vs bridge-emitted timestamps:")
print(f"  mean diff   : {diff.mean():+.4f} ms")
print(f"  std diff    : {diff.std():.4f} ms")
print(f"  max |diff|  : {np.abs(diff).max():.4f} ms")
print(f"  diff at t=0 : {diff[0]:+.4f} ms")
print(f"  diff at end : {diff[-1]:+.4f} ms")
print(f"  slope of diff(t): {1e6 * np.polyfit(t_rel, diff/1000.0, 1)[0]:+.3f} ppm")

# Same-stream sample-period check: per-sample ISI of bridge vs corrected
isi_bridge = np.diff(ecg_lsl_bridge) * 1000
isi_corr = np.diff(ecg_lsl_corrected) * 1000
print()
print(f"ISI (ms) statistics:")
print(f"  bridge:    mean {isi_bridge.mean():.4f}  std {isi_bridge.std():.4f}  min {isi_bridge.min():.3f}  max {isi_bridge.max():.3f}")
print(f"  corrected: mean {isi_corr.mean():.4f}    std {isi_corr.std():.4f}  min {isi_corr.min():.3f}  max {isi_corr.max():.3f}")

# Plot
fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
axes[0].plot(t_rel, diff, '-', lw=0.4, alpha=0.7)
axes[0].axhline(0, color='gray', lw=0.5)
axes[0].set_ylabel("corrected - bridge (ms)")
axes[0].set_title(f"Offline clock model vs bridge online EMA  "
                  f"({model.b_ppm:+.2f} ppm fit, residual {model.residual_std_ms:.2f} ms)")
axes[0].grid(alpha=0.3)

axes[1].plot(t_rel[1:], isi_bridge, '-', lw=0.3, alpha=0.4, color='gray',
             label=f'bridge (std {isi_bridge.std():.3f} ms)')
axes[1].plot(t_rel[1:], isi_corr, '-', lw=0.3, alpha=0.6, color='tab:blue',
             label=f'corrected (std {isi_corr.std():.3f} ms)')
axes[1].set_xlabel("time since recording start (s)")
axes[1].set_ylabel("per-sample ISI (ms)")
axes[1].legend(fontsize=9)
axes[1].grid(alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / "shimmer_clock_model_demo.png", dpi=130)
print(f"\nsaved {OUT/'shimmer_clock_model_demo.png'}")

# Sanity assertions
expected_max_diff_ms = max(50.0, 2 * model.b_ppm * 1e-6 * model.duration_s * 1000)
assert np.abs(diff).max() < expected_max_diff_ms, \
    f"correction differs from bridge by > {expected_max_diff_ms:.1f} ms; investigate"
print(f"\nsanity OK: max diff {np.abs(diff).max():.2f} ms < expected bound {expected_max_diff_ms:.2f} ms")
