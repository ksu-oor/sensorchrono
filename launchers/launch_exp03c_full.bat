@echo off
REM EXP-03c FULL: 5-min LabRecorder XDF recording
REM   - Shimmer ECG (4ch @ 256 Hz)  - electrodes: red+green on Logi USB driver, others on foam
REM   - BRIO mic Audio capture (48 kHz)  - redundant acoustic fiducial
REM   - Scheduled 1 kHz / 20 ms audio pulses through the Logi USB headset, 10 s interval
REM
REM Streams expected in LabRecorder after Update:
REM   ShimmerECG, ShimmerMarkers, ShimmerDiagnostics_ECG, Audio, AudioPulseSchedule
REM
REM Operator steps:
REM   1. Confirm Windows default playback device is "Speakers (Logi USB Headset)"
REM      (Sound settings -> Output). The pulse bridge uses --device "Logi USB" explicitly
REM      but having it as system default also routes any UI sounds away from the headphones.
REM   2. Run this .bat. Five windows open: LabRecorder, ShimmerECG, Audio capture,
REM      Audio pulses, plus this one.
REM   3. In LabRecorder: click Update, tick all 5 streams, set StudyRoot if you want,
REM      then click Start.
REM   4. After ~330 s the bridges finish and the pulse window prints its summary.
REM      Click STOP in LabRecorder.

set OUTDIR=C:\Users\ngoldbla\Desktop\LSL_data\EXP03c_full
mkdir "%OUTDIR%" 2>nul

start "LabRecorder" "C:\Users\ngoldbla\Desktop\LabRecorder\LabRecorder\LabRecorder.exe"
ping 127.0.0.1 -n 3 >nul

REM Shimmer ECG bridge: 300 s recording, headless start after 6 s
start "Shimmer ECG" cmd /k "cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi && .venv\Scripts\activate.bat && python shimmer_lsl_bridge.py ecg --ecg-port COM3 --record-seconds 300 --no-prompt --start-delay 6"
ping 127.0.0.1 -n 3 >nul

REM BRIO audio capture: 330 s so it bookends the ECG window
start "Audio Capture" cmd /k "cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi && .venv\Scripts\activate.bat && python audio_lsl_bridge.py --device BRIO --duration 330 --tag EXP03c --out-dir %OUTDIR%"
ping 127.0.0.1 -n 3 >nul

REM Audio pulse generator: 320 s, 1 kHz / 20 ms / 10 s spacing => ~30 pulses
REM Routed explicitly to Logi USB headset.
start "Audio Pulses" cmd /k "cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi && .venv\Scripts\activate.bat && python audio_pulse_bridge.py --device ""Logi USB"" --interval-s 10 --duration 320 --freq 1000 --duration-ms 20"

echo.
echo All launched. In LabRecorder:
echo   1) Click Update (wait until all 5 streams appear)
echo   2) Tick: ShimmerECG, ShimmerMarkers, ShimmerDiagnostics_ECG, Audio, AudioPulseSchedule
echo   3) Click Start. Wait ~330 s. Click Stop before closing windows.
echo Recording saves under your CurrentStudy BIDS path. Analyzer comes next.
