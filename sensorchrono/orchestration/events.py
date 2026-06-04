"""A tiny framework-agnostic signal/slot primitive.

The FSM and monitors emit through these instead of Qt signals so the
orchestration layer stays importable and testable without PySide6. The
Phase-3 GUI connects a Qt slot by passing ``some_qt_signal.emit`` (or any
callable) to :meth:`Signal.connect`.

Deliberately minimal: synchronous, in-order delivery; a raising subscriber is
isolated (its exception is routed to ``on_listener_error`` if set, else
re-raised) so one bad slot can't silently swallow an event.
"""
from __future__ import annotations

from typing import Callable

#: optional global hook for surfacing subscriber exceptions (tests/logging)
on_listener_error: Callable[[BaseException], None] | None = None


class Signal:
    """A list of callbacks invoked in subscription order on :meth:`emit`."""

    __slots__ = ("_slots", "name")

    def __init__(self, name: str = "") -> None:
        self._slots: list[Callable[..., None]] = []
        self.name = name

    def connect(self, slot: Callable[..., None]) -> Callable[..., None]:
        """Subscribe ``slot``. Returns it so it can be used as a decorator."""
        if slot not in self._slots:
            self._slots.append(slot)
        return slot

    def disconnect(self, slot: Callable[..., None]) -> None:
        if slot in self._slots:
            self._slots.remove(slot)

    def emit(self, *args, **kwargs) -> None:
        # iterate a copy so a slot may disconnect itself mid-dispatch
        for slot in list(self._slots):
            try:
                slot(*args, **kwargs)
            except BaseException as exc:  # one bad slot must not break the rest
                if on_listener_error is not None:
                    on_listener_error(exc)
                else:
                    raise

    def __len__(self) -> int:
        return len(self._slots)
