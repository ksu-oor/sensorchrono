"""EXP-06 live check-in.

Run this any time during the hour to verify all six streams are alive
and pushing data. Prints a one-shot status table and exits.

Catches the two failure modes that bit EXP-01 and EXP-03c:
  - a stream's outlet appears in LabRecorder but no samples are flowing
  - a bridge has silently crashed after Start was clicked
"""
import sys
import time
import numpy as np
import pylsl

EXPECTED = {
    "ShimmerECG":               {"min_rate_hz": 240, "type": "ECG"},
    "ShimmerDiagnostics_ECG":   {"min_rate_hz":  0.5, "type": "Diagnostics"},
    "ShimmerMarkers":           {"min_rate_hz":  0,   "type": "Markers"},
    "Audio":                    {"min_rate_hz": 40000, "type": "Audio"},
    "KeyboardFiducial":         {"min_rate_hz":  0,   "type": "Markers"},
    "VideoFrames":              {"min_rate_hz":  20,  "type": "Video"},
}

LISTEN_S = 4.0

print(f"resolving streams (3s)...")
streams = pylsl.resolve_streams(wait_time=3.0)
names_seen = {s.name() for s in streams}

print(f"\n{'stream':<28} {'seen?':>6} {'samples':>8} {'eff_rate':>10} {'verdict':>10}")
print("-" * 70)

all_ok = True
for name, expected in EXPECTED.items():
    matches = [s for s in streams if s.name() == name]
    if not matches:
        print(f"{name:<28} {'NO':>6} {'-':>8} {'-':>10} {'MISSING':>10}")
        all_ok = False
        continue
    inlet = pylsl.StreamInlet(matches[0], max_buflen=8)
    t0 = time.time(); n = 0
    while time.time() - t0 < LISTEN_S:
        chunk, _ = inlet.pull_chunk(timeout=0.3, max_samples=8192)
        if chunk:
            n += len(chunk)
    eff = n / LISTEN_S
    if expected["min_rate_hz"] > 0:
        ok = eff >= expected["min_rate_hz"]
    else:
        ok = True  # marker streams may legitimately be silent for stretches
    verdict = "OK" if ok else "LOW RATE"
    all_ok = all_ok and ok
    print(f"{name:<28} {'YES':>6} {n:>8d} {eff:>10.1f} {verdict:>10}")
    inlet.close_stream()

# Extras: any streams present that we didn't expect
unexpected = names_seen - set(EXPECTED.keys())
if unexpected:
    print(f"\nUnexpected streams also present: {sorted(unexpected)}")

print()
print("ALL STREAMS HEALTHY" if all_ok else "SOMETHING IS WRONG -- investigate before continuing")
sys.exit(0 if all_ok else 1)
