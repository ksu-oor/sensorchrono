"""Audio pulse fiducial bridge.

Plays a short tone burst (default 1 ms at 4 kHz) through the system default
output (intended: a wired earbud touching the Shimmer case and within
acoustic range of the BRIO mic) at a regular interval (default 10 s).

Pushes an LSL marker per pulse with metadata. IMPORTANT: this LSL marker
is the SCHEDULE TIME of the pulse (when sounddevice was asked to play it),
not the playback latency. The TRUE fiducial time is the mic-detected
onset post-hoc. The schedule marker is included for cross-checking only.

Schedule marker stream `AudioPulseSchedule` (Markers):
    {"seq": <int>, "freq_hz": <float>, "dur_ms": <float>}

Place the earbud in physical contact with the Shimmer device and within
~30 cm of the BRIO mic before running.
"""
import argparse
import json
import sys
import threading
import time

import numpy as np
import pylsl
import sounddevice as sd


def make_pulse(freq_hz, dur_ms, sample_rate, fade_ms=0.2):
    n = int(sample_rate * dur_ms / 1000.0)
    t = np.arange(n) / sample_rate
    sig = np.sin(2 * np.pi * freq_hz * t).astype(np.float32) * 0.95
    # short raised-cosine fade in/out so onsets don't have DC clicks
    fade_n = max(1, int(sample_rate * fade_ms / 1000.0))
    if fade_n * 2 < n:
        w = 0.5 * (1 - np.cos(np.pi * np.arange(fade_n) / fade_n))
        sig[:fade_n] *= w
        sig[-fade_n:] *= w[::-1]
    return sig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freq", type=float, default=1000.0,
                        help="Tone frequency in Hz (default 1000 = clearly audible)")
    parser.add_argument("--duration-ms", type=float, default=20.0,
                        help="Pulse duration in ms (default 20 = unambiguously audible)")
    parser.add_argument("--interval-s", type=float, default=10.0,
                        help="Inter-pulse interval in seconds (default 10)")
    parser.add_argument("--n-pulses", type=int, default=0,
                        help="Stop after N pulses. 0 = run until duration or Ctrl+C.")
    parser.add_argument("--duration", type=float, default=0.0,
                        help="Auto-stop after N seconds. 0 = run until Ctrl+C.")
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument("--device", default=None,
                        help="Output device name substring (default = system default)")
    args = parser.parse_args()

    # Resolve output device
    if args.device:
        out_idx = None
        for i, d in enumerate(sd.query_devices()):
            if args.device.lower() in d["name"].lower() and d["max_output_channels"] > 0:
                out_idx = i
                break
        if out_idx is None:
            sys.exit(f"No output device matching '{args.device}'")
    else:
        out_idx = sd.default.device[1]
    out_info = sd.query_devices()[out_idx]
    print(f"[pulse] output device: #{out_idx}: {out_info['name']}")
    print(f"[pulse] pulse: {args.duration_ms:.2f} ms @ {args.freq:.0f} Hz, every {args.interval_s:.1f} s")
    print(f"[pulse] NOTE: place earbud against Shimmer case and within ~30 cm of mic.")

    pulse = make_pulse(args.freq, args.duration_ms, args.sample_rate)

    info = pylsl.StreamInfo(
        name="AudioPulseSchedule",
        type="Markers",
        channel_count=1,
        nominal_srate=pylsl.IRREGULAR_RATE,
        channel_format=pylsl.cf_string,
        source_id="audio_pulse_player",
    )
    info.desc().append_child_value("manufacturer", "sensorchrono")
    ch = info.desc().append_child("channels").append_child("channel")
    ch.append_child_value("label", "marker_json")
    ch.append_child_value("type", "Markers")
    outlet = pylsl.StreamOutlet(info)
    print(f"[pulse] LSL outlet 'AudioPulseSchedule' is live.")

    t_start = pylsl.local_clock()
    t_end = t_start + args.duration if args.duration > 0 else None
    seq = 0

    try:
        # Pre-warm: open and close a short stream to avoid first-pulse latency hit
        sd.play(np.zeros(int(0.01 * args.sample_rate), dtype=np.float32),
                samplerate=args.sample_rate, device=out_idx)
        sd.wait()

        next_pulse_t = pylsl.local_clock() + 1.0   # first pulse after 1 s
        while True:
            now = pylsl.local_clock()
            if t_end is not None and now >= t_end:
                print(f"[pulse] duration {args.duration}s reached.")
                break
            if args.n_pulses > 0 and seq >= args.n_pulses:
                print(f"[pulse] n_pulses {args.n_pulses} reached.")
                break

            sleep_for = next_pulse_t - now
            if sleep_for > 0:
                time.sleep(min(sleep_for, 0.05))
                continue

            # Fire pulse: take LSL timestamp at the moment we hand it to sd.play
            t_fire = pylsl.local_clock()
            sd.play(pulse, samplerate=args.sample_rate, device=out_idx)
            seq += 1
            payload = json.dumps({
                "seq": seq,
                "freq_hz": args.freq,
                "dur_ms": args.duration_ms,
            }, separators=(",", ":"))
            outlet.push_sample([payload], t_fire)
            print(f"[pulse] fired #{seq} at t={t_fire - t_start:7.2f}s")
            sd.wait()
            next_pulse_t += args.interval_s
    except KeyboardInterrupt:
        print("\n[pulse] Ctrl+C received.")
    finally:
        print(f"[pulse] stopped. Fired {seq} pulses.")


if __name__ == "__main__":
    main()
