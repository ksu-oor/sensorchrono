@echo off
cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi
call .venv\Scripts\activate.bat
python shimmer_lsl_bridge.py ecg --ecg-port COM3 --record-seconds 120 --no-prompt --start-delay 3
echo.
echo === bridge process exited ===
pause
