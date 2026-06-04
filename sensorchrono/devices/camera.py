"""Adapter for ``video_lsl_bridge.py`` (Logitech BRIO → VideoFrames + .mp4)."""
from __future__ import annotations

import re
from pathlib import Path

from sensorchrono.contract import StreamName
from sensorchrono.devices.base import StreamDef
from sensorchrono.devices.bridge_adapter import BridgeAdapter, session_tag


class CameraAdapter(BridgeAdapter):
    name = "camera"
    BRIDGE_SCRIPT = "video_lsl_bridge.py"
    READY_PATTERN = re.compile(r"LSL outlet 'VideoFrames' is live")

    def streams(self) -> list[StreamDef]:
        return [StreamDef.from_contract(StreamName.VIDEO_FRAMES)]

    def _bridge_args(self, session) -> list[str]:
        args = [
            "--duration", f"{self._duration(session):.0f}",
            "--out-dir", str(session.out_dir),
            "--tag", session_tag(session),
        ]
        if session.bindings.camera_index is not None:
            args += ["--device", str(session.bindings.camera_index)]
        return args

    def mp4_path(self, session) -> Path:
        """Where the bridge writes the .mp4 (post-processing needs this).
        The bridge derives it as ``{out_dir}/{tag}_video.mp4``."""
        return Path(session.out_dir) / f"{session_tag(session)}_video.mp4"
