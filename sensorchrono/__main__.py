"""``python -m sensorchrono`` entry point (and the PyInstaller target later).

Phase 0: there is no GUI yet, so this prints an environment + profile summary
so the package is runnable end-to-end before the wizard lands (Phase 3). Once
``ui/main_window.py`` exists this will launch the Qt app instead.
"""
from __future__ import annotations

import sys

from sensorchrono import __version__
from sensorchrono.config import default_dry_run
from sensorchrono.profiles import list_profiles


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    print(f"sensorchrono {__version__}")
    print(f"platform={sys.platform}  dry_run_default={default_dry_run()}")
    try:
        profiles = list_profiles()
        print(f"profiles ({len(profiles)}): {', '.join(profiles) or '(none)'}")
    except Exception as exc:  # surface, don't swallow
        print(f"profiles: <error: {exc}>")
        return 1
    try:
        import pylsl
    except ImportError:
        lsl = "NOT installed — dry-run runs without real LSL outlets"
    except Exception as exc:  # installed but ABI/arch-broken — operator must fix
        lsl = f"installed but BROKEN: {exc}"
    else:
        try:
            lsl = f"available (liblsl {pylsl.library_version()})"
        except Exception as exc:
            lsl = f"installed but BROKEN: {exc}"
    print(f"pylsl: {lsl}")
    print("GUI arrives in Phase 3; run `pytest tests/` for the current surface.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
