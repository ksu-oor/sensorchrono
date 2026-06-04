"""Smoke test: does the EXG pick up audio pulses played through the
Logitech USB headphones (with electrodes taped on a foam layer above the
driver)?

Prereqs (in two separate terminals OR launch the bridge first then this):
  1) shimmer_lsl_bridge.py running and streaming 'ShimmerECG' on LSL
  2) Logitech USB headset plugged in, system audio output set to it
     (or pass --device "Logi USB")

This script does NOT touch LabRecorder. It listens to LSL directly,
fires audio pulses, then prints a pass/fail summary.
"""
import argparse
import csv
import os
import time
import sys
import numpy as np
import pylsl
import sounddevice as sd


def make_pulse(freq_hz, dur_ms, sample_rate, fade_ms=0.5, shape="tone"):
    """shape='tone': sine burst (carrier=freq_hz, length=dur_ms).
       shape='thump': low-frequency half-sine 'thump' (single big cone excursion).
           For 'thump', freq_hz is interpreted as the thump fundamental (e.g. 50 Hz)
           and dur_ms is one full cycle of that wave.
    """
    n = int(sample_rate * dur_ms / 1000.0)
    t = np.arange(n) / sample_rate
    if shape == "thump":
        # one full cycle of a low-freq sine: causes a clean cone push+pull,
        # most energy below 100 Hz so it survives EXG anti-alias filtering.
        sig = (np.sin(2 * np.pi * (1.0 / (dur_ms / 1000.0)) * t) * 0.95).astype(np.float32)
    else:
        sig = (np.sin(2 * np.pi * freq_hz * t) * 0.95).astype(np.float32)
    fade_n = max(1, int(sample_rate * fade_ms / 1000.0))
    if fade_n * 2 < n:
        w = 0.5 * (1 - np.cos(np.pi * np.arange(fade_n) / fade_n))
        sig[:fade_n] *= w
        sig[-fade_n:] *= w[::-1]
    return sig


def resolve_device(name_substr):
    if not name_substr:
        return sd.default.device[1]
    for i, d in enumerate(sd.query_devices()):
        if (name_substr.lower() in d["name"].lower()
                and d["max_output_channels"] > 0):
            return i
    sys.exit(f"No output device matching '{name_substr}'")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stream", default="ShimmerECG",
                    help="LSL stream name to subscribe to")
    ap.add_argument("--device", default="Logi USB",
                    help="Output device name substring (default: Logi USB)")
    ap.add_argument("--n-pulses", type=int, default=5)
    ap.add_argument("--interval-s", type=float, default=3.0)
    ap.add_argument("--freq", type=float, default=1000.0)
    ap.add_argument("--dur-ms", type=float, default=20.0)
    ap.add_argument("--shape", choices=["tone", "thump"], default="tone",
                    help="'tone'=20ms 1kHz sine burst; 'thump'=single low-freq cycle, much better EXG coupling")
    ap.add_argument("--channel", choices=["left", "right", "both"], default="right",
                    help="Which stereo channel(s) to play to. Default 'right' so the silent left driver is a stationary reference for differential EXG leads.")
    ap.add_argument("--sample-rate", type=int, default=48000)
    ap.add_argument("--pre-roll-s", type=float, default=2.0,
                    help="Quiet seconds before first pulse (baseline)")
    ap.add_argument("--post-roll-s", type=float, default=2.0)
    ap.add_argument("--win-ms", type=float, default=250.0,
                    help="Detection window after each pulse")
    ap.add_argument("--dump-csv", default=None,
                    help="If set, save raw EXG samples + pulse times to this CSV path")
    args = ap.parse_args()

    # ---- 1. Find LSL stream ----------------------------------------------------
    print(f"[lsl] resolving stream '{args.stream}' (10 s)...")
    streams = pylsl.resolve_byprop("name", args.stream, 1, timeout=10.0)
    if not streams:
        sys.exit(f"[lsl] no stream named '{args.stream}' found. "
                 f"Is shimmer_lsl_bridge.py running?")
    inlet = pylsl.StreamInlet(streams[0], max_buflen=120)
    inlet.open_stream()
    info = inlet.info()
    nch = info.channel_count()
    srate = info.nominal_srate()
    print(f"[lsl] connected: {info.name()} | {nch} ch @ {srate} Hz")

    # ---- 2. Resolve audio device ----------------------------------------------
    out_idx = resolve_device(args.device)
    out_info = sd.query_devices()[out_idx]
    print(f"[audio] device #{out_idx}: {out_info['name']}")
    pulse_mono = make_pulse(args.freq, args.dur_ms, args.sample_rate, shape=args.shape)
    # Build a stereo pulse: zero one channel so only one driver moves.
    pulse = np.zeros((pulse_mono.shape[0], 2), dtype=np.float32)
    if args.channel in ("left", "both"):
        pulse[:, 0] = pulse_mono
    if args.channel in ("right", "both"):
        pulse[:, 1] = pulse_mono
    print(f"[audio] pulse shape={args.shape} freq={args.freq:.0f}Hz dur={args.dur_ms:.0f}ms channel={args.channel}")

    # ---- 3. Schedule, fire pulses, collect samples ----------------------------
    fire_times = []
    t0 = pulse_t0 = pylsl.local_clock() + args.pre_roll_s
    for k in range(args.n_pulses):
        fire_times.append(pulse_t0 + k * args.interval_s)
    t_end = fire_times[-1] + args.post_roll_s

    print(f"[run] pre-roll {args.pre_roll_s}s, "
          f"{args.n_pulses} pulses @ {args.interval_s}s interval, "
          f"post-roll {args.post_roll_s}s "
          f"(total {t_end - t0 + args.pre_roll_s:.1f}s)")

    # Pre-warm the audio output (avoid first-pulse latency hit)
    sd.play(np.zeros(int(0.01 * args.sample_rate), dtype=np.float32),
            samplerate=args.sample_rate, device=out_idx)
    sd.wait()

    rec_ts, rec_samp = [], []
    fired = 0
    while pylsl.local_clock() < t_end:
        # drain LSL
        chunk, ts = inlet.pull_chunk(timeout=0.0, max_samples=512)
        if chunk:
            rec_samp.extend(chunk)
            rec_ts.extend(ts)
        # fire next pulse if due
        now = pylsl.local_clock()
        if fired < args.n_pulses and now >= fire_times[fired]:
            sd.play(pulse, samplerate=args.sample_rate, device=out_idx)
            print(f"[run] pulse #{fired+1} fired at t={now - t0:6.2f}s")
            fired += 1
        time.sleep(0.005)

    # final drain
    time.sleep(0.5)
    chunk, ts = inlet.pull_chunk(timeout=0.0, max_samples=8192)
    if chunk:
        rec_samp.extend(chunk)
        rec_ts.extend(ts)

    samples = np.asarray(rec_samp, dtype=np.float64)
    ts = np.asarray(rec_ts, dtype=np.float64)
    print(f"[run] collected {len(samples)} EXG samples over {ts[-1]-ts[0]:.1f}s")

    # ---- 4. Analyze ------------------------------------------------------------
    # ShimmerECG channel layout (from bridge): [device_ts/32768, lead1, lead2, lead2-lead1]
    # Skip channel 0 (timestamp), analyze the three signal channels.
    ch_names = ["lead1", "lead2", "lead2-lead1"]
    sig_chs = [1, 2, 3] if nch >= 4 else list(range(1, nch))
    win_s = args.win_ms / 1000.0

    print()
    print(f"{'channel':<14} {'baseline pp':>12} {'pulse pp (mean)':>17}"
          f" {'SNR':>8} {'verdict':>10}")
    print("-" * 70)

    # Build baseline mask: regions far from any pulse
    pulse_mask = np.zeros_like(ts, dtype=bool)
    for tf in fire_times:
        pulse_mask |= (ts >= tf) & (ts < tf + win_s)
    # Baseline = everything else inside [t0 - pre_roll, t_end] minus a 100 ms guard around each pulse
    guard = 0.1
    baseline_mask = np.ones_like(ts, dtype=bool)
    for tf in fire_times:
        baseline_mask &= ~((ts >= tf - guard) & (ts < tf + win_s + guard))

    any_pass = False
    for ch_idx, name in zip(sig_chs, ch_names[:len(sig_chs)]):
        sig = samples[:, ch_idx]
        # Per-pulse peak-to-peak
        pulse_pps = []
        for tf in fire_times:
            m = (ts >= tf) & (ts < tf + win_s)
            if m.sum() >= 4:
                pulse_pps.append(sig[m].max() - sig[m].min())
        if not pulse_pps:
            print(f"{name:<14}  (no samples in pulse windows)")
            continue
        pulse_pp_mean = float(np.mean(pulse_pps))
        # Baseline peak-to-peak over equivalent-length windows
        base = sig[baseline_mask]
        if base.size < 10:
            base_pp = np.nan
        else:
            # Estimate as a robust pp via 5th-95th percentile spread
            base_pp = float(np.percentile(base, 95) - np.percentile(base, 5))
        # Flatline detection: a real electrode always shows >0 pp from noise.
        # If both baseline and pulse are ~0, the channel is disconnected.
        FLATLINE_EPS = 1e-9
        if base_pp < FLATLINE_EPS and pulse_pp_mean < FLATLINE_EPS:
            snr = 0.0
            verdict = "FLATLINE"
        elif base_pp < FLATLINE_EPS:
            # Baseline exactly zero but pulse > 0: still suspicious (likely clipping)
            snr = float("inf")
            verdict = "suspect"
        else:
            snr = pulse_pp_mean / base_pp
            verdict = "PASS" if snr >= 3.0 else "weak"
        any_pass |= (verdict == "PASS")
        print(f"{name:<14} {base_pp:>12.4g} {pulse_pp_mean:>17.4g}"
              f" {snr:>8.2f} {verdict:>10}")

    print()
    print(f"Pulses fired: {fired}/{args.n_pulses}")
    print(f"Overall: {'PASS — coupling detectable' if any_pass else 'FAIL — no clear coupling on any channel'}")

    # Optional CSV dump for visual inspection
    if args.dump_csv:
        os.makedirs(os.path.dirname(args.dump_csv) or ".", exist_ok=True)
        with open(args.dump_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["lsl_time", "dev_ts", "lead1", "lead2", "lead2_minus_lead1"])
            for k in range(len(samples)):
                w.writerow([f"{ts[k]:.6f}"] + [f"{x:.6g}" for x in samples[k]])
        # Also dump pulse times
        pulses_csv = args.dump_csv.replace(".csv", "_pulses.csv")
        with open(pulses_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["pulse_idx", "lsl_time"])
            for i, tf in enumerate(fire_times[:fired]):
                w.writerow([i + 1, f"{tf:.6f}"])
        print(f"[csv] wrote {args.dump_csv} and {pulses_csv}")

    inlet.close_stream()


if __name__ == "__main__":
    main()
