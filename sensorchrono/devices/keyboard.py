"""Adapter for ``keyboard_fiducial_bridge.py`` (USB HID keystroke → marker).

On Windows ``pynput``'s listener is a global OS hook, so it captures the
calibration spacebar taps without needing window focus.
"""
from __future__ import annotations

import re

from sensorchrono.contract import StreamName
from sensorchrono.devices.base import StreamDef
from sensorchrono.devices.bridge_adapter import BridgeAdapter


class KeyboardAdapter(BridgeAdapter):
    name = "keyboard"
    BRIDGE_SCRIPT = "keyboard_fiducial_bridge.py"
    READY_PATTERN = re.compile(r"LSL outlet 'KeyboardFiducial' is live")

    def streams(self) -> list[StreamDef]:
        return [StreamDef.from_contract(StreamName.KEYBOARD_FIDUCIAL)]

    def _bridge_args(self, session) -> list[str]:
        return ["--duration", f"{self._duration(session):.0f}"]
