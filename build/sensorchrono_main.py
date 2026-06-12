"""Frozen-app entry point (PyInstaller analyses THIS script).

Self-dispatching: a frozen ``sys.executable`` can't do ``python -m``, so the app
re-invokes its own exe with a leading flag to run a worker instead of the GUI:

* ``--run-postprocess`` runs the analysis pipeline subprocess;
* ``--run-bridge <module> [args...]`` imports a capture bridge by name and runs
  it (this is how real capture works when frozen — see ``bridge_adapter``).

With no recognised flag it launches the GUI.
"""
from __future__ import annotations

import sys


def _unbuffer_std_streams() -> None:
    """Make this worker's stdout/stderr flush on every write.

    A PyInstaller-frozen interpreter **ignores ``PYTHONUNBUFFERED``** and
    block-buffers a child's stdout when it's a pipe. A capture bridge runs for
    minutes without exiting, so its one-line readiness signal (``… is live``)
    sits unflushed in that buffer and never reaches the parent supervisor's pipe
    within the readiness window — staging then times out *even though the LSL
    stream is already live* (confirmed on-hardware: all streams up, 0 bytes of
    bridge stdout seen). ``write_through=True`` forces each write straight
    through. Guarded: a windowed build may expose ``None``/non-reconfigurable
    streams, in which case there's nothing to flush anyway."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True, write_through=True)
        except Exception:
            pass


def _main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "--run-postprocess":
        _unbuffer_std_streams()
        from sensorchrono.orchestration.postprocess_runner import _main as pp_main

        return pp_main(argv[1:])
    if argv and argv[0] == "--run-bridge":
        _unbuffer_std_streams()  # critical: supervisor reads readiness from this stdout
        import importlib

        # No setup_logging() here: bridge stdout is teed to a per-session file by
        # the parent supervisor, and the rotating GUI log file is not safe to
        # share across the GUI + several bridge processes.
        module = importlib.import_module(argv[1])
        return module.main(argv[2:]) or 0
    # GUI branch: the frozen exe has no console, so a log file is the only record.
    from sensorchrono.diagnostics_log import log_environment_snapshot, setup_logging

    setup_logging(debug="--debug" in argv)
    log_environment_snapshot()
    from sensorchrono.ui.main_window import run

    return run(argv)


if __name__ == "__main__":
    raise SystemExit(_main())
