# SensorChrono — Setup & Admin Guide

For the technical installer who configures the lab machine once. Operators then
run sessions with the [Operator Guide](USER_GUIDE.md).

## 1. Install

1. Build the installer (see [build/PACKAGING.md](../build/PACKAGING.md)) or get
   `SensorChrono-<ver>-setup.exe`.
2. Run it (admin rights). It installs to `Program Files\SensorChrono` and makes
   a desktop + Start-menu shortcut.
3. **First run, Windows Defender / SmartScreen** may warn ("Windows protected
   your PC") because the build is unsigned. Click *More info → Run anyway*, or
   add a Defender exclusion for the install folder. (Code-signing removes this;
   out of scope for v1.)

## 2. Hardware prerequisites

| Device | Setup |
|---|---|
| Shimmer3 EXG | Paired over Bluetooth → note the **outgoing COM port** (e.g. COM3). |
| Webcam (any UVC) | USB; provides the **camera** (a device index, usually 0). Any UVC webcam works — a Logitech BRIO was just the reference test unit. |
| Microphone (any input device) | The **mic** (input device by name/index, or the system default). Any input device works. |
| USB keyboard | Wired HID — used for the calibration fiducial. |
| LabRecorder | Installed separately; see §4. |

Find the bindings:
- **COM port:** Device Manager → Ports (COM & LPT) → the Shimmer's *outgoing* port.
- **Camera index:** usually `0`; if multiple cameras, try `0/1/2`.
- **Mic device:** pick your input device by name (e.g. "Microphone (...)") or index, or leave blank for the system default.

## 3. Configure device bindings

Launch the app. On the **Setup** screen (config mode), set the COM port, camera
index, and mic device, then run **Preflight** — it confirms each one actually
responds. Bindings are saved to `config.yaml` so operators don't touch them.

Validation is strict on purpose: a real (non-dry-run) session **cannot start**
without a bound COM port and camera index. This is what prevents wrong-port /
dead-device sessions.

## 4. LabRecorder Remote Control (the one critical check)

SensorChrono drives LabRecorder headlessly so operators never tick stream
checkboxes by hand. It prefers the **Remote Control Server (RCS)** on TCP
**22345**. ⚠️ **Some released `LabRecorder.exe` builds don't ship RCS** — verify
yours once:

```powershell
# With LabRecorder open, from PowerShell:
Test-NetConnection localhost -Port 22345
#   TcpTestSucceeded : True   -> RCS is available, you're done.
```

If RCS is **not** available, the app falls back automatically, in order:
1. **`LabRecorderCLI`** — set its path in config if you have it.
2. **Manual-confirm** — the app prompts the operator to press Start/Stop in
   LabRecorder and confirm. Works everywhere, just not fully hands-off.

To enable RCS: in LabRecorder, ensure the Remote Control option is on (newer
builds), or build LabRecorder from source with RCS, or rely on the fallback.

## 5. Calibration requirement

A valid calibrated recording needs the **30-second calibration block**: ~15
firm spacebar presses ~2 s apart. Without enough clean taps the output is
labelled *uncalibrated* (stored profile lags; residuals may exceed ±20 ms).
Brief operators to do the taps deliberately.

## 6. Known limitation to set expectations

**ECG absolute lag is a lower bound only** (the Bluetooth one-way minimum; it
excludes the Shimmer's internal ADC/filter delay). Audio and video lag are fully
measured per-recording. Don't claim sub-ms ECG-to-physical sync.

---

# Phase 5 — Windows hardware bring-up runbook

The app and pipeline are fully validated on macOS against *real LSL traffic*,
but the **end-to-end hardware path can only be signed off on the Windows lab
machine**. Do this once before declaring v1.0.0.

### Steps
1. Install the app (§1) and configure bindings (§3).
2. Verify LabRecorder RCS (§4). If absent, switch the recorder backend to CLI or
   manual and note it.
3. Run **one real session** (e.g. 5 min) with Shimmer + BRIO + keyboard:
   - Confirm **Preflight** passes for all required devices.
   - Confirm the **staging gate blocks until all four streams are green**
     (ShimmerECG, Audio, VideoFrames, KeyboardFiducial — plus ShimmerDiagnostics).
   - Do the **calibration taps**; confirm the counter reaches threshold.
   - Let it record, then stop.
4. Confirm the outputs exist: `*_video.mp4`, the `.xdf`, and the post-processing
   files (`pipeline_report.md`, `shimmer_ecg.csv`, `frames.csv`, …).

### Acceptance criteria (all must hold)
- [ ] Staging gate correctly **refuses** to enable "Go to Recording" while any
      stream is missing/under-rate (pull a USB cable to verify it goes red).
- [ ] `.xdf` **and** `.mp4` are both written.
- [ ] `pipeline_report.json` `overall_status` is `ok` (or `warn` with only the
      expected ECG-lag-lower-bound note).
- [ ] **Stage-5 residual ≈ 0 ms** after lag subtraction (`5_residual_check` in
      the report — `audio_post_lag_median_ms` and `video_post_lag_median_ms`
      both within a few ms of 0).
- [ ] The Done summary reflects the calibration actually performed
      (calibrated vs uncalibrated, fiducial count).

### If something fails
- Shimmer bridge hangs → confirm the adapter passed `--no-prompt` (it always
  does; a hang means a different issue — check the COM port).
- A stream never goes green → that bridge isn't producing; check its device.
- Post-processing errors → run it directly for detail:
  `python -m analysis.postprocess <recording>.xdf --out-dir OUT --mp4 <recording>.mp4`

Once every box is ticked, this build is **hardware-validated**. Releases are
published **automatically** — there is no manual `git tag` step: merging to `main`
runs `.github/workflows/release.yml`, which bumps the version and publishes the
Windows installer to [Releases](https://github.com/ksu-oor/sensorchrono/releases).
Because the pipeline can't run on hardware, treat this checklist as the gate *before
relying on a build for real recording*: run it against the installed release and
confirm a green checklist before using that build in the lab. To cut a deliberate
minor/major (e.g. the first hardware-blessed `1.1.0`), bump `__version__` in
`sensorchrono/__init__.py` and merge — see [CHANGELOG.md](../CHANGELOG.md).
