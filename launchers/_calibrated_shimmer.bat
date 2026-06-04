@echo off
cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi
call .venv\Scripts\activate.bat
if "%RECORD_SECONDS%"=="" set RECORD_SECONDS=600
python shimmer_lsl_bridge.py ecg --ecg-port COM3 --record-seconds %RECORD_SECONDS% --no-prompt --start-delay 8
echo. & echo === Shimmer ECG exited === & pause
