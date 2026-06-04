"""Base value types: the LivenessReport gate logic and StreamDef defaults."""
from __future__ import annotations

from sensorchrono.contract import StreamName
from sensorchrono.devices.base import LivenessReport, StreamDef, StreamLiveness


def _row(name: StreamName, ok: bool, note: str = "") -> StreamLiveness:
    return StreamLiveness(
        name=name,
        present=ok,
        measured_rate_hz=256.0 if ok else 0.0,
        expected_rate_hz=256.0,
        max_gap_s=0.0,
        ok=ok,
        measured_channels=4 if ok else 0,
        expected_channels=4,
        note=note,
    )


def test_liveness_report_ok_requires_all_streams_ok():
    good = LivenessReport("d", (_row(StreamName.SHIMMER_ECG, True),))
    assert good.ok is True
    assert good.problems() == []

    mixed = LivenessReport(
        "d",
        (
            _row(StreamName.SHIMMER_ECG, True),
            _row(StreamName.AUDIO, False, note="no samples"),
        ),
    )
    assert mixed.ok is False
    assert mixed.problems() == ["Audio: no samples"]


def test_empty_liveness_report_is_not_ok():
    # An adapter that declares no streams must not green-light the gate.
    assert LivenessReport("d", ()).ok is False


def test_streamdef_from_contract_carries_channels():
    # The corrected contract: VideoFrames is 2 channels (frame_idx, cap_pos_ms).
    vf = StreamDef.from_contract(StreamName.VIDEO_FRAMES)
    assert vf.channels == 2
    assert vf.nominal_rate_hz == 30.0
    # rate override is honoured (a camera running at a non-default fps)
    assert StreamDef.from_contract(StreamName.VIDEO_FRAMES, rate_hz=60.0).nominal_rate_hz == 60.0
