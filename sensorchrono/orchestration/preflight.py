"""Preflight device scan — confirm each selected device actually responds
*before* staging, structurally killing the "wrong COM port / dead camera"
foot-guns.

Each check returns a :class:`CheckResult` (pass / warn / fail, required or
not). A required failure is a red-X blocker; a warning is a yellow-! the
operator can proceed past. All hardware libraries are imported lazily and a
missing library degrades the check to a warning (it can't be *proved* good,
but it shouldn't hard-block on the dev box). In dry-run the hardware checks are
skipped entirely.
"""
from __future__ import annotations

import socket
from dataclasses import dataclass, field

# status constants
PASS = "pass"
WARN = "warn"
FAIL = "fail"

DEFAULT_RCS_HOST = "localhost"
DEFAULT_RCS_PORT = 22345


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # PASS | WARN | FAIL
    detail: str = ""
    required: bool = True


@dataclass
class PreflightReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True iff no *required* check failed (warnings don't block)."""
        return not self.blockers()

    def blockers(self) -> list[CheckResult]:
        return [c for c in self.checks if c.required and c.status == FAIL]

    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == WARN]


# -- individual checks (each importable + independently testable) ----------
def check_labrecorder(host: str = DEFAULT_RCS_HOST, port: int = DEFAULT_RCS_PORT, *, timeout: float = 1.0) -> CheckResult:
    """Is LabRecorder's Remote Control Server reachable on its TCP port?
    A warning (not a blocker): the recorder layer falls back to CLI / manual."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return CheckResult("labrecorder_rcs", PASS, f"RCS reachable at {host}:{port}", required=False)
    except OSError as exc:
        return CheckResult("labrecorder_rcs", WARN, f"RCS not reachable ({exc}); will use CLI/manual fallback", required=False)


def check_serial_port(port: str | None) -> CheckResult:
    if not port:
        return CheckResult("shimmer_serial", FAIL, "no COM port bound")
    try:
        import serial
    except Exception:
        return CheckResult("shimmer_serial", WARN, "pyserial not installed; cannot probe port", required=True)
    try:
        sp = serial.Serial(port, timeout=0.5)
        sp.close()
        return CheckResult("shimmer_serial", PASS, f"{port} opened")
    except Exception as exc:
        return CheckResult("shimmer_serial", FAIL, f"{port} did not open: {exc}")


def check_camera(index: int | None) -> CheckResult:
    if index is None:
        return CheckResult("camera", FAIL, "no camera index bound")
    try:
        import cv2
    except Exception:
        return CheckResult("camera", WARN, "opencv not installed; cannot probe camera", required=True)
    cap = None
    try:
        cap = cv2.VideoCapture(index)
        if cap.isOpened():
            return CheckResult("camera", PASS, f"camera {index} opened")
        return CheckResult("camera", FAIL, f"camera {index} did not open")
    finally:
        if cap is not None:
            cap.release()


def check_microphone(device: str | int | None) -> CheckResult:
    try:
        import sounddevice as sd
    except Exception:
        return CheckResult("microphone", WARN, "sounddevice not installed; cannot probe mic", required=True)
    try:
        sd.query_devices(device, "input")
        return CheckResult("microphone", PASS, f"input device {device!r} present")
    except Exception as exc:
        return CheckResult("microphone", FAIL, f"input device {device!r} not found: {exc}")


def check_all(session, *, rcs_host: str = DEFAULT_RCS_HOST, rcs_port: int = DEFAULT_RCS_PORT) -> PreflightReport:
    """Run every check appropriate to ``session``. In dry-run, hardware checks
    are skipped (synthetic adapters need no hardware) and only LabRecorder
    reachability is probed informationally."""
    if getattr(session, "dry_run", False):
        return PreflightReport(
            checks=[
                CheckResult("dry_run", PASS, "dry-run: hardware checks skipped (synthetic streams)", required=False),
                check_labrecorder(rcs_host, rcs_port),
            ]
        )
    b = session.bindings
    return PreflightReport(
        checks=[
            check_serial_port(b.shimmer_com_port),
            check_camera(b.camera_index),
            check_microphone(b.mic_device),
            check_labrecorder(rcs_host, rcs_port),
        ]
    )
