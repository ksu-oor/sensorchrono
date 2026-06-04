"""postprocess_runner: command construction + report parsing (no real pipeline)."""
from __future__ import annotations

import json

import pytest

from sensorchrono.orchestration.postprocess_runner import (
    PostprocessError,
    build_command,
    parse_report,
)


def test_build_command_minimal():
    cmd = build_command("r.xdf", "OUT", python="py")
    assert cmd[:5] == ["py", "-m", "sensorchrono.orchestration.postprocess_runner", "--xdf", "r.xdf"]
    assert "--out-dir" in cmd and "OUT" in cmd
    assert "--mp4" not in cmd and "--profile-lag-json" not in cmd


def test_build_command_full():
    cmd = build_command("r.xdf", "OUT", mp4="v.mp4", profile_lag_ms={"Audio": 46.5}, skip_parquet=True, python="py")
    assert "--mp4" in cmd and "v.mp4" in cmd
    i = cmd.index("--profile-lag-json")
    assert json.loads(cmd[i + 1]) == {"Audio": 46.5}
    assert "--skip-parquet" in cmd


def test_parse_report_reads_status_and_stages(tmp_path):
    data = {
        "xdf": "r.xdf", "mp4": None, "out_dir": str(tmp_path),
        "stages": [{"name": "5_residual_check", "status": "ok", "detail": "{}", "artifacts": []}],
        "audit_verdict": "PASS", "audit_summary_issues": [], "overall_status": "ok",
    }
    (tmp_path / "pipeline_report.json").write_text(json.dumps(data))
    (tmp_path / "pipeline_report.md").write_text("# report")
    res = parse_report(tmp_path)
    assert res.ok and not res.failed
    assert res.audit_verdict == "PASS"
    assert res.stage("5_residual_check")["status"] == "ok"
    assert res.report_md is not None
    assert "overall=ok" in res.summary()


def test_parse_report_missing_raises(tmp_path):
    with pytest.raises(PostprocessError):
        parse_report(tmp_path)
