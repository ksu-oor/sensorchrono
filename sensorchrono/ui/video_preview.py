"""Live camera preview widget + a synthetic frame source for dry-run.

The ``VideoFrames`` LSL stream carries only frame *timestamps*, not pixels, so
a live preview can't come from LSL. In real captures the preview would open its
own read-only ``cv2`` capture (Phase 5); in dry-run we show a moving synthetic
pattern so the staging page has something to look at.
"""
from __future__ import annotations

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets


class VideoPreview(QtWidgets.QLabel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setText("no video")
        self.setStyleSheet("background:#111; color:#777; border:1px solid #333;")

    def show_status(self, text: str) -> None:
        """Show a text status instead of a frame. Used during real capture, where
        the camera is held exclusively by the recording bridge so no live preview
        is possible — an honest message beats a fake synthetic image."""
        self.setPixmap(QtGui.QPixmap())  # clear any prior frame
        self.setText(text)

    def set_frame(self, frame_bgr: np.ndarray) -> None:
        """Display an ``HxWx3`` uint8 BGR frame (as cv2 delivers)."""
        if frame_bgr is None or getattr(frame_bgr, "ndim", 0) != 3:
            return
        h, w, _ = frame_bgr.shape
        rgb = np.ascontiguousarray(frame_bgr[:, :, ::-1])
        # .copy() so the QImage owns its bytes (rgb may be freed before paint)
        img = QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888).copy()
        pix = QtGui.QPixmap.fromImage(img).scaled(
            self.width(), self.height(),
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(pix)


def synthetic_frame(t: float, w: int = 320, h: int = 180) -> np.ndarray:
    """A scrolling colour gradient — gives the dry-run preview visible motion."""
    x = (np.arange(w) + int(t * 60)) % 256
    row = x.astype(np.uint8)
    base = np.tile(row, (h, 1))
    return np.stack([base, np.roll(base, 40, axis=1), 255 - base], axis=2).astype(np.uint8)
