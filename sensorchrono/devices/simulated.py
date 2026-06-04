"""Synthetic device adapters for hardware-free dry-run.

These let the *entire* app — preflight, supervisor, liveness gate, wizard,
GUI — run on macOS with no Shimmer / camera / mic attached. Each adapter
conforms to :class:`~sensorchrono.devices.base.DeviceAdapter`.

Two operating modes, chosen automatically:
  * **With ``pylsl`` installed** — ``launch()`` starts a background thread that
    publishes a real LSL outlet, so ``lsl_monitor`` and LabRecorder can see it.
  * **Without ``pylsl``** (e.g. this bare macOS box) — no outlet is created;
    the adapter still reports ready + healthy so the FSM/unit tests exercise
    the full path. ``pylsl`` is imported lazily *inside* ``launch()`` so this
    module imports cleanly with zero native dependencies.

The pure ``synth_*`` generators below are importable on their own (numpy only)
— used by the push thread, the future waveform widget, and the tests.
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import numpy as np

from sensorchrono.contract import StreamName, spec
from sensorchrono.devices.base import (
    DeviceAdapter,
    LivenessReport,
    ReadyResult,
    StreamDef,
    StreamLiveness,
)

if TYPE_CHECKING:
    from sensorchrono.config import SessionConfig


# --------------------------------------------------------------------------
# Pure synthetic-signal generators (numpy only — unit-testable, no LSL)
# --------------------------------------------------------------------------
def synth_ecg(
    n_samples: int, fs_hz: float, *, hr_bpm: float = 60.0, t0: float = 0.0
) -> np.ndarray:
    """Synthetic ECG-ish waveform for dry-run, ``n_samples`` long at ``fs_hz``.

    *** Learning-mode contribution point ***
    The placeholder below is a plain sine at the heart rate — recognisably
    periodic, but nothing like a real ECG. A real beat has a small P wave, a
    sharp QRS spike, and a broader T wave. If you want the dry-run trace to
    look clinical, replace the marked line with your own per-beat morphology.
    One approach (sum of Gaussians over the beat phase ``ph = (t*hr/60) % 1``):

        P =  0.10*exp(-((ph-0.15)/0.020)**2)
        Q = -0.15*exp(-((ph-0.23)/0.008)**2)
        R =  1.00*exp(-((ph-0.25)/0.008)**2)
        S = -0.25*exp(-((ph-0.27)/0.008)**2)
        T =  0.25*exp(-((ph-0.45)/0.040)**2)
        return (P+Q+R+S+T).astype(np.float64)

    Constraints to keep tests + the waveform widget happy: return a finite
    float64 array of length ``n_samples`` roughly within [-1.5, 1.5] mV.
    """
    t = (np.arange(n_samples, dtype=np.float64) / fs_hz) + t0
    beat_hz = hr_bpm / 60.0
    phase = (t * beat_hz) % 1.0  # position within each beat, 0..1

    def _bump(center: float, width: float, amp: float) -> np.ndarray:
        return amp * np.exp(-0.5 * ((phase - center) / width) ** 2)

    # Sum of Gaussians over the beat phase: low P, sharp QRS (Q/R/S),
    # broad T. Peak ~1.0 mV at the R wave, comfortably within +/-1.5 mV.
    ecg = (
        _bump(0.150, 0.022, 0.10)   # P wave
        + _bump(0.235, 0.0075, -0.12)  # Q
        + _bump(0.250, 0.0075, 1.00)   # R
        + _bump(0.265, 0.0075, -0.28)  # S
        + _bump(0.420, 0.040, 0.30)    # T wave
    )
    return ecg.astype(np.float64)


def synth_audio_block(
    n_samples: int,
    fs_hz: float,
    *,
    t0: float = 0.0,
    tap_period_s: float = 2.0,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Synthetic mic block: low broadband noise with a short click burst every
    ``tap_period_s`` — mimics the spacebar calibration taps the in-situ lag
    calibration keys off. Returns float32 in roughly [-1, 1]."""
    rng = rng or np.random.default_rng(0)
    t = (np.arange(n_samples, dtype=np.float64) / fs_hz) + t0
    block = 0.01 * rng.standard_normal(n_samples)
    phase = (t % tap_period_s)
    click = (phase < 0.005)  # 5 ms click at the start of each period
    block[click] += 0.6 * np.sin(2.0 * np.pi * 2000.0 * t[click])
    return np.clip(block, -1.0, 1.0).astype(np.float32)


# --------------------------------------------------------------------------
# Adapter base + concrete simulated devices
# --------------------------------------------------------------------------
class _SimAdapter(DeviceAdapter):
    """Shared dry-run lifecycle. Subclasses declare ``name`` + ``streams()``
    and (optionally) a per-stream sample generator for the push thread."""

    name = "sim"

    def __init__(self) -> None:
        self._running = False
        self._t0 = 0.0
        self._thread: threading.Thread | None = None
        self._stop_evt = threading.Event()
        self._lsl_active = False
        self._lsl_error = ""
        self._outlets: list[tuple[object, StreamDef]] = []
        #: test/fault-injection hook — seconds before the device reports ready.
        #: 0.0 = instant (real dry-run); set >timeout to exercise the timeout path.
        self.startup_delay_s = 0.0

    # subclasses override
    def streams(self) -> list[StreamDef]:  # pragma: no cover - abstract-ish
        raise NotImplementedError

    def launch(self, session: "SessionConfig") -> None:
        if self._running:
            return  # idempotent: a double-click must not spawn a second outlet
        self._stop_evt = threading.Event()  # fresh event each launch (never reuse)
        self._running = True
        self._t0 = time.monotonic()
        self._lsl_error = ""
        self._outlets = []
        self._maybe_start_lsl()

    def _outlet_failed(self) -> bool:
        """True if we claimed an LSL outlet but its push thread has died."""
        return self._lsl_active and (self._thread is None or not self._thread.is_alive())

    def is_ready(self, timeout_s: float) -> ReadyResult:
        call_start = time.monotonic()
        if not self._running:
            return ReadyResult(False, f"{self.name}: not launched")
        deadline = call_start + max(0.0, timeout_s)
        while True:
            elapsed = time.monotonic() - call_start  # time spent blocking in is_ready
            if self._outlet_failed():
                return ReadyResult(False, f"{self.name}: LSL outlet failed ({self._lsl_error})", elapsed)
            # readiness gates on warm-up since launch, not since this call
            if (time.monotonic() - self._t0) >= self.startup_delay_s:
                if self._lsl_active:
                    mode = "LSL outlet live"
                elif self._lsl_error:  # pylsl present but outlet build failed
                    mode = f"synthetic (LSL outlet failed: {self._lsl_error})"
                else:
                    mode = "synthetic (no pylsl)"
                return ReadyResult(True, f"{self.name}: {mode}", elapsed)
            if time.monotonic() >= deadline:
                return ReadyResult(False, f"{self.name}: not ready within {timeout_s:.2f}s", elapsed)
            time.sleep(0.01)

    def check_liveness(self, window_s: float) -> LivenessReport:
        failed = self._outlet_failed()
        healthy = self._running and not failed
        if not self._running:
            note = "device not running"
        elif failed:
            note = f"LSL outlet thread died: {self._lsl_error or 'unknown'}"
        else:
            note = ""
        rows: list[StreamLiveness] = []
        for sdef in self.streams():
            expected = sdef.nominal_rate_hz
            is_marker = expected == 0.0
            rows.append(
                StreamLiveness(
                    name=sdef.name,
                    present=healthy,
                    measured_rate_hz=0.0 if (is_marker or not healthy) else expected,
                    expected_rate_hz=expected,
                    max_gap_s=0.0,
                    ok=healthy,
                    measured_channels=sdef.channels if healthy else 0,
                    expected_channels=sdef.channels,
                    note=note,
                )
            )
        return LivenessReport(device=self.name, streams=tuple(rows))

    def stop(self) -> None:
        self._running = False
        self._stop_evt.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._lsl_active = False
        self._outlets = []

    # -- optional real-LSL emission (best-effort; skipped without pylsl) ----
    def _maybe_start_lsl(self) -> None:
        """Build the LSL outlets *synchronously* so a construction failure
        surfaces here (and degrades to pure-synthetic) instead of dying in a
        background thread while the liveness gate keeps reporting healthy."""
        try:
            import pylsl  # lazy: absent on the bare dev box
        except Exception:
            self._lsl_active = False  # graceful: no liblsl -> pure synthetic
            return
        try:
            self._outlets = self._build_outlets(pylsl)
        except Exception as exc:  # ABI mismatch, name collision, no permission, ...
            self._lsl_active = False
            self._lsl_error = repr(exc)
            self._outlets = []
            return
        self._lsl_active = True
        self._thread = threading.Thread(target=self._push_loop, name=f"sim-{self.name}", daemon=True)
        self._thread.start()

    def _build_outlets(self, pylsl) -> list[tuple[object, StreamDef]]:  # pragma: no cover - needs liblsl
        built: list[tuple[object, StreamDef]] = []
        for sdef in self.streams():
            rate = sdef.nominal_rate_hz
            info = pylsl.StreamInfo(
                name=str(sdef.name),
                type=sdef.content_type,
                channel_count=sdef.channels,
                nominal_srate=rate if rate > 0 else pylsl.IRREGULAR_RATE,
                channel_format="float32",
                source_id=f"sim-{sdef.name}",
            )
            built.append((pylsl.StreamOutlet(info), sdef))
        return built

    def _push_loop(self) -> None:  # pragma: no cover - requires liblsl at runtime
        tick = 1.0 / 50.0  # push in ~20 ms chunks
        while not self._stop_evt.wait(tick):
            now = time.monotonic() - self._t0
            for outlet, sdef in self._outlets:
                rate = sdef.nominal_rate_hz
                if rate <= 0:
                    continue  # marker streams pushed on events only
                n = max(1, int(rate * tick))
                if sdef.name == StreamName.SHIMMER_ECG:
                    ecg = synth_ecg(n, rate, t0=now)
                    chunk = np.tile(ecg[:, None], (1, sdef.channels)).astype(np.float32)
                elif sdef.name == StreamName.AUDIO:
                    chunk = synth_audio_block(n, rate, t0=now)[:, None]
                else:
                    chunk = np.zeros((n, sdef.channels), dtype=np.float32)
                outlet.push_chunk(chunk.tolist())


class SimulatedShimmerEXG(_SimAdapter):
    name = "shimmer_exg"

    def streams(self) -> list[StreamDef]:
        return [
            StreamDef.from_contract(StreamName.SHIMMER_ECG),
            StreamDef.from_contract(StreamName.SHIMMER_DIAGNOSTICS_ECG),
        ]


class SimulatedCamera(_SimAdapter):
    name = "camera"

    def streams(self) -> list[StreamDef]:
        return [StreamDef.from_contract(StreamName.VIDEO_FRAMES)]


class SimulatedMicrophone(_SimAdapter):
    name = "mic"

    def streams(self) -> list[StreamDef]:
        return [StreamDef.from_contract(StreamName.AUDIO)]


class SimulatedKeyboard(_SimAdapter):
    name = "keyboard"

    def streams(self) -> list[StreamDef]:
        return [StreamDef.from_contract(StreamName.KEYBOARD_FIDUCIAL)]


def default_simulated_fleet() -> list[DeviceAdapter]:
    """The proven v1 core, all synthetic — what dry-run launches by default."""
    return [
        SimulatedShimmerEXG(),
        SimulatedCamera(),
        SimulatedMicrophone(),
        SimulatedKeyboard(),
    ]
