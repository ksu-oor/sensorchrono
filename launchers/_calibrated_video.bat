@echo off
cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi
call .venv\Scripts\activate.bat
if "%RECORD_SECONDS%"=="" set RECORD_SECONDS=600
set /a DUR=%RECORD_SECONDS%+30
python video_lsl_bridge.py --device 0 --width 1280 --height 720 --fps 30 --duration %DUR% --tag calibrated --out-dir C:\Users\ngoldbla\Desktop\LSL_data\recordings\latest
echo. & echo === Video exited === & pause
