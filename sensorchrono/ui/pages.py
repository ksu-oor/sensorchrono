"""One widget per wizard state. Pages are dumb: they render what they're told
and emit a Qt signal when the operator acts; :class:`MainWindow` wires those
signals to the :class:`SessionController` and pushes state back to the pages.
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from sensorchrono.ui.video_preview import VideoPreview
from sensorchrono.ui.waveform import AudioLevelMeter, WaveformWidget

_OK = "✓"
_WARN = "!"
_FAIL = "✗"


class SetupPage(QtWidgets.QWidget):
    started = QtCore.Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        form = QtWidgets.QFormLayout()
        self.participant = QtWidgets.QLineEdit()
        self.session = QtWidgets.QLineEdit()
        self.task = QtWidgets.QLineEdit()
        self.duration = QtWidgets.QSpinBox()
        self.duration.setRange(5, 14400)
        self.duration.setSuffix(" s")
        self.dry_run = QtWidgets.QCheckBox("dry run (synthetic streams, no hardware)")
        self.out_dir = QtWidgets.QLabel()
        self.out_dir.setStyleSheet("color:#888;")
        form.addRow("Participant", self.participant)
        form.addRow("Session", self.session)
        form.addRow("Task", self.task)
        form.addRow("Duration", self.duration)
        form.addRow("", self.dry_run)
        form.addRow("Output dir", self.out_dir)

        self.error = QtWidgets.QLabel()
        self.error.setStyleSheet("color:#d44;")
        self.error.setWordWrap(True)
        start = QtWidgets.QPushButton("Start session →")
        start.clicked.connect(self.started.emit)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("<h2>Set up recording</h2>"))
        lay.addLayout(form)
        lay.addWidget(self.error)
        lay.addStretch(1)
        lay.addWidget(start, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

    def load(self, session) -> None:
        self.participant.setText(session.participant)
        self.session.setText(session.session)
        self.task.setText(session.task)
        self.duration.setValue(int(session.duration_s))
        self.dry_run.setChecked(bool(session.dry_run))
        self.out_dir.setText(str(session.out_dir))
        self.error.clear()

    def apply_to(self, session) -> None:
        session.participant = self.participant.text().strip()
        session.session = self.session.text().strip()
        session.task = self.task.text().strip()
        session.duration_s = int(self.duration.value())
        session.dry_run = self.dry_run.isChecked()

    def show_error(self, message: str) -> None:
        self.error.setText(message)


class PreflightPage(QtWidgets.QWidget):
    proceed = QtCore.Signal()
    rescan = QtCore.Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.list = QtWidgets.QListWidget()
        self._proceed = QtWidgets.QPushButton("Proceed to staging →")
        self._proceed.setEnabled(False)
        self._proceed.clicked.connect(self.proceed.emit)
        rescan = QtWidgets.QPushButton("Rescan")
        rescan.clicked.connect(self.rescan.emit)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(rescan)
        buttons.addStretch(1)
        buttons.addWidget(self._proceed)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("<h2>Preflight — are the devices responding?</h2>"))
        lay.addWidget(self.list)
        lay.addLayout(buttons)

    def update_report(self, report) -> None:
        self.list.clear()
        for c in report.checks:
            icon = {"pass": _OK, "warn": _WARN, "fail": _FAIL}.get(c.status, "?")
            req = "" if c.required else "  (optional)"
            self.list.addItem(f"{icon}  {c.name}: {c.detail}{req}")
        self._proceed.setEnabled(report.ok)


class LivenessPage(QtWidgets.QWidget):
    go_record = QtCore.Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["stream", "rate (Hz)", "ch", "ok"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        self.preview = VideoPreview()
        self.waveform = WaveformWidget()
        self.meter = AudioLevelMeter()

        right = QtWidgets.QVBoxLayout()
        right.addWidget(self.preview)
        right.addWidget(self.waveform)
        right.addWidget(self.meter)

        split = QtWidgets.QHBoxLayout()
        split.addWidget(self.table, 1)
        split.addLayout(right, 1)

        self._go = QtWidgets.QPushButton("Go to Recording →")
        self._go.setEnabled(False)
        self._go.clicked.connect(self.go_record.emit)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("<h2>Staging — every stream live and healthy?</h2>"))
        lay.addLayout(split)
        lay.addWidget(self._go, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

    def update_report(self, report) -> None:
        self.table.setRowCount(len(report.streams))
        for i, s in enumerate(report.streams):
            cells = [str(s.name), f"{s.measured_rate_hz:.0f}/{s.expected_rate_hz:.0f}",
                     f"{s.measured_channels}/{s.expected_channels}", _OK if s.ok else _FAIL]
            for j, text in enumerate(cells):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(text))
        self._go.setEnabled(report.ok)


class CalibratePage(QtWidgets.QWidget):
    done_calibration = QtCore.Signal(bool)  # allow_uncalibrated

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.count_label = QtWidgets.QLabel("0 / 0 clean taps")
        self.count_label.setStyleSheet("font-size:28px;")
        self.count_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.bar = QtWidgets.QProgressBar()
        hint = QtWidgets.QLabel("Tap the spacebar firmly about every 2 seconds (~15 times).")
        hint.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        self._done = QtWidgets.QPushButton("Calibrated — start recording →")
        self._done.setEnabled(False)
        self._done.clicked.connect(lambda: self.done_calibration.emit(False))
        fallback = QtWidgets.QPushButton("Skip / accept fallback (uncalibrated) →")
        fallback.clicked.connect(lambda: self.done_calibration.emit(True))

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(fallback)
        buttons.addStretch(1)
        buttons.addWidget(self._done)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("<h2>Calibration block</h2>"))
        lay.addWidget(hint)
        lay.addStretch(1)
        lay.addWidget(self.count_label)
        lay.addWidget(self.bar)
        lay.addStretch(1)
        lay.addLayout(buttons)

    def update_count(self, count: int, min_count: int, calibrated: bool) -> None:
        self.count_label.setText(f"{count} / {min_count} clean taps")
        self.bar.setRange(0, max(1, min_count))
        self.bar.setValue(min(count, min_count))
        self._done.setEnabled(calibrated)


class RecordPage(QtWidgets.QWidget):
    stop_record = QtCore.Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.countdown = QtWidgets.QLabel("recording…")
        self.countdown.setStyleSheet("font-size:32px;")
        self.countdown.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.status = QtWidgets.QLabel("")
        self.status.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        stop = QtWidgets.QPushButton("Stop recording")
        stop.clicked.connect(self.stop_record.emit)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("<h2>Recording</h2>"))
        lay.addStretch(1)
        lay.addWidget(self.countdown)
        lay.addWidget(self.status)
        lay.addStretch(1)
        lay.addWidget(stop, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

    def set_remaining(self, seconds: float) -> None:
        self.countdown.setText(f"{int(seconds)} s remaining")


class DonePage(QtWidgets.QWidget):
    start_another = QtCore.Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.summary = QtWidgets.QLabel("")
        self.summary.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.summary.setWordWrap(True)
        another = QtWidgets.QPushButton("Start another →")
        another.clicked.connect(self.start_another.emit)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("<h2>Done</h2>"))
        lay.addWidget(self.summary)
        lay.addStretch(1)
        lay.addWidget(another, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

    def show_summary(self, controller) -> None:
        s = controller.session
        cal = "calibrated" if controller.calibrated else "uncalibrated (profile-default lags)"
        pp = controller.postprocess_result
        verdict = pp.summary() if pp is not None else "post-processing skipped (dry-run / no XDF)"
        self.summary.setText(
            f"<b>{s.participant} / {s.session} / {s.task}</b><br>"
            f"duration {s.duration_s}s · fiducials {controller.fiducial_count} · {cal}<br>"
            f"<br>post-processing: {verdict}"
        )


class ErrorPage(QtWidgets.QWidget):
    retry = QtCore.Signal()
    abort = QtCore.Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.message = QtWidgets.QLabel("")
        self.message.setStyleSheet("color:#d44;")
        self.message.setWordWrap(True)
        retry = QtWidgets.QPushButton("Retry")
        retry.clicked.connect(self.retry.emit)
        abort = QtWidgets.QPushButton("Abort")
        abort.clicked.connect(self.abort.emit)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(abort)
        buttons.addStretch(1)
        buttons.addWidget(retry)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("<h2>Something went wrong</h2>"))
        lay.addWidget(self.message)
        lay.addStretch(1)
        lay.addLayout(buttons)

    def show_error(self, message: str) -> None:
        self.message.setText(message)
