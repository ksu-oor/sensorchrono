"""Frozen-app entry point (PyInstaller analyses THIS script).

Self-dispatching: when re-invoked as a post-processing subprocess (the
``--run-postprocess`` flag, used because a frozen ``sys.executable`` can't do
``python -m``), it runs the pipeline; otherwise it launches the GUI.
"""
from __future__ import annotations

import sys


def _main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "--run-postprocess":
        from sensorchrono.orchestration.postprocess_runner import _main as pp_main

        return pp_main(argv[1:])
    from sensorchrono.ui.main_window import run

    return run(argv)


if __name__ == "__main__":
    raise SystemExit(_main())
