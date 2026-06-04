@echo off
cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi
call .venv\Scripts\activate.bat
python audio_pulse_bridge.py --device "Logi USB" --interval-s 10 --duration 340 --freq 1000 --duration-ms 20
echo.
echo === audio pulses exited ===
pause
