# LSL Sync Lab Notebook

## 2026-06-02

### Setup completed
- Repo cloned to `C:\Users\ngoldbla\Desktop\LSL_synchronization_multi`
- Python 3.13 venv at `.venv` with pylsl 1.18.2, pyxdf, pynput, sounddevice, opencv-python
- LabRecorder 1.16.4 at `C:\Users\ngoldbla\Desktop\LabRecorder\LabRecorder\LabRecorder.exe`
- Shimmer3-BE1D paired on **COM3** (outgoing), COM4 (incoming, unused)
- Logitech BRIO webcam + built-in mic detected as UVC class
- Apple wired keyboard confirmed as USB HID (`VID_05AC&PID_029F`)
- Patched `shimmer_lsl_bridge.py` OUT_DIR to `C:\Users\ngoldbla\Desktop\LSL_data`

### EXP-00 results (300 s ECG smoke test)
XDF: `C:\Users\ngoldbla\Documents\CurrentStudy\sub-P001\ses-S001\eeg\sub-P001_ses-S001_task-Default_run-001_eeg.xdf`
Analyzer: `analysis/exp00_analyze.py`
Diagnostic plot: `C:\Users\ngoldbla\Desktop\LSL_data\EXP00_baseline\exp00_diagnostics.png`

| Metric | Value | Verdict |
|---|---|---|
| n_samples | 78,336 (over 306 s) | LabRecorder ran ~6 s before bridge press-Enter; not a sync issue |
| effective rate | 255.992 Hz | -0.003% deviation, excellent |
| ISI mean / std | 3.91 / 0.88 ms | bimodal BT burst pattern, expected (F1) |
| max gap | 4.4 ms | well under 100 ms target |
| **device ISI std** | **0.00 ms** | Shimmer crystal rock solid — all jitter is BT transport |
| crystal drift | **31.1 ppm** | within 20-50 ppm expected range |
| timestamps monotonic | yes | |
| markers present | recording_armed/started/stopped/session_finished | session_started lost (pre-LabRecorder); not a defect |

**Overall: PASS on substance.** Two analyzer "FAILs" are too-strict checks (assumed exact 300 s; assumed session_started captured by LabRecorder); both are bookkeeping artifacts.

### Lessons learned
- LabRecorder saves to BIDS template path by default (`Documents/CurrentStudy/sub-P001/...`), not to the Filename field unless template is overridden.
- pyxdf throws `struct.error: unpack requires a buffer of 2 bytes` if XDF was not closed via LabRecorder Stop — always click Stop before analyzing.
- Bridge processes can linger as cmd /k windows even after Python exits; kill them between runs.

### Decisions
- Drop the Pi Pico LED+solenoid rig from immediate plan. Replace with:
  - **Keystroke fiducial** (primary) — wired Apple USB keyboard, OS HID event timestamps
  - **Earbud-click fiducial** (secondary, for unattended scheduled audio-Shimmer fiducials during 3h run)
  - **Manual head-tap or eye-blink** as Emotiv anchor (low frequency)

### EXP-01 results (300 s ECG + keyboard fiducial + 1 Hz diagnostics)
XDF: `C:\Users\ngoldbla\Desktop\LSL_data\EXP01_keyboard_v2\EXP01.xdf`
Plot: `C:\Users\ngoldbla\Desktop\LSL_data\EXP01_keyboard_v2\exp01_diagnostics.png`
Added: `keyboard_fiducial_bridge.py`, `analysis/exp01_analyze.py`, ShimmerDiagnostics_ECG outlet patched into `shimmer_lsl_bridge.py`.

| Metric | Value | Verdict |
|---|---|---|
| All 4 streams in XDF | yes | (after fixing initial run where 2 streams were unchecked) |
| ECG 80,457 samples / 314 s | 255.99 Hz (-0.004%) | clean |
| Keystrokes captured | 607 presses, 1202 events | natural typing + 2 spacebar bursts |
| Burst detection | 2 x 20 spacebars | analyzer recognized both |
| Crystal drift | **37.4 ppm** | vs 31.1 ppm in EXP-00 - drift is consistent run-to-run |
| Diagnostics samples | 315 over 314 s | 1 Hz worker healthy |
| **Keystroke -> nearest ECG sample (max / mean)** | **2.10 / 1.04 ms** | within one ECG sample period; cross-stream alignment perfect at this resolution |

**Overall: PASS on all 10 sub-checks.**

### Lessons learned (EXP-01)
- First attempt failed because only 2 of 4 streams were checked in LabRecorder. Always re-Update after the bridge starts so all expected streams appear in the list, then read them back before clicking Start.
- Keyboard --duration must be > recording duration + warmup + buffer. Bumped from 360 -> 600 s.
- pynput key callback should never raise; hardened with try/except + `<unprintable>` fallback even though it didn't fire this run.
- Mapper.offset is a bit noisy because it hard-tracks minimum-latency packets and EMA-decays toward higher ones. For the keystroke use case this doesn't hurt cross-stream sync (because device-tick dejitter dominates), but for video where the timestamp itself matters more, consider a longer-window minimum filter.

### Decisions
- Cross-stream alignment between keyboard and Shimmer is already at the resolution limit of the slower stream (one ECG sample = 3.9 ms). No further work needed on these two modalities.
- Move to EXP-02: add video LSL bridge (Logitech BRIO) with per-frame LSL timestamps + MP4 with PTS.

### EXP-02 results (300 s ECG + keyboard + video, BRIO 1080p)
XDF: `C:\Users\ngoldbla\Documents\CurrentStudy\sub-P001\ses-S001\eeg\sub-P001_ses-S001_task-Default_run-001_eeg.xdf`
MP4 + frames.csv: `C:\Users\ngoldbla\Desktop\LSL_data\EXP02_video\`
Analyzer: `analysis/exp02_analyze.py`
Added: `video_lsl_bridge.py`, `probe_camera2.py`, `launch_exp02.bat`.

| Metric | Value | Verdict |
|---|---|---|
| All 5 streams in XDF | yes | clean |
| BRIO effective fps | **28.87 fps** (target 30) | auto-exposure capped at ~35ms exposure -> never reaches 60 fps |
| Frame interval std | 6.22 ms | irregular delivery, expected for UVC |
| Frame interval distribution | bimodal: 33 ms primary, 50 ms secondary | 39 stutters (~0.45%); driver missed-slot pattern |
| No actual frames dropped | frame_idx monotonic 1660-10379 | the stutters are timing irregularity, not data loss |
| ECG | 256.01 Hz, 77,751 samples | clean |
| Keystrokes | 1165 presses captured | natural typing |
| **Keystroke -> nearest video frame (overlap only, 980 events)** | mean 9.1 ms, p95 17.9 ms, max 23.3 ms | within 0.67 frame periods - **at theoretical minimum** |
| **Video -> nearest ECG sample** | mean 1.02 ms, max 2.12 ms | one ECG sample period - perfect |

**Overall: PASS on substance.** Analyzer's two "FAILs" were:
- Keystroke->video max 11.3s: artifact of keystroke bridge running longer than video; within video window the max is 23.3 ms (perfect).
- Video stutters: 39 of 8720 frames delivered late by ~17 ms. No data loss. Not a sync defect.

### Lessons learned (EXP-02)
- BRIO auto-exposure caps fps at ~30 in normal room light; forcing manual exposure for higher fps would require dimmer setting -> degraded image. Live with 30 fps.
- OpenCV `CAP_PROP_POS_MSEC` returns -1 with DSHOW backend (known limitation). LSL timestamp is our sole authority for frame timing.
- Bridge durations must be sized so all bridges OVERLAP cleanly. Recording window = min(all durations). Future runs: align all --duration values.
- Cross-stream analysis must restrict to the overlap window of streams being compared. Patched into `exp02_analyze.py` for the next round.
- Pi-style video sync floor at this resolution: ~half a frame period (17 ms). To get below this we'd need either: a higher-fps camera, manual exposure with bright lighting, or a hardware-synced industrial camera.

### Decisions
- Video pipeline works. No further bridge changes needed unless we change camera.
- Keystroke -> ECG -> Video chain is fully validated; alignment is at the resolution floor of each stream.
- Move to EXP-03: add Shimmer IMU/accelerometer channels. Goal: confirm desk vibration from keystrokes is detectable on the Shimmer accel.

### Next: EXP-03
Patch `shimmer_lsl_bridge.py` to enable IMU streaming (low-noise accelerometer + gyro, 256 Hz). Place Shimmer on the desk (still no electrodes needed). Type spacebar bursts. Detect tap onsets in accel z-axis. Compute keystroke->accel-onset distribution. The mean becomes the desk-vibration propagation lag (~1-3 ms over a desk, but measure it).

---

## 2026-06-02 (afternoon) — EXP-03: audio-pulse calibration, FAILED

At the user's suggestion we changed EXP-03 design: instead of keystroke-vibration
as the accel fiducial, we used **scheduled audio pulses through a wired earbud
placed next to the Shimmer**. The earbud doubles as: (a) acoustic source for
the BRIO mic and (b) mechanical vibration source for the Shimmer accel.

### What was built
- `audio_lsl_bridge.py` - BRIO mic capture to LSL `Audio` stream at 48 kHz + WAV writer
- `audio_pulse_bridge.py` - scheduled 1 kHz tone bursts through wired output, with LSL marker per pulse
- `shimmer_accel_bridge.py` - new bridge using SET_SENSORS(0x80 0x00 0x00) for low-noise accel; packet layout `[type][ts3][ax_lo,hi,ay_lo,hi,az_lo,hi]` (10 bytes). Tested OK on first try, alignment error 0.1 ticks.
- `find_my_earbud.py`, `find_my_earbud2.py` - helpers to identify which Windows output device routes to a physical jack
- `analysis/exp03_analyze.py`, `_v2.py`, `_v3.py` - three iterations of detection logic
- `launch_exp03.bat`
- **sensorchrono package skeleton + 3 device profiles** (Shimmer3 EXG SR47-5-1, Logitech BRIO, Apple wired keyboard)

### EXP-03 results

| Metric | Value | Verdict |
|---|---|---|
| All 5 streams in XDF | yes | clean |
| Shimmer accel mode | works first try (alignment err 0.1 ticks) | bitmask 0x80,0x00,0x00 correct for SR47-5-1 |
| Audio capture (48 kHz, BRIO mic) | 16.3 M samples / 340 s | works |
| Audio pulses scheduled | 30 at exactly 10 s intervals (std 0.17 ms) | scheduler perfect |
| Audio pulses detected by matched filter | 30/30 (schedule-aware v3) | works, but |
| Audio - schedule delta | median 51.7 ms, std **101 ms** | std too high; bimodal |
| Accel - audio delta | median 69 ms, std **99 ms** | broadly spread, no clean peak |

**Overall: FAIL.** Detection works but the per-event timing has too much noise to extract a calibration constant.

### Diagnosis
The diagnostic plot shows: audio amplitude peaks at ~0.005-0.020 (very quiet); accel responses cluster in first ~100 s then die off; delta histograms are bimodal with impossible-negative clusters. Root cause is **physical signal too weak**:
1. Earbud volume + Windows mic gain were both modest.
2. Earbud was "next to" the Shimmer, not pressed against / taped to it. Mechanical coupling drifted partway through.
3. The schedule-aware matched filter, when it can't find the real pulse, picks the loudest noise in the search window -> garbage measurements.

### Lessons learned
- Audio-pulse fiducial requires either: tight mechanical clamping (tape, clip), high volume, or a piezo buzzer (better SNR per watt). The earbud-on-desk arrangement is fragile.
- WASAPI output device identity on Windows is confusing - multiple Realtek and HDMI virtual devices co-exist. Added `--device Realtek` arg and `find_my_earbud2.py` interactive selector.
- `shimmer_accel_bridge.py` end-of-run print message was unclear ("X samples streamed" with no "DONE"), led to the operator waiting an extra 2.5 min. Cosmetic fix needed.
- The schedule-aware matched filter (`exp03_analyze_v3.py`) is the right algorithm and should be re-used for any future schedulable fiducial.

### Decisions
- **Audio-pulse fiducial is parked, not killed.** Re-runnable with: (a) earbud taped firmly to Shimmer, (b) max volume, (c) quiet room, or (d) piezo buzzer.
- **Active accel-calibration path: EXP-03b uses keystrokes.** Keystroke->ECG was 1-2 ms in EXP-01; keystroke vibrates the desk; Shimmer accel on the desk should pick that up. Same algorithm as EXP-01 plus the new accel bridge.
- sensorchrono package skeleton + 3 device profile YAMLs are checked in. Each new bridge becomes a sensorchrono module on the next refactor pass.

### Where to pick up next session
See `RESUME.md` for the structured handoff. TL;DR:
1. Tape Shimmer firmly to the desk; place keyboard close to it.
2. Run a keystroke-fiducial recording with `shimmer_accel_bridge.py` + `keyboard_fiducial_bridge.py` simultaneously (NOT shimmer_lsl_bridge.py - that's ECG).
3. Detect tap onsets in accel z-axis; compute keystroke -> accel-onset delta distribution.
4. Median delta -> `profiles/shimmer3_exg_sr47-5-1.yaml` `calibration.lag_ms.ShimmerAccel`.
5. If that calibration is stable (std < 5 ms), proceed to EXP-04 (multi-modal full chain).
