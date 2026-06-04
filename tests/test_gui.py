"""Headless GUI tests (offscreen Qt). Skipped where PySide6 isn't installed
(system Python); they run under the venv. They exercise FSM↔page wiring and the
custom widgets — not real LSL timing."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

import numpy as np
from PySide6 import QtWidgets

from sensorchrono.config import SessionConfig
from sensorchrono.contract import StreamName
from sensorchrono.devices.base import LivenessReport, StreamLiveness
from sensorchrono.orchestration.postprocess_runner import PostprocessResult
from sensorchrono.orchestration.session import SessionState
from sensorchrono.ui.main_window import MainWindow
from sensorchrono.ui.video_preview import VideoPreview, synthetic_frame
from sensorchrono.ui.waveform import AudioLevelMeter, WaveformWidget


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _session(tmp_path, **over):
    kw = dict(participant="p01", session="s1", task="rest", duration_s=15, out_dir=tmp_path / "o", dry_run=True)
    kw.update(over)
    return SessionConfig(**kw)


def test_window_starts_on_setup(app, tmp_path):
    w = MainWindow(_session(tmp_path))
    assert w.stack.currentWidget() is w.setup


def test_setup_advances_to_preflight(app, tmp_path):
    w = MainWindow(_session(tmp_path))
    w.setup.started.emit()
    app.processEvents()
    assert w.controller.state == SessionState.PREFLIGHT
    assert w.stack.currentWidget() is w.preflight
    # dry-run preflight is ok -> proceed button enabled
    assert w.preflight._proceed.isEnabled()


def test_invalid_config_keeps_setup_and_shows_error(app, tmp_path):
    w = MainWindow(_session(tmp_path))
    w.setup.participant.setText("")  # empty -> ConfigError
    w.setup.started.emit()
    app.processEvents()
    assert w.stack.currentWidget() is w.setup
    assert w.setup.error.text()


def test_liveness_button_tracks_report(app, tmp_path):
    w = MainWindow(_session(tmp_path))
    green = LivenessReport("fleet", (StreamLiveness(StreamName.AUDIO, True, 48000, 48000, 0.0, True, 1, 1, ""),))
    w.liveness.update_report(green)
    assert w.liveness._go.isEnabled()
    red = LivenessReport("fleet", (StreamLiveness(StreamName.AUDIO, False, 0, 48000, 0.0, False, 0, 1, "absent"),))
    w.liveness.update_report(red)
    assert not w.liveness._go.isEnabled()


def test_calibrate_done_button_needs_threshold(app, tmp_path):
    w = MainWindow(_session(tmp_path))
    w.calibrate.update_count(3, 10, calibrated=False)
    assert not w.calibrate._done.isEnabled()
    w.calibrate.update_count(10, 10, calibrated=True)
    assert w.calibrate._done.isEnabled()


def test_widgets_render_without_error(app):
    wf = WaveformWidget(buffer_n=256)
    wf.append(np.sin(np.linspace(0, 10, 500)))  # more than the buffer
    assert wf._buf.shape == (256,)
    m = AudioLevelMeter()
    m.set_level(0.5)
    assert m.value() == 50
    vp = VideoPreview()
    vp.resize(320, 180)
    vp.set_frame(synthetic_frame(1.0))
    assert vp.pixmap() is not None and not vp.pixmap().isNull()


def test_done_page_summary(app, tmp_path):
    w = MainWindow(_session(tmp_path))
    w._build_controller(w._base_session)
    w.controller.calibrated = True
    w.controller.postprocess_result = PostprocessResult(overall_status="ok", audit_verdict="PASS")
    w.done.show_summary(w.controller)
    text = w.done.summary.text()
    assert "p01" in text and ("ok" in text or "PASS" in text)
