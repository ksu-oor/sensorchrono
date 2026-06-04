@echo off
cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi
call .venv\Scripts\activate.bat
if "%RECORD_SECONDS%"=="" set RECORD_SECONDS=600
set /a DUR=%RECORD_SECONDS%+30
python audio_lsl_bridge.py --device BRIO --duration %DUR% --tag calibrated --out-dir C:\Users\ngoldbla\Desktop\LSL_data\recordings\latest
echo. & echo === Audio exited === & pause
