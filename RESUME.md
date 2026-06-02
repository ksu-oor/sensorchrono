# Resume Guide

**Last session ended:** 2026-06-02
**Status:** EXP-00, EXP-01, EXP-02 PASSED. EXP-03 (audio-pulse calibration) FAILED — pulse SNR too low. Active next step: EXP-03b (keystroke-based accel calibration).

Read this first when resuming. Detailed history is in `CHANGELOG.md`. Strategic context is in `outputs/`.

---

## What works today (verified)

| Component | File(s) | Verified by |
|---|---|---|
| Shimmer ECG @ 256 Hz | `shimmer_lsl_bridge.py` | EXP-00, EXP-01, EXP-02 |
| Shimmer accel @ 256 Hz (low-noise) | `shimmer_accel_bridge.py` | EXP-03 smoke test + run |
| Audio capture @ 48 kHz from BRIO mic | `audio_lsl_bridge.py` | EXP-03 (recording works; calibration didn't) |
| Audio pulse player (scheduled tone bursts) | `audio_pulse_bridge.py` | EXP-03 (pulses fired at 0.17 ms interval std) |
| Video @ ~30 fps from BRIO + MP4 + frames.csv | `video_lsl_bridge.py` | EXP-02 |
| Keyboard fiducial (USB HID -> LSL marker) | `keyboard_fiducial_bridge.py` | EXP-01, EXP-02 |
| pyxdf-based per-experiment analyzers | `analysis/exp0[0-3]_analyze*.py` | inline |
| Schedule-aware matched-filter pulse detector | `analysis/exp03_analyze_v3.py` | inline |
| Per-rig device profiles | `profiles/*.yaml` | structural, not yet consumed by any tool |
| `sensorchrono/` package skeleton | empty `__init__.py` in subdirs | placeholder for v1 migration |

## What doesn't work / open

- **`calibration.lag_ms.ShimmerAccel` is null.** Needs measurement. Active path: keystroke-based via EXP-03b.
- **`calibration.lag_ms.VideoFrames` is null.** EXP-04 will measure (keystroke -> video frame containing finger).
- **`calibration.lag_ms.Audio` is null.** EXP-04 / EXP-03b will measure (keystroke acoustic click).
- **`calibration.lag_ms.Emotiv*` is null.** EXP-07 will measure.
- **Postprocessor (`analysis/postprocess.py`) is not yet built.** Design in `outputs/post_processing_design.md`.
- **`sensorchrono` package modules are skeleton only.** No code migrated yet.

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
