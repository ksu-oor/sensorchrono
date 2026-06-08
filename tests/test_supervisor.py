"""BridgeProcess against tiny real subprocesses + Supervisor fleet lifecycle."""
from __future__ import annotations

import re
import sys

import pytest

from sensorchrono.config import SessionConfig
from sensorchrono.devices.simulated import default_simulated_fleet
from sensorchrono.orchestration.supervisor import BridgeProcess, BridgeSpec, Supervisor


def _bridge(prog: str, pattern: str) -> BridgeProcess:
    spec = BridgeSpec("t", [sys.executable, "-u", "-c", prog], re.compile(pattern))
    return BridgeProcess(spec)


def _session(tmp_path):
    return SessionConfig(participant="p", session="s", task="t", duration_s=30, out_dir=tmp_path / "o", dry_run=True)


def test_bridge_ready_detected():
    bp = _bridge("import time;print(\"[t] LSL outlet 'X' is live.\");time.sleep(30)", r"is live")
    bp.start()
    try:
        r = bp.wait_ready(5.0)
        assert r.ok, r.detail
        assert bp.is_alive()
    finally:
        bp.stop()
    assert not bp.is_alive()


def test_bridge_ready_detected_without_dash_u_or_flush():
    # Regression: production argv carries NO ``-u`` (only the test helper did),
    # and a bridge's readiness print is not explicitly flushed. A child whose
    # stdout is a pipe block-buffers by default, so the line would strand in the
    # buffer past the deadline while the LSL stream is already live (the real
    # "staging fails though the stream is up" bug). BridgeProcess.start must
    # force PYTHONUNBUFFERED so the line arrives immediately.
    prog = "import time;print(\"[t] LSL outlet 'X' is live.\");time.sleep(30)"
    bp = BridgeProcess(BridgeSpec("t", [sys.executable, "-c", prog], re.compile(r"is live")))
    bp.start()
    try:
        r = bp.wait_ready(5.0)
        assert r.ok, r.detail
    finally:
        bp.stop()


def test_bridge_early_exit_is_failure():
    bp = _bridge("import sys;sys.exit(3)", r"is live")
    bp.start()
    try:
        r = bp.wait_ready(5.0)
        assert not r.ok and "rc=3" in r.detail
    finally:
        bp.stop()


def test_bridge_timeout_when_never_ready():
    bp = _bridge("import time;time.sleep(30)", r"is live")
    bp.start()
    try:
        r = bp.wait_ready(0.3)
        assert not r.ok and "not ready" in r.detail
    finally:
        bp.stop()


def test_supervisor_fleet_lifecycle(tmp_path):
    sup = Supervisor(default_simulated_fleet())
    sup.launch_all(_session(tmp_path))
    r = sup.wait_until_ready(2.0)
    assert r.ok, r.problems()
    assert sup.stop_all() == []


def test_supervisor_not_ready_on_slow_device(tmp_path):
    fleet = default_simulated_fleet()
    fleet[0].startup_delay_s = 5.0  # warms up far longer than the timeout
    sup = Supervisor(fleet)
    sup.launch_all(_session(tmp_path))
    try:
        assert not sup.wait_until_ready(0.3).ok
    finally:
        sup.stop_all()


def test_wait_until_ready_does_not_starve_fast_device_behind_slow(tmp_path):
    # A slow device listed first must NOT consume the whole deadline and starve
    # the fast ones behind it (the real "shimmer ate 20s -> camera not ready
    # within 0.0s" bug). The poll loop gives each device the full window.
    fleet = default_simulated_fleet()
    fleet[0].startup_delay_s = 10.0  # slow: won't be ready inside the window
    sup = Supervisor(fleet)
    sup.launch_all(_session(tmp_path))
    try:
        r = sup.wait_until_ready(0.5)
        assert not r.ok  # the slow device alone keeps the fleet from all-ready
        ready_names = [name for name, res in r.results.items() if res.ok]
        assert len(ready_names) == len(fleet) - 1  # every fast device still recognised
    finally:
        sup.stop_all()


def test_supervisor_requires_adapters():
    with pytest.raises(ValueError):
        Supervisor([])
