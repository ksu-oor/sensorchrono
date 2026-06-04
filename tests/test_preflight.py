"""Preflight: dry-run skip path, LabRecorder reachability, blocker logic."""
from __future__ import annotations

import socket

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
