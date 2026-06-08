"""Enumerate the hardware an operator can bind on the SETUP page.

Import-safe on any platform (stdlib only at import time) so it is unit-testable
on macOS/CI. Every probe imports its hardware library lazily and degrades to an
empty list if the library is missing or the scan raises — the SETUP page stays
usable (the operator can always type a value manually) and tests never touch
real hardware.

Three probes, mirroring the three bindings in
:class:`sensorchrono.config.DeviceBindings`:

* :func:`serial_ports` — COM ports for the Shimmer (Bluetooth RFCOMM shows up
  as a "Standard Serial over Bluetooth link" COM port). Cheap + non-intrusive.
* :func:`microphones` — sounddevice input devices for the BRIO mic. Cheap.
* :func:`cameras` — UVC camera indices. **Intrusive** (the only portable way to
  know an index is live is to briefly open it), so it is *opt-in*: the SETUP
  page calls it only when the operator clicks "Rescan devices", never on every
  keystroke or at startup.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SerialPort:
    device: str  # e.g. "COM3"
    description: str = ""


@dataclass(frozen=True)
class AudioInput:
    index: int
    name: str


def serial_ports() -> list[SerialPort]:
    """Available serial/COM ports, best-effort. Empty if pyserial is absent."""
    try:
        from serial.tools import list_ports
    except Exception:
        return []
    try:
        ports = list_ports.comports()
    except Exception:
        return []
    out = [SerialPort(device=str(p.device), description=str(p.description or "")) for p in ports]
    # Bluetooth RFCOMM ports (the Shimmer) sort to the front so the most likely
    # pick is the default; everything else keeps OS order after them.
    out.sort(key=lambda p: (0 if "bluetooth" in p.description.lower() else 1, p.device))
    return out


def microphones() -> list[AudioInput]:
    """Available audio *input* devices, best-effort. Empty without sounddevice."""
    try:
        import sounddevice as sd
    except Exception:
        return []
    try:
        devices = sd.query_devices()
    except Exception:
        return []
    out: list[AudioInput] = []
    for i, d in enumerate(devices):
        try:
            if int(d.get("max_input_channels", 0)) > 0:
                out.append(AudioInput(index=i, name=str(d.get("name", f"device {i}"))))
        except Exception:
            continue
    return out


def cameras(max_index: int = 4, *, warmup_reads: int = 0) -> list[int]:
    """Probe camera indices ``0..max_index-1`` and return those that open.

    Intrusive (opens each device briefly), so callers should treat this as an
    operator-initiated action, not an every-frame poll. Empty without OpenCV.
    On Windows we prefer the DirectShow backend, which enumerates UVC cameras
    far faster and more reliably than the default MSMF backend.
    """
    try:
        import cv2
    except Exception:
        return []
    backend = getattr(cv2, "CAP_DSHOW", 0)
    found: list[int] = []
    for idx in range(max(0, max_index)):
        cap = None
        try:
            cap = cv2.VideoCapture(idx, backend) if backend else cv2.VideoCapture(idx)
            if cap.isOpened():
                ok = True
                for _ in range(max(0, warmup_reads)):
                    ok, _frame = cap.read()
                    if not ok:
                        break
                if ok:
                    found.append(idx)
        except Exception:
            pass
        finally:
            if cap is not None:
                cap.release()
    return found
