"""``python -m sensorchrono`` entry point (and the PyInstaller target).

Launches the PySide6 wizard. With ``--info`` (or when PySide6 isn't installed)
it prints an environment/profile summary instead — handy on a bare box.
``--debug`` raises the file log to DEBUG (same as ``SENSORCHRONO_DEBUG=1``).
"""
from __future__ import annotations

import sys

from sensorchrono import __version__
from sensorchrono.config import default_dry_run
from sensorchrono.diagnostics_log import log_environment_snapshot, setup_logging
from sensorchrono.profiles import list_profiles


def _print_info() -> int:
    print(f"sensorchrono {__version__}")
    print(f"platform={sys.platform}  dry_run_default={default_dry_run()}")
    try:
        profiles = list_profiles()
        print(f"profiles ({len(profiles)}): {', '.join(profiles) or '(none)'}")
    except Exception as exc:
        print(f"profiles: <error: {exc}>")
        return 1
    try:
        import pylsl
    except ImportError:
        lsl = "NOT installed — dry-run runs without real LSL outlets"
    except Exception as exc:
        lsl = f"installed but BROKEN: {exc}"
    else:
        try:
            lsl = f"available (liblsl {pylsl.library_version()})"
        except Exception as exc:
            lsl = f"installed but BROKEN: {exc}"
    print(f"pylsl: {lsl}")
    try:
        import PySide6  # noqa: F401

        print("PySide6: available — `python -m sensorchrono` launches the GUI")
    except Exception:
        print("PySide6: NOT installed — `pip install PySide6 pyqtgraph` to run the GUI")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    debug = "--debug" in argv
    log_path = setup_logging(debug=debug)
    log_environment_snapshot()
    if "--info" in argv:
        print(f"logs: {log_path}")
        return _print_info()
    argv = [a for a in argv if a != "--debug"]  # GUI run() doesn't parse it
    try:
        from sensorchrono.ui.main_window import run
    except Exception as exc:  # PySide6 missing → fall back to the text summary
        print(f"GUI unavailable ({exc}); showing info instead.\n")
        return _print_info()
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
