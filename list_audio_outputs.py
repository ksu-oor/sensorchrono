"""List all sounddevice output devices with hostapi + sample rate.
Use this to find the AirPods Max (or any new USB audio device) name substring
to pass into audio_pulse_bridge.py --device.
"""
import sounddevice as sd

hostapis = sd.query_hostapis()
print(f"{'idx':>3}  {'hostapi':<10}  {'out':>3}  {'sr':>6}  name")
print("-" * 80)
for i, d in enumerate(sd.query_devices()):
    if d["max_output_channels"] == 0:
        continue
    ha = hostapis[d["hostapi"]]["name"][:10]
    print(f"{i:>3}  {ha:<10}  {d['max_output_channels']:>3}  "
          f"{int(d['default_samplerate']):>6}  {d['name']}")

print()
print(f"System default output: #{sd.default.device[1]}  "
      f"({sd.query_devices(sd.default.device[1])['name']})")
