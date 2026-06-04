"""The :class:`DeviceAdapter` seam and the small value types it exchanges
with the orchestration layer. This is what makes the app extensible: adding a
modality is one new subclass; the FSM, supervisor, monitor, and UI iterate
over adapters without knowing their concrete type.

**Design note — ``launch()`` returns ``None``, not ``Popen``.**
The plan sketched ``launch() -> Popen``. But simulated adapters drive
in-process threads (or a synthetic LSL outlet), not a subprocess; tying the
interface to ``Popen`` would leak the real-bridge implementation into the
contract and exclude the dry-run adapters. Instead each adapter owns its
process/threads internally and exposes behaviour (``is_ready``,
``check_liveness``, ``stop``). Real adapters keep a ``Popen``; simulated ones
keep threads — the orchestrator never needs to know which.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sensorchrono.contract import StreamName, StreamSpec, spec

if TYPE_CHECKING:  # avoid a circular import at runtime (config imports nothing here)
    from sensorchrono.config import SessionConfig


@dataclass(frozen=True, slots=True)
class StreamDef:
    """A logical LSL stream an adapter declares it will emit. Distinct from
    :class:`~sensorchrono.contract.StreamSpec` (the *expected* ground truth):
    an adapter declares what it *will* produce, which liveness then checks
    against the contract's expectation."""

    name: StreamName
    content_type: str
    channels: int
    nominal_rate_hz: float

    @classmethod
    def from_contract(cls, name: StreamName, *, rate_hz: float | None = None) -> "StreamDef":
        """Build a declaration from the canonical spec, optionally overriding
        the rate (e.g. a camera running at a non-default ``--fps``)."""
        s: StreamSpec = spec(name)
        return cls(s.name, s.content_type, s.channels, s.nominal_rate_hz if rate_hz is None else rate_hz)


@dataclass(frozen=True, slots=True)
class ReadyResult:
    """Outcome of waiting for a device's outlet(s) to come live."""

    ok: bool
    detail: str = ""
    elapsed_s: float = 0.0


@dataclass(frozen=True, slots=True)
class StreamLiveness:
    """Per-stream health over an observation window.

    Channel counts are carried (not just rate) so a Phase-1 ``lsl_monitor``
    populating this from a real inlet can catch the single most common
    "wrong stream resolved" failure — a present, correctly-rated stream with
    the wrong *shape* (e.g. a 1-channel outlet where the contract expects 2)."""

    name: StreamName
    present: bool
    measured_rate_hz: float
    expected_rate_hz: float
    max_gap_s: float
    ok: bool
    measured_channels: int = 0
    expected_channels: int = 0
    note: str = ""


@dataclass(frozen=True, slots=True)
class LivenessReport:
    """A device's per-stream liveness verdict. ``ok`` is the gate the staging
    page uses to enable the big "Go to Recording" button."""

    device: str
    streams: tuple[StreamLiveness, ...] = ()

    @property
    def ok(self) -> bool:
        return bool(self.streams) and all(s.ok for s in self.streams)

    def problems(self) -> list[str]:
        """Human-readable reasons any stream failed, for the UI / logs."""
        return [f"{s.name}: {s.note or 'not healthy'}" for s in self.streams if not s.ok]


class DeviceAdapter(ABC):
    """One capture modality. Concrete adapters drive a real bridge subprocess
    (Phase 2) or synthesize data (dry-run). All methods operate on adapter-
    internal state so the orchestrator stays implementation-agnostic."""

    #: short stable id, e.g. "shimmer_exg", "camera", "mic", "keyboard".
    name: str = "device"

    @abstractmethod
    def streams(self) -> list[StreamDef]:
        """Logical LSL streams this device emits."""

    @abstractmethod
    def launch(self, session: "SessionConfig") -> None:
        """Start capture (spawn the bridge subprocess or the synthetic
        generator). MUST be non-blocking: return once started, not when the
        capture finishes."""

    @abstractmethod
    def is_ready(self, timeout_s: float) -> ReadyResult:
        """Block up to ``timeout_s`` until the device's outlet(s) are live."""

    @abstractmethod
    def check_liveness(self, window_s: float) -> LivenessReport:
        """Observe a live window and report rate / gap / presence per stream."""

    @abstractmethod
    def stop(self) -> None:
        """Graceful teardown. Must be idempotent — safe to call when already
        stopped or never launched."""
