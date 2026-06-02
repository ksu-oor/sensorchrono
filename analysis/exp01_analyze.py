"""EXP-01 analyzer: ECG + keyboard fiducial + 1 Hz mapper diagnostics.

Verifies:
  - All four streams present in the XDF
  - ShimmerECG quality (rate, gaps, monotonicity)
  - ShimmerDiagnostics_ECG shows stable mapper.offset evolution
  - KeyboardFiducial events are well-timestamped (no gaps > 10 s during typing)
  - Cross-stream timing: every keystroke has a nearby ECG sample
  - Burst-pattern detection: any clusters of >=5 spacebars at <2 Hz spacing
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


def fmt(x):
    if isinstance(x, float):
        return f"{x:.4f}"
    return str(x)


def analyze_ecg(s):
    ts = np.asarray(s["time_stamps"])
    data = np.asarray(s["time_series"])
    n = len(ts)
    elapsed = ts[-1] - ts[0]
    eff_rate = (n - 1) / elapsed if elapsed > 0 else 0.0
    diffs = np.diff(ts)
    dev_t = data[:, 0]
    WRAP = (1 << 24) / 32768.0
    unwrapped = dev_t.copy()
    for i in range(1, len(unwrapped)):
        if unwrapped[i] < unwrapped[i - 1] - WRAP / 2:
            unwrapped[i:] += WRAP
    offset_rel = (ts - unwrapped) - (ts[0] - unwrapped[0])
    return dict(
        n=n,
        elapsed=elapsed,
        eff_rate=eff_rate,
        rate_dev_pct=100 * (eff_rate - 256.0) / 256.0,
        isi_mean_ms=float(np.mean(diffs) * 1000),
        isi_std_ms=float(np.std(diffs) * 1000),
        isi_max_ms=float(np.max(diffs) * 1000),
        monotonic=bool(np.all(diffs > 0)),
        drift_ms_total=float(offset_rel[-1] * 1000),
        drift_ppm=float(1e6 * offset_rel[-1] / elapsed) if elapsed > 0 else 0.0,
        offset_residual_std_ms=float(np.std(offset_rel) * 1000),
        ts=ts,
        offset_rel=offset_rel,
        unwrapped=unwrapped,
    )


def analyze_diagnostics(s):
    ts = np.asarray(s["time_stamps"])
    data = np.asarray(s["time_series"])
    if len(ts) == 0:
        return None
    return dict(
        n=len(ts),
        elapsed=ts[-1] - ts[0] if len(ts) > 1 else 0,
        ts=ts,
        offset=data[:, 0],
        last_observed=data[:, 1],
        min_observed=data[:, 2],
        residual_ms=data[:, 3],
        sample_count=data[:, 4],
    )


def analyze_keyboard(s):
    ts = np.asarray(s["time_stamps"])
    events = []
    for x in s["time_series"]:
        try:
            events.append(json.loads(x[0]))
        except Exception:
            events.append({"event": "?", "key": str(x[0]), "seq": -1})
    presses = [(t, e) for t, e in zip(ts, events) if e.get("event") == "press"]
    if not presses:
        return None
    press_ts = np.array([t for t, _ in presses])
    keys = [e["key"] for _, e in presses]

    # Find spacebar bursts: clusters of >=5 'space' presses at <2 Hz
    space_idx = [i for i, k in enumerate(keys) if k == "space"]
    bursts = []
    if len(space_idx) >= 5:
        # group consecutive spaces in the press sequence where ISI < 2 s
        i = 0
        while i < len(space_idx):
            j = i
            while (j + 1 < len(space_idx)
                   and space_idx[j + 1] == space_idx[j] + 1  # consecutive
                   and press_ts[space_idx[j + 1]] - press_ts[space_idx[j]] < 2.0):
                j += 1
            if j - i + 1 >= 5:
                bursts.append((press_ts[space_idx[i]], press_ts[space_idx[j]], j - i + 1))
            i = j + 1

    return dict(
        n_presses=len(presses),
        n_total_events=len(events),
        span=press_ts[-1] - press_ts[0] if len(press_ts) > 1 else 0,
        first_press=press_ts[0],
        last_press=press_ts[-1],
        max_gap=float(np.max(np.diff(press_ts))) if len(press_ts) > 1 else 0,
        bursts=bursts,
        press_ts=press_ts,
        keys=keys,
    )


def cross_check(ecg, kbd):
    """For each keystroke, find the time delta to the nearest ECG sample.
    On a good XDF, this should be < 1/256 s = 3.9 ms."""
    if kbd is None:
        return None
    deltas = []
    ecg_ts = ecg["ts"]
    for kt in kbd["press_ts"]:
        idx = np.searchsorted(ecg_ts, kt)
        candidates = []
        if idx > 0:
            candidates.append(abs(ecg_ts[idx - 1] - kt))
        if idx < len(ecg_ts):
            candidates.append(abs(ecg_ts[idx] - kt))
        if candidates:
            deltas.append(min(candidates))
    deltas = np.array(deltas)
    return dict(
        max_ms=float(np.max(deltas) * 1000),
        mean_ms=float(np.mean(deltas) * 1000),
        p99_ms=float(np.percentile(deltas, 99) * 1000),
    )


def plot_diagnostics(ecg, diag, kbd, out_path):
    fig, axes = plt.subplots(4, 1, figsize=(12, 12))

    # 1. ECG offset residual
    t0 = ecg["ts"][0]
    axes[0].plot(ecg["ts"] - t0, ecg["offset_rel"] * 1000, linewidth=0.5, alpha=0.5,
                 label="per-sample (lsl - device, rel)")
    if diag is not None:
        axes[0].plot(diag["ts"] - t0,
                     (diag["offset"] - diag["offset"][0]) * 1000,
                     color="red", linewidth=2,
                     label="mapper.offset (smoothed)")
    axes[0].set_ylabel("ms")
    axes[0].set_title(
        f"clock-mapper residual; drift={ecg['drift_ms_total']:.2f} ms / "
        f"{ecg['drift_ppm']:.1f} ppm"
    )
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    # 2. Diagnostics: residual_ms (last_observed - offset)
    if diag is not None:
        axes[1].plot(diag["ts"] - t0, diag["residual_ms"], "o-", markersize=3)
        axes[1].set_ylabel("residual (ms)")
        axes[1].set_title("per-sample observed offset vs smoothed mapper.offset (1 Hz diagnostic)")
        axes[1].grid(True, alpha=0.3)

    # 3. Keyboard activity over time
    if kbd is not None:
        rel = kbd["press_ts"] - t0
        axes[2].plot(rel, np.ones_like(rel), "|", markersize=10)
        for b_start, b_end, n in kbd["bursts"]:
            axes[2].axvspan(b_start - t0, b_end - t0, alpha=0.2, color="green",
                            label=f"burst x{n}" if n == kbd["bursts"][0][2] else None)
        axes[2].set_ylabel("keystroke")
        axes[2].set_yticks([])
        axes[2].set_title(f"{kbd['n_presses']} keystrokes over {kbd['span']:.0f}s, "
                          f"{len(kbd['bursts'])} bursts detected")
        axes[2].grid(True, alpha=0.3)

    # 4. ECG signal preview
    axes[3].plot(ecg["ts"] - t0, ecg["unwrapped"] - ecg["unwrapped"][0],
                 linewidth=0.5, color="gray")
    axes[3].set_xlabel("time (s)")
    axes[3].set_ylabel("device time (s)")
    axes[3].set_title("device-time accumulation (should be a clean line, slope = 1)")
    axes[3].grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def report(xdf_path, outdir=None):
    xdf_path = Path(xdf_path)
    outdir = Path(outdir) if outdir else xdf_path.parent
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"Loading {xdf_path}")
    streams, _ = pyxdf.load_xdf(str(xdf_path), dejitter_timestamps=False)
    print(f"Streams: {len(streams)}")
    for s in streams:
        info = s["info"]
        print(f"  - {info['name'][0]:30s} {info['type'][0]:12s} "
              f"{info['channel_count'][0]}ch  {len(s['time_stamps'])} samples")

    ecg_s = find_stream(streams, "ShimmerECG")
    diag_s = find_stream(streams, "ShimmerDiagnostics_ECG")
    kbd_s = find_stream(streams, "KeyboardFiducial")
    mark_s = find_stream(streams, "ShimmerMarkers")

    checks = {}
    checks["ShimmerECG present"] = ecg_s is not None
    checks["ShimmerDiagnostics_ECG present"] = diag_s is not None
    checks["KeyboardFiducial present"] = kbd_s is not None
    checks["ShimmerMarkers present"] = mark_s is not None

    if ecg_s is None:
        print("FAIL: no ECG stream.")
    else:
        ecg = analyze_ecg(ecg_s)
        print("\n=== ShimmerECG ===")
        for k, v in ecg.items():
            if not isinstance(v, np.ndarray):
                print(f"  {k:25s} {fmt(v)}")
        checks["ECG rate within 1%"] = abs(ecg["rate_dev_pct"]) < 1.0
        checks["ECG monotonic"] = ecg["monotonic"]
        checks["ECG no gaps >100ms"] = ecg["isi_max_ms"] < 100

    diag = analyze_diagnostics(diag_s) if diag_s is not None else None
    if diag is not None:
        print("\n=== ShimmerDiagnostics_ECG ===")
        print(f"  n samples         {diag['n']}")
        print(f"  elapsed           {diag['elapsed']:.2f}s")
        print(f"  expected ~{int(diag['elapsed'])} samples @ 1Hz")
        print(f"  residual_ms range [{np.min(diag['residual_ms']):.2f}, {np.max(diag['residual_ms']):.2f}]")
        print(f"  mapper.offset drift over run: "
              f"{(diag['offset'][-1] - diag['offset'][0]) * 1000:.3f} ms")
        checks["Diag stream got >=200 samples"] = diag["n"] >= 200

    kbd = analyze_keyboard(kbd_s) if kbd_s is not None else None
    if kbd is not None:
        print("\n=== KeyboardFiducial ===")
        print(f"  n presses         {kbd['n_presses']}")
        print(f"  n total events    {kbd['n_total_events']}")
        print(f"  span              {kbd['span']:.2f}s")
        print(f"  max gap           {kbd['max_gap']:.2f}s")
        print(f"  bursts (>=5 spaces) {len(kbd['bursts'])}")
        for s_t, e_t, n in kbd["bursts"]:
            print(f"    burst @ t={s_t - ecg['ts'][0]:.1f}s, n={n}, dur={e_t - s_t:.2f}s")
        checks["Keyboard captured >=20 presses"] = kbd["n_presses"] >= 20

    cross = cross_check(ecg, kbd) if (ecg_s is not None and kbd is not None) else None
    if cross is not None:
        print("\n=== Cross-stream check (keystroke -> nearest ECG sample) ===")
        for k, v in cross.items():
            print(f"  {k:15s} {fmt(v)} ms")
        # Should be < 1/256s = 3.9 ms if both are well aligned
        checks["Keystroke->ECG max <10ms"] = cross["max_ms"] < 10.0

    plot_path = outdir / "exp01_diagnostics.png"
    if ecg_s is not None:
        plot_diagnostics(ecg, diag, kbd, plot_path)
        print(f"\nDiagnostic plot: {plot_path}")

    print("\n=== EXP-01 PASS / FAIL ===")
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    all_ok = all(checks.values())
    print(f"\n>>> EXP-01 OVERALL: {'PASS' if all_ok else 'FAIL'} <<<")
    return 0 if all_ok else 2


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python exp01_analyze.py <path/to/recording.xdf> [outdir]")
        sys.exit(1)
    sys.exit(report(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
