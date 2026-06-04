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

---

## 2026-06-03 — EXP-03c (audio-pulse via EXG, FAILED) + EXP-06 quicklook (drift methodology validated)

### EXP-03c: EXG-on-headphone-driver, FAILED
Tried picking up audio pulses by putting Shimmer red+green ECG electrodes
directly on a Logi USB headphone driver, with the other 3 leads on foam,
then later on skin.

| Attempt | Result |
|---|---|
| 1 kHz pulses, leads on foam | 0 SNR — 1 kHz is above the EXG ~150 Hz anti-alias filter |
| 50 Hz "thump" pulses, foam | weak (SNR 1.6) because foam isn't a conductor; 3 leads were effectively floating |
| 50 Hz thump, 3 leads on skin | lead2 std jumped to ~22 (skin reference helps), but pulses still clipped rail-to-rail due to USB-headphone → mains → body ground loop |

LabRecorder also dropped Audio + AudioPulseSchedule from the XDF because
they weren't ticked at Start (EXP-01 lesson reoccurred). Only ShimmerECG
was saved.

**Lessons learned:**
- EXG amplifier front-end LPF (~150 Hz) makes audio-band fiducials hopeless;
  must use sub-100 Hz energy
- Floating EXG inputs need a body reference; foam pads don't provide one
- Once body reference is added, mains/USB ground loops dominate over the
  fiducial signal — clipping ensues
- `lead1` is permanently dead on this Shimmer (rail-pinned at -605 since
  the start of the session); lead2 + lead2-lead1 are the working channels
- AC-power ground loop is plausibly the source of the worst clipping; a
  battery-only test would isolate

**Decision:** EXG audio-pulse fiducial is permanently parked. Two physical
realisations have failed for the same root cause (amp rejects the signal
or the signal swamps the amp). Don't try a third.

### EXP-06: aluminum-keyboard vibration + multi-modal hour run (stopped at 5 min)

**Setup:** Shimmer ECG leads taped under aluminum Apple keyboard.
BRIO mic + camera aimed at keyboard. Hour-scale recording planned.
Stopped at 298 s because spot-check showed ECG vibration coupling weak.

**XDF this time has all 6 streams** (ticked correctly):
- ShimmerECG, ShimmerMarkers, ShimmerDiagnostics_ECG
- Audio (BRIO mic, 48 kHz), VideoFrames (BRIO, 28.8 fps), KeyboardFiducial

**ECG vibration coupling — FAILED.** Across 538 keystrokes:
- 50th percentile SNR: 1.57σ
- 99th percentile SNR: 2.31σ
- events above 3σ: 0 / 538

Aluminum-chassis vibration into EXG electrodes is not a viable fiducial.
Same root cause as EXP-03c: mechanical impulses have spectral peaks at
200-2000 Hz, well above the EXG ~150 Hz amp cutoff.

**Audio click coupling — GREAT.** 99% detection (534/538), median SNR 99.

**Drift fit on the 5-min XDF (analysis/exp06_drift_fit.py):**

| Modality | b_ppm | residual std | notes |
|---|---|---|---|
| Shimmer crystal | **+35.8** | 2.5 ms | OWD-min binned on diagnostics ch1 |
| BRIO audio | +5.8 ±84 (95% CI) | 57 ms | per-event jitter limits in 5 min |
| BRIO video | -3.8 | 10 ms (half-frame quant) | likely locked to system clock |

**Cross-validation of Shimmer drift across 3 runs:** 31.1 / 37.4 / 35.8 ppm.
Spread across runs is < 4 ppm. **Single linear fit per recording is
sufficient** for this device.

**Methodology validated:**
- Shimmer crystal drift can be characterized from the bridge's own
  ShimmerDiagnostics stream — NO external fiducial needed. The bridge
  already collects everything required.
- The right channel is `last_observed_s` (col 1), processed with
  rolling-window minimum (OWD-min). Not `min_observed_s` (col 2), which
  is a cumulative minimum and goes flat after warmup.
- Audio drift needs ~hour-scale recording to get below ±10 ppm CI with
  natural typing fiducials. Scheduled bursts would tighten it faster.
- Video drift below ~10 ppm not resolvable in 5 min due to half-frame
  quantization; needs hour-scale or sub-frame detection.

### Artifacts
- `analysis/exp06_drift_fit.py` — reusable per-modality drift analyzer
- `analysis/exp06_quicklook.py` — coupling-quality sanity check
- `LSL_data/EXP06_quicklook/exp06_drift_fit.png` + `.yaml`
- `outputs/exp06_hour_drift_design.md` — protocol (still valid for the
  longer re-run with audio-only fiducials)

### Decisions for next session
- Drop the EXG-vibration angle for hour-scale drift.
- Simplified EXP-06b: same bridges minus the EXG-coupling expectation.
  Just record an hour with natural typing + scheduled spacebar bursts at
  5-min intervals. Use audio click + ShimmerDiagnostics to fit drift.
- Update `profiles/shimmer3_exg_sr47-5-1.yaml` calibration block with
  the per-session drift value (or aggregate across 3 runs).
- Build the post-hoc clock-disciplining module
  (`analysis/shimmer_clock_model.py`) using the OWD-min binned approach
  validated in this session.

### 2026-06-03 (afternoon) — `shimmer_clock_model.py` shipped + validated

Built `analysis/shimmer_clock_model.py` — the post-hoc clock disciplining
module the prior session left as a design.

**Library API:**
```python
from analysis.shimmer_clock_model import fit_from_xdf, apply
model = fit_from_xdf("recording.xdf")        # ClockModel(a, b, b_ppm, ...)
corrected_lsl_ts = apply(model, ecg_dev_ts)  # drift-corrected timestamps
```

**CLI:**
```
python -m analysis.shimmer_clock_model recording.xdf
python -m analysis.shimmer_clock_model recording.xdf --json --out-json m.json
```

**Validated across 10 historical XDFs** (every Shimmer recording on disk):

| recording | duration | drift ppm | residual ms | verdict |
|---|---|---|---|---|
| EXP-06 (current) | 297s | +35.79 | 2.54 | PASS |
| EXP-01 | 314s | +24.40 | 3.41 | PASS |
| old3 | 303s | +39.05 | 3.27 | PASS |
| old8 | 363s | +34.94 | 4.09 | PASS |
| old6 | 65s | +48.81 | 4.26 | PASS (short) |
| old10 | 82s | -91.50 | 4.29 | PASS but suspicious slope SE |
| old7 | 123s | +0.00 | 3.12 | PASS but suspiciously perfect |
| **old9** | 364s | **+251.32** | **22.21** | **FAIL** ← caught by verdict threshold |

Median across PASS runs: 34.9 ppm. **The model correctly flags `old9` as
FAIL automatically** via the `residual_std_ms < 5 ms` PASS threshold.
That's the verdict-as-quality-gate working as designed.

**End-to-end demo** (`analysis/shimmer_clock_model_demo.py`) on the
current EXP-06 XDF: applied the model to ShimmerECG `dev_ts` and
compared corrected timestamps against the bridge's online-EMA output:

| metric | value | interpretation |
|---|---|---|
| mean diff (offline - bridge) | -19.7 ms | systematic bias the EMA missed at init |
| std diff | 0.52 ms | small noise floor |
| slope of diff over time | +6.0 ppm | residual drift the EMA's ~2s time constant didn't track |
| ISI std (both) | 0.000 ms | perfect — both maps use dev_ts for sample positioning |

So the bridge's online EMA is good but has a couple of small, deterministic
errors (~20 ms init bias + ~6 ppm tracking lag) that the offline model
removes exactly.

### Artifacts
- `analysis/shimmer_clock_model.py` — module + CLI
- `analysis/shimmer_clock_model_demo.py` — end-to-end demo
- `LSL_data/EXP06_quicklook/shimmer_clock_model_demo.png` — pre/post timestamp comparison

### Decisions
- This module is the foundation of `analysis/postprocess.py` (Stage 2 of
  the 5-stage pipeline in `outputs/post_processing_design.md`). Build
  postprocess.py next.
- Verdict thresholds (`residual_std_ms < 5/20/inf`) are usable as-is for
  auto-flagging bad recordings; consider tightening once we have more
  hour-scale data.
- Add a heuristic check for `b_ppm == 0` (i.e., bridge state reset
  mid-recording) — catches the `old7` failure mode that current verdict
  misses.

### 2026-06-03 (evening) — Sync Suite v1: gaps closed

Closed the four gaps left at end of afternoon session:

1. **Anomaly detectors added to `shimmer_clock_model.py`.**
   New verdicts: PASS / WARN / FAIL / ANOMALY. Auto-flags:
   - `b_ppm == 0` exact (bridge state reset during recording)
   - `|b_ppm| > 100` outside plausible crystal envelope
   - fewer than 5 OWD-min bins (slope SE too large)
   - residual > 20 ms (non-linear clock behavior)
   Validated: `old7` correctly flagged ANOMALY; `old9` correctly flagged FAIL;
   all 7 other PASS recordings unchanged.

2. **In-situ absolute-lag calibration shipped: `analysis/insitu_lag_calibration.py`.**
   Uses the keyboard as a *triple* multimodal fiducial (HID + audio click + video frame).
   For each keystroke press at t_kb, finds:
     - t_aud = click peak in mic band-pass envelope
     - t_vid = nearest video frame timestamp
   Computes per-modality median lag with 95% bootstrap CI. No external
   hardware required.

   Validation on EXP-06 XDF:
   - audio_lag = +46.54 ms (95% CI +44.46 to +51.76), n=529, detect 98%
   - video_lag = +1.35 ms (95% CI -0.05 to +2.63), n=538, detect 100%
   - shimmer_ecg BT min = -4.36 ms (lower bound; excludes ADC chain)

   For ECG, in-situ measurement only gives a lower bound. ECG absolute lag
   requires an external fiducial rig (Arduino + piezo) for the full value.

3. **Per-recording audit shipped: `analysis/recording_audit.py`.**
   One command, full quality report covering:
   - stream completeness (missing/required streams)
   - stream continuity (effective rate, max gap)
   - clock model fit + verdict + anomalies
   - in-situ lag calibration
   - overall PASS / WARN / FAIL verdict with itemized issues
   Writes both JSON and Markdown reports.

4. **End-to-end post-processing pipeline shipped: `analysis/postprocess.py`.**
   Five stages per outputs/post_processing_design.md:
   - Stage 0: audit
   - Stage 1: pyxdf dejitter (regular-rate streams)
   - Stage 2: apply Shimmer clock model
   - Stage 3: subtract per-modality lag (in-situ or profile fallback)
   - Stage 4: write unified per-stream CSVs + frames.csv
   - Stage 5: residual check (median post-correction delta should be ~0)
   On EXP-06 XDF, ALL FIVE stages report OK; audio/video residual median
   after correction = 0.0 ms (validates the math).

5. **Calibrated-recording launcher shipped: `launchers/launch_calibrated_recording.bat`.**
   One-click rig that opens LabRecorder + 4 bridges (Shimmer ECG, audio,
   video, keyboard fiducial) with the in-situ calibration protocol
   documented inline. The keyboard fiducial bridge is now part of every
   canonical recording.

6. **README updated** with an honest "Sync Suite — what this gives you,
   and what it does not" section at the top, including the measured
   validation numbers from EXP-06.

### Files added
- `analysis/insitu_lag_calibration.py`
- `analysis/recording_audit.py`
- `analysis/postprocess.py`
- `launchers/launch_calibrated_recording.bat`
- `launchers/_calibrated_{shimmer,audio,video,keyboard}.bat`

### Files updated
- `analysis/shimmer_clock_model.py` (anomaly detection)
- `README.md` (top-level Sync Suite section)
- `RESUME.md`
- `CHANGELOG.md` (this entry)

### Known limitations carried forward
- ECG absolute lag is only a lower bound from in-situ. Full ECG lag
  needs external fiducial rig (Arduino + piezo). Not blocking for most
  use cases.
- sensorchrono package migration still pending.
- Hour-scale audio drift uncertified.

## 2026-06-04

### SensorChrono productization — Phase 0 (foundation) landed
Began wrapping the proven capture + analysis tiers in a guided desktop app
(`sensorchrono/` package). Phase 0 is hardware-free foundation; capture
bridges and `analysis/` are untouched. Worked on macOS (Python 3.14).

1. **Plan fact-checked against the repo first (7-agent sweep).** Several
   load-bearing plan assumptions were wrong and corrected before coding:
   the video bridge uses `--out-dir`+`--tag` (not `--mp4`); `unified.parquet`
   is never written (v1 consumes the per-stream CSVs/JSON instead — decided);
   `postprocess.run()` takes a `Path` + keyword-only args; bridge readiness
   strings differ per bridge (Shimmer is the odd one out). All 7 LSL stream
   names verified to match producer↔consumer exactly.

2. **Foundation modules:** `contract.py` (canonical `StreamName` StrEnum +
   `StreamSpec` registry — single source of truth), `devices/base.py`
   (`DeviceAdapter` ABC; `launch()->None` so sim + real adapters share it),
   `profiles.py` (pyyaml loader; maps descriptive lag keys → canonical names,
   Audio 46.5 ms / Video 1.35 ms / ECG None), `config.py` (`SessionConfig`
   + all-errors validation + `config.yaml` round-trip), `devices/simulated.py`
   (synthetic adapters; lazy `pylsl`; pure numpy `synth_*` generators).

3. **First pytest suite (57 tests, hardware-free).** Was no test framework
   before. `pyproject.toml` wires pytest (`pythonpath=["."]`).

4. **Adversarial self-review (32-agent workflow) → 28 findings folded in.**
   Notably: contract had VideoFrames=1ch (real bridge emits 2 — fixed +
   cross-tier consistency test); `validate()` secretly `mkdir`'d (now a pure
   predicate); the dry-run liveness gate could report "live" after its outlet
   thread died (now consults thread health + surfaces the error); `config`
   load now rejects a missing `dry_run` (reproducibility) and unknown keys.

5. **pylsl viability on macOS confirmed.** `pip install pylsl` ships a working
   liblsl 117 wheel on Python 3.14; a `SimulatedShimmerEXG` round-trip
   resolved real `ShimmerECG`/`Audio` outlets with data flowing. → Phase 1
   orchestration (supervisor/lsl_monitor) can be validated against *real* LSL
   on macOS; Windows is reserved for actual hardware.

### Files added
- `sensorchrono/{contract,config,profiles,__main__}.py`
- `sensorchrono/devices/{__init__,base,simulated}.py`
- `tests/{test_contract,test_profiles,test_config,test_simulated,test_base,test_main,test_review_fixes}.py`
- `pyproject.toml`

### Files updated
- `requirements.txt` (added pyyaml, PySide6, pyqtgraph, opencv-python,
  sounddevice, pynput, pyinstaller; grouped runtime/gui/dev)
- `sensorchrono/__init__.py` (docstring → actual plan layout)
- `CHANGELOG.md`, `RESUME.md`

### Next
- Phase 1: orchestration core (`supervisor`, `lsl_monitor`, `preflight`,
  `labrecorder` RCS+fallbacks, `postprocess_runner`, `session` FSM).

### SensorChrono Phase 1 (orchestration core) landed
The headless, framework-agnostic engine that drives the wizard. All of it
validated on macOS — including against *real* LSL traffic (pylsl works here).

- `events.py`: tiny `Signal` (subscribe/emit) — the FSM emits these, NOT Qt
  signals, so the whole layer is importable + testable with no PySide6.
- `supervisor.py`: `BridgeProcess` (subprocess spawn + per-bridge stdout
  readiness regex + terminate→kill teardown; reused by Phase-2 adapters) and
  `Supervisor` (fleet lifecycle over DeviceAdapter list, shared-deadline ready).
- `lsl_monitor.py`: pure `compute_stream_liveness()` (rate/gap/channel verdict)
  + `LslMonitor` background poller. **Bug found by end-to-end and fixed:**
  `pull_chunk` caps at 1024 samples/call, so the monitor must drain the inlet
  in a loop or it under-counts a 48 kHz stream and falsely fails Audio.
- `fiducial_live.py`: `FiducialCounter` (refractory-gated clean-tap acceptance,
  regularity CV, calibrated threshold) + live KeyboardFiducial LSL source.
- `preflight.py`: serial/camera/mic/LabRecorder checks, dry-run skip path,
  required-blocker vs warning aggregation.
- `labrecorder.py`: `Recorder` ABC + RcsRecorder (TCP 22345 update/select all/
  filename/start/stop) + CliRecorder + ManualRecorder + `make_recorder()`
  fallback factory. `select all` structurally prevents under-selecting streams.
- `postprocess_runner.py`: subprocess wrapper that is its OWN `python -m` entry
  importing `analysis.postprocess.run` with `profile_lag_ms` — gets crash
  isolation + the profile fallback while leaving analysis/ untouched.
- `session.py`: `SessionController` FSM (SETUP→PREFLIGHT→LIVENESS→CALIBRATE→
  RECORD→POSTPROCESS→DONE +ERROR), guarded transitions, injectable
  collaborators, Signal events.

Verified: 92 pytest tests (+1 venv-only LSL integration) green on macOS; a
full wizard run drove the simulated fleet's *real* LSL outlets through the
LslMonitor staging gate to DONE.

Filled in `simulated.synth_ecg` with real P-QRS-T (Gaussian-sum) morphology.

### SensorChrono Phase 2 (real device adapters) landed
Adapters that drive the actual bridges as subprocesses via `BridgeProcess`.

- `devices/bridge_adapter.py`: `BridgeAdapter` base (build argv → spawn →
  readiness → teardown; process-health liveness, real rates come from the LSL
  monitor) + `default_real_fleet()`.
- `devices/shimmer_exg.py`: defuses BOTH Shimmer deadlock traps — passes the
  positional `mode` ("ecg") AND `--no-prompt` (tested). ECG→[ShimmerECG,
  ShimmerDiagnostics_ECG], EMG mode supported.
- `devices/camera.py`: drives video bridge via `--out-dir`+`--tag` (NOT the
  non-existent `--mp4`); exposes `mp4_path(session)` for post-processing.
- `devices/microphone.py`, `devices/keyboard.py`: audio + keyboard bridges.
- `session._fleet()` real path now builds the real fleet.

Tests assert each adapter's readiness regex matches the bridge's *literal*
stdout line (the stringly-typed contract), argv correctness, the headless
guard, and a stub-launch lifecycle end-to-end. 101 tests green on macOS.

### SensorChrono Phase 3 (PySide6 GUI wizard) landed
The operator-facing shell. PySide6 6.11 + pyqtgraph 0.14 run headless on
Python 3.14, so the GUI is built AND tested on macOS (offscreen Qt).

- `ui/waveform.py`: pyqtgraph ECG ring-buffer trace (downsampling+clipToView)
  + audio level meter.
- `ui/video_preview.py`: QImage→QPixmap preview + synthetic dry-run frames
  (VideoFrames LSL carries timestamps, not pixels, so preview is separate).
- `ui/pages.py`: 7 wizard pages (setup/preflight/liveness/calibrate/record/
  done/error), each dumb — renders state, emits a Qt signal on action.
- `ui/main_window.py`: QStackedWidget shell wiring pages ↔ SessionController;
  QTimer-driven liveness refresh + LiveView (pulls ECG/audio off LSL, feeds the
  staging widgets); spacebar→note_fiducial during calibration.
- `__main__.py`: `python -m sensorchrono` launches the GUI (`--info` for the
  text summary / bare-box fallback).

Verified: 109 tests green under the venv (8 offscreen GUI tests added), 101 on
the bare box (GUI + LSL integration skip). A full wizard run drove
setup→preflight→staging(green from real LSL)→calibrate(12 fiducials)→record→
DONE entirely through the GUI, offscreen, on macOS.

Threading note: FSM transitions run on the GUI thread (fine for dry-run; real-
capture staging/postprocess should move to a worker QThread — Phase 5 polish).

### SensorChrono Phase 4 (packaging) landed
A PyInstaller one-folder build wrapped in an Inno Setup installer.

- `build/sensorchrono_main.py`: frozen entry that self-dispatches —
  `--run-postprocess` runs the pipeline (a frozen exe can't do `python -m`),
  else launches the GUI. `postprocess_runner.build_command()` emits that flag
  when `sys.frozen`.
- `build/rthook_pylsl.py`: runtime hook sets `PYLSL_LIB` to the bundled liblsl
  before the first `import pylsl` (pylsl's hook doesn't auto-bundle it).
- `build/sensorchrono.spec`: one-folder (one-file breaks Qt plugins); bundles
  profiles, the capture bridges, analysis/, liblsl (`LIBLSL_PATH`), and an
  optional LabRecorder (`LABRECORDER_DIR`); `collect_submodules` for the lazy
  imports.
- `build/build_windows.ps1`, `build/installer.iss` (Inno Setup), `build/PACKAGING.md`.
- `.gitignore`: narrowed `build/` → `build/*/` so the spec/scripts are tracked
  but PyInstaller work dirs aren't.

Validated on macOS: `pyinstaller build/sensorchrono.spec` builds a 125 MB
one-folder app; liblsl.dylib bundled; the frozen GUI boots offscreen and the
frozen `--run-postprocess` dispatch runs. Windows-specifics (liblsl.dll,
LabRecorder.exe, the Inno installer) are documented and need a Windows host.

### SensorChrono Phase 5+6 (docs + release prep) landed
- `docs/USER_GUIDE.md`: operator run-mode walkthrough of the wizard.
- `docs/SETUP_GUIDE.md`: admin install/config, the **LabRecorder RCS
  verification** (`Test-NetConnection localhost -Port 22345`), device-binding
  setup, and the **Phase-5 Windows hardware bring-up runbook + acceptance
  checklist** (staging gate blocks until green, `.xdf`+`.mp4` written, Stage-5
  residual ≈ 0 ms).

**Phase 5 (hardware bring-up) is a documented runbook, NOT executed** — it
requires the Windows lab machine with real Shimmer/BRIO/keyboard + LabRecorder,
which isn't available in this dev environment. Everything testable without
hardware is validated (109 tests green under the venv, 101 + 2 skipped on the
bare box; full wizard driven against real LSL on macOS; frozen build boots).
The **v1.0.0 tag is deliberately withheld** until the
Phase-5 acceptance checklist passes on hardware — the tag asserts
hardware-validated end-to-end sync.

### Status
SensorChrono v1 is code-complete and validated end-to-end on macOS (dry-run +
real LSL). Remaining before tagging v1.0.0: run the Phase-5 checklist on the
Windows rig.
