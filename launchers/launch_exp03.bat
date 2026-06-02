@echo off
echo Launching EXP-03: Shimmer accel + audio capture + audio pulses

mkdir "C:\Users\ngoldbla\Desktop\LSL_data\EXP03_audio_pulse" 2>nul

start "LabRecorder" "C:\Users\ngoldbla\Desktop\LabRecorder\LabRecorder\LabRecorder.exe"
ping 127.0.0.1 -n 3 >nul

start "Audio Capture" cmd /k "cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi && .venv\Scripts\activate.bat && python audio_lsl_bridge.py --device BRIO --duration 360 --tag EXP03 --out-dir C:\Users\ngoldbla\Desktop\LSL_data\EXP03_audio_pulse"
ping 127.0.0.1 -n 2 >nul

start "Shimmer Accel" cmd /k "cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi && .venv\Scripts\activate.bat && python shimmer_accel_bridge.py --port COM3 --record-seconds 300 --warmup 2"
ping 127.0.0.1 -n 3 >nul

start "Audio Pulses" cmd /k "cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi && .venv\Scripts\activate.bat && python audio_pulse_bridge.py --interval-s 10 --duration 320 --device Realtek"

echo All launched. Switch to LabRecorder; expect streams:
echo   Audio, ShimmerAccel, ShimmerDiagnostics_Accel, ShimmerMarkers, AudioPulseSchedule
