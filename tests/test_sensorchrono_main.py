"""Frozen entry-point dispatch (build/sensorchrono_main.py).

The frozen exe can't do ``python -m``, so it self-dispatches on a leading flag.
We exercise the ``--run-bridge`` branch here: it must import the named module
and hand it the remaining argv, returning a clean exit code even when the
bridge's ``main()`` returns ``None``. ``build/`` is not a package, so we load
the entry module by file path.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_ENTRY_PATH = Path(__file__).resolve().parents[1] / "build" / "sensorchrono_main.py"


def _load_entry():
    spec = importlib.util.spec_from_file_location("sensorchrono_main_entry", _ENTRY_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # __name__ != "__main__", so the guard stays inert
    return mod


def test_run_bridge_dispatches_remaining_argv_to_module_main(monkeypatch):
    entry = _load_entry()
    recorded = {}

    def _fake_main(argv):
        recorded["argv"] = argv
        return 0

    fake = types.ModuleType("fake_bridge_mod")
    fake.main = _fake_main
    monkeypatch.setitem(sys.modules, "fake_bridge_mod", fake)
    monkeypatch.setattr(
        sys, "argv",
        ["SensorChrono.exe", "--run-bridge", "fake_bridge_mod", "--out-dir", "X", "--tag", "t"],
    )

    assert entry._main() == 0
    assert recorded["argv"] == ["--out-dir", "X", "--tag", "t"]


def test_run_bridge_unbuffers_stdout_before_dispatch(monkeypatch):
    # Regression: the frozen interpreter ignores PYTHONUNBUFFERED and block-buffers
    # a long-running bridge's stdout, so its readiness line ("… is live") never
    # reaches the supervisor and staging times out though the stream is live. The
    # dispatch MUST unbuffer stdout BEFORE handing off to the (non-returning) bridge.
    entry = _load_entry()
    calls: list[str] = []
    monkeypatch.setattr(entry, "_unbuffer_std_streams", lambda: calls.append("unbuffer"))
    fake = types.ModuleType("fake_bridge_buf")
    fake.main = lambda argv: calls.append("main")
    monkeypatch.setitem(sys.modules, "fake_bridge_buf", fake)
    monkeypatch.setattr(sys, "argv", ["SensorChrono.exe", "--run-bridge", "fake_bridge_buf"])

    assert entry._main() == 0
    assert calls == ["unbuffer", "main"], "stdout must be unbuffered before the bridge runs"


def test_unbuffer_std_streams_enables_write_through(monkeypatch):
    import io

    entry = _load_entry()
    w = io.TextIOWrapper(io.BytesIO(), line_buffering=False, write_through=False)
    monkeypatch.setattr(sys, "stdout", w)
    monkeypatch.setattr(sys, "stderr", w)
    entry._unbuffer_std_streams()
    assert w.write_through is True and w.line_buffering is True


def test_unbuffer_std_streams_survives_none_streams(monkeypatch):
    # A windowed build may have sys.stdout = None; unbuffering must not raise.
    entry = _load_entry()
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    entry._unbuffer_std_streams()  # should be a quiet no-op


def test_run_bridge_none_return_becomes_zero(monkeypatch):
    # Real bridges' main() returns None; the dispatch must still yield exit 0.
    entry = _load_entry()
    fake = types.ModuleType("fake_bridge_none")
    fake.main = lambda argv: None
    monkeypatch.setitem(sys.modules, "fake_bridge_none", fake)
    monkeypatch.setattr(sys, "argv", ["SensorChrono.exe", "--run-bridge", "fake_bridge_none"])

    assert entry._main() == 0
