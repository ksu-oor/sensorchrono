"""Profile loading must surface the real fallback lags + drift from the
committed YAML, mapped to canonical stream names."""
from __future__ import annotations

import pytest

from sensorchrono.contract import StreamName
from sensorchrono.profiles import ProfileError, list_profiles, load_profile

SHIMMER = "shimmer3_exg_sr47-5-1"


def test_list_profiles_includes_committed_yaml():
    profiles = list_profiles()
    assert SHIMMER in profiles
    # Three committed profiles today.
    assert "logitech_brio" in profiles
    assert "apple_wired_usb_keyboard" in profiles


def test_shimmer_profile_fallback_lags_mapped_to_canonical_names():
    p = load_profile(SHIMMER)
    # Descriptive YAML keys (Audio_BRIO_via_USB, VideoFrames_BRIO_via_USB)
    # must map back to canonical stream names.
    assert p.lag_ms(StreamName.AUDIO) == pytest.approx(46.5)
    assert p.lag_ms(StreamName.VIDEO_FRAMES) == pytest.approx(1.35)
    # ECG lag is only a lower bound / unmeasured -> None, not 0.
    assert p.lag_ms(StreamName.SHIMMER_ECG) is None


def test_shimmer_profile_drift_and_bridge_defaults():
    p = load_profile(SHIMMER)
    assert p.drift_median_ppm == pytest.approx(35.8)
    assert p.bridge_defaults["exg"]["sampling_rate_hz"] == 256
    assert p.bridge_defaults["exg"]["mode"] == "ecg"


def test_unknown_profile_raises():
    with pytest.raises(ProfileError):
        load_profile("does-not-exist")


def test_profile_without_calibration_is_tolerated():
    # The keyboard profile has no calibration/bridges; loading must not crash.
    p = load_profile("apple_wired_usb_keyboard")
    assert isinstance(p.fallback_lag_ms, dict)
    assert p.drift_median_ppm is None or isinstance(p.drift_median_ppm, float)
