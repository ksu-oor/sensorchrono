@echo off
start "LabRecorder" "C:\Users\ngoldbla\Desktop\LabRecorder\LabRecorder\LabRecorder.exe"
timeout /t 2 /nobreak >nul
start "Shimmer Bridge EXP00" cmd /k "cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi && .venv\Scripts\activate.bat && python shimmer_lsl_bridge.py ecg --ecg-port COM3 --record-seconds 300"
echo Both launched.
