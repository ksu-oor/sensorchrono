"""Adapter for ``audio_lsl_bridge.py`` (BRIO mic → Audio @ 48 kHz)."""
from __future__ import annotations

import re

from sensorchrono.contract import StreamName
from sensorchrono.devices.base import StreamDef
from sensorchrono.devices.bridge_adapter import BridgeAdapter, session_tag


class MicrophoneAdapter(BridgeAdapter):
    name = "mic"
    BRIDGE_SCRIPT = "audio_lsl_bridge.py"
    READY_PATTERN = re.compile(r"LSL outlet 'Audio' is live")

    def streams(self) -> list[StreamDef]:
        return [StreamDef.from_contract(StreamName.AUDIO)]

    def _bridge_args(self, session) -> list[str]:
        args = [
            "--duration", f"{self._duration(session):.0f}",
            "--out-dir", str(session.out_dir),
            "--tag", session_tag(session),
        ]
        if session.bindings.mic_device is not None:
            args += ["--device", str(session.bindings.mic_device)]
        return args
