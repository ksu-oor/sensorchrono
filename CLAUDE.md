# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A research data-acquisition + post-processing toolkit for **multi-modal Lab Streaming Layer (LSL) synchronization**. It captures time-aligned streams from a Shimmer3 ECG/accel unit, a Logitech BRIO (video + mic), and a USB keyboard, records them to a single `.xdf` via LabRecorder, then post-processes that XDF into a **drift-corrected, lag-calibrated, audit-certified** dataset.

There is no application server, build step, or package install — this is a collection of scripts and library modules driven from the command line.

## Platform reality

**This runs on Windows in practice**, against real hardware. Bridges talk to COM ports (Bluetooth Shimmer), `sounddevice` audio devices, UVC cameras, and raw USB HID. Launchers are `.bat` files; many scripts have hardcoded `C:\Users\ngoldbla\...` default paths.

You are likely editing on macOS/Linux where the hardware is absent. **You cannot run the bridges or end-to-end pipeline here** — only edit code and reason about it. The analysis modules (`python -m analysis.*`) can run anywhere given an `.xdf` file as input, but no XDFs are committed (gitignored).

## Architecture — the two tiers

**Tier 1 — real-time bridges (repo root).** Each `*_lsl_bridge.py` captures one modality and pushes it to LSL as a named stream, plus a `*Markers` and/or `*Diagnostics_*` sidecar stream:

| Bridge | LSL stream(s) it creates |
|---|---|
| `shimmer_lsl_bridge.py` | `ShimmerECG` / `ShimmerEMG`, `ShimmerMarkers`, `ShimmerDiagnostics_*` |
| `shimmer_accel_bridge.py` | `ShimmerAccel`, diagnostics |
| `video_lsl_bridge.py` | `VideoFrames` (+ writes `.mp4` and `frames.csv`) |
| `audio_lsl_bridge.py` | `Audio` (48 kHz from BRIO mic) |
| `keyboard_fiducial_bridge.py` | `KeyboardFiducial` (USB HID keystroke → LSL marker) |

LabRecorder (external, not in repo) subscribes to these and writes the `.xdf`.

**Tier 2 — post-hoc analysis (`analysis/`).** Reads the recorded `.xdf` (via `pyxdf`) and produces corrected timestamps + reports. These modules are **dual library + CLI** — they expose importable functions *and* a `main(argv)`, run as `python -m analysis.<module>`:

- `shimmer_clock_model.py` — fits Shimmer crystal drift `corrected = a + b*dev_ts` from the 1 Hz `ShimmerDiagnostics_ECG` stream (one-way-delay min-filter + Theil-Sen). Auto-flags anomalies (`b_ppm==0`, `|b_ppm|>100`, residual >20 ms).
- `insitu_lag_calibration.py` — measures absolute audio/video lag using every keystroke as a free fiducial (HID time vs. mic click vs. nearest video frame).
- `recording_audit.py` — one-command per-recording PASS/WARN/FAIL quality report (completeness + drift + lag).
- `postprocess.py` — the canonical **5-stage end-to-end pipeline**; composes the three modules above. Stages: dejitter → apply clock model → subtract per-modality lag → build unified table + frame map → re-detect fiducials and certify residuals.
- `exp0[0-6]_*.py` — per-experiment analyzers from dev sessions; treat as historical references, not active API.

### The contract that ties the tiers together

Analysis code hard-references LSL **stream names** as strings (`"ShimmerECG"`, `"Audio"`, `"VideoFrames"`, `"KeyboardFiducial"`, `"ShimmerDiagnostics_ECG"`). Renaming a stream in a bridge silently breaks downstream analysis. Keep names in sync, and prefer adding `main()`-callable + importable functions when extending `analysis/` so `postprocess.py` can compose them.

## Common commands

```bash
# Post-process a recording end-to-end (primary analysis workflow)
python -m analysis.postprocess PATH/TO/recording.xdf --out-dir OUT/
python -m analysis.postprocess recording.xdf --mp4 recording.mp4

# Quality report for a single recording
python -m analysis.recording_audit recording.xdf

# Fit/inspect Shimmer drift, or in-situ lag, on their own
python -m analysis.shimmer_clock_model recording.xdf
python -m analysis.insitu_lag_calibration recording.xdf

# Inspect an XDF interactively (opens a file picker + plots)
python plot_xdf_streams.py

# Start live bridges (Windows + hardware only)
python run_lsl_streams.py                 # interactive Shimmer/EMOTIV launcher
launchers\launch_calibrated_recording.bat # canonical one-click multi-bridge rig
```

`requirements.txt` (`pip install -r requirements.txt`): matplotlib, numpy, pyserial, pylsl, pyxdf, scipy, websockets. On Windows the project venv is invoked as `.venv\Scripts\python.exe`.

## Testing

There is **no unit-test framework** (no pytest suite). `quicktest_*.py` and `smoke_test_*.py` are manual hardware-in-the-loop scripts. Validation is empirical: run a module against a real `.xdf` and check the reported residuals/verdict (e.g. Stage-5 residual should be ~0 ms after lag subtraction). Don't assume `pytest` exists; when verifying analysis changes, run the relevant `python -m analysis.*` CLI on a sample XDF.

## Conventions

- **`sensorchrono/` is an empty skeleton** — a planned future package home for the bridges. Do not migrate code into it unless explicitly asked; everything currently lives at repo root + `analysis/`.
- Device calibration lives in `profiles/*.yaml` (committed). Raw data — `*.xdf`, `*.csv`, `*.png` — is **gitignored** and lives outside the repo.
- When running multiple bridges together, give them the **same `--duration`** (wrapper bridges typically use `record_seconds + 60` so they outlast the recording window).
- A valid calibrated recording must include a **30-second calibration block** (10–20 firm spacebar presses ~2 s apart) — this is what makes in-situ lag measurable. Without it, lag values are null.
- **Known limitation to respect:** `ShimmerECG` absolute lag is only a *lower bound* (Bluetooth one-way minimum); it excludes internal ADC/filter delay. Audio/video lag are fully measured; ECG is not. Don't claim sub-ms ECG-to-physical sync.

## Where to look for context

- `RESUME.md` — current status, what works/doesn't, next planned experiments. Read first when resuming.
- `CHANGELOG.md` — detailed per-session lab notebook. Sign off each working session with a new entry (what was done / learned / next).
- `outputs/` — design docs: `post_processing_design.md` (pipeline spec), `lsl_sync_experiment_plan.md` (roadmap + pass criteria), `PRD_lsl_sync_suite.md`.
- `README.md` — hardware setup (Shimmer pairing, EMOTIV/Cortex credentials, electrode placement, packet/timing reference).
