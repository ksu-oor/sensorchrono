@echo off
cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi
call .venv\Scripts\activate.bat
mkdir "C:\Users\ngoldbla\Desktop\LSL_data\EXP03c_smoke" 2>nul
echo === thump shape (50 Hz, in ECG passband) ===
python smoke_test_exg_audio_coupling.py --stream ShimmerECG --device "Logi USB" --n-pulses 5 --interval-s 3 --shape thump --freq 50 --dur-ms 30 --channel right --dump-csv C:\Users\ngoldbla\Desktop\LSL_data\EXP03c_smoke\smoke_thump_right.csv
echo.
echo === thump shape, LEFT channel (cross-check) ===
python smoke_test_exg_audio_coupling.py --stream ShimmerECG --device "Logi USB" --n-pulses 5 --interval-s 3 --shape thump --freq 50 --dur-ms 30 --channel left --dump-csv C:\Users\ngoldbla\Desktop\LSL_data\EXP03c_smoke\smoke_thump_left.csv
echo.
echo === DONE === 
pause
