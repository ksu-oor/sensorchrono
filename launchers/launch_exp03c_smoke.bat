@echo off
REM EXP-03c smoke test: red+green Shimmer ECG leads on Logi USB headset driver.
REM Confirms electrical coupling BEFORE committing to a 5-min LabRecorder run.
REM Two windows pop up. Wait for ShimmerECG to print "LSL outlet: ShimmerECG @ 256 Hz"
REM in the bridge window, then the smoke test window will fire 5 pulses over ~17 s.

mkdir "C:\Users\ngoldbla\Desktop\LSL_data\EXP03c_smoke" 2>nul

start "Shimmer ECG (smoke)" cmd /k "cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi && .venv\Scripts\activate.bat && python shimmer_lsl_bridge.py ecg --ecg-port COM3 --record-seconds 60 --no-prompt --start-delay 4"
ping 127.0.0.1 -n 6 >nul

start "EXG-Audio Coupling Smoke" cmd /k "cd /d C:\Users\ngoldbla\Desktop\LSL_synchronization_multi && .venv\Scripts\activate.bat && python smoke_test_exg_audio_coupling.py --stream ShimmerECG --device ""Logi USB"" --n-pulses 5 --interval-s 3 --shape thump --freq 50 --dur-ms 30 --channel right --dump-csv C:\Users\ngoldbla\Desktop\LSL_data\EXP03c_smoke\smoke_thump_right.csv & echo. & echo --- now repeating with tone burst for comparison --- & python smoke_test_exg_audio_coupling.py --stream ShimmerECG --device ""Logi USB"" --n-pulses 5 --interval-s 3 --shape tone --freq 1000 --dur-ms 20 --channel right --dump-csv C:\Users\ngoldbla\Desktop\LSL_data\EXP03c_smoke\smoke_tone_right.csv"

echo.
echo Watch the "EXG-Audio Coupling Smoke" window for SNR / verdict.
echo PASS on any lead = proceed to launch_exp03c_full.bat.
echo FAIL on all = move one of red/green back onto foam, re-run this script.
