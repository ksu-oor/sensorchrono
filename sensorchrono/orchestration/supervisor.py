"""Process + fleet supervision.

Two pieces:

* :class:`BridgeProcess` — spawn one capture-bridge subprocess, watch its
  stdout for a per-bridge readiness line, and tear it down gracefully
  (``terminate`` → wait → ``kill``). Phase-2 real adapters build one of these
  with their specific command + readiness regex; the Shimmer adapter is the
  reason the readiness regex is per-bridge (its line has no "is live").

* :class:`Supervisor` — own a *fleet* of :class:`DeviceAdapter` and drive the
  whole-fleet lifecycle: launch all, wait for all to be ready under one shared
  deadline, tear all down. Adapter-agnostic, so it works identically for the
  simulated fleet (dry-run) and the real one.
"""
from __future__ import annotations

import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from sensorchrono.devices.base import DeviceAdapter, ReadyResult


@dataclass
class BridgeSpec:
    """How to launch + recognise one capture-bridge subprocess."""

    name: str  # device id, e.g. "camera"
    argv: list[str]  # full command, e.g. [python, "-m", "sensorchrono.bridges.video_lsl_bridge", "--duration", "90", ...]
    ready_pattern: re.Pattern[str]  # matches the bridge's stdout readiness line
    cwd: Path | None = None


class BridgeProcess:
    """A single bridge subprocess with readiness detection + safe teardown."""

    def __init__(self, spec: BridgeSpec, *, max_log_lines: int = 200) -> None:
        self.spec = spec
        self._proc: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._ready = threading.Event()
        self._log: deque[str] = deque(maxlen=max_log_lines)
        self._lock = threading.Lock()

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        if self._proc is not None:
            return  # idempotent
        self._proc = subprocess.Popen(
            self.spec.argv,
            cwd=str(self.spec.cwd) if self.spec.cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # line-buffered
        )
        self._reader = threading.Thread(target=self._read_stdout, name=f"bridge-{self.spec.name}", daemon=True)
        self._reader.start()

    def _read_stdout(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.rstrip("\n")
            with self._lock:
                self._log.append(line)
            if not self._ready.is_set() and self.spec.ready_pattern.search(line):
                self._ready.set()

    def wait_ready(self, timeout_s: float) -> ReadyResult:
        """Block until the readiness line appears, the process dies, or timeout."""
        start = time.monotonic()
        deadline = start + max(0.0, timeout_s)
        while True:
            if self._ready.is_set():
                return ReadyResult(True, f"{self.spec.name}: ready", time.monotonic() - start)
            rc = self.returncode
            if rc is not None:  # exited before printing readiness -> failure
                tail = " | ".join(self.recent_output()[-3:])
                return ReadyResult(False, f"{self.spec.name}: exited rc={rc} before ready ({tail})", time.monotonic() - start)
            if time.monotonic() >= deadline:
                tail = " | ".join(self.recent_output()[-3:])
                return ReadyResult(False, f"{self.spec.name}: not ready within {timeout_s:.1f}s ({tail})", time.monotonic() - start)
            time.sleep(0.02)

    def stop(self, term_grace_s: float = 5.0) -> None:
        """Graceful teardown: terminate (SIGTERM), wait, then kill (SIGKILL)."""
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=term_grace_s)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=term_grace_s)
                except subprocess.TimeoutExpired:  # pragma: no cover - extreme
                    pass
        if self._reader is not None:
            self._reader.join(timeout=2.0)
            self._reader = None
        self._proc = None

    # -- introspection ------------------------------------------------------
    @property
    def returncode(self) -> int | None:
        return self._proc.poll() if self._proc is not None else None

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def recent_output(self) -> list[str]:
        with self._lock:
            return list(self._log)


@dataclass
class FleetReadiness:
    """Aggregate readiness of every device in the fleet."""

    results: dict[str, ReadyResult] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.results) and all(r.ok for r in self.results.values())

    def problems(self) -> list[str]:
        return [r.detail for r in self.results.values() if not r.ok]


class Supervisor:
    """Owns a fleet of adapters and drives the whole-fleet lifecycle."""

    def __init__(self, adapters: list[DeviceAdapter]) -> None:
        if not adapters:
            raise ValueError("Supervisor needs at least one device adapter")
        self.adapters = adapters
        self._launched = False

    def launch_all(self, session) -> None:
        for a in self.adapters:
            a.launch(session)
        self._launched = True

    def wait_until_ready(self, timeout_s: float) -> FleetReadiness:
        """Wait for every adapter to report ready, sharing one deadline so a
        slow first device doesn't grant the rest extra time."""
        deadline = time.monotonic() + max(0.0, timeout_s)
        results: dict[str, ReadyResult] = {}
        for a in self.adapters:
            remaining = max(0.0, deadline - time.monotonic())
            results[a.name] = a.is_ready(remaining)
        return FleetReadiness(results)

    def stop_all(self) -> list[tuple[str, Exception]]:
        """Tear every adapter down (reverse launch order), best-effort.
        Returns any per-adapter errors instead of raising, so one failure
        can't strand the others still running."""
        errors: list[tuple[str, Exception]] = []
        for a in reversed(self.adapters):
            try:
                a.stop()
            except Exception as exc:  # keep tearing the rest down
                errors.append((a.name, exc))
        self._launched = False
        return errors
