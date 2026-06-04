@echo off
cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi
call .venv\Scripts\activate.bat
python keyboard_fiducial_bridge.py --duration 3700 --quiet
echo.
echo === Keyboard bridge exited ===
pause
