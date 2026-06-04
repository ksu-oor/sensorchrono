"""Real bridge adapters: command construction, the readiness-regex contract,
the headless-Shimmer guard, and a stub-launch lifecycle (no hardware)."""
from __future__ import annotations

from sensorchrono.config import DeviceBindings, SessionConfig
from sensorchrono.contract import StreamName
from sensorchrono.devices.base import DeviceAdapter
from sensorchrono.devices.bridge_adapter import default_real_fleet
from sensorchrono.devices.camera import CameraAdapter
from sensorchrono.devices.keyboard import KeyboardAdapter
from sensorchrono.devices.microphone import MicrophoneAdapter
from sensorchrono.devices.shimmer_exg import ShimmerExgAdapter


def _session(tmp_path, **over):
    kw = dict(participant="p01", session="s1", task="rest", duration_s=30, out_dir=tmp_path / "o", dry_run=False)
    kw.update(over)
    return SessionConfig(**kw)


def test_ready_patterns_match_real_bridge_output():
    # The exact lines the bridges print — the stringly-typed contract that
    # silently breaks if either side drifts.
    assert ShimmerExgAdapter()._ready_pattern().search("[COM3] LSL outlet: ShimmerECG @ 256 Hz")
    assert ShimmerExgAdapter(mode="emg")._ready_pattern().search("[COM5] LSL outlet: ShimmerEMG @ 512 Hz")
    assert CameraAdapter().READY_PATTERN.search("[video] LSL outlet 'VideoFrames' is live.")
    assert MicrophoneAdapter().READY_PATTERN.search("[audio] LSL outlet 'Audio' is live.")
    assert KeyboardAdapter().READY_PATTERN.search("[keyboard_fiducial] LSL outlet 'KeyboardFiducial' is live.")


def test_shimmer_argv_is_always_headless(tmp_path):
    a = ShimmerExgAdapter()
    argv = a.build_argv(_session(tmp_path, bindings=DeviceBindings(shimmer_com_port="COM3", shimmer_ecg_port="COM3")))
    # both deadlock traps must be defused: --no-prompt AND a positional mode
    assert "--no-prompt" in argv
    assert "ecg" in argv
    assert "--record-seconds" in argv
    assert argv[argv.index("--ecg-port") + 1] == "COM3"


def test_shimmer_rejects_bad_mode():
    import pytest

    with pytest.raises(ValueError):
        ShimmerExgAdapter(mode="eeg")


def test_camera_argv_and_mp4_path(tmp_path):
    a = CameraAdapter()
    s = _session(tmp_path, bindings=DeviceBindings(camera_index=2))
    argv = a.build_argv(s)
    assert "--out-dir" in argv and str(s.out_dir) in argv
    assert argv[argv.index("--device") + 1] == "2"
    tag = argv[argv.index("--tag") + 1]
    assert a.mp4_path(s) == s.out_dir / f"{tag}_video.mp4"
    assert tag == "p01_s1_rest"


def test_streams_are_canonical():
    assert {s.name for s in ShimmerExgAdapter().streams()} == {
        StreamName.SHIMMER_ECG, StreamName.SHIMMER_DIAGNOSTICS_ECG,
    }
    assert ShimmerExgAdapter(mode="emg").streams()[0].name is StreamName.SHIMMER_EMG
    assert CameraAdapter().streams()[0].name is StreamName.VIDEO_FRAMES
    assert MicrophoneAdapter().streams()[0].name is StreamName.AUDIO
    assert KeyboardAdapter().streams()[0].name is StreamName.KEYBOARD_FIDUCIAL


def test_check_liveness_before_launch_is_not_ok():
    assert CameraAdapter().check_liveness(0.1).ok is False


def test_default_real_fleet():
    fleet = default_real_fleet()
    assert {a.name for a in fleet} == {"shimmer_exg", "camera", "mic", "keyboard"}
    assert all(isinstance(a, DeviceAdapter) for a in fleet)


def test_adapter_launch_ready_stop_with_stub(tmp_path):
    # A stub that mimics the video bridge's readiness line, then idles.
    stub = tmp_path / "stub_bridge.py"
    stub.write_text(
        "import sys, time\n"
        "print(\"[video] LSL outlet 'VideoFrames' is live.\")\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n"
    )
    a = CameraAdapter(script_path=stub)
    a.launch(_session(tmp_path, bindings=DeviceBindings(camera_index=0)))
    try:
        r = a.is_ready(5.0)
        assert r.ok, r.detail
        assert a.check_liveness(0.1).ok  # process is alive
    finally:
        a.stop()
    assert a.is_ready(0.1).ok is False  # torn down


def test_session_real_mode_builds_real_fleet(tmp_path):
    from sensorchrono.orchestration.session import SessionController

    s = _session(tmp_path, bindings=DeviceBindings(shimmer_com_port="COM3", camera_index=0))
    c = SessionController(s)
    assert {a.name for a in c._fleet()} == {"shimmer_exg", "camera", "mic", "keyboard"}
