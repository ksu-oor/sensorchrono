@echo off
cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi
call .venv\Scripts\activate.bat
mkdir "C:\Users\ngoldbla\Desktop\LSL_data\EXP06_drift" 2>nul
python audio_lsl_bridge.py --device BRIO --duration 3650 --tag EXP06 --out-dir C:\Users\ngoldbla\Desktop\LSL_data\EXP06_drift
echo.
echo === Audio bridge exited ===
pause
