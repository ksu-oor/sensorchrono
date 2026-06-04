"""Live keyboard-fiducial counting for the calibration block.

During CALIBRATE the operator taps the spacebar ~15 times ~2 s apart; each
clean tap is a free multi-modal fiducial (HID time vs mic click vs video
frame) that the in-situ lag calibration later keys off. This module counts
*clean* taps in real time so the UI can show progress and decide when enough
have been collected.

:class:`FiducialCounter` is pure (no LSL) and holds the acceptance policy;
:class:`LiveFiducialMonitor` is the threaded LSL source that feeds it from the
``KeyboardFiducial`` marker stream.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from sensorchrono.contract import StreamName


@dataclass
class FiducialCounter:
    """Refractory-gated acceptance of keystroke fiducials.

    A tap is accepted only if it falls at least ``refractory_s`` after the last
    accepted one — this rejects key-repeat / double-taps that would corrupt the
    lag estimate. ``min_count`` clean taps means the block is calibratable."""

    refractory_s: float = 0.8
    min_count: int = 10
    accepted: list[float] = field(default_factory=list)

    def offer(self, t: float) -> bool:
        """Offer a tap timestamp (seconds). Returns True if accepted as clean."""
        if not self.accepted or (t - self.accepted[-1]) >= self.refractory_s:
            self.accepted.append(t)
            return True
        return False

    @property
    def count(self) -> int:
        return len(self.accepted)

    @property
    def calibrated(self) -> bool:
        return self.count >= self.min_count

    def intervals(self) -> list[float]:
        return [b - a for a, b in zip(self.accepted, self.accepted[1:])]

    def regularity_cv(self) -> float | None:
        """Coefficient of variation of inter-tap intervals — a quality signal
        (lower = more metronome-like). ``None`` until there are ≥2 intervals."""
        iv = self.intervals()
        if len(iv) < 2:
            return None
        mean = sum(iv) / len(iv)
        if mean == 0:
            return None
        var = sum((x - mean) ** 2 for x in iv) / len(iv)
        return (var ** 0.5) / mean

    def reset(self) -> None:
        self.accepted.clear()


class LiveFiducialMonitor:
    """Pulls ``KeyboardFiducial`` markers off the LSL hub and feeds a
    :class:`FiducialCounter`, invoking ``on_count`` after each accepted tap."""

    def __init__(
        self,
        counter: FiducialCounter | None = None,
        *,
        poll_hz: float = 20.0,
        on_count: Callable[[int], None] | None = None,
    ) -> None:
        self.counter = counter or FiducialCounter()
        self.poll_dt = 1.0 / poll_hz
        self.on_count = on_count
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="fiducial-live", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:  # pragma: no cover - exercised via venv integration test
        try:
            import pylsl
        except Exception:
            return
        found = pylsl.resolve_byprop("name", str(StreamName.KEYBOARD_FIDUCIAL), 1, 2.0)
        if not found:
            return
        inlet = pylsl.StreamInlet(found[0])
        while not self._stop.wait(self.poll_dt):
            _, stamps = inlet.pull_chunk(timeout=0.0)
            for t in stamps:
                if self.counter.offer(t) and self.on_count is not None:
                    self.on_count(self.counter.count)
