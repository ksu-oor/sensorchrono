"""Play a 3-second beep through each output device, with pauses.
Press Enter to advance, type 'y' if you heard it, anything else to skip.
"""
import sys
import time
import numpy as np
import sounddevice as sd

DURATION = 3.0
FREQ = 1000.0
SR = 48000

devices = sd.query_devices()
seen = set()
candidates = []
for i, d in enumerate(devices):
    if d["max_output_channels"] == 0: continue
    if d["name"] in seen: continue
    seen.add(d["name"])
    candidates.append((i, d["name"]))

t = np.arange(int(SR * DURATION)) / SR
sig = (np.sin(2 * np.pi * FREQ * t) * 0.9).astype(np.float32)
fade = int(0.01 * SR)
sig[:fade] *= np.linspace(0, 1, fade)
sig[-fade:] *= np.linspace(1, 0, fade)

heard = []
for i, name in candidates:
    print(f"\n--- Device #{i}: {name} ---")
    input("Press Enter to play 3-second beep through this device... ")
    try:
        sd.play(sig, samplerate=SR, device=i)
        sd.wait()
    except Exception as e:
        print(f"   error: {e}")
        continue
    ans = input("Did you hear it? (y/n): ").strip().lower()
    if ans.startswith("y"):
        heard.append((i, name))

print("\n========================================")
if heard:
    print("Devices you heard:")
    for i, n in heard:
        print(f"  #{i:2d}  {n}")
else:
    print("No device produced audible output. Check earbud connection.")
