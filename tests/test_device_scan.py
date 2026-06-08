"""device_scan must be import-safe and hardware-safe: every probe degrades to
an empty list rather than raising, and the camera probe is opt-in (it never
opens a device unless explicitly asked over a non-empty index range)."""
from __future__ import annotations

from sensorchrono.orchestration import device_scan


def test_serial_ports_returns_typed_list():
    ports = device_scan.serial_ports()
    assert isinstance(ports, list)
    for p in ports:
        assert isinstance(p, device_scan.SerialPort)
        assert isinstance(p.device, str) and p.device


def test_microphones_returns_typed_list():
    mics = device_scan.microphones()
    assert isinstance(mics, list)
    for m in mics:
        assert isinstance(m, device_scan.AudioInput)
        assert isinstance(m.index, int)
        assert isinstance(m.name, str)


def test_cameras_empty_range_opens_nothing():
    # max_index=0 must short-circuit without touching any camera backend.
    assert device_scan.cameras(max_index=0) == []


def test_serial_ports_survive_missing_pyserial(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name.startswith("serial"):
            raise ImportError("no pyserial here")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert device_scan.serial_ports() == []
