# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**SensorChrono** — a guided desktop app (PySide6 wizard) for time-aligned, multi-modal **Lab Streaming Layer (LSL) synchronization**. It captures streams from a Shimmer3 ECG/EMG unit, a Logitech BRIO (video + mic), and a USB keyboard, records them to one `.xdf` via a bundled LabRecorder, then post-processes that XDF into a **drift-corrected, lag-calibrated, audit-certified** dataset.

The product is the `sensorchrono/` package; `analysis/` is the post-processing pipeline it drives. It ships as a Windows installer (PyInstaller one-folder + Inno Setup, built in CI — see `build/` and `.github/workflows/release.yml`) and is `pip install`-able from source. There IS a real package, a build step, and a `pytest` suite (`tests/`).

## Platform reality

**Real capture runs on Windows**, against hardware. Bridges talk to COM ports (Bluetooth Shimmer), `sounddevice` audio devices, UVC cameras, and raw USB HID. You are likely editing on macOS/Linux where the hardware is absent: **you cannot run the live bridges or end-to-end capture here**. But the **app shell, the analysis pipeline (`python -m analysis.*` on an `.xdf`), and the full `pytest` suite all run anywhere** — the suite self-skips the GUI/LSL tests when PySide6/pylsl are absent. No XDFs are committed (gitignored).

## Architecture — the two tiers

**Tier 1 — real-time capture bridges (`sensorchrono/bridges/`).** Each `*_lsl_bridge.py` captures one modality and pushes it to LSL as a named stream, plus a `*Markers` and/or `*Diagnostics_*` sidecar:

| Bridge (`sensorchrono/bridges/`) | LSL stream(s) it creates |
|---|---|
| `shimmer_lsl_bridge.py` | `ShimmerECG` / `ShimmerEMG`, `ShimmerMarkers`, `ShimmerDiagnostics_*` |
| `video_lsl_bridge.py` | `VideoFrames` (+ writes `.mp4` and `frames.csv`) |
| `audio_lsl_bridge.py` | `Audio` (48 kHz from BRIO mic) |
| `keyboard_fiducial_bridge.py` | `KeyboardFiducial` (USB HID keystroke → LSL marker) |

The bridges are run as subprocesses by the device adapters (`sensorchrono/devices/`). `sensorchrono/bridges/__init__.py` is **deliberately empty** — the bridges pull heavy platform deps (`serial`/`cv2`/`sounddevice`/`pynput`), so they are imported only when actually run, never at package import.

**Tier 2 — post-hoc analysis (`analysis/`).** Reads the recorded `.xdf` (via `pyxdf`) and produces corrected timestamps + reports. Modules are **dual library + CLI** (`python -m analysis.<module>`):

- `shimmer_clock_model.py` — fits Shimmer crystal drift `corrected = a + b*dev_ts` from the 1 Hz `ShimmerDiagnostics_ECG` stream (one-way-delay min-filter + Theil-Sen). Auto-flags anomalies (`b_ppm==0`, `|b_ppm|>100`, residual >20 ms).
- `insitu_lag_calibration.py` — measures absolute audio/video lag using every keystroke as a free fiducial (HID time vs. mic click vs. nearest video frame).
- `recording_audit.py` — one-command per-recording PASS/WARN/FAIL quality report (completeness + drift + lag).
- `postprocess.py` — the canonical **5-stage end-to-end pipeline** composing the three above: dejitter → apply clock model → subtract per-modality lag → build unified table + frame map → re-detect fiducials and certify residuals.

### The contract that ties the tiers together

Analysis code hard-references LSL **stream names** as strings (`"ShimmerECG"`, `"Audio"`, `"VideoFrames"`, `"KeyboardFiducial"`, `"ShimmerDiagnostics_ECG"`) — centralized in `sensorchrono/contract.py`. Renaming a stream in a bridge silently breaks downstream analysis. Keep names in sync, and prefer adding `main(argv)`-callable + importable functions when extending `analysis/` so `postprocess.py` can compose them.

### Frozen-app self-dispatch (important)

In a PyInstaller build, `sys.executable` is `SensorChrono.exe`, not Python — so `python -m module` can't work. The frozen entry `build/sensorchrono_main.py` self-dispatches on a leading flag instead: `--run-postprocess` runs the analysis pipeline, `--run-bridge <module> [args]` runs a capture bridge. The adapters/runner build dev (`-m`) vs frozen (`--run-*`) argv accordingly (`devices/bridge_adapter.py`, `orchestration/postprocess_runner.py`). **If you add a new spawned worker, mirror this pattern** or it will silently relaunch the GUI when frozen.

## Common commands

```bash
# Run the app
python -m sensorchrono                 # GUI (needs PySide6)
python -m sensorchrono --info          # environment + profiles summary, no GUI

# Tests (hardware-free; GUI/LSL tests self-skip if deps absent)
pip install -r requirements.txt -r requirements-dev.txt
pytest -q

# Post-process a recording end-to-end (primary analysis workflow)
python -m analysis.postprocess PATH/TO/recording.xdf --out-dir OUT/
python -m analysis.postprocess recording.xdf --mp4 recording.mp4

# Quality report / drift / lag on their own
python -m analysis.recording_audit recording.xdf
python -m analysis.shimmer_clock_model recording.xdf
python -m analysis.insitu_lag_calibration recording.xdf

# Build the Windows installer (Windows + project venv)
build\build_windows.ps1                # PyInstaller one-folder -> dist\SensorChrono\
# then compile build\installer.iss with Inno Setup
```

`requirements.txt` = runtime deps (PySide6, pyqtgraph, numpy, scipy, pyserial, pylsl, pyxdf, pyyaml, sounddevice, pynput, opencv-python, matplotlib, websockets, pyinstaller). `requirements-dev.txt` = pytest (kept out of the frozen bundle). On Windows the project venv is `.venv\Scripts\python.exe`.

## Testing

There **is** a `pytest` suite in `tests/`, run hardware-free in CI (`.github/workflows/ci.yml`, Linux + offscreen Qt). GUI tests use `importorskip("PySide6")` and LSL tests `importorskip("pylsl")`, so they skip cleanly on a bare box. Keep new tests import-safe the same way; validate analysis changes empirically too (Stage-5 residual should be ~0 ms after lag subtraction). `quicktest_*` / `smoke_test_*` hardware-in-the-loop scripts are gone — the GUI's live LSL monitor + the test suite cover their roles.

## Conventions

- The bridges live in `sensorchrono/bridges/` and are reached **by module name**, not by path — never spawn `[sys.executable, "x_lsl_bridge.py"]` (that's the historical frozen bug). Use the adapter's `build_argv`.
- Device calibration lives in `profiles/*.yaml` (committed). Raw data — `*.xdf`, `*.csv`, `*.png` — is **gitignored** and lives outside the repo.
- When running multiple bridges together, give them the **same `--duration`** (wrapper bridges use `record_seconds + buffer` so they outlast the recording window).
- A valid calibrated recording must include a **30-second calibration block** (10–20 firm spacebar presses ~2 s apart) — this is what makes in-situ lag measurable. Without it, lag values are null.
- **LabRecorder** is auto-launched headlessly via its Remote Control Server (`orchestration/labrecorder_launcher.py`, RCS on `localhost:22345`); if RCS never comes up it falls back to the operator-guided `ManualRecorder`. The fallback is load-bearing — preserve it.
- **Known limitation to respect:** `ShimmerECG` absolute lag is only a *lower bound* (Bluetooth one-way minimum); it excludes internal ADC/filter delay. Audio/video lag are fully measured; ECG is not. Don't claim sub-ms ECG-to-physical sync.
- **Releases are automatic.** Every merge to `main` runs `release.yml`, which auto-bumps the patch and publishes the Windows installer to GitHub Releases. The version authority is `build/next_version.py` (latest git tag + the committed `__version__` *floor* in `sensorchrono/__init__.py`); tags + Releases are the real version record — `__version__` is **not** rewritten back (no bot commits). To cut a minor/major, bump `__version__` and merge. `next_version.py` is **stdlib-only and must not import `sensorchrono`** (it runs before deps install). Keep its logic in sync with `tests/test_next_version.py`. Use `[skip release]` in the merge commit **subject** (first line) to skip a build — a `gate` job checks only the subject, so a body that merely mentions the token won't self-skip (this footgun silently skipped PR #5's own release).

## Where to look for context

- `CHANGELOG.md` — detailed per-session lab notebook. Sign off each working session with a new entry (what was done / learned / next).
- `README.md` — the product page (download, quick start, run-from-source, hardware matrix, project layout).
- `docs/` — `USER_GUIDE.md` (operators), `SETUP_GUIDE.md` (admins), `HARDWARE.md` (Shimmer pairing, electrode placement, packet/timing reference).
- `build/PACKAGING.md` — Windows packaging strategy (PyInstaller one-folder + Inno Setup + bundled LabRecorder).
