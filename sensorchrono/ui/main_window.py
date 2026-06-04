"""The QMainWindow shell: a QStackedWidget of wizard pages wired to a
:class:`SessionController`. The FSM is the single source of truth — page
buttons call controller transitions, and the controller's Signals drive which
page is shown and what it displays.

Threading note: FSM transitions run on the GUI thread. In dry-run they're fast
(no hardware waits, post-processing skipped). For real captures the long steps
(staging readiness, post-processing) should move to a worker QThread — flagged
for Phase 5. Liveness + the live feed are pulled by QTimers on the GUI thread,
which keeps cross-thread widget access safe.
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from sensorchrono.config import ConfigError, SessionConfig, default_dry_run
from sensorchrono.contract import StreamName
from sensorchrono.orchestration.lsl_monitor import LslMonitor
from sensorchrono.orchestration.session import SessionController, SessionState
from sensorchrono.ui.pages import (
    CalibratePage,
    DonePage,
    ErrorPage,
    LivenessPage,
    PreflightPage,
    RecordPage,
    SetupPage,
)
from sensorchrono.ui.video_preview import synthetic_frame

_PAGE_ORDER = [
    SessionState.SETUP, SessionState.PREFLIGHT, SessionState.LIVENESS,
    SessionState.CALIBRATE, SessionState.RECORD, SessionState.POSTPROCESS,
    SessionState.DONE, SessionState.ERROR,
]


class LiveView(QtCore.QObject):
    """Pull ECG/audio off LSL and push synthetic video into the staging widgets
    via a GUI-thread QTimer. Best-effort: degrades silently without pylsl."""

    def __init__(self, page: LivenessPage, *, dry_run: bool, fps: int = 30) -> None:
        super().__init__()
        self._page = page
        self._dry_run = dry_run
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(int(1000 / fps))
        self._timer.timeout.connect(self._tick)
        self._t0 = time.monotonic()
        self._ecg = None
        self._audio = None

    def start(self) -> None:
        self._resolve_inlets()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._ecg = self._audio = None

    def _resolve_inlets(self) -> None:
        try:
            import pylsl
        except Exception:
            return
        for name, attr in ((StreamName.SHIMMER_ECG, "_ecg"), (StreamName.AUDIO, "_audio")):
            found = pylsl.resolve_byprop("name", str(name), 1, 0.5)
            if found:
                setattr(self, attr, pylsl.StreamInlet(found[0], max_buflen=2))

    def _tick(self) -> None:
        if self._ecg is not None:
            samples, _ = self._ecg.pull_chunk(timeout=0.0, max_samples=512)
            if samples:
                self._page.waveform.append([row[0] for row in samples])
        if self._audio is not None:
            samples, _ = self._audio.pull_chunk(timeout=0.0, max_samples=4096)
            if samples:
                import numpy as np

                rms = float(np.sqrt(np.mean(np.square(np.asarray(samples, dtype=float)))))
                self._page.meter.set_level(min(1.0, rms * 4))
        self._page.preview.set_frame(synthetic_frame(time.monotonic() - self._t0))


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, session: SessionConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SensorChrono")
        self._base_session = session
        self.controller: SessionController | None = None
        self._monitor: LslMonitor | None = None
        self._live: LiveView | None = None
        self._record_t0 = 0.0

        # pages
        self.setup = SetupPage()
        self.preflight = PreflightPage()
        self.liveness = LivenessPage()
        self.calibrate = CalibratePage()
        self.record = RecordPage()
        self.postprocess = QtWidgets.QLabel("post-processing…", alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        self.done = DonePage()
        self.error = ErrorPage()
        self._pages = {
            SessionState.SETUP: self.setup, SessionState.PREFLIGHT: self.preflight,
            SessionState.LIVENESS: self.liveness, SessionState.CALIBRATE: self.calibrate,
            SessionState.RECORD: self.record, SessionState.POSTPROCESS: self.postprocess,
            SessionState.DONE: self.done, SessionState.ERROR: self.error,
        }
        self.stack = QtWidgets.QStackedWidget()
        for st in _PAGE_ORDER:
            self.stack.addWidget(self._pages[st])
        self.setCentralWidget(self.stack)
        self.statusBar().showMessage("ready")

        # page → controller wiring
        self.setup.started.connect(self._start_session)
        self.preflight.proceed.connect(self._go_staging)
        self.preflight.rescan.connect(self._rescan)
        self.liveness.go_record.connect(self._begin_calibration)
        self.calibrate.done_calibration.connect(self._to_recording)
        self.record.stop_record.connect(self._stop_recording)
        self.done.start_another.connect(self._restart)
        self.error.retry.connect(self._retry)
        self.error.abort.connect(self._abort)

        # timers
        self._liveness_timer = QtCore.QTimer(self)
        self._liveness_timer.setInterval(500)
        self._liveness_timer.timeout.connect(self._refresh)

        self.setup.load(self._base_session)
        self.stack.setCurrentWidget(self.setup)

    # -- controller lifecycle ----------------------------------------------
    def _build_controller(self, session: SessionConfig) -> None:
        if session.dry_run:
            from sensorchrono.devices.simulated import default_simulated_fleet

            fleet = default_simulated_fleet()
        else:
            from sensorchrono.devices.bridge_adapter import default_real_fleet

            fleet = default_real_fleet()
        expected = [s.name for a in fleet for s in a.streams()]
        self._monitor = LslMonitor(expected)
        self.controller = SessionController(
            session, adapters=fleet, monitor=self._monitor, recorder=self._make_recorder(session),
        )
        c = self.controller
        c.state_changed.connect(self._on_state)
        c.progress.connect(self.statusBar().showMessage)
        c.errored.connect(self.error.show_error)
        c.liveness_updated.connect(self.liveness.update_report)
        c.fiducial_counted.connect(self._on_fiducial)

    def _make_recorder(self, session: SessionConfig):
        if session.dry_run:
            return None
        from sensorchrono.orchestration.labrecorder import make_recorder

        def prompt(msg):
            QtWidgets.QMessageBox.information(self, "LabRecorder", msg)

        def confirm(msg):
            return QtWidgets.QMessageBox.question(self, "LabRecorder", msg) == QtWidgets.QMessageBox.StandardButton.Yes

        try:
            return make_recorder(manual_prompt=prompt, manual_confirm=confirm)
        except Exception:
            return None

    # -- transitions (page actions) ----------------------------------------
    def _start_session(self) -> None:
        self.setup.apply_to(self._base_session)
        self._build_controller(self._base_session)
        try:
            self.controller.run_preflight()
        except ConfigError as exc:
            self.setup.show_error(str(exc))

    def _go_staging(self) -> None:
        self.controller.start_staging()
        if self.controller.state == SessionState.LIVENESS:
            self._start_live()

    def _rescan(self) -> None:
        try:
            self.controller.run_preflight()
        except ConfigError as exc:
            self.setup.show_error(str(exc))

    def _begin_calibration(self) -> None:
        self.controller.start_calibration()

    def _to_recording(self, allow_uncalibrated: bool) -> None:
        self.controller.to_recording(allow_uncalibrated=allow_uncalibrated)

    def _stop_recording(self) -> None:
        mp4 = None  # real captures pass the camera adapter's mp4_path here (Phase 5)
        self.controller.stop_recording(xdf_path=None, mp4_path=mp4)

    def _restart(self) -> None:
        self._stop_live()
        self.setup.load(self._base_session)
        self.stack.setCurrentWidget(self.setup)

    def _retry(self) -> None:
        if self.controller is not None:
            try:
                self.controller.run_preflight()
            except ConfigError as exc:
                self.stack.setCurrentWidget(self.setup)
                self.setup.show_error(str(exc))

    def _abort(self) -> None:
        self._stop_live()
        self.stack.setCurrentWidget(self.setup)

    # -- controller signal handlers ----------------------------------------
    def _on_state(self, old: SessionState, new: SessionState) -> None:
        self.stack.setCurrentWidget(self._pages[new])
        if new == SessionState.PREFLIGHT and self.controller.preflight_report:
            self.preflight.update_report(self.controller.preflight_report)
        elif new == SessionState.LIVENESS:
            if self.controller.last_liveness:
                self.liveness.update_report(self.controller.last_liveness)
            self._liveness_timer.start()
        elif new == SessionState.CALIBRATE:
            self.calibrate.update_count(0, self.controller._fiducial.min_count, False)
            self.setFocus()
        elif new == SessionState.RECORD:
            self._record_t0 = time.monotonic()
        elif new in (SessionState.DONE, SessionState.ERROR):
            self._stop_live()
            if new == SessionState.DONE:
                self.done.show_summary(self.controller)

    def _on_fiducial(self, count: int) -> None:
        self.calibrate.update_count(count, self.controller._fiducial.min_count, self.controller._fiducial.calibrated)

    def _refresh(self) -> None:
        c = self.controller
        if c is None:
            return
        if c.state in (SessionState.LIVENESS, SessionState.CALIBRATE, SessionState.RECORD):
            c.refresh_liveness()
        if c.state == SessionState.RECORD:
            remaining = c.session.duration_s - (time.monotonic() - self._record_t0)
            self.record.set_remaining(max(0.0, remaining))
            if remaining <= 0:
                self._stop_recording()

    # -- live feed + key capture -------------------------------------------
    def _start_live(self) -> None:
        if self._live is None:
            self._live = LiveView(self.liveness, dry_run=self._base_session.dry_run)
        self._live.start()

    def _stop_live(self) -> None:
        self._liveness_timer.stop()
        if self._live is not None:
            self._live.stop()
        if self._monitor is not None:
            self._monitor.stop()

    def keyPressEvent(self, event) -> None:
        if (event.key() == QtCore.Qt.Key.Key_Space and self.controller is not None
                and self.controller.state == SessionState.CALIBRATE):
            self.controller.note_fiducial(time.monotonic())
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self._stop_live()
        super().closeEvent(event)


def run(argv: list[str] | None = None) -> int:
    import sys

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv if argv is None else argv)
    session = SessionConfig(
        participant="p01", session="s1", task="rest", duration_s=60,
        out_dir=Path.home() / "sensorchrono_out", dry_run=default_dry_run(),
    )
    win = MainWindow(session)
    win.resize(960, 640)
    win.show()
    return app.exec()
