"""Shimmer3 accelerometer-only LSL bridge.

Streams the on-board LOW-NOISE accelerometer (KXTC9-2050) at 256 Hz.
Uses the same tick->LSL clock mapper as the ECG bridge.

Protocol (per Shimmer LogAndStream firmware reference):

  SET_SENSORS (0x08) + 3 bytes (sensors0, sensors1, sensors2)
  Low-noise accelerometer = bit 0x80 of sensors0
  -> Command: 0x08 0x80 0x00 0x00

  SET_SAMPLING_RATE_COMMAND (0x05) + uint16
  rate = 32768 / sample_rate -> for 256 Hz, value = 128
  Protocol uses (2 << 14) / sample_rate -> 32768/256 = 128 (same answer)

  GET_PACKET_FORMAT: each sample packet has
    - 1 byte packet type (0x00 = DATA_PACKET)
    - 3 bytes timestamp (24-bit, little-endian, 32768 Hz ticks)
    - 6 bytes accel payload (3 axes x int16 little-endian)
    = 10 bytes total

  Conversion: low-noise accel is 12-bit ADC mapped to a 16-bit register.
  Sensitivity (range +/- 2g, 8 sensitivity counts/mg per Shimmer docs):
    raw_int / 80.0 / 1000.0 ~ g       (approximate; calibration coefs
    are stored in the device; we use a nominal conversion here)

  If first packet read with this layout looks like garbage (bytes don't
  alternate predictably), this protocol assumption is wrong - we fall
  back to verbose diagnostic mode.
"""
import argparse
import struct
import sys
import threading
import time

import numpy as np
import pylsl
import serial

# Re-use the mapper from the ECG bridge
sys.path.insert(0, ".")
from shimmer_lsl_bridge import LslTimestampMapper, create_marker_outlet, emit_marker


PACKET_SIZE = 10
EXPECTED_DELTA = 128   # 32768 / 256
SENSITIVITY = 83.0     # counts per g, nominal low-noise accel; replace with cal


def send_cmd(ser, cmd, name, accept=(b"\xff",), timeout=3):
    ser.write(cmd)
    start = time.time()
    while time.time() - start < timeout:
        b = ser.read(1)
        if b in accept:
            print(f"[{ser.name}] {name}: ACK")
            return True
    print(f"[{ser.name}] {name}: TIMEOUT")
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="COM3")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--sampling-rate", type=int, default=256)
    parser.add_argument("--record-seconds", type=float, default=300.0)
    parser.add_argument("--warmup", type=float, default=2.0)
    args = parser.parse_args()

    print(f"[accel] opening {args.port}")
    ser = serial.Serial(args.port, args.baud, timeout=1)
    ser.reset_input_buffer()
    ser.reset_output_buffer()

    # Stop in case device was streaming from a previous session
    send_cmd(ser, struct.pack("B", 0x20), "STOP")
    time.sleep(0.3)
    ser.reset_input_buffer()

    # Enable low-noise accelerometer only
    # sensors0=0x80 (A_ACCEL), sensors1=0x00, sensors2=0x00
    send_cmd(ser,
             struct.pack("BBBB", 0x08, 0x80, 0x00, 0x00),
             "SET_SENSORS (low-noise accel)")

    # Set sampling rate
    rate_val = int((2 << 14) / args.sampling_rate)
    send_cmd(ser,
             struct.pack("<BH", 0x05, rate_val),
             f"SET_SAMPLING_RATE = {args.sampling_rate} Hz")

    # Start streaming
    send_cmd(ser, struct.pack("B", 0x07), "START_STREAMING")

    # Read a buffer and find packet alignment by best-matching tick delta
    print(f"[accel] reading initial buffer for alignment...")
    sync_buf = b""
    while len(sync_buf) < PACKET_SIZE * 20:
        sync_buf += ser.read(PACKET_SIZE * 20 - len(sync_buf))

    best_offset, best_score = 0, float("inf")
    for offset in range(PACKET_SIZE):
        scores, prev, pos = [], None, offset
        while pos + 4 <= len(sync_buf):
            # Try: byte 0 is packet-type marker, bytes 1..3 are 24-bit ts LE
            t0, t1, t2 = sync_buf[pos + 1], sync_buf[pos + 2], sync_buf[pos + 3]
            ts = t0 + (t1 << 8) + (t2 << 16)
            if prev is not None:
                d = (ts - prev) & 0xFFFFFF
                scores.append(abs(d - EXPECTED_DELTA))
            prev = ts
            pos += PACKET_SIZE
        if scores:
            score = sum(scores) / len(scores)
            if score < best_score:
                best_score, best_offset = score, offset

    print(f"[accel] alignment: offset={best_offset}, mean-tick-error={best_score:.1f}")
    buffer = sync_buf[best_offset:]

    if best_score > 50:
        # Bad alignment -> probably wrong packet format. Dump raw bytes for debug.
        print(f"[accel] WARNING: poor alignment quality. Dumping first 60 bytes for inspection:")
        print("[accel] hex:", sync_buf[:60].hex())
        print("[accel] If timestamps are garbage, the sensor bitmask or packet structure")
        print("[accel] is wrong for this firmware. Aborting to avoid recording noise.")
        ser.write(struct.pack("B", 0x20))
        ser.close()
        sys.exit(2)

    # LSL outlets
    info = pylsl.StreamInfo("ShimmerAccel", "Accel", 4, args.sampling_rate,
                            pylsl.cf_float32, f"shimmer_accel_{ser.name}")
    chns = info.desc().append_child("channels")
    for label, unit in [("ts_sec", "seconds"),
                        ("accel_x", "g"), ("accel_y", "g"), ("accel_z", "g")]:
        ch = chns.append_child("channel")
        ch.append_child_value("label", label)
        ch.append_child_value("unit", unit)
        ch.append_child_value("type", "Accel")
    info.desc().append_child_value("manufacturer", "Shimmer")
    info.desc().append_child_value("model", "Shimmer3 EXG SR47-5-1 (accel)")
    outlet = pylsl.StreamOutlet(info)
    print(f"[accel] LSL outlet 'ShimmerAccel' is live @ {args.sampling_rate} Hz")

    marker_outlet = create_marker_outlet()
    marker_lock = threading.Lock()
    emit_marker(marker_outlet, marker_lock, "stream_ready", "Accel",
                device_port=ser.name, nominal_srate=args.sampling_rate)

    # Diagnostics outlet (1 Hz)
    diag_info = pylsl.StreamInfo("ShimmerDiagnostics_Accel", "Diagnostics", 5, 1.0,
                                 pylsl.cf_float32, f"shimmer_diag_accel_{ser.name}")
    dchns = diag_info.desc().append_child("channels")
    for label in ["offset_s", "last_observed_s", "min_observed_s",
                  "residual_ms", "samples_since_reset"]:
        ch = dchns.append_child("channel")
        ch.append_child_value("label", label)
        ch.append_child_value("unit", "various")
        ch.append_child_value("type", "Diagnostics")
    diag_outlet = pylsl.StreamOutlet(diag_info)

    mapper = LslTimestampMapper(ticks_per_second=32768)
    diag_stop = threading.Event()

    def diag_worker():
        while not diag_stop.is_set():
            if mapper.offset is not None and mapper.last_observed_offset is not None:
                residual_ms = (mapper.last_observed_offset - mapper.offset) * 1000.0
                diag_outlet.push_sample([
                    float(mapper.offset),
                    float(mapper.last_observed_offset),
                    float(mapper.observed_min_offset or 0.0),
                    float(residual_ms),
                    float(mapper.samples_since_reset),
                ])
            time.sleep(1.0)

    diag_thread = threading.Thread(target=diag_worker, daemon=True)
    diag_thread.start()

    print(f"[accel] streaming for {args.record_seconds:.0f} s (after {args.warmup:.1f} s warmup)...")
    print(f"[accel] press Ctrl+C to stop early")

    t_warmup_end = pylsl.local_clock() + args.warmup
    t_start = None
    n_samples = 0

    try:
        while True:
            chunk = ser.read(ser.in_waiting or PACKET_SIZE)
            if chunk:
                buffer += chunk

            now = pylsl.local_clock()
            if t_start is None and now >= t_warmup_end:
                t_start = now
                emit_marker(marker_outlet, marker_lock, "recording_started", "Accel",
                            timestamp=now)
                print(f"[accel] recording started")

            if t_start is not None and (now - t_start) >= args.record_seconds:
                break

            while len(buffer) >= PACKET_SIZE:
                # packet: [type][ts3][ax_lo,ax_hi,ay_lo,ay_hi,az_lo,az_hi]
                pkt = buffer[:PACKET_SIZE]
                buffer = buffer[PACKET_SIZE:]
                ts = pkt[1] + (pkt[2] << 8) + (pkt[3] << 16)
                ax = struct.unpack("<h", pkt[4:6])[0] / SENSITIVITY / 1000.0  # nominal
                ay = struct.unpack("<h", pkt[6:8])[0] / SENSITIVITY / 1000.0
                az = struct.unpack("<h", pkt[8:10])[0] / SENSITIVITY / 1000.0
                arrival_lsl = pylsl.local_clock()
                lsl_t, dev_t = mapper.to_lsl_time(ts, arrival_lsl)
                outlet.push_sample([ts / 32768.0, ax, ay, az], lsl_t)
                n_samples += 1
    except KeyboardInterrupt:
        print("\n[accel] Ctrl+C received.")
    finally:
        diag_stop.set()
        emit_marker(marker_outlet, marker_lock, "recording_stopped", "Accel",
                    samples=n_samples)
        print(f"[accel] {n_samples} samples streamed.")
        try:
            ser.write(struct.pack("B", 0x20))
            time.sleep(0.2)
        except Exception:
            pass
        ser.close()


if __name__ == "__main__":
    main()
