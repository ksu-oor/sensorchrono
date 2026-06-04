"""The wizard FSM: full happy path + guards, driven headless with the
simulated fleet and fakes (no Qt, no hardware, no LabRecorder)."""
from __future__ import annotations

import pytest

from sensorchrono.config import SessionConfig
from sensorchrono.contract import StreamName
from sensorchrono.devices.base import (
    DeviceAdapter,
    LivenessReport,
    ReadyResult,
    StreamDef,
    StreamLiveness,
)
from sensorchrono.devices.simulated import default_simulated_fleet
from sensorchrono.orchestration import preflight
from sensorchrono.orchestration.postprocess_runner import PostprocessResult
from sensorchrono.orchestration.session import (
    InvalidTransition,
    SessionController,
    SessionState,
)


def _session(tmp_path, **over):
    kw = dict(participant="p01", session="s1", task="rest", duration_s=30, out_dir=tmp_path / "o", dry_run=True)
    kw.update(over)
    return SessionConfig(**kw)


class _FakeRecorder:
    def __init__(self):
        self.started = self.stopped = False

    def start(self, session, *, run=1):
        self.started = True

    def stop(self):
        self.stopped = True


def test_full_happy_path(tmp_path):
    rec = _FakeRecorder()
    result = PostprocessResult(overall_status="ok", audit_verdict="PASS")
    c = SessionController(
        _session(tmp_path),
        adapters=default_simulated_fleet(),
        recorder=rec,
        postprocess_fn=lambda xdf, mp4: result,
    )
    states: list[SessionState] = []
    c.state_changed.connect(lambda old, new: states.append(new))
    counts: list[int] = []
    c.fiducial_counted.connect(counts.append)

    c.run_preflight()
    assert c.state == SessionState.PREFLIGHT
    c.start_staging()
    assert c.state == SessionState.LIVENESS and c.staging_green
    c.start_calibration()
    assert c.state == SessionState.CALIBRATE and rec.started
    for t in [float(i) for i in range(12)]:  # 12 clean taps, ≥ min_count
        c.note_fiducial(t)
    assert c.fiducial_count >= 10 and counts[-1] >= 10
    c.to_recording()
    assert c.state == SessionState.RECORD and c.calibrated
    c.stop_recording()
    assert c.state == SessionState.DONE and rec.stopped
    assert c.postprocess_result is result
    assert states == [
        SessionState.PREFLIGHT, SessionState.LIVENESS, SessionState.CALIBRATE,
        SessionState.RECORD, SessionState.POSTPROCESS, SessionState.DONE,
    ]


def test_invalid_transition_out_of_order(tmp_path):
    c = SessionController(_session(tmp_path), adapters=default_simulated_fleet())
    with pytest.raises(InvalidTransition):
        c.start_calibration()  # not in LIVENESS


def test_preflight_blocker_goes_to_error(tmp_path):
    bad = preflight.PreflightReport(
        checks=[preflight.CheckResult("camera", preflight.FAIL, "dead camera", required=True)]
    )
    c = SessionController(_session(tmp_path), adapters=default_simulated_fleet(), preflight_fn=lambda s: bad)
    c.run_preflight()
    assert c.state == SessionState.ERROR and c.error


class _NotGreenAdapter(DeviceAdapter):
    name = "ng"

    def streams(self):
        return [StreamDef.from_contract(StreamName.AUDIO)]

    def launch(self, session):
        pass

    def is_ready(self, timeout_s):
        return ReadyResult(True, "ng: ready")  # comes up fine...

    def check_liveness(self, window_s):
        # ...but never produces healthy samples
        return LivenessReport("ng", (StreamLiveness(
            StreamName.AUDIO, True, 0.0, 48000.0, 0.0, False, 0, 1, "no samples"),))

    def stop(self):
        pass


def test_liveness_not_green_blocks_calibration(tmp_path):
    c = SessionController(_session(tmp_path), adapters=[_NotGreenAdapter()])
    c.run_preflight()
    c.start_staging()
    assert c.state == SessionState.LIVENESS and not c.staging_green
    with pytest.raises(InvalidTransition):
        c.start_calibration()


def test_uncalibrated_recording_requires_opt_in(tmp_path):
    c = SessionController(_session(tmp_path), adapters=default_simulated_fleet(), postprocess_fn=lambda x, m: None)
    c.run_preflight()
    c.start_staging()
    c.start_calibration()
    c.note_fiducial(0.0)  # only one tap -> not calibrated
    with pytest.raises(InvalidTransition):
        c.to_recording(allow_uncalibrated=False)
    c.to_recording(allow_uncalibrated=True)  # explicit opt-in proceeds
    assert c.state == SessionState.RECORD and not c.calibrated
