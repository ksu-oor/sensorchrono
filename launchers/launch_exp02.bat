@echo off
echo Launching EXP-02: ECG + keyboard + video

mkdir "C:\Users\ngoldbla\Desktop\LSL_data\EXP02_video" 2>nul

start "LabRecorder" "C:\Users\ngoldbla\Desktop\LabRecorder\LabRecorder\LabRecorder.exe"
ping 127.0.0.1 -n 3 >nul

start "Keyboard Fiducial" cmd /k "cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi && .venv\Scripts\activate.bat && python keyboard_fiducial_bridge.py --duration 600"
ping 127.0.0.1 -n 2 >nul

start "Video Bridge" cmd /k "cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi && .venv\Scripts\activate.bat && python video_lsl_bridge.py --duration 360 --tag EXP02 --out-dir C:\Users\ngoldbla\Desktop\LSL_data\EXP02_video"
ping 127.0.0.1 -n 3 >nul

start "Shimmer Bridge EXP02" cmd /k "cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi && .venv\Scripts\activate.bat && python shimmer_lsl_bridge.py ecg --ecg-port COM3 --record-seconds 300"

echo All launched. Switch to LabRecorder; expect 5 streams:
echo   ShimmerECG, ShimmerMarkers, ShimmerDiagnostics_ECG, KeyboardFiducial, VideoFrames
