@echo off
REM ===================================================================
REM Calibrated multi-modal recording: Shimmer ECG + BRIO video + audio
REM + keyboard fiducial for in-situ lag calibration.
REM
REM USAGE
REM   launchers\launch_calibrated_recording.bat
REM
REM This is the canonical recording launcher. It includes the keyboard
REM bridge automatically because every recording needs at least one
REM in-situ calibration block to anchor absolute lag measurements.
REM
REM PROTOCOL
REM   At the start of every recording, do a 30-second CALIBRATION BLOCK:
REM     1. Sit quietly, no background noise.
REM     2. Type 10-20 keystrokes spaced ~2 seconds apart on a key whose
REM        click is audible (the spacebar is loud and consistent).
REM     3. Make sure your hands are in view of the camera.
REM   AFTER the calibration block, do your real recording activity.
REM   The calibration block provides absolute-lag anchors that
REM   analysis/postprocess.py uses to subtract per-modality lag.
REM
REM AFTER STOPPING
REM   Run the post-processor:
REM     python -m analysis.postprocess PATH\TO\recording.xdf --out-dir OUT\
REM ===================================================================

if "%RECORD_SECONDS%"=="" set RECORD_SECONDS=600
set OUTDIR=C:\Users\ngoldbla\Desktop\LSL_data\recordings\%date:~10,4%%date:~4,2%%date:~7,2%_%time:~0,2%%time:~3,2%%time:~6,2%
set OUTDIR=%OUTDIR: =0%

echo Launching calibrated recording rig (%RECORD_SECONDS% s)
echo Output dir: %OUTDIR%
mkdir "%OUTDIR%" 2>nul

start "LabRecorder" "C:\Users\ngoldbla\Desktop\LabRecorder\LabRecorder\LabRecorder.exe"
ping 127.0.0.1 -n 3 >nul

start "Shimmer ECG" cmd /k C:\Users\ngoldbla\Desktop\LSL_synchronization_multi\launchers\_calibrated_shimmer.bat
ping 127.0.0.1 -n 4 >nul

start "Audio Capture" cmd /k C:\Users\ngoldbla\Desktop\LSL_synchronization_multi\launchers\_calibrated_audio.bat
ping 127.0.0.1 -n 3 >nul

start "Video Capture" cmd /k C:\Users\ngoldbla\Desktop\LSL_synchronization_multi\launchers\_calibrated_video.bat
ping 127.0.0.1 -n 3 >nul

start "Keyboard Fiducial" cmd /k C:\Users\ngoldbla\Desktop\LSL_synchronization_multi\launchers\_calibrated_keyboard.bat

echo.
echo === LabRecorder steps ===
echo   1. Click Update. Verify ALL 6 streams are listed:
echo        ShimmerECG, ShimmerMarkers, ShimmerDiagnostics_ECG,
echo        Audio, KeyboardFiducial, VideoFrames
echo   2. Tick every single one.
echo   3. Click Start. Confirm the .xdf filename appears.
echo.
echo === Verify with the live check-in ===
echo   .venv\Scripts\python.exe analysis\exp06_checkin.py
echo.
echo === Calibration block (FIRST 30 SECONDS) ===
echo   Type 10-20 spacebar presses spaced ~2 seconds apart.
echo   No background noise. Hands visible in camera.
echo.
echo === When done ===
echo   Wait for all bridges to print "exited", then click STOP in LabRecorder.
echo   Then post-process:
echo     python -m analysis.postprocess PATH\TO\recording.xdf --out-dir %OUTDIR%
