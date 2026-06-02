"""EXP-02 analyzer: ECG + keyboard + video.

Adds video-frame analysis to EXP-01's checks:
  - All 5 streams present
  - VideoFrames frame index monotonic, no duplicates
  - Effective fps in expected range (target +/- 2 fps)
  - Frame-interval jitter (camera irregularity)
  - Cross-stream: keystroke -> nearest video frame, expected <= 1 frame period
  - Cross-stream: ECG -> video frame timing consistency
"""
import sys
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pyxdf


def find_stream(streams, name):
    for s in streams:
        if s["info"]["name"][0] == name:
            return s
    return None


def analyze_video(s, target_fps):
    ts = np.asarray(s["time_stamps"])
    data = np.asarray(s["time_series"])
    frame_idx = data[:, 0].astype(int)
    n = len(ts)
    if n < 2:
        return None
    diffs = np.diff(ts)
    elapsed = ts[-1] - ts[0]
    eff_fps = (n - 1) / elapsed
    # gap-detect: any interval >= 1.5x target frame period is a "stutter"
    target_period = 1.0 / target_fps
    n_stutters = int(np.sum(diffs > 1.5 * target_period))
    # frame_idx monotonic?
    frame_diffs = np.diff(frame_idx)
    monotonic = bool(np.all(frame_diffs == 1))
    return dict(
        n=n,
        elapsed=elapsed,
        eff_fps=eff_fps,
        fps_dev_pct=100 * (eff_fps - target_fps) / target_fps,
        isi_mean_ms=float(np.mean(diffs) * 1000),
        isi_std_ms=float(np.std(diffs) * 1000),
        isi_max_ms=float(np.max(diffs) * 1000),
        isi_p99_ms=float(np.percentile(diffs, 99) * 1000),
        n_stutters=n_stutters,
        first_idx=int(frame_idx[0]),
        last_idx=int(frame_idx[-1]),
        frame_idx_monotonic=monotonic,
        ts=ts,
    )


def analyze_keyboard(s):
    ts = np.asarray(s["time_stamps"])
    events = [json.loads(x[0]) for x in s["time_series"]]
    presses = [(t, e) for t, e in zip(ts, events) if e.get("event") == "press"]
    press_ts = np.array([t for t, _ in presses])
    return dict(n=len(presses), press_ts=press_ts)


def analyze_ecg(s):
    ts = np.asarray(s["time_stamps"])
    diffs = np.diff(ts)
    elapsed = ts[-1] - ts[0]
    return dict(n=len(ts), elapsed=elapsed, eff_rate=(len(ts) - 1)/elapsed,
                isi_max_ms=float(np.max(diffs) * 1000), ts=ts)


def nearest_delta(target_times, ref_times):
    if len(target_times) == 0 or len(ref_times) == 0:
        return None
    deltas = []
    for t in target_times:
        i = np.searchsorted(ref_times, t)
        cands = []
        if i > 0: cands.append(abs(ref_times[i-1] - t))
        if i < len(ref_times): cands.append(abs(ref_times[i] - t))
        if cands: deltas.append(min(cands))
    return np.array(deltas)


def report(xdf_path, outdir):
    xdf_path = Path(xdf_path)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"Loading {xdf_path}")
    streams, _ = pyxdf.load_xdf(str(xdf_path), dejitter_timestamps=False)
    print(f"Streams: {len(streams)}")
    for s in streams:
        info = s["info"]
        print(f"  - {info['name'][0]:30s} {info['type'][0]:12s} "
              f"{info['channel_count'][0]}ch  {len(s['time_stamps'])} samples")

    ecg_s = find_stream(streams, "ShimmerECG")
    kbd_s = find_stream(streams, "KeyboardFiducial")
    vid_s = find_stream(streams, "VideoFrames")
    diag_s = find_stream(streams, "ShimmerDiagnostics_ECG")

    checks = {}
    checks["ShimmerECG present"] = ecg_s is not None
    checks["KeyboardFiducial present"] = kbd_s is not None
    checks["VideoFrames present"] = vid_s is not None
    checks["ShimmerDiagnostics_ECG present"] = diag_s is not None

    if vid_s is None:
        print("FAIL: No VideoFrames stream.")
    else:
        target_fps = float(vid_s["info"]["nominal_srate"][0])
        vid = analyze_video(vid_s, target_fps)
        print(f"\n=== VideoFrames (target {target_fps:.1f} fps) ===")
        for k, v in vid.items():
            if not isinstance(v, np.ndarray):
                print(f"  {k:25s} {v}")
        checks["Video fps within target +/- 10%"] = abs(vid["fps_dev_pct"]) < 10.0
        checks["Video frame_idx monotonic"] = vid["frame_idx_monotonic"]
        checks["Video < 5 stutters (>1.5x period)"] = vid["n_stutters"] < 5

    ecg = analyze_ecg(ecg_s) if ecg_s else None
    if ecg:
        print(f"\n=== ShimmerECG ===")
        print(f"  n={ecg['n']}, elapsed={ecg['elapsed']:.2f}s, "
              f"eff_rate={ecg['eff_rate']:.3f} Hz, max_isi={ecg['isi_max_ms']:.2f} ms")
        checks["ECG no gaps >100 ms"] = ecg["isi_max_ms"] < 100

    kbd = analyze_keyboard(kbd_s) if kbd_s else None
    if kbd:
        print(f"\n=== KeyboardFiducial ===")
        print(f"  n presses: {kbd['n']}")
        checks["Keyboard >= 20 presses"] = kbd["n"] >= 20

    # Cross-stream checks
    if vid_s and kbd and len(kbd["press_ts"]) > 0:
        d = nearest_delta(kbd["press_ts"], vid["ts"])
        if d is not None:
            print(f"\n=== Cross: keystroke -> nearest video frame ===")
            print(f"  max:  {np.max(d)*1000:.2f} ms")
            print(f"  mean: {np.mean(d)*1000:.2f} ms")
            print(f"  p99:  {np.percentile(d, 99)*1000:.2f} ms")
            # Expected to be at most one frame period (~35 ms at 28.5 fps)
            target_period_ms = 1000.0 / vid["eff_fps"]
            checks[f"Keystroke->frame max <= 1.5 x frame period ({1.5*target_period_ms:.1f} ms)"] = (
                np.max(d) * 1000 < 1.5 * target_period_ms
            )

    if ecg_s and vid_s:
        # For each video frame, find nearest ECG sample. Should be within 1 ECG period (3.9 ms).
        d_ev = nearest_delta(vid["ts"], ecg["ts"])
        if d_ev is not None:
            print(f"\n=== Cross: video frame -> nearest ECG sample ===")
            print(f"  max:  {np.max(d_ev)*1000:.2f} ms")
            print(f"  mean: {np.mean(d_ev)*1000:.2f} ms")
            print(f"  p99:  {np.percentile(d_ev, 99)*1000:.2f} ms")
            checks["Video->ECG max <= 5 ms"] = np.max(d_ev) * 1000 < 5.0

    # Plot
    fig, axes = plt.subplots(4, 1, figsize=(12, 12))

    if vid:
        diffs = np.diff(vid["ts"]) * 1000
        axes[0].plot(vid["ts"] - vid["ts"][0], np.concatenate([[0], diffs]),
                     ",-", markersize=1, linewidth=0.5)
        axes[0].axhline(1000/target_fps, color="r", linestyle="--", label=f"nominal {target_fps:.0f} fps")
        axes[0].set_ylabel("frame interval (ms)")
        axes[0].set_title(f"VideoFrames interval; eff {vid['eff_fps']:.2f} fps, std {vid['isi_std_ms']:.2f} ms")
        axes[0].legend(); axes[0].grid(True, alpha=0.3)

        axes[1].hist(diffs, bins=100)
        axes[1].set_yscale("log")
        axes[1].set_xlabel("frame interval (ms)")
        axes[1].set_title("frame-interval histogram")
        axes[1].grid(True, alpha=0.3)

    if kbd and vid:
        t0 = vid["ts"][0]
        axes[2].plot(kbd["press_ts"] - t0, np.ones_like(kbd["press_ts"]), "|", markersize=10,
                     label=f"{len(kbd['press_ts'])} keystrokes")
        axes[2].plot(vid["ts"] - t0, np.zeros_like(vid["ts"]) + 0.5, ".", markersize=1, alpha=0.3,
                     label=f"{vid['n']} video frames")
        axes[2].set_ylim(-0.2, 1.5)
        axes[2].set_yticks([])
        axes[2].set_xlabel("time (s)")
        axes[2].set_title("keystrokes vs video frames (timeline)")
        axes[2].legend(); axes[2].grid(True, alpha=0.3)

    if kbd and vid:
        d = nearest_delta(kbd["press_ts"], vid["ts"])
        axes[3].hist(d * 1000, bins=50)
        axes[3].set_xlabel("nearest-frame delta (ms)")
        axes[3].set_title(f"keystroke -> nearest video frame; "
                          f"max {np.max(d)*1000:.1f} ms, mean {np.mean(d)*1000:.1f} ms")
        axes[3].grid(True, alpha=0.3)

    fig.tight_layout()
    plot_path = outdir / "exp02_diagnostics.png"
    fig.savefig(plot_path, dpi=120)
    plt.close(fig)
    print(f"\nDiagnostic plot: {plot_path}")

    print("\n=== EXP-02 PASS / FAIL ===")
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    all_ok = all(checks.values())
    print(f"\n>>> EXP-02 OVERALL: {'PASS' if all_ok else 'FAIL'} <<<")
    return 0 if all_ok else 2


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python exp02_analyze.py <path/to/xdf> [outdir]")
        sys.exit(1)
    sys.exit(report(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else Path(sys.argv[1]).parent))
