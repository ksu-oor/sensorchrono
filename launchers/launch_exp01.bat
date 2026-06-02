@echo off
echo Launching EXP-01: ECG + keyboard fiducial + diagnostics

start "LabRecorder" "C:\Users\ngoldbla\Desktop\LabRecorder\LabRecorder\LabRecorder.exe"
ping 127.0.0.1 -n 3 >nul

start "Keyboard Fiducial" cmd /k "cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi && .venv\Scripts\activate.bat && python keyboard_fiducial_bridge.py --duration 600"
ping 127.0.0.1 -n 2 >nul

start "Shimmer Bridge EXP01" cmd /k "cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi && .venv\Scripts\activate.bat && python shimmer_lsl_bridge.py ecg --ecg-port COM3 --record-seconds 300"

echo All launched. Switch to LabRecorder; expect 4 streams:
echo   ShimmerECG, ShimmerMarkers, ShimmerDiagnostics_ECG, KeyboardFiducial
