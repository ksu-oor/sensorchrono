# LSL Multi-Modal Synchronization Plan: Shimmer + Emotiv + USB-C Video

**Repository:** https://github.com/ksu-oor/LSL_synchronization_multi
**Hardware:** RTX 4090 workstation · Shimmer3 EXG SR47-5-1 (dual ADS1292R, 4ch, BT 2.1+EDR via RN42) for ECG/EMG + on-board accelerometer · Emotiv Insight 2.0 (5ch EEG @ 128 SPS, BLE 5.0, Cortex API, motion subscription available) · Logitech UVC webcam (USB, no hardware sync, Media Foundation timestamps) · **wired USB keyboard** (Apple wired or any wired HID keyboard — Bluetooth keyboards are disallowed due to 10–30 ms jittery HID latency)
**Goal:** Build and validate a recording stack where Shimmer Bluetooth biosignals and USB-C A/V are aligned to ≤1 ms relative jitter and ≤5 ms absolute fiducial error, sustained over a 3-hour session.
**Status:** Plan only. No experiments run yet.

---

## 1. What "sync to the millisecond" actually means here

There are three different things people lump together:

| Layer | What it means | Achievable with this stack |
|---|---|---|
| **A. Absolute wall-clock alignment** of a sample to the physical event that produced it | Bounded by the sensor's transport latency (BT) and the camera's capture pipeline | ~10–100 ms unless you inject a hardware fiducial |
| **B. Relative alignment between streams** after recording (XDF post-hoc) | Bounded by clock drift estimation quality and per-stream timestamp accuracy | **Sub-millisecond is realistic** with the existing tick→LSL mapper + LabRecorder clock_offsets + pyxdf dejitter |
| **C. Per-sample regularity** (jitter of inter-sample intervals within one stream) | Bounded by sensor crystal stability and transport buffering | <100 µs after dejittering a regular-rate stream |

The repo's current `LslTimestampMapper` (`shimmer_lsl_bridge.py`, lines ~25–60) already targets B and C correctly: it unwraps the 24-bit 32768 Hz device tick counter, takes the *minimum* observed (arrival − device_time) as the latency offset (Cristian's algorithm), then a slow EMA (`drift_alpha=0.002`) tracks crystal drift without chasing transport jitter. The 3-hour validation will tell us whether `drift_alpha` is well-chosen.

**Our target:** ≤1 ms 95th-percentile error on B, characterized by repeated hardware fiducials throughout a 3-hour run.

---

## 2. System architecture and the gaps to close

Current state of the repo:
- `shimmer_lsl_bridge.py` — ECG (256 Hz) and EMG (512 Hz) over BT serial, with a tick→LSL mapper. **Solid baseline.**
- `emotiv_lsl_bridge.py` — Emotiv Cortex → LSL.
- `plot_xdf_streams.py` — post-hoc inspection.
- **No video outlet. No audio outlet. No hardware fiducial. No automated sync-quality metrics. No drift logging.**

Required additions:
1. **Video LSL outlet** that pushes one sample per frame containing `(frame_index, capture_timestamp_lsl, optional_phash)` while writing frames to disk in a container that preserves PTS (MP4/MKV with monotonic PTS). Reference implementations: `markspan/TimeShot`, `vahid-sb/LSL_Video_Acquisition`. Use Media Foundation or DirectShow timestamps via OpenCV `CAP_PROP_POS_MSEC` *plus* `pylsl.local_clock()` at the moment `cap.read()` returns — log both.
2. **Audio LSL outlet** (PCM chunks → LSL at e.g. 48 kHz) so the camera's own audio is alignable independent of the video file's muxed audio.
3. **Primary fiducial: keystrokes.** A wired USB keypress is an excellent natural fiducial because the same physical event is observable on **four independent channels**, all timestamped against the LSL clock:
   - OS HID event (callback timestamp via `pynput` or `keyboard` library + `pylsl.local_clock()`) — the *reference*.
   - Audio click in the webcam mic — onset detection in PCM, sub-ms within a chunk.
   - Video frame of the finger landing — ROI frame-diff, ±0.5 frame.
   - **Shimmer on-board accelerometer** picking up the table vibration — sharp onset, ~2 ms at 256 Hz.

   We push every keystroke as a `KeyboardFiducial` LSL marker stream and analyze each modality's lag relative to it. Hundreds to thousands of fiducials per session, zero hardware cost.

   **Constraint:** keyboard must be wired USB (HID polling ≤1 ms jitter). Bluetooth keyboards add 10–30 ms of jittery latency and are disallowed for this work.

   **What keystrokes do NOT fiducialize: Emotiv** (head-mounted, not on the desk). We handle Emotiv via:
   - (a) Cristian-style LSL clock mapping (primary, unattended).
   - (b) Occasional manual head-tap right after a keystroke every ≈5 min during the 3-hour run (gives a direct fiducial chain for Emotiv at low frequency).
   - (c) Optional eye-blink fiducial (blink deliberately on a keystroke; ±30 ms via AF3/AF4 deflection + video eyelid detection).

   The Pi Pico v2 rig from earlier drafts is **deferred** unless keystroke fiducials prove insufficient in EXP-03/EXP-08.

4. **Secondary fiducial: scheduled earbud-click audio pulses.** A wired headphone earbud (or small speaker) is placed physically touching the Shimmer case. A Python script plays a 1 ms 4 kHz tone burst every 10 s. The pulse is detected:
   - In the webcam mic's audio LSL stream (acoustic, sub-ms onset within chunk).
   - In the Shimmer accelerometer's LSL stream (mechanical coupling, ~2 ms at 256 Hz accel).

   **Timestamping rule:** the fiducial time is the *mic-detected onset*, not the OS playback time. Windows WASAPI shared-mode output adds 20–100 ms of jittery buffering we refuse to inherit. By using mic-onset as the timestamp, the audio LSL outlet's per-sample timestamping is the authority, and we measure Shimmer-accel onset relative to it.

   Each burst encodes its sequence number in a short tone pattern (e.g. Morse-style short/long burst pairs) so fiducials remain uniquely identifiable even if some are missed.

   **Limitation:** no visual signal in the video stream — audio-only fiducials do not directly validate video sync. Keystroke fiducials remain the path for video. The earbud track is purely for unattended dense audio↔Shimmer validation during the 3-hour run.
4. **Sync diagnostics logger:** every minute, record `(stream, n_samples, effective_rate, mean_offset, offset_std, mapper.offset, mapper.observed_min_latency)` to a CSV that can be plotted post-run.
5. **Realtime monitor** (separate process or Jupyter): inlets to every LSL stream printing `time_correction()` once a second so we can watch the per-stream offset live.

---

## 3. Known failure modes we expect to hit

These are not hypothetical — they are documented in LSL and Shimmer ecosystem issues and will absolutely show up.

| # | Failure mode | Why it happens | Detection | Mitigation |
|---|---|---|---|---|
| F1 | **RFCOMM packet bursting** — Shimmer samples arrive in clumps every 20–50 ms, not one-by-one | Bluetooth RFCOMM batches across baseband slots | Plot arrival-time deltas; expect bimodal | Use device tick as the truth and only let the LSL mapper accept the min-latency packets to set offset (already done) |
| F2 | **Transport latency outliers** when the BT host stack stalls (Windows BT driver, antenna contention with the Emotiv puck) | Two BT devices sharing one host controller compete for slots | Spikes in observed_offset; gaps in samples | Use a *separate* USB BT dongle for the Shimmer; pin antennas; disable BT background scanning |
| F3 | **Crystal drift** between Shimmer 32768 Hz crystal, Emotiv internal clock, PC TSC, camera clock | All free-running oscillators, typically 10–50 ppm | Slope in offset(t) plot over 3 h | EMA drift term in mapper; verify the slope is small and linear; consider piecewise-linear refit in pyxdf |
| F4 | **Camera frame-drop without notification** when CPU/GPU contend or USB bus saturates | UVC drivers silently drop frames | Frame index gaps; nominal_srate vs effective_srate divergence | Push *every successful* `cap.read()` to LSL with the captured frame index; reconcile with ffprobe PTS post-hoc |
| F5 | **OpenCV capture timestamp lag** — `cap.read()` returns long after sensor exposure | Driver buffering of 1–3 frames | LED-fiducial test will show systematic offset | Calibrate a fixed `t_capture = t_read - lag_const`; measure lag_const with the LED rig |
| F6 | **LabRecorder writes the timestamp at push time, not capture time** if you don't supply one | pylsl `push_sample()` without explicit `timestamp` arg uses `local_clock()` *now* | XDF shows offset of full BT latency | Always pass an explicit corrected timestamp (the current bridge does this for Shimmer; the new video outlet must too) |
| F7 | **Wrap-around of 24-bit Shimmer tick counter every 512 s** | 2^24 / 32768 ≈ 512 s | Sudden negative deltas | Existing `_unwrap_ticks()` handles it. 3-hour run will wrap ~21 times — test this explicitly |
| F8 | **Emotiv Cortex timestamps are not LSL-clock** — they're Unix epoch from the headset firmware | Cortex returns its own time field | Per-sample correlation drift between Shimmer and Emotiv | Apply the same Cristian-style mapper to Emotiv samples; do not trust Cortex's `time` directly |
| F9 | **System sleep / power events** mid-recording | Windows power management | Long gap, mapper.offset jumps | Disable sleep, USB selective suspend, Bluetooth power saving for the session |
| F10 | **Audio/video desync inside the camera** | Camera firmware muxes A/V with its own clock | Lip-sync test fails even with perfect LSL | Stream audio as its own LSL outlet from the host, ignore the camera's muxed audio for sync purposes |

---

## 4. Experiment progression — 5-minute loops

Each loop is 300 s. Each loop produces an XDF, a diagnostics CSV, and a one-page auto-report saved to `experiments/EXP_<n>_<tag>/`. The acceptance metric for moving to the next experiment is in the **Pass** column.

### EXP-00 · Smoke test (current code, no changes)
Run `shimmer_lsl_bridge.py --shimmer ecg --record-seconds 300`. Record with LabRecorder. Just confirm samples arrive and the XDF is loadable.
- **Pass:** effective rate within ±1% of 256 Hz; no gaps >100 ms; XDF opens in pyxdf.

### EXP-01 · Per-stream regularity baseline
Same as EXP-00 but compute and save:
- inter-sample interval histogram (LSL time)
- inter-sample interval histogram (device time)
- mapper.offset vs time
- `cumulative_samples - nominal_rate * elapsed`
- **Pass:** device-time intervals tight (<5 ticks std); LSL-time intervals reveal BT burst pattern but mean = nominal.

### EXP-02 · Add a video LSL outlet
Implement `video_lsl_bridge.py`: open the USB-C camera at fixed resolution+fps, push `(frame_idx, hw_timestamp_ms)` to a `VideoFrames` LSL outlet at the camera's nominal rate, write video to MP4 with monotonic PTS, simultaneously write a `frames.csv` with `(frame_idx, t_read_lsl, t_capture_ms, dropped_flag)`.
- **Pass:** effective fps within ±0.5% of nominal; <1 dropped frame per 5 minutes; frame_idx in CSV matches MP4 frame count from ffprobe.

### EXP-03 · Keystroke fiducial — calibration run
Place the Shimmer on the same desk surface as the keyboard. Frame the keyboard in the webcam FOV. Run a `keyboard_fiducial_bridge.py` that hooks every keypress and pushes a `KeyboardFiducial` LSL marker stamped with `pylsl.local_clock()` taken inside the callback. During the 5 min, type a known burst pattern: 10 spacebar taps at ≈1 Hz, pause, 10 more, pause, then natural typing.

Post-hoc, for every keypress event detect:
- audio click onset (PCM transient detector, threshold + dead-time)
- video keypress frame (ROI frame-diff on the key region)
- Shimmer accel onset (z-axis high-pass + threshold)

Compute per-modality lag distribution Δ = t_detected − t_keypress.
- **Pass:** each Δ has stddev <5 ms over ≥50 keystrokes; means are reproducible across two consecutive 5-min runs (within ±2 ms). The means become per-modality calibration constants.

### EXP-04 · Audio outlet integration
Stream PCM from the webcam mic at 48 kHz in 10 ms chunks to an `AudioPCM` LSL outlet (the audio detection in EXP-03 can be done offline from the recorded WAV, but a live outlet lets us close the loop in real time). Re-run the EXP-03 keystroke protocol.
- **Pass:** audio-click Δ stddev <2 ms; video-keypress Δ stddev <1 frame; Shimmer-accel Δ stddev <5 ms.

### EXP-05 · Stress test — co-locate all three Bluetooth radios
Run Shimmer + Emotiv simultaneously while the camera is recording at high bitrate. Stress CPU on a 4th core (we have an RTX 4090 + plenty of CPU — saturate the iGPU/CPU on purpose).
- **Pass:** no stream loses >0.5% of samples; mapper.offset for each Shimmer doesn't jump by more than its quiescent stddev.

### EXP-06 · Drift characterization at 5 min
Plot mapper.offset(t) for Shimmer ECG, Shimmer EMG, Emotiv EEG, video frame_idx vs LSL time. Linear-fit each; record slope in ppm.
- **Pass:** slopes are stable across 3 consecutive 5-min runs (within ±2 ppm). If unstable, the drift_alpha EMA is wrong.

### EXP-07 · Emotiv on-desk calibration
Place the **Emotiv Insight 2.0 directly on the desk** next to the keyboard for this 5-min experiment only (not on the head). Bring up `emotiv_lsl_bridge.py` with both `eeg` and `mot` subscriptions. Run the same keystroke-burst protocol from EXP-03. Detect the keystroke in Emotiv's accel; compare to the `KeyboardFiducial` marker.
- **Pass:** Emotiv keystroke-detection Δ stddev <5 ms over ≥50 keystrokes; mean is reproducible across two consecutive 5-min runs. The mean becomes the Emotiv calibration constant. This directly validates the Cristian-style LSL clock mapping for the Emotiv — once validated here, we trust the mapping during the head-worn 3-hour run.

### EXP-08 · Keystroke-only fiducial validation, 5 min
No head taps. Just typing. Compute pairwise alignment between video, audio, and Shimmer using the calibrated per-modality lags from EXP-04. For Emotiv, just record its LSL-clock-mapped data and check that the Cristian filter's offset is stable.
- **Pass:** video↔audio↔Shimmer pairwise alignment error 95th-pct ≤1 ms; Emotiv mapper.offset drift <2 ppm. This is where we earn "millisecond sync" for the three desk-coupled modalities.

### EXP-09 · Repeat EXP-08 with sleep/USB-suspend deliberately enabled
We want to *see* the failure mode F9 so we know our diagnostics catch it.
- **Pass:** the diagnostics CSV clearly flags the event; we then re-disable sleep for production.

### EXP-10 · 30-minute pre-validation
Half-length dress rehearsal of the final 3-hour protocol. 30 min, 30 fiducials, all three modalities, full diagnostics.
- **Pass:** post-correction 95th-percentile fiducial alignment error ≤1 ms within each pair (video↔Shimmer, video↔Emotiv, Shimmer↔Emotiv).

---

## 5. Final validation — 3-hour protocol

Run all four modalities (video, audio, Shimmer, Emotiv-on-head) continuously for **3 hours** (10,800 s). Fiducials come from:
- **Natural typing** (operator working/taking notes) — expected several hundred keystrokes.
- **Scheduled bursts:** every 5 min, 10 spacebar taps at ~1 Hz (≈36 bursts × 10 = 360 dense fiducials).

Emotiv is on the head and not directly fiducialized during this run — we rely on the EXP-07 calibration plus continuous monitoring of the Emotiv LSL mapper's offset drift. If the offset drifts beyond ±2 ms relative to its EXP-07 baseline, the run is flagged.

**Pre-flight checklist**
- Wall power, no battery saver.
- Disable Windows sleep, USB selective suspend, BT power saving.
- Separate USB BT dongle for Shimmer; Emotiv on its own Cortex puck; camera on a dedicated USB-C controller (check Device Manager hubs).
- Cold-start all bridges, let mapper.offset settle for 60 s before pressing record.
- ECG/EMG electrodes well-attached; LED in frame and not saturated; Pico powered and verified emitting markers.

**During the run**
- Realtime monitor prints per-stream offset and effective rate every 60 s; alarms if drift slope exceeds 5 ppm/hr or rate deviates >0.2%.
- Diagnostics CSV writes one row per minute per stream.

**Acceptance criteria for "perfect sync"** (operational definition):
| Metric | Target |
|---|---|
| Per-fiducial alignment error, median | ≤0.5 ms |
| Per-fiducial alignment error, 95th pct | ≤1.0 ms |
| Per-fiducial alignment error, max | ≤3.0 ms |
| Drift slope of any pairwise offset over 3 h | ≤2 ppm |
| Dropped frames | <0.1% |
| Lost Shimmer samples | <0.05% |
| Mapper.offset stability (stddev of residuals after linear detrend) | <0.5 ms |
| Tick-counter wraps detected and handled | all 21 (3 h × 3600 / 512 ≈ 21.1) |

If any of these fail, the post-mortem is data-driven: the diagnostics CSV plus the fiducial log tells us exactly which stream and which time.

---

## 6. Concrete code changes to ship before EXP-02

Minimal patch list to the repo:

1. **New** `video_lsl_bridge.py`: camera → `VideoFrames` LSL outlet + `frames.csv` + MP4 writer. Borrow structure from `markspan/TimeShot`.
2. **New** `audio_lsl_bridge.py`: sounddevice or pyaudio → `AudioPCM` LSL outlet at 48 kHz.
3. **New** `fiducial_pico_bridge.py`: read Pico USB CDC, push `FiducialMarkers` outlet.
4. **New** `sync_diagnostics.py`: subscribes to every LSL stream, writes per-minute diagnostics CSV, prints a live table.
5. **Modify** `run_lsl_streams.py` to optionally spawn the video/audio/fiducial/diagnostics processes.
6. **Modify** `shimmer_lsl_bridge.py`:
   - Expose `mapper.offset`, `mapper.observed_min_latency` to a per-second log (currently it's internal).
   - Add unit test for `_unwrap_ticks()` across a synthetic wrap.
   - Make `drift_alpha` configurable per run (so EXP-06 can sweep it).
7. **New** `analysis/fiducial_align.py`: load XDF + fiducial log, compute Δ per pulse, plot, report acceptance metrics.

---

## 7. Resolved decisions (2026-06-02)

1. **EEG source = Emotiv Insight 2.0** (5ch @ 128 SPS, BLE). Shimmer SR47-5-1 = ECG/EMG + accelerometer fiducial channel.
2. **Camera = Logitech UVC webcam** + its built-in mic, both pulled via OpenCV/Media Foundation + sounddevice. No hardware sync available; capture lag will be measured once per session with the LED fiducial.
3. **Fiducial = mechanical (tap) + optical (LED).** Start with hand-clap v0; aim for Pico v2 before the 3-hour run. **No electrical injection through EXG inputs while a subject is wearing them** — safety-justified and unnecessary given accelerometer-based detection works equally well.
4. **Emotiv timing path:** subscribe to both `eeg` and `mot` streams via Cortex; map Cortex epoch-timestamps into the LSL clock with the same Cristian-style min-offset filter used for Shimmer.

---

## 8. Sources

- LSL Time Synchronization docs — https://labstreaminglayer.readthedocs.io/info/time_synchronization.html
- LSL paper (PMC12434378) — https://pmc.ncbi.nlm.nih.gov/articles/PMC12434378/
- Shimmer LogAndStream firmware manual — https://shimmersensing.com/wp-content/docs/support/documentation/LogAndStream_for_Shimmer3_Firmware_User_Manual_rev0.11a.pdf
- Shimmer Consensys Pro LSL integration — https://www.shimmersensing.com/consensys-pro-now-integrated-with-lab-streaming-layer-lsl/
- Shimmer Timestamps wiki — https://github.com/ShimmerResearch/ShimmerAndroidAPI/wiki/Timestamps
- TimeShot multi-camera LSL — https://github.com/markspan/TimeShot
- LSL_Video_Acquisition — https://github.com/vahid-sb/LSL_Video_Acquisition
- pylsl timestamp semantics — https://github.com/labstreaminglayer/pylsl/issues/103
- This repo — https://github.com/ksu-oor/LSL_synchronization_multi
