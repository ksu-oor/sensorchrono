@echo off
cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi
call .venv\Scripts\activate.bat
mkdir "C:\Users\ngoldbla\Desktop\LSL_data\EXP03c_full" 2>nul
python audio_lsl_bridge.py --device BRIO --duration 360 --tag EXP03c --out-dir C:\Users\ngoldbla\Desktop\LSL_data\EXP03c_full
echo.
echo === audio capture exited ===
pause
