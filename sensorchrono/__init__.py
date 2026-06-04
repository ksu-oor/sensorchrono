"""sensorchrono — guided multi-modal LSL recording app.

Wraps the proven capture bridges (repo root ``*_lsl_bridge.py``) and the
post-processing pipeline (``analysis/``) in an orchestration shell that walks
an operator through: select equipment → liveness check → calibrate → record →
auto post-process → aligned outputs. The hard sync math is unchanged; this
package is the shell that drives it.

Layout (built across phases — see the plan):
    contract.py        canonical LSL stream-name constants (single source of truth)
    config.py          SessionConfig + device bindings + config.yaml round-trip
    profiles.py        load profiles/*.yaml -> fallback lags + bridge defaults
    devices/           DeviceAdapter ABC + real bridge drivers + simulated (dry-run)
    orchestration/     supervisor, lsl_monitor, preflight, labrecorder, session FSM  (Phase 1)
    ui/                PySide6 wizard pages + live video/waveform widgets          (Phase 3)

Run ``python -m sensorchrono`` for an environment/profile summary, and
``pytest tests/`` for the current tested surface.
"""

__version__ = "0.1.0"
