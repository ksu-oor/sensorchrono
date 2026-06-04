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


def _main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "--run-postprocess":
        from sensorchrono.orchestration.postprocess_runner import _main as pp_main

        return pp_main(argv[1:])
    if argv and argv[0] == "--run-bridge":
        import importlib

        module = importlib.import_module(argv[1])
        return module.main(argv[2:]) or 0
    from sensorchrono.ui.main_window import run

    return run(argv)


if __name__ == "__main__":
    raise SystemExit(_main())
