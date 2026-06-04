"""The one runnable surface in Phase 0: `python -m sensorchrono`."""
from __future__ import annotations

import sensorchrono.__main__ as entry


def test_main_returns_zero(capsys):
    assert entry.main([]) == 0
    out = capsys.readouterr().out
    assert "sensorchrono" in out
    assert "profiles" in out
    assert "pylsl" in out


def test_main_returns_one_when_profiles_fail(monkeypatch, capsys):
    def boom():
        raise RuntimeError("disk gone")

    monkeypatch.setattr(entry, "list_profiles", boom)
    assert entry.main([]) == 1
    assert "error" in capsys.readouterr().out.lower()
