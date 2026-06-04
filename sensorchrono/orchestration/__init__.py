"""Orchestration layer — drives the capture bridges + analysis pipeline.

Headless and framework-agnostic by design: the FSM (:mod:`session`) emits
plain :class:`~sensorchrono.orchestration.events.Signal` callbacks, not Qt
signals, so the whole layer imports and unit-tests on a box with no PySide6
(and no hardware). The Phase-3 GUI subscribes Qt slots to these signals.
"""
