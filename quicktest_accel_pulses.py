"""Quick 60-second standalone test of audio-pulse vs Shimmer accel.

Plays 10 audio pulses (one every 5 s) through Realtek headphone output
while simultaneously reading Shimmer accel directly over the serial port.
No LSL, no LabRecorder. Saves accel + pulse-schedule to a NPZ, then plots.

Use this to quickly verify if the earbud-on-Shimmer coupling is sufficient.
"""
import argparse
import struct
import sys
import time
import threading
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import serial
import sounddevice as sd


PULSE_FREQ = 200.0       # accelerometer-friendly (vs 1 kHz, too high)
PULSE_DUR_S = 0.100      # 25 accel samples at 256 Hz (vs 5)
PULSE_INTERVAL_S = 5.0
N_PULSES = 10
TOTAL_S = 60.0
SAMPLE_RATE = 48000
ACCEL_SAMPLE_HZ = 256


def make_pulse():
    n = int(SAMPLE_RATE * PULSE_DUR_S)
    t = np.arange(n) / SAMPLE_RATE
    sig = (np.sin(2 * np.pi * PULSE_FREQ * t) * 0.95).astype(np.float32)
    fade = max(1, int(0.0002 * SAMPLE_RATE))
    sig[:fade] *= np.linspace(0, 1, fade)
    sig[-fade:] *= np.linspace(1, 0, fade)
    return sig


def find_realtek_output():
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0 and "realtek" in d["name"].lower():
            return i
    return sd.default.device[1]


def shimmer_send(ser, cmd, name):
    ser.write(cmd)
    t0 = time.time()
    while time.time() - t0 < 2:
        b = ser.read(1)
        if b == b"\xff":
            print(f"  {name}: ACK")
            return True
    print(f"  {name}: TIMEOUT")
    return False


def accel_reader(ser, out_buf, stop_event):
    """Read accel packets continuously, append (t_perf, ts_dev, ax, ay, az) to out_buf."""
    buf = b""
    PKT = 10
    # Find packet alignment from a small initial buffer
    sync = b""
    while len(sync) < PKT * 10:
        sync += ser.read(PKT * 10 - len(sync))
    best_off, best_err = 0, float("inf")
    for offset in range(PKT):
        scores, prev, pos = [], None, offset
        while pos + 4 <= len(sync):
            t0 = sync[pos+1]; t1 = sync[pos+2]; t2 = sync[pos+3]
            ts = t0 + (t1 << 8) + (t2 << 16)
            if prev is not None:
                d = (ts - prev) & 0xFFFFFF
                scores.append(abs(d - 128))
            prev = ts
            pos += PKT
        if scores:
            score = sum(scores) / len(scores)
            if score < best_err:
                best_err, best_off = score, offset
    print(f"[accel] alignment: offset={best_off}, err={best_err:.2f} ticks")
    buf = sync[best_off:]

    while not stop_event.is_set():
        chunk = ser.read(ser.in_waiting or PKT)
        if chunk:
            buf += chunk
        while len(buf) >= PKT:
            pkt = buf[:PKT]; buf = buf[PKT:]
            ts = pkt[1] + (pkt[2] << 8) + (pkt[3] << 16)
            ax = struct.unpack("<h", pkt[4:6])[0]
            ay = struct.unpack("<h", pkt[6:8])[0]
            az = struct.unpack("<h", pkt[8:10])[0]
            out_buf.append((time.perf_counter(), ts, ax, ay, az))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="COM3")
    parser.add_argument("--out-dir", default=r"C:\Users\ngoldbla\Desktop\LSL_data\quicktest")
    args = parser.parse_args()
    Path(args.out_dir).mkdir(parents=True, exist_ok=True)

    # 1. Open Shimmer + start accel
    print(f"[quicktest] opening {args.port}")
    ser = serial.Serial(args.port, 115200, timeout=1)
    ser.reset_input_buffer(); ser.reset_output_buffer()
    shimmer_send(ser, struct.pack("B", 0x20), "STOP")
    time.sleep(0.3)
    ser.reset_input_buffer()
    shimmer_send(ser, struct.pack("BBBB", 0x08, 0x80, 0x00, 0x00), "SET_SENSORS accel")
    shimmer_send(ser, struct.pack("<BH", 0x05, int((2 << 14) / ACCEL_SAMPLE_HZ)),
                 f"RATE {ACCEL_SAMPLE_HZ}")
    shimmer_send(ser, struct.pack("B", 0x07), "START")

    out_buf = []
    stop_ev = threading.Event()
    reader = threading.Thread(target=accel_reader, args=(ser, out_buf, stop_ev), daemon=True)
    reader.start()
    print("[accel] reading...")

    # 2. Open audio output
    out_dev = find_realtek_output()
    print(f"[audio] output device {out_dev}: {sd.query_devices()[out_dev]['name']}")
    pulse = make_pulse()

    # 3. Fire pulses at known times, record schedule + audio captured
    print(f"\n[run] will play {N_PULSES} pulses, one every {PULSE_INTERVAL_S}s, "
          f"total {TOTAL_S}s")
    print(f"[run] **listen** in the earbud taped to Shimmer; you should hear each pulse")
    t_start = time.perf_counter()
    schedule = []
    # Start audio capture
    audio_buf = []
    def audio_cb(indata, frames, t, status):
        audio_buf.append((time.perf_counter(), indata.copy()))
    audio_in = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, blocksize=480,
                              dtype="float32", callback=audio_cb, device=None)
    audio_in.start()
    print(f"[audio] capturing from default mic")

    for k in range(N_PULSES):
        t_target = t_start + 1.0 + k * PULSE_INTERVAL_S
        while time.perf_counter() < t_target:
            time.sleep(0.001)
        t_fire = time.perf_counter()
        sd.play(pulse, samplerate=SAMPLE_RATE, device=out_dev, blocking=False)
        schedule.append(t_fire)
        print(f"[pulse] #{k+1} at t={t_fire - t_start:6.2f}s")

    while time.perf_counter() - t_start < TOTAL_S:
        time.sleep(0.1)

    # Stop everything
    stop_ev.set()
    time.sleep(0.5)
    audio_in.stop(); audio_in.close()
    ser.write(struct.pack("B", 0x20))
    time.sleep(0.2)
    ser.close()
    print(f"\n[done] captured {len(out_buf)} accel samples, {len(audio_buf)} audio blocks")

    # Build arrays
    accel = np.array(out_buf)         # cols: perf_t, ts_dev, ax, ay, az
    accel_t = accel[:, 0] - t_start
    az = accel[:, 4] / 83.0 / 1000.0  # nominal g
    audio_data = np.concatenate([b[1].flatten() for b in audio_buf]) if audio_buf else np.array([])
    audio_t0 = audio_buf[0][0] - t_start if audio_buf else 0
    audio_t_axis = audio_t0 + np.arange(len(audio_data)) / SAMPLE_RATE
    schedule_rel = np.array([s - t_start for s in schedule])

    # Save
    np.savez(Path(args.out_dir) / "quicktest.npz",
             accel_t=accel_t, az=az, audio=audio_data, audio_t=audio_t_axis,
             schedule=schedule_rel)

    # 4. Quick analysis
    print(f"\n=== Quick analysis ===")
    print(f"accel z range: {np.min(az)*1000:.2f} to {np.max(az)*1000:.2f} mg")
    print(f"accel z std (HP-filtered): ", end="")
    from scipy.signal import butter, sosfiltfilt
    fs = 1.0 / np.median(np.diff(accel_t))
    sos = butter(4, 20.0, btype="high", fs=fs, output="sos")
    az_hp = sosfiltfilt(sos, az)
    print(f"{np.std(az_hp)*1000:.3f} mg")

    # For each scheduled pulse, look in a +/- 100ms window for accel peak
    deltas = []
    snrs = []
    for st in schedule_rel:
        i_lo = np.searchsorted(accel_t, st - 0.05)
        i_hi = np.searchsorted(accel_t, st + 0.25)
        if i_hi - i_lo < 5: continue
        seg = az_hp[i_lo:i_hi]
        seg_t = accel_t[i_lo:i_hi]
        peak_i = np.argmax(np.abs(seg))
        peak_val = abs(seg[peak_i])
        # SNR vs rest of segment
        mask = np.ones_like(seg, dtype=bool); mask[max(0, peak_i-3):peak_i+4] = False
        noise = np.median(np.abs(seg[mask])) if mask.sum() > 5 else np.median(np.abs(seg))
        snr = peak_val / (noise + 1e-12)
        deltas.append(seg_t[peak_i] - st)
        snrs.append(snr)
    deltas = np.array(deltas) * 1000
    snrs = np.array(snrs)
    print(f"\nAccel peak in [-50ms, +250ms] window around each scheduled pulse:")
    for k, (d, s) in enumerate(zip(deltas, snrs), 1):
        flag = "OK" if s > 3 else "low"
        print(f"  pulse #{k:2d}: delta={d:7.2f} ms  SNR={s:5.1f}  [{flag}]")
    good = snrs > 3
    if good.sum() > 0:
        print(f"\nDetections with SNR > 3: {good.sum()}/{len(snrs)}")
        print(f"  delta median: {np.median(deltas[good]):.2f} ms")
        print(f"  delta std:    {np.std(deltas[good]):.2f} ms")
        print(f"  delta range:  [{np.min(deltas[good]):.2f}, {np.max(deltas[good]):.2f}] ms")

    # Plot
    fig, axes = plt.subplots(3, 1, figsize=(12, 9))
    axes[0].plot(accel_t, az_hp * 1000, linewidth=0.5)
    for st in schedule_rel:
        axes[0].axvline(st, color="green", linestyle=":", alpha=0.7)
    axes[0].set_ylabel("accel z HP (mg)")
    axes[0].set_title("Shimmer accel z-axis (high-pass 20 Hz); green=pulse schedule")
    axes[0].grid(True, alpha=0.3)

    if len(audio_data):
        decim = max(1, len(audio_data) // 8000)
        axes[1].plot(audio_t_axis[::decim], audio_data[::decim], linewidth=0.4)
        for st in schedule_rel:
            axes[1].axvline(st, color="green", linestyle=":", alpha=0.7)
        axes[1].set_ylabel("audio")
        axes[1].set_title("BRIO mic audio capture")
        axes[1].grid(True, alpha=0.3)

    if len(deltas):
        axes[2].scatter(np.arange(1, len(deltas)+1), deltas, c=snrs,
                        cmap="viridis", s=80)
        axes[2].axhline(0, color="red", linestyle="--")
        axes[2].set_xlabel("pulse #")
        axes[2].set_ylabel("delta (ms): accel peak - pulse schedule")
        axes[2].set_title("per-pulse delta (color=SNR)")
        plt.colorbar(axes[2].collections[0], ax=axes[2], label="SNR")
        axes[2].grid(True, alpha=0.3)

    fig.tight_layout()
    plot_path = Path(args.out_dir) / "quicktest.png"
    fig.savefig(plot_path, dpi=120)
    plt.close(fig)
    print(f"\nPlot: {plot_path}")


if __name__ == "__main__":
    main()
