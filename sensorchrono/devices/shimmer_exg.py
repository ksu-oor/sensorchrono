"""Adapter for ``sensorchrono/bridges/shimmer_lsl_bridge.py`` (Shimmer3 EXG: ECG or EMG).

Two deadlock traps the adapter MUST avoid for a headless run:
  1. the bridge blocks on ``input()`` unless ``--no-prompt`` is passed, and
  2. the positional ``mode`` argument prompts interactively if omitted.
Both are enforced here and covered by a test.
"""
from __future__ import annotations

import re

from sensorchrono.contract import StreamName
from sensorchrono.devices.base import StreamDef
from sensorchrono.devices.bridge_adapter import BridgeAdapter


class ShimmerExgAdapter(BridgeAdapter):
    name = "shimmer_exg"
    BRIDGE_MODULE = "sensorchrono.bridges.shimmer_lsl_bridge"
    # readiness line: "[COM3] LSL outlet: ShimmerECG @ 256 Hz" (or ShimmerEMG)
    READY_PATTERN = re.compile(r"LSL outlet: ShimmerECG")

    def __init__(self, *, mode: str = "ecg", start_delay_s: float = 3.0, **kw) -> None:
        super().__init__(**kw)
        if mode not in ("ecg", "emg"):
            raise ValueError(f"unsupported shimmer mode {mode!r} (v1 supports ecg|emg)")
        self.mode = mode
        self.start_delay_s = start_delay_s

    def _ready_pattern(self) -> re.Pattern[str]:
        return re.compile(r"LSL outlet: ShimmerEMG") if self.mode == "emg" else self.READY_PATTERN

    def streams(self) -> list[StreamDef]:
        if self.mode == "emg":
            return [StreamDef.from_contract(StreamName.SHIMMER_EMG)]
        return [
            StreamDef.from_contract(StreamName.SHIMMER_ECG),
            StreamDef.from_contract(StreamName.SHIMMER_DIAGNOSTICS_ECG),
        ]

    def _bridge_args(self, session) -> list[str]:
        port = session.bindings.shimmer_ecg_port or session.bindings.shimmer_com_port
        args = [
            self.mode,  # positional: prevents the interactive mode prompt
            "--no-prompt",  # MANDATORY: never block on input()
            "--record-seconds", f"{self._duration(session):.0f}",
            "--start-delay", f"{self.start_delay_s:g}",
        ]
        if port:
            flag = "--emg-port" if self.mode == "emg" else "--ecg-port"
            args += [flag, str(port)]
        return args
