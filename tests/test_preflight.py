"""Preflight: dry-run skip path, LabRecorder reachability, blocker logic."""
from __future__ import annotations

import socket

import pytest

from sensorchrono.config import DeviceBindings, SessionConfig
from sensorchrono.orchestration import preflight


def _session(tmp_path, **over):
    kw = dict(participant="p", session="s", task="t", duration_s=30, out_dir=tmp_path / "o", dry_run=True)
    kw.update(over)
    return SessionConfig(**kw)


def test_dry_run_skips_hardware(tmp_path):
    rep = preflight.check_all(_session(tmp_path))
    assert rep.ok
    assert any(c.name == "dry_run" for c in rep.checks)


def test_labrecorder_reachable_passes():
    srv = socket.socket()
    srv.bind(("localhost", 0))
    srv.listen(1)
    host, port = srv.getsockname()
    try:
        r = preflight.check_labrecorder(host, port)
        assert r.status == preflight.PASS and not r.required
    finally:
        srv.close()


def test_labrecorder_unreachable_is_nonblocking_warn():
    r = preflight.check_labrecorder("localhost", 1, timeout=0.5)
    assert r.status == preflight.WARN and not r.required


def test_real_capture_without_bindings_blocks(tmp_path):
    sess = _session(tmp_path, dry_run=False, bindings=DeviceBindings())
    rep = preflight.check_all(sess)
    assert not rep.ok
    assert any(c.name == "shimmer_serial" and c.status == preflight.FAIL for c in rep.checks)
    assert any(c.name == "camera" and c.status == preflight.FAIL for c in rep.checks)


# -- RCS dry-run wording ----------------------------------------------------
def test_dry_run_rcs_unreachable_is_worded_as_expected(tmp_path):
    # In dry-run, RCS-not-reachable is the benign expected state (LabRecorder
    # isn't launched until a real session), not a fault.
    r = preflight.check_labrecorder("localhost", 1, timeout=0.3, dry_run=True)
    assert r.status == preflight.WARN and not r.required
    assert "expected in dry run" in r.detail
    assert "fallback" not in r.detail.lower()


def test_real_rcs_unreachable_keeps_fallback_wording():
    r = preflight.check_labrecorder("localhost", 1, timeout=0.3, dry_run=False)
    assert r.status == preflight.WARN
    assert "fallback" in r.detail.lower()


def test_check_all_dry_run_uses_expected_rcs_wording(tmp_path):
    # Port 1 refuses instantly, so the dry-run wording path runs end-to-end.
    rep = preflight.check_all(_session(tmp_path), rcs_port=1)
    rcs = next(c for c in rep.checks if c.name == "labrecorder_rcs")
    assert "expected in dry run" in rcs.detail


# -- COM-port classification (the domain-judgment contribution point) -------
class _FakePort:
    def __init__(self, device, description="", hwid="", vid=None, pid=None):
        self.device = device
        self.description = description
        self.hwid = hwid
        self.vid = vid
        self.pid = pid


def test_classify_absent_port_lists_available():
    available = [_FakePort("COM4", "Shimmer3-1234")]
    msg = preflight.classify_serial_error(FileNotFoundError("nope"), "COM3", available)
    assert "COM3" in msg
    assert "COM4" in msg  # the operator is told where the Shimmer actually is


def test_classify_access_denied_says_in_use():
    available = [_FakePort("COM3", "Shimmer3-1234")]
    msg = preflight.classify_serial_error(PermissionError("Access is denied"), "COM3", available)
    assert "in use" in msg.lower()


def test_classify_present_but_not_found():
    available = [_FakePort("COM3", "Shimmer3-1234")]
    msg = preflight.classify_serial_error(FileNotFoundError("missing"), "COM3", available)
    assert "COM3" in msg


def test_classify_generic_oserror_is_verbatim():
    msg = preflight.classify_serial_error(OSError("semaphore timeout"), "COM3", [])
    assert "semaphore timeout" in msg


def test_check_serial_port_classifies_permission_error(monkeypatch):
    serial = pytest.importorskip("serial")
    from serial.tools import list_ports

    monkeypatch.setattr(list_ports, "comports", lambda: [_FakePort("COM3", "Shimmer3-1234")])

    def _boom(*a, **k):
        raise PermissionError("Access is denied")

    monkeypatch.setattr(serial, "Serial", _boom)
    r = preflight.check_serial_port("COM3")
    assert r.status == preflight.FAIL
    assert "in use" in r.detail.lower()


def test_check_serial_port_absent_lists_other_ports(monkeypatch):
    serial = pytest.importorskip("serial")
    from serial.tools import list_ports

    monkeypatch.setattr(list_ports, "comports", lambda: [_FakePort("COM4", "Shimmer3-1234")])

    def _boom(*a, **k):
        raise FileNotFoundError("could not open port COM3")

    monkeypatch.setattr(serial, "Serial", _boom)
    r = preflight.check_serial_port("COM3")
    assert r.status == preflight.FAIL
    assert "COM4" in r.detail


def test_enumerate_serial_ports_returns_list_or_none():
    ports = preflight.enumerate_serial_ports()
    assert ports is None or isinstance(ports, list)
