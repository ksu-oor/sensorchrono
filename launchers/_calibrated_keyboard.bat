@echo off
cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi
call .venv\Scripts\activate.bat
if "%RECORD_SECONDS%"=="" set RECORD_SECONDS=600
set /a DUR=%RECORD_SECONDS%+60
python keyboard_fiducial_bridge.py --duration %DUR% --quiet
echo. & echo === Keyboard exited === & pause
