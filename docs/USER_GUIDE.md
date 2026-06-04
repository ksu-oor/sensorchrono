# SensorChrono — Operator Guide

SensorChrono records **time-aligned ECG, audio, and video** in one session and
automatically produces drift-corrected, lag-calibrated output. It walks you
through a fixed journey and won't let you start recording until every stream is
confirmed live — so the classic mistakes (a dead camera, a stream not ticked in
LabRecorder) can't happen.

You don't need to understand the sync math. Just follow the wizard.

## Before you start

1. Plug in the **Shimmer** (powered on, paired), the **BRIO** (USB), and the
   **keyboard** used for calibration.
2. Make sure **LabRecorder** is running (the app drives it for you; it just
   needs to be open — your admin will have set this up).
3. Double-click **SensorChrono**.

> If you only want to rehearse without hardware, tick **dry run** on the setup
> screen — the app generates synthetic streams so you can practise the flow.

## The wizard, step by step

### 1. Set up
Enter the **participant**, **session**, and **task** labels, and the recording
**duration**. Pick the output folder (your admin usually pre-sets this). Click
**Start session →**. If a label has a space or slash, or the duration is out of
range, you'll see a red message — fix it and retry.

### 2. Preflight
The app checks each device actually responds (COM port opens, camera opens, mic
present, LabRecorder reachable). A green ✓ passes, a yellow ! is a non-blocking
warning, a red ✗ is a blocker. **Proceed** only lights up when nothing is
blocking. If a device is red, check the cable/power and click **Rescan**.

### 3. Staging — the liveness gate
All bridges start and the app watches the live LSL streams. You'll see a table
of each stream's **rate** and **channel count**, plus a **live ECG trace**, a
**mic level meter**, and a **video preview**. Every row must read OK. The big
**Go to Recording →** button stays disabled until **all streams are green** —
this is the gate that guarantees the feeds are really flowing. When it's green,
click it.

### 4. Calibration block
Recording starts and you do the calibration taps: **press the spacebar firmly,
about once every 2 seconds, ~15 times.** The on-screen counter shows how many
**clean** taps were registered (taps closer than ~0.8 s apart are ignored). When
you reach the threshold, **Calibrated — start recording →** lights up.

- These taps are what let the app measure the exact audio/video lag for *this*
  recording. Do them well.
- If you can't get enough clean taps, you can **Skip / accept fallback** — the
  output still works but is labelled **uncalibrated** (it uses stored average
  lags; residuals may exceed ±20 ms).

### 5. Recording
The main recording runs with a live countdown and health readout. It stops
automatically at the duration, or click **Stop recording** to end early. If a
stream dies mid-recording the app goes to an error screen **but keeps the
partial recording**.

### 6. Done
You get a summary: streams, duration, fiducial count, calibrated/uncalibrated,
and the post-processing verdict. From here you can start another session.

## What you get (in the output folder)

| File | What it is |
|---|---|
| `*_video.mp4` | the recorded video |
| `<recording>.xdf` | the raw multi-stream recording (LabRecorder) |
| `pipeline_report.md` / `.json` | what the pipeline did + PASS/WARN/FAIL verdict |
| `shimmer_ecg.csv` | ECG samples on the corrected master clock |
| `frames.csv` | video frame index → corrected timestamp |
| `audio_meta.json` | audio timing on the corrected clock |
| `keyboard_fiducial.csv` | the calibration keystrokes |

## Troubleshooting

| Symptom | Do this |
|---|---|
| A stream is red at staging | Check that device's cable/power; the ECG trace/meter tells you which feed is dead. Go back and Rescan if needed. |
| Calibration counter isn't moving | Tap the **spacebar** (not other keys), firmly, ~2 s apart. Make sure the app window has focus. |
| "uncalibrated" on the summary | You didn't reach enough clean taps. The data is still usable; redo the calibration next session for measured lag. |
| Error screen mid-recording | The partial recording is saved. Note the message and tell your admin. |
| App won't start / "protected your PC" | First-run Defender prompt — see the Setup Guide (admin). |
