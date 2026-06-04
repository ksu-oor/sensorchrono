"""Keyboard fiducial bridge.

Captures every key press/release and pushes it to LSL as a marker stream
named `KeyboardFiducial`. The timestamp is `pylsl.local_clock()` taken
inside the pynput callback, so it carries the smallest delay we can
extract from a wired USB HID keyboard (~1 ms polling jitter).

Each marker is a compact JSON string with:
    {"event": "press"|"release", "key": "<name>", "seq": <int>}

The keystroke sequence index makes per-event analysis trivial post-hoc.

Usage:
    python keyboard_fiducial_bridge.py --duration 300

Press Ctrl+C to stop early. Esc by default DOES NOT exit (we don't want
to lose data if you fat-finger Esc). Stop with Ctrl+C in the terminal.
"""
import argparse
import json
import sys
import threading
import time

import pylsl
from pynput import keyboard


class FiducialOutlet:
    def __init__(self, source_id="keyboard_fiducial"):
        info = pylsl.StreamInfo(
            name="KeyboardFiducial",
            type="Markers",
            channel_count=1,
            nominal_srate=pylsl.IRREGULAR_RATE,
            channel_format=pylsl.cf_string,
            source_id=source_id,
        )
        info.desc().append_child_value("manufacturer", "Feynman")
        ch = info.desc().append_child("channels").append_child("channel")
        ch.append_child_value("label", "marker_json")
        ch.append_child_value("type", "Markers")
        self.outlet = pylsl.StreamOutlet(info)
        self.lock = threading.Lock()
        self.seq = 0
        print(f"[keyboard_fiducial] LSL outlet 'KeyboardFiducial' is live.")

    def push(self, event, key_name, ts=None):
        if ts is None:
            ts = pylsl.local_clock()
        with self.lock:
            self.seq += 1
            payload = {"event": event, "key": key_name, "seq": self.seq}
            self.outlet.push_sample([json.dumps(payload, separators=(",", ":"))], ts)
            return ts, self.seq


def key_to_name(key):
    """Best-effort key name. Never raises."""
    try:
        c = getattr(key, "char", None)
        if c is not None:
            return c
    except Exception:
        pass
    try:
        return str(key).replace("Key.", "")
    except Exception:
        return "<unprintable>"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=0.0,
                        help="Auto-exit after N seconds. 0 = run until Ctrl+C.")
    parser.add_argument("--quiet", action="store_true",
                        help="Don't print each keystroke to the console.")
    args = parser.parse_args(argv)

    outlet = FiducialOutlet()
    stop_event = threading.Event()
    t_start = pylsl.local_clock()

    err_count = {"n": 0}

    def on_press(key):
        try:
            name = key_to_name(key)
            ts, seq = outlet.push("press", name)
            if not args.quiet:
                print(f"[{ts - t_start:8.4f}s] #{seq:5d}  press   {name!r}")
        except Exception as e:
            err_count["n"] += 1
            sys.stderr.write(f"[keyboard_fiducial] on_press error #{err_count['n']}: {e!r}\n")
            sys.stderr.flush()

    def on_release(key):
        try:
            outlet.push("release", key_to_name(key))
        except Exception as e:
            err_count["n"] += 1
            sys.stderr.write(f"[keyboard_fiducial] on_release error #{err_count['n']}: {e!r}\n")
            sys.stderr.flush()

    # suppress=False means we don't block the keypress from reaching other apps.
    # The listener catches its own exceptions internally; our callbacks now never raise.
    listener = keyboard.Listener(on_press=on_press, on_release=on_release, suppress=False)
    listener.daemon = True
    listener.start()
    print(f"[keyboard_fiducial] Listening. {'Ctrl+C to stop.' if args.duration == 0 else f'auto-stop in {args.duration:.0f} s.'}")
    print(f"[keyboard_fiducial] Type freely. Burst recommendation: press SPACE 10 times at ~1 Hz a few times during the run.")

    try:
        if args.duration > 0:
            t_end = t_start + args.duration
            while pylsl.local_clock() < t_end and not stop_event.is_set():
                time.sleep(0.1)
        else:
            while not stop_event.is_set():
                time.sleep(0.5)
                if not listener.running:
                    sys.stderr.write("[keyboard_fiducial] WARNING: listener thread is no longer running. Restarting.\n")
                    sys.stderr.flush()
                    listener = keyboard.Listener(on_press=on_press, on_release=on_release, suppress=False)
                    listener.daemon = True
                    listener.start()
    except KeyboardInterrupt:
        print("\n[keyboard_fiducial] Ctrl+C received; stopping.")
    finally:
        listener.stop()
        print(f"[keyboard_fiducial] Stopped. Pushed {outlet.seq} events.")


if __name__ == "__main__":
    main()
