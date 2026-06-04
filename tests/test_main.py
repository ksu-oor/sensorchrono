"""`python -m sensorchrono --info` (the text summary; GUI path covered in test_gui)."""
from __future__ import annotations

import sensorchrono.__main__ as entry


def test_info_returns_zero(capsys):
    assert entry.main(["--info"]) == 0
    out = capsys.readouterr().out
    assert "sensorchrono" in out
    assert "profiles" in out
    assert "pylsl" in out


def test_info_returns_one_when_profiles_fail(monkeypatch, capsys):
    def boom():
        raise RuntimeError("disk gone")

    monkeypatch.setattr(entry, "list_profiles", boom)
    assert entry.main(["--info"]) == 1
    assert "error" in capsys.readouterr().out.lower()
