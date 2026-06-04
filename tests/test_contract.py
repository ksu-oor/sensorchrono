"""The stream-name contract is the load-bearing string in this whole repo —
if a name here drifts from what the bridges emit / analysis consumes, sync
silently breaks. These tests pin the exact literal values."""
from __future__ import annotations

import pytest

from sensorchrono.contract import (
    ANALYSIS_CONSUMED,
    STREAM_SPECS,
    StreamName,
    spec,
)


def test_canonical_names_are_exact_literals():
    # Frozen ground truth, verified against the bridges + analysis/.
    assert StreamName.SHIMMER_ECG == "ShimmerECG"
    assert StreamName.SHIMMER_EMG == "ShimmerEMG"
    assert StreamName.SHIMMER_MARKERS == "ShimmerMarkers"
    assert StreamName.SHIMMER_DIAGNOSTICS_ECG == "ShimmerDiagnostics_ECG"
    assert StreamName.SHIMMER_ACCEL == "ShimmerAccel"
    assert StreamName.AUDIO == "Audio"
    assert StreamName.VIDEO_FRAMES == "VideoFrames"
    assert StreamName.KEYBOARD_FIDUCIAL == "KeyboardFiducial"


def test_every_stream_name_has_a_spec():
    for name in StreamName:
        assert name in STREAM_SPECS, f"{name} missing a StreamSpec"
        assert STREAM_SPECS[name].name is name


def test_spec_accepts_str_and_enum_and_rejects_unknown():
    assert spec("ShimmerECG").nominal_rate_hz == 256.0
    assert spec(StreamName.AUDIO).channels == 1
    with pytest.raises(ValueError):
        spec("NotAStream")


def test_analysis_consumed_is_subset_of_known_streams():
    assert ANALYSIS_CONSUMED <= set(StreamName)
    # The four streams postprocess actually reads, plus diagnostics for drift.
    assert StreamName.SHIMMER_ECG in ANALYSIS_CONSUMED
    assert StreamName.AUDIO in ANALYSIS_CONSUMED
    assert StreamName.VIDEO_FRAMES in ANALYSIS_CONSUMED
    assert StreamName.KEYBOARD_FIDUCIAL in ANALYSIS_CONSUMED
    assert StreamName.SHIMMER_DIAGNOSTICS_ECG in ANALYSIS_CONSUMED
