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


def test_debug_flag_sets_up_log_file(tmp_path, monkeypatch, capsys):
    # --debug (with --info to avoid launching the GUI) must configure logging and
    # leave a log file behind, with the env snapshot written into it.
    monkeypatch.setenv("SENSORCHRONO_LOG_DIR", str(tmp_path / "logs"))
    assert entry.main(["--info", "--debug"]) == 0
    out = capsys.readouterr().out
    assert "logs:" in out
    log_file = tmp_path / "logs" / "sensorchrono.log"
    assert log_file.is_file()
    assert "environment snapshot" in log_file.read_text(encoding="utf-8")
