"""Simulated adapters must conform to the DeviceAdapter ABC and run the full
launch→ready→liveness→stop lifecycle on a box with no pylsl/liblsl."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sensorchrono.config import DEFAULT_PROFILE_ID, SessionConfig
from sensorchrono.contract import StreamName
from sensorchrono.devices.base import DeviceAdapter, StreamDef
from sensorchrono.devices.simulated import (
    SimulatedCamera,
    SimulatedKeyboard,
    SimulatedMicrophone,
    SimulatedShimmerEXG,
    default_simulated_fleet,
    synth_audio_block,
    synth_ecg,
)


def _session(tmp_path: Path) -> SessionConfig:
    return SessionConfig(
        participant="p01",
        session="s1",
        task="rest",
        duration_s=30,
        out_dir=tmp_path / "out",
        profile_id=DEFAULT_PROFILE_ID,
        dry_run=True,
    )


def test_fleet_is_the_proven_core():
    fleet = default_simulated_fleet()
    names = {a.name for a in fleet}
    assert names == {"shimmer_exg", "camera", "mic", "keyboard"}
    assert all(isinstance(a, DeviceAdapter) for a in fleet)


def test_streams_use_canonical_names():
    assert {s.name for s in SimulatedShimmerEXG().streams()} == {
        StreamName.SHIMMER_ECG,
        StreamName.SHIMMER_DIAGNOSTICS_ECG,
    }
    assert SimulatedCamera().streams()[0].name is StreamName.VIDEO_FRAMES
    assert SimulatedMicrophone().streams()[0].name is StreamName.AUDIO
    assert SimulatedKeyboard().streams()[0].name is StreamName.KEYBOARD_FIDUCIAL
    for adapter in default_simulated_fleet():
        for sdef in adapter.streams():
            assert isinstance(sdef, StreamDef)


def test_lifecycle_without_pylsl(tmp_path):
    a = SimulatedShimmerEXG()
    # before launch
    assert a.is_ready(0.1).ok is False
    assert a.check_liveness(0.1).ok is False
    # launch -> ready -> healthy
    a.launch(_session(tmp_path))
    assert a.is_ready(0.1).ok is True
    report = a.check_liveness(0.1)
    assert report.ok is True
    assert {s.name for s in report.streams} == {
        StreamName.SHIMMER_ECG,
        StreamName.SHIMMER_DIAGNOSTICS_ECG,
    }
    # stop is idempotent
    a.stop()
    a.stop()
    assert a.is_ready(0.1).ok is False


def test_synth_ecg_shape_and_bounds():
    n, fs = 2560, 256.0
    sig = synth_ecg(n, fs, hr_bpm=72.0)
    assert sig.shape == (n,)
    assert sig.dtype == np.float64
    assert np.all(np.isfinite(sig))
    assert np.abs(sig).max() <= 1.5  # contract the morphology must keep
    # real QRS morphology, not a gentle sine: a tall sharp R wave and a
    # negative Q/S deflection should both be present.
    assert sig.max() > 0.8
    assert sig.min() < -0.05


def test_synth_audio_block_has_periodic_taps():
    fs = 48000.0
    block = synth_audio_block(int(fs * 4), fs, tap_period_s=2.0)
    assert block.dtype == np.float32
    assert np.all(np.abs(block) <= 1.0)
    # The click bursts should make the peak clearly louder than the noise floor.
    assert np.abs(block).max() > 0.3
