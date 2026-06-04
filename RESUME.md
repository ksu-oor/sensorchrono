# Resume Guide

**Last session ended:** 2026-06-04
**Status:** **Sync Suite v1 shipped** + **SensorChrono Phase 0 (app foundation) landed.**

> **SensorChrono productization in progress** — wrapping the proven tiers in a
> guided desktop app under `sensorchrono/`. Phase 0 done (contract/config/
> profiles/DeviceAdapter ABC/simulated adapters + first pytest suite, 57 tests
> green on macOS, no hardware). Capture bridges + `analysis/` untouched. Next:
> Phase 1 orchestration core. See `CHANGELOG.md` 2026-06-04 and the plan.
> Dev note: `pip install pylsl` works on this Python 3.14 box (liblsl 117), so
> real synthetic-LSL dry-run runs on macOS — Windows only needed for hardware.

The Sync Suite pipeline (unchanged, still the analysis engine the app drives):

  1. `launchers/launch_calibrated_recording.bat` opens LabRecorder + 4 bridges with in-situ calibration protocol
  2. `analysis/recording_audit.py` produces one-command per-recording quality reports
  3. `analysis/shimmer_clock_model.py` corrects Shimmer crystal drift, auto-flags anomalies
  4. `analysis/insitu_lag_calibration.py` measures audio + video absolute lag from keystroke fiducials
  5. `analysis/postprocess.py` runs the full 5-stage pipeline end-to-end

Validation on EXP-06 XDF (all 5 stages OK, residual 0.0 ms post-correction). EXP-03/EXP-03c parked permanently. ECG absolute lag remains a lower bound only — awaits external fiducial rig (out of scope for software). `sensorchrono/` package migration still pending.

Read this first when resuming. Detailed history is in `CHANGELOG.md`. Strategic context is in `outputs/`.

---

## What works today (verified)

| Component | File(s) | Verified by |
|---|---|---|
| Shimmer ECG @ 256 Hz | `shimmer_lsl_bridge.py` | EXP-00/01/02/06 |
| Shimmer accel @ 256 Hz (low-noise) | `shimmer_accel_bridge.py` | EXP-03 smoke test + run |
| Audio capture @ 48 kHz from BRIO mic | `audio_lsl_bridge.py` | EXP-03, EXP-06 (99% click-detect rate) |
| Audio pulse player (scheduled tone bursts) | `audio_pulse_bridge.py` | EXP-03 (pulses fired at 0.17 ms interval std) |
| Video @ ~30 fps from BRIO + MP4 + frames.csv | `video_lsl_bridge.py` | EXP-02, EXP-06 |
| Keyboard fiducial (USB HID -> LSL marker) | `keyboard_fiducial_bridge.py` | EXP-01/02/06 |
| pyxdf-based per-experiment analyzers | `analysis/exp0[0-3]_analyze*.py` + `exp06_*` | inline |
| **Post-hoc Shimmer clock model with anomaly flags** | `analysis/shimmer_clock_model.py` | **validated 10 XDFs, 8 PASS, 1 ANOMALY auto-flagged, 1 FAIL auto-flagged** |
| **In-situ absolute-lag calibration (audio + video)** | `analysis/insitu_lag_calibration.py` | **validated EXP-06: audio +46.5 ms, video +1.4 ms** |
| **Per-recording quality audit** | `analysis/recording_audit.py` | **one command, full report** |
| **End-to-end 5-stage post-processing pipeline** | `analysis/postprocess.py` | **all 5 stages OK on EXP-06, residual 0.0 ms** |
| **Calibrated-recording launcher** | `launchers/launch_calibrated_recording.bat` | **canonical one-click rig with calibration protocol** |
| Per-rig device profiles | `profiles/*.yaml` | Shimmer profile has measured `drift_ppm_observed` from 3 runs |
| **SensorChrono app — Phase 0 foundation** | `sensorchrono/{contract,config,profiles,devices/}` | **57 pytest tests green (macOS, hardware-free); real-LSL dry-run round-trip verified** |

## What doesn't work / open

- **ECG absolute lag (`lag_ms.ShimmerECG`) is only a lower bound from in-situ calibration.** The BT one-way minimum (~few ms) excludes the Shimmer's internal ADC + filter-chain delay. Audio/video absolute lag are fully measured. For ECG-physical sync at sub-ms precision, need an external piezo+Arduino LSL marker bridge — hardware build, out of software scope.
- **Audio-clock drift over hour scale is unmeasured.** 5-min recording was too short to bound below ±84 ppm CI with natural typing fiducials. Run simplified EXP-06b (no ECG-coupling expectation) if hour-scale audio drift matters.
- **`sensorchrono` package migration still pending.** Everything works at repo root + `analysis/`. Migration to a proper package layout is a refactor, not new capability.
- **`old9` clock anomaly (251 ppm, 22 ms residual)** is now correctly auto-flagged FAIL by `shimmer_clock_model.py`. Root cause (bridge restart? BT congestion?) still unconfirmed but no longer a blind spot.
- **`old7` zero-ppm anomaly** is now auto-flagged ANOMALY ("b_ppm_exact_zero (likely bridge state reset)"). Same status as above — detected, not yet root-caused.

## Hardware state (assumed unchanged)

| Item | Identifier | Status |
|---|---|---|
| Shimmer3 EXG SR47-5-1 | `Shimmer3-BE1D` on COM3 | paired, working |
| Logitech BRIO | UVC device 0 | working at 1080p @ ~28.5 fps |
| BRIO mic | sounddevice device #1 | working at 48 kHz |
| Apple wired keyboard | VID_05AC&PID_029F | USB HID, working |
| Earbud audio output | `Speakers (Realtek(R) Audio)` / device "Realtek" | works for `sounddevice` output |
| Emotiv Insight 2.0 | not yet powered/paired | TODO |

If Shimmer is unpaired or on a different COM port: see CHANGELOG "Setup completed" section for the pairing procedure.

---

## Immediate next experiment: EXP-03b

**Goal:** Measure `lag_ms.ShimmerAccel` using keystrokes as fiducial.

**Why:** EXP-03 with audio pulses failed (signal too weak). Keystrokes already proved 1-2 ms alignment to ECG in EXP-01; their desk vibration should similarly couple to the Shimmer accelerometer when both sit on the same desk.

**Setup:**
1. Place the Shimmer firmly on the desk close to the keyboard (no tape needed, but flat contact with the desk surface).
2. No electrodes needed (we only care about the on-board accel).
3. Make sure the Shimmer is paired and on COM3 (check Device Manager).

**Bridges to run (4 total):**
- `shimmer_accel_bridge.py --port COM3 --record-seconds 300`
- `keyboard_fiducial_bridge.py --duration 360`
- LabRecorder (capture both streams + their marker streams)

**Streams expected in LabRecorder:**
- `ShimmerAccel`
- `ShimmerMarkers`
- `ShimmerDiagnostics_Accel`
- `KeyboardFiducial`

**During the 5-minute recording:**
- Type naturally + 3 burst patterns of 10 spacebar presses at ~1 Hz.

**Analyzer (to be written, modeled on `exp01_analyze.py`):**
1. Load XDF, locate the 4 streams.
2. For each keystroke at time `t_k`, search `ShimmerAccel` z-axis in `[t_k - 50 ms, t_k + 300 ms]` for the impulse peak using the same windowed detector as `exp03_analyze_v3.py:find_accel_in_window`.
3. Compute delta per keystroke; report median + std + max.
4. Pass if: detection rate >= 80%, std < 5 ms across >=50 keystrokes.

**Calibration constant to update:**
`profiles/shimmer3_exg_sr47-5-1.yaml`:
```yaml
calibration:
  status: measured
  measured_at: <ISO date>
  reference_fiducial: keyboard_keystroke
  n_events: <int>
  lag_ms:
    ShimmerAccel: <median ms>
```

## After EXP-03b passes

Order of next experiments (each ~5 min recording + analyze + update profile YAML):

1. **EXP-04** — Add audio capture + measure `lag_ms.Audio` via keystroke acoustic click.
2. **EXP-05** — Full multi-bridge stress test (Shimmer ECG + accel + video + audio + keyboard) for 5 min.
3. **EXP-06** — Drift characterization: 3 back-to-back 5-min runs, check whether ppm drift slope is stable.
4. **EXP-07** — Emotiv on-desk calibration once you've set up Cortex + creds.
5. **EXP-08** — Combined pipeline shakedown.
6. **EXP-09** — Deliberate fault injection (yank BT, cover camera) to verify the diagnostics catch them.
7. **EXP-10** — 30-min dress rehearsal.
8. **3-hour validation** — the formal MVP acceptance test.

Build `analysis/postprocess.py` (per `outputs/post_processing_design.md`) any time after EXP-06.

## Key documents

- `outputs/lsl_sync_experiment_plan.md` — full experimental roadmap with pass criteria
- `outputs/post_processing_design.md` — five-stage post-processing pipeline spec
- `outputs/PRD_lsl_sync_suite.md` — sensorchrono v1 product requirements
- `CHANGELOG.md` — detailed per-experiment session log

## Conventions to keep

- Recordings save to `C:\Users\ngoldbla\Documents\CurrentStudy\sub-P001\...` (LabRecorder default BIDS path)
- Per-experiment plot + processed CSVs go to `C:\Users\ngoldbla\Desktop\LSL_data\EXP<NN>_<tag>\`
- Analyzers live in `analysis/`. Bridges live at repo root for now; they migrate to `sensorchrono/bridges/` once stable.
- Device profile YAML changes are committed; raw XDFs are NOT (`.gitignore` already covers this).
- Always run all bridges with the same `--duration` (set to `record_seconds + 60` for the wrapper bridges so they outlast the recording).
- Sign off each session with a CHANGELOG entry: what was done, what was learned, what's next.
