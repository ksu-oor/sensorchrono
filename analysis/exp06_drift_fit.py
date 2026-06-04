"""EXP-06 drift fit on the 5-min XDF.

Fits per-modality (a, b) clock models against the keyboard-as-reference,
demonstrates the methodology, and reports residuals + ppm estimates.

Three independent drift measurements:

  1. SHIMMER CRYSTAL (no external fiducial needed)
     ShimmerDiagnostics_ECG stream contains per-second snapshots of the
     bridge's clock mapper. Channel 1 = last_observed_s = (lsl_time - dev_ts)
     for the most recent packet. The slope of this vs lsl_time directly
     measures the device-vs-system clock drift in s/s = ppm * 1e-6.

  2. BRIO AUDIO CLOCK (via keystroke -> click latency)
     For each keystroke press at t_kb, find the click peak in the BRIO
     mic envelope. delta = t_click - t_kb. If audio clock drifts vs LSL
     clock, delta trends linearly over the recording.

  3. BRIO VIDEO CLOCK (via keystroke -> nearest-frame deviation)
     For each keystroke press, compute the time to the nearest frame.
     Same idea: a drifting video clock makes this delta trend.

Outputs:
  outputs/EXP06_quicklook/exp06_drift_fit.png   (3 stacked plots)
  outputs/EXP06_quicklook/exp06_drift_fit.yaml  (per-modality {a,b,n,rmse})
"""
from pathlib import Path
import yaml
import numpy as np
import pyxdf
from scipy.signal import butter, filtfilt, hilbert
import matplotlib.pyplot as plt

XDF = r"C:\Users\ngoldbla\Documents\CurrentStudy\sub-P001\ses-S001\eeg\sub-P001_ses-S001_task-Default_run-001_eeg.xdf"
OUT = Path(r"C:\Users\ngoldbla\Desktop\LSL_data\EXP06_quicklook")
OUT.mkdir(parents=True, exist_ok=True)


def theil_sen(x, y):
    """Robust line fit. Returns (slope, intercept). O(n^2) but n is small."""
    n = len(x)
    if n < 2:
        return 0.0, np.mean(y) if n else 0.0
    if n > 2000:
        idx = np.random.default_rng(0).choice(n, size=2000, replace=False)
        x = x[idx]; y = y[idx]; n = 2000
    slopes = []
    for i in range(n):
        for j in range(i + 1, n):
            if x[j] != x[i]:
                slopes.append((y[j] - y[i]) / (x[j] - x[i]))
    slope = float(np.median(slopes))
    intercept = float(np.median(y - slope * x))
    return slope, intercept


print(f"loading {XDF}")
streams, _ = pyxdf.load_xdf(XDF)
by = {s['info']['name'][0]: s for s in streams}

results = {}

# ----- 1. Shimmer crystal drift -----------------------------------
print("\n=== 1. SHIMMER ECG CRYSTAL ===")
diag = by['ShimmerDiagnostics_ECG']
d_ts = np.asarray(diag['time_stamps'])
d_v = np.asarray(diag['time_series'])  # cols: offset, last, min, residual_ms, samples
print(f"  {len(d_ts)} diagnostic samples over {d_ts[-1]-d_ts[0]:.1f}s")

# Use last_observed_s (col 1) with rolling-minimum outlier rejection.
# This is the OWD-min approach used by PTP/NTP for jittery transports.
# min_observed_s (col 2) is a CUMULATIVE minimum and so monotonic
# non-increasing -- useless for slope fitting after warmup.
t = d_ts - d_ts[0]
y_last = d_v[:, 1]  # last_observed_s (raw per-packet, jittery)
y_off = d_v[:, 0]   # mapper offset (smoothed)

# Rolling-window minimum: in each WINDOW seconds, take the min of
# last_observed_s. This filters out bimodal BT-jitter outliers and
# tracks the underlying clock drift.
WINDOW_S = 10.0
bin_idx = np.floor(t / WINDOW_S).astype(int)
uniq = np.unique(bin_idx)
t_bin = np.array([t[bin_idx == b].mean() for b in uniq])
y_bin = np.array([y_last[bin_idx == b].min() for b in uniq])
print(f"  binned into {len(uniq)} windows of {WINDOW_S}s (rolling-min)")

slope_last, intercept_last = theil_sen(t_bin, y_bin)
ppm_last = slope_last * 1e6
pred_last = intercept_last + slope_last * t_bin
resid_last = y_bin - pred_last
print(f"  rolling-min OWD slope: {ppm_last:+.2f} ppm")
print(f"  residual std on bins: {1000*resid_last.std():.3f} ms")
print(f"  (positive ppm = system clock runs FASTER than Shimmer crystal)")

# For the plot we still want to show the raw last_observed cloud + the fit
pred_full = intercept_last + slope_last * t
resid_full = y_last - pred_full

results['shimmer_ecg'] = {
    'channel': 'ShimmerDiagnostics_ECG ch1 (last_observed_s), OWD-min binned',
    'b_ppm': round(ppm_last, 3),
    'a_offset_s': round(intercept_last, 6),
    'n_diagnostic_samples': int(len(t)),
    'n_bins': int(len(uniq)),
    'window_s': WINDOW_S,
    'rmse_residual_ms_binned': round(float(1000 * resid_last.std()), 4),
    'rmse_residual_ms_raw': round(float(1000 * resid_full.std()), 4),
    'duration_s': round(float(t[-1]), 2),
    'sign_convention': 'positive ppm = system clock faster than device crystal',
}

# ----- 2. Audio clock drift ---------------------------------------
print("\n=== 2. BRIO AUDIO CLOCK ===")
kb = by['KeyboardFiducial']
kb_ts = np.asarray(kb['time_stamps'])
kb_ev = [v[0] for v in kb['time_series']]
press_ts = np.array([t for t, e in zip(kb_ts, kb_ev) if 'press' in e])
print(f"  {len(press_ts)} key presses")

audio = by['Audio']
a_ts = np.asarray(audio['time_stamps'])
a_v = np.asarray([v[0] for v in audio['time_series']], dtype=np.float32)
a_fs = float(audio['info']['nominal_srate'][0])


def bp(x, lo, hi, fs, order=4):
    b, a = butter(order, [lo / (fs / 2), hi / (fs / 2)], btype='band')
    return filtfilt(b, a, x)


print("  filtering audio 1-6 kHz + envelope...")
a_bp = bp(a_v, 1000, 6000, a_fs)
a_env = np.abs(hilbert(a_bp))

deltas_aud = []
ref_t = []
for tp in press_ts:
    mask = (a_ts >= tp - 0.03) & (a_ts <= tp + 0.15)
    if mask.sum() < 100:
        continue
    seg = a_env[mask]
    seg_t = a_ts[mask]
    base = seg[:int(0.02 * a_fs)]
    base_med = float(np.median(base))
    base_mad = float(np.median(np.abs(base - base_med))) + 1e-9
    j = int(np.argmax(seg))
    peak = float(seg[j])
    snr = (peak - base_med) / (1.4826 * base_mad)
    if snr < 10:  # tighter than quicklook's 6
        continue
    deltas_aud.append(seg_t[j] - tp)
    ref_t.append(tp)
deltas_aud = np.array(deltas_aud)
ref_t = np.array(ref_t)
print(f"  audio click confirmed: {len(deltas_aud)} / {len(press_ts)}")

# Fit drift. Use ref_t relative to recording start for clarity.
t_rel = ref_t - press_ts[0] if len(press_ts) else np.array([])
slope_aud, intercept_aud = theil_sen(t_rel, deltas_aud)
ppm_aud = slope_aud * 1e6
pred_aud = intercept_aud + slope_aud * t_rel
resid_aud = deltas_aud - pred_aud
print(f"  Theil-Sen fit: {ppm_aud:+.2f} ppm, intercept {1000*intercept_aud:.2f} ms")
print(f"  raw std {1000*deltas_aud.std():.2f} ms; residual std {1000*resid_aud.std():.2f} ms")
print(f"  (per-event jitter is dominated by keystroke timing variability, not drift)")

# Robust slope confidence interval via bootstrap
rng = np.random.default_rng(7)
slopes = []
for _ in range(200):
    idx = rng.choice(len(t_rel), size=len(t_rel), replace=True)
    s, _ = theil_sen(t_rel[idx], deltas_aud[idx])
    slopes.append(s * 1e6)
ppm_aud_lo, ppm_aud_hi = np.percentile(slopes, [2.5, 97.5])
print(f"  95%CI on drift: [{ppm_aud_lo:+.2f}, {ppm_aud_hi:+.2f}] ppm")

results['brio_audio'] = {
    'channel': 'BRIO mic via keystroke-click envelope',
    'b_ppm': round(ppm_aud, 3),
    'b_ppm_95CI': [round(float(ppm_aud_lo), 3), round(float(ppm_aud_hi), 3)],
    'a_offset_ms': round(1000 * intercept_aud, 4),
    'n_events': int(len(deltas_aud)),
    'rmse_residual_ms': round(float(1000 * resid_aud.std()), 4),
    'raw_std_ms': round(float(1000 * deltas_aud.std()), 4),
    'duration_s': round(float(t_rel[-1]), 2) if len(t_rel) else 0.0,
}

# ----- 3. Video clock drift ----------------------------------------
print("\n=== 3. BRIO VIDEO CLOCK ===")
vid = by['VideoFrames']
v_ts = np.asarray(vid['time_stamps'])
print(f"  {len(v_ts)} frames")

# For each press, find the nearest frame timestamp.
# Then drift_video = (nearest_frame_ts - press_ts) modulo half-frame.
# Over time the trend reveals video-clock drift relative to system.
nearest_dt = []
ref_v = []
for tp in press_ts:
    idx = np.searchsorted(v_ts, tp)
    candidates = []
    if idx > 0:
        candidates.append(v_ts[idx - 1] - tp)
    if idx < len(v_ts):
        candidates.append(v_ts[idx] - tp)
    if not candidates:
        continue
    j = int(np.argmin([abs(c) for c in candidates]))
    nearest_dt.append(candidates[j])
    ref_v.append(tp)
nearest_dt = np.array(nearest_dt)
ref_v = np.array(ref_v)
print(f"  matched {len(nearest_dt)} keystrokes to nearest frame")

# Video frame period is ~33 ms, so the raw |nearest_dt| is uniform on
# [-16.5, +16.5] ms. The drift signal is the slow trend in the mean of
# nearest_dt over time. Use a rolling-window mean to expose it.
t_rel_v = ref_v - ref_v[0]
slope_v, intercept_v = theil_sen(t_rel_v, nearest_dt)
ppm_v = slope_v * 1e6
pred_v = intercept_v + slope_v * t_rel_v
resid_v = nearest_dt - pred_v
print(f"  Theil-Sen fit: {ppm_v:+.2f} ppm")
print(f"  raw std {1000*nearest_dt.std():.2f} ms (bounded by half-frame=16.5ms)")
print(f"  residual std {1000*resid_v.std():.2f} ms")

results['brio_video'] = {
    'channel': 'BRIO video via keystroke->nearest-frame',
    'b_ppm': round(ppm_v, 3),
    'a_offset_ms': round(1000 * intercept_v, 4),
    'n_events': int(len(nearest_dt)),
    'rmse_residual_ms': round(float(1000 * resid_v.std()), 4),
    'raw_std_ms': round(float(1000 * nearest_dt.std()), 4),
    'duration_s': round(float(t_rel_v[-1]), 2),
    'note': 'nearest-frame metric is bounded by half-frame period; drift'
            ' below ~5 ppm not resolvable in 5 min',
}

# ----- Plots -------------------------------------------------------
fig, axes = plt.subplots(3, 1, figsize=(13, 11))

# Shimmer crystal
ax = axes[0]
ax.plot(t, 1000 * y_last, '.', ms=2, alpha=0.25, color='gray', label='last_observed_s (raw)')
ax.plot(t_bin, 1000 * y_bin, 'o', ms=6, color='tab:blue', label=f'10s rolling-min')
ax.plot(t, 1000 * pred_full, 'r-', lw=1.5, label=f'fit: {ppm_last:+.2f} ppm')
ax.set_xlabel('time since recording start (s)')
ax.set_ylabel('lsl_time - dev_ts offset (ms)')
ax.set_title(f'1. Shimmer ECG crystal: {ppm_last:+.2f} ppm  '
             f'(bin-residual std {1000*resid_last.std():.2f} ms)')
ax.legend(fontsize=8); ax.grid(alpha=0.3)

# Audio
ax = axes[1]
ax.plot(t_rel, 1000 * deltas_aud, '.', ms=3, alpha=0.5, label=f'delta (n={len(deltas_aud)})')
ax.plot(t_rel, 1000 * pred_aud, 'r-', lw=1.5,
        label=f'fit: {ppm_aud:+.2f} ppm  95%CI [{ppm_aud_lo:+.1f}, {ppm_aud_hi:+.1f}]')
ax.set_xlabel('time since first keystroke (s)')
ax.set_ylabel('keystroke -> click (ms)')
ax.set_title(f'2. BRIO audio clock: {ppm_aud:+.2f} ppm  '
             f'(raw std {1000*deltas_aud.std():.1f} ms = typing jitter)')
ax.legend(fontsize=8); ax.grid(alpha=0.3)

# Video — use a rolling-mean to expose drift through the half-frame uniform
window = 31
ax = axes[2]
ax.plot(t_rel_v, 1000 * nearest_dt, '.', ms=2, alpha=0.3, label='per-event')
if len(nearest_dt) >= window:
    roll = np.convolve(nearest_dt, np.ones(window) / window, mode='valid')
    ax.plot(t_rel_v[(window - 1) // 2:(window - 1) // 2 + len(roll)],
            1000 * roll, 'tab:orange', lw=1.5, label=f'rolling mean (w={window})')
ax.plot(t_rel_v, 1000 * pred_v, 'r-', lw=1.5, label=f'fit: {ppm_v:+.2f} ppm')
ax.set_xlabel('time since first keystroke (s)')
ax.set_ylabel('keystroke -> nearest frame (ms)')
ax.set_title(f'3. BRIO video clock: {ppm_v:+.2f} ppm  '
             f'(per-event bounded by half-frame ~16.5 ms)')
ax.legend(fontsize=8); ax.grid(alpha=0.3)

fig.tight_layout()
fig.savefig(OUT / 'exp06_drift_fit.png', dpi=130)
print(f"\nsaved {OUT / 'exp06_drift_fit.png'}")

# YAML output
results['meta'] = {
    'xdf': XDF,
    'recording_duration_s': round(float(d_ts[-1] - d_ts[0]), 2),
    'method': 'Theil-Sen linear fit per modality',
    'notes': 'Shimmer drift comes from its own diagnostics stream (no '
             'external fiducial). Audio drift via keystroke->click '
             'envelope. Video drift via keystroke->nearest-frame.',
}
with open(OUT / 'exp06_drift_fit.yaml', 'w') as f:
    yaml.safe_dump(results, f, sort_keys=False, default_flow_style=False)
print(f"saved {OUT / 'exp06_drift_fit.yaml'}")

# ----- Summary -----------------------------------------------------
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
for name, r in results.items():
    if name == 'meta':
        continue
    print(f"\n{name}:")
    for k, v in r.items():
        print(f"  {k}: {v}")
