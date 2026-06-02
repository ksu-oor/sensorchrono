"""Video LSL bridge.

Captures from a UVC webcam (Logitech BRIO at device 0 by default),
publishes per-frame timing to an LSL outlet named `VideoFrames`,
writes the video to MP4 with monotonic PTS, and writes a CSV with
per-frame timing so post-hoc analysis doesn't need to decode the video.

LSL stream `VideoFrames`:
    channels (cf_double64):
        0: frame_idx
        1: cap_pos_ms      (OpenCV's CAP_PROP_POS_MSEC at read time)
    nominal_srate: target fps (used as a hint only; actual is irregular)

CSV `frames.csv`:
    frame_idx, t_read_lsl, t_pos_ms, dropped_flag

Timestamp semantics: t_read_lsl = pylsl.local_clock() taken IMMEDIATELY
after cap.read() returns. This is the smallest delay we can extract
from a UVC camera without a hardware-sync extension unit. The frame
content is older than this timestamp by 1-3 driver-buffer frames; the
fixed lag is characterized post-hoc against the keyboard fiducial.
"""
import argparse
import csv
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pylsl


DEFAULTS = dict(
    device=0,
    width=1920,
    height=1080,
    fps=30,
    codec="MJPG",
    backend="dshow",
)

BACKENDS = {
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "any": cv2.CAP_ANY,
}


def open_camera(device, width, height, fps, codec, backend):
    cap = cv2.VideoCapture(device, BACKENDS[backend])
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open camera device {device} with backend {backend}.")
    fourcc = cv2.VideoWriter_fourcc(*codec)
    cap.set(cv2.CAP_PROP_FOURCC, fourcc)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
    actual_fourcc = "".join([chr((fourcc_int >> (8 * i)) & 0xFF) for i in range(4)])
    print(f"[video] opened device {device} via {backend}: "
          f"{actual_w}x{actual_h} @ {actual_fps} fps fourcc='{actual_fourcc}'")
    return cap, actual_w, actual_h, actual_fps


def create_outlet(target_fps):
    info = pylsl.StreamInfo(
        name="VideoFrames",
        type="VideoFrames",
        channel_count=2,
        nominal_srate=float(target_fps),
        channel_format=pylsl.cf_double64,
        source_id="brio_video",
    )
    chns = info.desc().append_child("channels")
    for label, unit in [("frame_idx", "count"), ("cap_pos_ms", "milliseconds")]:
        ch = chns.append_child("channel")
        ch.append_child_value("label", label)
        ch.append_child_value("unit", unit)
        ch.append_child_value("type", "VideoFrames")
    info.desc().append_child_value("manufacturer", "Logitech")
    info.desc().append_child_value("model", "BRIO")
    outlet = pylsl.StreamOutlet(info, chunk_size=1, max_buffered=600)
    print(f"[video] LSL outlet 'VideoFrames' is live.")
    return outlet


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=int, default=DEFAULTS["device"])
    parser.add_argument("--width", type=int, default=DEFAULTS["width"])
    parser.add_argument("--height", type=int, default=DEFAULTS["height"])
    parser.add_argument("--fps", type=int, default=DEFAULTS["fps"])
    parser.add_argument("--codec", default=DEFAULTS["codec"])
    parser.add_argument("--backend", choices=list(BACKENDS), default=DEFAULTS["backend"])
    parser.add_argument("--duration", type=float, default=0.0,
                        help="Auto-stop after N seconds. 0 = run until Ctrl+C.")
    parser.add_argument("--out-dir", default=r"C:\Users\ngoldbla\Desktop\LSL_data")
    parser.add_argument("--tag", default="exp02")
    parser.add_argument("--preview", action="store_true",
                        help="Show a low-rate preview window (consumes CPU).")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mp4_path = out_dir / f"{args.tag}_video.mp4"
    csv_path = out_dir / f"{args.tag}_frames.csv"

    cap, w, h, actual_fps = open_camera(
        args.device, args.width, args.height, args.fps, args.codec, args.backend
    )

    fourcc_writer = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(mp4_path), fourcc_writer, args.fps, (w, h))
    if not writer.isOpened():
        print(f"[video] WARNING: VideoWriter failed to open mp4v writer, retrying H264...")
        fourcc_writer = cv2.VideoWriter_fourcc(*"H264")
        writer = cv2.VideoWriter(str(mp4_path), fourcc_writer, args.fps, (w, h))
    print(f"[video] writing MP4 to {mp4_path}")

    outlet = create_outlet(args.fps)

    csv_f = open(csv_path, "w", newline="")
    csv_w = csv.writer(csv_f)
    csv_w.writerow(["frame_idx", "t_read_lsl", "t_pos_ms", "dropped"])
    print(f"[video] writing frame CSV to {csv_path}")

    # Warm up: discard first 10 frames (settles auto-exposure)
    print("[video] warming up...")
    for _ in range(10):
        cap.read()

    t_start = pylsl.local_clock()
    t_end = t_start + args.duration if args.duration > 0 else None
    frame_idx = 0
    dropped = 0
    last_print = t_start
    print("[video] streaming...")

    try:
        while True:
            ret, frame = cap.read()
            t_read = pylsl.local_clock()
            if not ret:
                dropped += 1
                csv_w.writerow([frame_idx, t_read, -1.0, 1])
                if dropped <= 3:
                    sys.stderr.write(f"[video] read failed (frame_idx={frame_idx})\n")
                if dropped > 30:
                    sys.stderr.write("[video] too many read failures, stopping.\n")
                    break
                continue
            cap_pos_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            outlet.push_sample([float(frame_idx), float(cap_pos_ms)], t_read)
            writer.write(frame)
            csv_w.writerow([frame_idx, f"{t_read:.6f}", f"{cap_pos_ms:.3f}", 0])
            frame_idx += 1

            # progress
            if t_read - last_print >= 5.0:
                elapsed = t_read - t_start
                fps_eff = frame_idx / elapsed if elapsed > 0 else 0
                print(f"[video] t={elapsed:6.1f}s  frames={frame_idx:6d}  "
                      f"eff_fps={fps_eff:5.2f}  dropped={dropped}")
                last_print = t_read

            if args.preview and frame_idx % 5 == 0:
                cv2.imshow("preview", cv2.resize(frame, (640, 360)))
                if cv2.waitKey(1) & 0xFF == 27:
                    print("[video] esc pressed, stopping.")
                    break

            if t_end is not None and t_read >= t_end:
                print(f"[video] duration {args.duration}s reached.")
                break
    except KeyboardInterrupt:
        print("\n[video] Ctrl+C received.")
    finally:
        elapsed = pylsl.local_clock() - t_start
        eff_fps = frame_idx / elapsed if elapsed > 0 else 0
        print(f"[video] stopped. {frame_idx} frames in {elapsed:.1f}s = {eff_fps:.2f} fps. dropped={dropped}")
        cap.release()
        writer.release()
        csv_f.close()
        if args.preview:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
