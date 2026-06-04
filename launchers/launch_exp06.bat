@echo off
REM EXP-06: Hour-scale multi-modal drift characterization.
REM Five windows open (4 bridges + LabRecorder + this orchestrator).
REM See outputs\exp06_hour_drift_design.md for the full protocol.
REM
REM Before running:
REM   - Shimmer ECG leads taped to bottom of aluminum Apple keyboard
REM   - BRIO webcam aimed at keyboard
REM   - Shimmer powered on (blue LED blinking)
REM   - LSL data drive has > 20 GB free
REM   - You can commit to ~1 hour at the desk with intermittent typing
REM
REM Streams expected in LabRecorder after Update:
REM   ShimmerECG, ShimmerMarkers, ShimmerDiagnostics_ECG,
REM   Audio, KeyboardFiducial, BRIOVideo (or whatever video_lsl_bridge names it)

echo Launching EXP-06 (hour drift characterization)

start "LabRecorder" "C:\Users\ngoldbla\Desktop\LabRecorder\LabRecorder\LabRecorder.exe"
ping 127.0.0.1 -n 3 >nul

start "Shimmer ECG" cmd /k C:\Users\ngoldbla\Desktop\LSL_synchronization_multi\launchers\_start_exp06_shimmer.bat
ping 127.0.0.1 -n 3 >nul

start "Audio Capture" cmd /k C:\Users\ngoldbla\Desktop\LSL_synchronization_multi\launchers\_start_exp06_audio.bat
ping 127.0.0.1 -n 3 >nul

start "Video Capture" cmd /k C:\Users\ngoldbla\Desktop\LSL_synchronization_multi\launchers\_start_exp06_video.bat
ping 127.0.0.1 -n 3 >nul

start "Keyboard Fiducial" cmd /k C:\Users\ngoldbla\Desktop\LSL_synchronization_multi\launchers\_start_exp06_keyboard.bat
ping 127.0.0.1 -n 3 >nul

echo.
echo All four bridges + LabRecorder launched.
echo.
echo === LabRecorder steps ===
echo   1. Click Update (wait until ALL 6 streams appear):
echo        ShimmerECG, ShimmerMarkers, ShimmerDiagnostics_ECG,
echo        Audio, KeyboardFiducial, VideoFrames
echo   2. Tick every single one of them.
echo   3. Click Start.
echo   4. Verify the .xdf filename appears in the status bar.
echo.
echo === Then run the checkin from another terminal: ===
echo   .venv\Scripts\python.exe analysis\exp06_checkin.py
echo.
echo === Typing protocol during the hour ===
echo   - Natural typing throughout (work, notes, code, whatever).
echo   - At minutes 5, 10, 15, ..., 55: type SPACE 20 times at ~1 Hz.
echo   - DO NOT close any window until all bridges print their exit lines.
echo.
echo === When all bridges have exited: ===
echo   - Click STOP in LabRecorder. THIS IS MANDATORY.
echo   - Note the XDF path it reports.
