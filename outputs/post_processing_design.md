# Post-Processing Design: From Noisy LSL Streams to Aligned Multi-Modal Dataset

**Goal:** Take a recorded `.xdf` (LSL streams) + `.mp4` (video) + `.wav` (audio) from any recording session and produce a unified, drift-corrected, lag-calibrated, time-aligned dataset suitable for analysis at sample-level precision.

**Status:** Design only. Implementation lives in `analysis/postprocess.py` (to be written).

---

## The pipeline at a glance

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  raw .xdf    │  │  raw .mp4    │  │  raw .wav    │
│ (LSL bursts) │  │ (camera PTS) │  │ (audio PCM)  │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       v                 v                 v
   Stage 1: pyxdf dejitter per stream
   Stage 2: pyxdf clock-offset correction
       │                 │                 │
       v                 v                 v
   Stage 3: subtract per-modality fixed lag (from calibration runs)
       │                 │                 │
       v                 v                 v
   Stage 4: remux MP4 with corrected PTS; resample audio to corrected timeline
       │                 │                 │
       └───────┬─────────┴─────────┬───────┘
               v                   v
        unified Parquet     synced .mp4
        (sample-level)      (frame-aligned)
               │                   │
               v                   v
   Stage 5: re-detect fiducials, measure residual Δ, certify pass/fail
```

---

## Stage 1 — Dejitter per stream

**Tool:** `pyxdf.load_xdf(path, dejitter_timestamps=True, jitter_break_threshold_seconds=1.0)`

**What it does:** For each regular-rate stream (ECG at 256 Hz, accel, video at ~30 Hz), pyxdf treats the observed timestamps as `t_i = t_0 + i / f_nominal + noise_i`. It does a linear regression of `(i, t_i)` and replaces the timestamps with the regression line. Breaks (gaps > 1 s) split into segments fit separately.

**What's removed:** the bursty BT transport noise we saw in EXP-01's middle plot. The ±15 ms per-sample residuals collapse to <0.1 ms.

**What's preserved:** the *actual* per-sample positions. The Shimmer's onboard crystal is rock-solid (`device_isi_std = 0.00 ms`), so the device-tick channel is the regression's truth.

**Verification:** after Stage 1, plot `np.diff(corrected_ts)` for each stream. Should be a flat line at `1/f_nominal` with std < 100 µs.

---

## Stage 2 — Clock-offset (drift) correction

**Tool:** also `pyxdf.load_xdf` (built into the same call)

**What's happening internally:**
- LabRecorder runs a background thread that pings every producer ~every 5 s with a `time_correction()` query
- Each query measures the offset between the producer's `pylsl.local_clock()` and LabRecorder's `pylsl.local_clock()` using a 4-message Cristian-style exchange
- These offsets get saved into the XDF in a per-stream "clock_offsets" record (you can see them with `streams[i]['clock_offsets']`)

**What pyxdf does with them:** linearly interpolates the offset values across the recording and subtracts them from each stream's timestamps. This eats any *drift* (in our case 30–40 ppm) between when the producer started and when each sample was recorded.

**Verification:** after Stage 2, the slope of `corrected_ts(i) - i/f_nominal` should be < 2 ppm. If higher, the EMA in the Shimmer bridge's `LslTimestampMapper` may be biasing the clock_offsets — investigate.

**Important:** for streams where the producer is on the *same* PC as LabRecorder (Shimmer bridge, keyboard bridge, video bridge, audio bridge), Stage 2 effectively does nothing because the clocks ARE the same `pylsl.local_clock()`. Stage 2 is critical when producers run on *different* PCs. For our single-PC setup, Stage 1 carries most of the weight; Stage 2 is a safety net.

---

## Stage 3 — Per-modality fixed-lag calibration

This is what makes the difference between "syncing software clocks" and "syncing actual physical events."

**Lags we measure during EXP-03 / EXP-04 / EXP-07:**

| Modality | Source of lag | Expected magnitude |
|---|---|---|
| Shimmer ECG / accel | BT one-way latency floor (Cristian min) | ~5–20 ms |
| Video (BRIO) | UVC driver buffering + OpenCV grab path | ~17–66 ms (1–2 frame periods) |
| Audio (BRIO mic) | WASAPI shared-mode capture buffering | ~10–30 ms |
| Emotiv EEG | Cortex websocket + BLE | ~50–150 ms |
| Emotiv accel | same as EEG | same |

**How we measure each lag (using fiducials):**

For Shimmer accel — keystroke fiducial (or earbud-click) → desk vibration → accel z-axis spike:
```python
Δ_shimmer_accel = median_over_N_events(t_accel_spike - t_keystroke)
```

For Video — keystroke fiducial → finger visible in frame → frame-diff onset on key region:
```python
Δ_video = median_over_N_events(t_keystroke_frame - t_keystroke)
```

For Audio — keystroke / earbud click → mic transient detector:
```python
Δ_audio = median_over_N_events(t_audio_onset - t_keystroke)
```

For Emotiv — earbud click → desk vibration → Emotiv accel (during on-desk calibration):
```python
Δ_emotiv_accel = median_over_N_events(t_emotiv_accel_spike - t_audio_onset)
```

**These constants are recording-rig-specific** (room, hardware, OS, drivers) and reusable across sessions until you change something. They live in a config file:

```yaml
# config/calibration.yaml
calibration_date: 2026-06-02
rig_id: ngoldbla_rtx4090_brio
lag_constants_ms:
  shimmer_ecg: 0.0          # the reference; everything else is relative to ECG
  shimmer_accel: 0.0        # same path as ECG
  video_brio_1080p30: 23.4   # placeholder until EXP-03/04 measures
  audio_brio_mic_48k: 12.7   # placeholder
  emotiv_eeg: 87.2           # placeholder until EXP-07
  emotiv_mot: 87.2           # same path as EEG
```

**Applied in Stage 3:**
```python
corrected_ts[stream] = corrected_ts[stream] - lag_constants_ms[stream] / 1000
```

After Stage 3, all per-sample timestamps refer to **when the physical event was sensed**, not when its bytes arrived at our software.

---

## Stage 4 — Mate the MP4 to the corrected timeline

The MP4 file has internal PTS values set by OpenCV's `VideoWriter` at the *nominal* frame rate (e.g. 30 fps). These PTS values are wrong because:
1. The actual capture intervals were irregular (33 vs 50 ms in EXP-02)
2. The first frame wasn't at t=0 in the corrected timeline

**The map we have:** `frames.csv` from `video_lsl_bridge.py` contains `(frame_idx, t_read_lsl)` for every frame. After Stages 1–3, `t_read_lsl` is on the corrected timeline. So we know each frame's corrected presentation time.

**Two output options:**

### Option A — Lookup table only (lazy)

Just save the corrected `(frame_idx → t_corrected)` mapping as a Parquet. Analysis tools query "at time T, which frame?" via interpolation. Doesn't touch the MP4. **Pros:** zero re-encoding cost, original video preserved. **Cons:** can't play the MP4 in a standard player and have it sync to the EXG.

### Option B — Remux the MP4 with corrected PTS

```bash
ffmpeg -i raw.mp4 -map 0 -c copy -output_ts_offset <t_first_corrected> \
    -f mp4 -movflags faststart synced.mp4
```

Combined with a **VFR (variable frame rate)** PTS list from the corrected `t_read_lsl` values, ffmpeg can produce an MP4 where each frame's presentation time is the corrected LSL time. **Pros:** the resulting `synced.mp4` plays in any player and scrubbing by time corresponds to the EXG timestamp. **Cons:** requires ffmpeg, marginal re-encoding cost.

**Decision:** Do A by default (fast, lossless), offer B as `--remux` flag for delivery to analysts.

**Same idea for audio:** the `.wav` has nominal-rate samples but the actual capture instants are in the corrected `AudioPCM` LSL stream. Resample WAV to the corrected timeline using `scipy.signal.resample_poly` or `librosa.resample`, then save as a new WAV anchored to the corrected origin.

---

## Stage 5 — Validation by fiducial residual

The post-processing claim is: "after pipeline, every modality is aligned to the keystroke timeline within ε."

To verify, we **re-detect fiducials on the post-processed data** and measure the residual Δ:

```python
for modality in [ecg, accel, video, audio, emotiv_eeg]:
    fiducials_in_modality = detect_fiducials(modality_post)
    deltas = []
    for kt in keystroke_times:
        m = nearest(fiducials_in_modality, kt)
        deltas.append(m - kt)
    print(f"{modality}: mean Δ = {np.mean(deltas)*1000:.2f} ms, "
          f"p95 = {np.percentile(deltas, 95)*1000:.2f} ms")
```

**Pass criteria** (operationalized as the *post-processed* targets):

| Pair | Target median Δ | Target p95 Δ |
|---|---|---|
| ECG ↔ Keystroke | ≤0.5 ms | ≤2 ms |
| Accel ↔ Keystroke | ≤0.5 ms | ≤2 ms |
| Audio ↔ Keystroke | ≤2 ms | ≤5 ms |
| Video ↔ Keystroke | ≤16 ms | ≤33 ms (≤1 frame at 30 fps) |
| Emotiv EEG ↔ Keystroke | ≤2 ms | ≤5 ms |
| Emotiv accel ↔ Keystroke | ≤2 ms | ≤5 ms |

If we hit these on the 3-hour recording, the system is **certified**: any future recording made on this rig can be post-processed to this same precision **automatically**, with no further fiducials needed *as long as the calibration constants haven't drifted*.

---

## How to use this in a future session (the goal-state UX)

Once the pipeline is built and the calibration constants are measured (EXP-03 / EXP-04 / EXP-07), the workflow for any future researcher running this rig is:

```bash
# 1. Record (no fiducials needed if you trust the calibration; with fiducials if you want to re-verify)
python run_all_bridges.py --duration 1800  # 30 min

# 2. Post-process
python analysis/postprocess.py recordings/2026-06-15_session/ \
    --calibration config/calibration.yaml \
    --output processed/2026-06-15_session/ \
    --remux

# 3. Analyze
import pyarrow.parquet as pq
ds = pq.read_table("processed/2026-06-15_session/unified.parquet").to_pandas()
# columns: t_sync, ecg_lead1, ecg_lead2, accel_x, accel_y, accel_z, eeg_af3, ..., frame_idx
# t_sync is a single monotonic time axis; every modality is aligned to it
```

The unified Parquet has one row per highest-rate sample (the Shimmer @ 256 Hz). Lower-rate modalities (video @ 30 Hz, Emotiv @ 128 Hz) are forward-filled or interpolated as appropriate.

This is the **end-state product**: a single command takes raw recording → analysis-ready dataset. The 3-hour validation proves the calibration is stable enough that this works without re-fiducializing every session.

---

## What needs to be built

| Component | Status | Notes |
|---|---|---|
| `analysis/postprocess.py` | **TODO** | Implements stages 1–4; outputs unified Parquet + optional synced MP4 |
| `analysis/calibrate.py` | **TODO** | Reads an EXP-03/04/07 XDF, fits per-modality lag, writes/updates `calibration.yaml` |
| `analysis/validate_sync.py` | **TODO** | Stage 5 — re-detects fiducials post-processing, prints pass/fail table |
| `config/calibration.yaml` | **TODO** | Lives in repo, updated each calibration run |
| `run_all_bridges.py` | **partial** | Currently a per-experiment .bat; consolidate into one script with `--duration` |

---

## Important honesty about limits

After this pipeline, our sync is bounded by:
- **ECG / accel:** ~ECG sample period (3.9 ms) — limited by the Shimmer's sample rate
- **Audio:** sub-ms — limited by our onset detector's noise floor
- **Video:** ~one frame period (33 ms at 30 fps) — limited by the BRIO's actual frame rate
- **Emotiv:** ~EEG sample period (7.8 ms at 128 Hz) — limited by the Emotiv's sample rate

To beat these floors you would need: higher-rate sensors (Shimmer at 1024 Hz, camera at 120+ fps with manual exposure) or a *hardware* sync infrastructure (TTL + photodiode + parallel-port markers). The 3-hour validation will tell us whether the *software-only* approach holds those numbers stable over time. Our hypothesis (well-supported by the EXP-00–EXP-02 data) is yes.
