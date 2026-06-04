@echo off
cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi
call .venv\Scripts\activate.bat
mkdir "C:\Users\ngoldbla\Desktop\LSL_data\EXP06_drift" 2>nul
python video_lsl_bridge.py --device 0 --width 1280 --height 720 --fps 30 --duration 3650 --tag EXP06 --out-dir C:\Users\ngoldbla\Desktop\LSL_data\EXP06_drift
echo.
echo === Video bridge exited ===
pause
