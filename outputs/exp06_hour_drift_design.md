# EXP-06: hour-scale multi-modal drift characterization

**Goal:** measure the drift trajectory of the Shimmer ECG clock, BRIO audio
clock, and BRIO video clock against the wired USB keyboard (system clock)
reference, over a one-hour continuous recording. Then fit per-modality
clock models that can be applied offline to re-synchronize all streams.

**Why now:** EXP-00 / EXP-01 / EXP-02 already proved cross-modal alignment
to ≤ 2 ms over 5 min. The open question is whether that holds at hour
scale (where a 30-40 ppm drift accumulates to ~110-150 ms). EXP-03c
(audio pulse coupling) is parked indefinitely due to ground-loop/clipping
issues. The aluminum-keyboard rig sidesteps all the EXP-03 physical
coupling problems.

## Physical setup

- Shimmer3 ECG leads taped to the **underside of an aluminum Apple
  keyboard chassis**. Keystroke mechanical impacts couple into the metal
  and produce small triboelectric / mechanical transients on the EXG
  channels. Lead2 (LL-RA) is the working channel; lead1 has been dead
  since 2026-06-03 and is not required for this experiment.
- BRIO webcam pointed at the keyboard so finger strikes are visible.
- BRIO built-in mic captures the audible click of each keystroke.
- Apple wired USB keyboard provides HID-timestamped fiducials.

## Streams (six total in LabRecorder)

| Stream | Rate | Source bridge |
|---|---|---|
| ShimmerECG | 256 Hz | shimmer_lsl_bridge.py ecg |
| ShimmerMarkers | irregular | (same) |
| ShimmerDiagnostics_ECG | 1 Hz | (same) |
| Audio | 48 kHz | audio_lsl_bridge.py |
| KeyboardFiducial | irregular | keyboard_fiducial_bridge.py |
| (video LSL stream) | ~30 Hz | video_lsl_bridge.py |

Video also writes `frames.csv` + MP4 alongside; the LSL stream carries
per-frame timestamps + frame index.

## Typing protocol (the human side)

Two layers running in parallel:

1. **Natural typing.** Do real work (email, code, notes) — provides
   continuous, randomly-spaced fiducials across the hour. Don't type
   constantly; intermittent bursts give the dataset varied densities.
2. **Scheduled marker bursts** at the 5, 10, 15, ..., 55 min marks
   (11 bursts total). Each burst = **20 spacebar presses at ~1 Hz**.
   These guarantee dense fiducial clusters at known offsets so the drift
   fit has anchor points even if natural typing thins out.

Total target: ≥ 600 keystrokes spread across 3600 s, with at least one
fiducial in every 60 s window. Pass criterion (data side):
`max keystroke gap ≤ 90 s`.

## Recording duration plan

| Bridge | --duration | Why |
|---|---|---|
| Shimmer ECG | `--record-seconds 3600 --no-prompt --start-delay 8` | hour |
| Audio | `--duration 3650` | bookend the hour |
| Video | `--duration 3650` | bookend the hour |
| Keyboard | `--duration 3700` | outlast everything |
| LabRecorder | manual Stop at end | |

All bridges launch ~5-8 s before LabRecorder Start so all outlets exist
before Update; **all five streams must be ticked**. This is the EXP-01 /
EXP-03c failure mode that has bitten us twice — automate the verification
by probing LSL after Start before stepping away.

## Offline analyzer (`analysis/exp06_analyze.py`, to write post-recording)

For each `press` event in `KeyboardFiducial` at LSL time `t_kb`:

1. Search `ShimmerECG` lead2 in `[t_kb - 50 ms, t_kb + 250 ms]` for the
   largest |signal - local_median| excursion above 4-sigma robust noise.
   → `t_ecg`. Compute `delta_ecg = t_ecg - t_kb`.
2. Search `Audio` in `[t_kb - 30 ms, t_kb + 150 ms]` for the click onset
   via a 200-2000 Hz band-pass envelope peak.
   → `t_aud`. Compute `delta_aud = t_aud - t_kb`.
3. Search video frame timestamps for the closest frame to `t_kb`. (Frame
   rate too coarse to detect motion intra-frame from CSV alone, so the
   metric here is `delta_vid = t_vid_nearest - t_kb`, which over an hour
   should track the video clock drift to within ±0.5 frame periods.)
4. Discard keystrokes where no clean fiducial is found on a given
   modality (e.g., overlapping audio noise, hand off keyboard).

Outputs:
- `exp06_drift_trajectories.png` — three subplots: delta_modality vs
  t_kb, with linear fit overlay.
- `exp06_residuals.png` — same after subtracting the linear fit, to
  reveal any non-linear component (temperature drift, thermal step
  responses).
- `exp06_calibration.yaml` — per-modality `{a, b_ppm, n_events,
  rmse_residual_ms}` constants. The b_ppm tells us how much the modality
  clock drifts per million LSL ticks.
- `exp06_summary.md` — verdict per modality:
  - **PASS** if `|b_ppm| < 100` (well within crystal spec) AND residual
    RMSE after fit `< 5 ms` (i.e., a linear model is sufficient).
  - **WARN** if linear fit OK but residual RMSE 5-20 ms (need higher-
    order model).
  - **FAIL** if residual RMSE > 20 ms or non-linear trajectory.

## Disk / storage budget

| File | Estimated size |
|---|---|
| XDF (ECG + Audio + Markers + Video LSL stream) | ~1.0-1.5 GB |
| BRIO mic WAV alongside | ~700 MB |
| Video MP4 (1080p ~30 fps, mjpg) | ~5-10 GB |
| Video frames.csv | ~5 MB |
| **Total** | **~7-12 GB** |

Make sure the destination drive has > 20 GB free before launch.

## Known risks and mitigations

| Risk | Mitigation |
|---|---|
| Streams not all ticked in LabRecorder (EXP-01 / EXP-03c bug) | After Start, probe all 6 stream names from a Python script before declaring "recording" — automated check. |
| Bluetooth disconnect mid-recording | Diagnostics outlet emits packet_loss at 1 Hz; analyzer flags any minute with > 5 % loss. |
| Lead2 of ECG drifts off the chassis during the hour | Tape firmly; lead2 std should remain in the tens-of-counts range; analyzer prints rolling std per minute. |
| Operator forgets a scheduled burst | Set a timer / use a stopwatch app; not catastrophic if a couple bursts are skipped as long as `max keystroke gap ≤ 90 s`. |
| Camera USB power dropout | Video stream gaps are detected by analyzer; ECG/audio/keyboard continue independently. |

## What this experiment closes out

- The "hour-scale drift stability" open question from `RESUME.md`.
- Provides the validation dataset for the to-be-built clock-disciplining
  model (`analysis/shimmer_clock_model.py`).
- Settles the question "is a single linear (a + b·t) fit sufficient per
  recording?" via the residuals plot.
