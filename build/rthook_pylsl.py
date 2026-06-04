"""PyInstaller runtime hook: point pylsl at the bundled liblsl before import.

pylsl's PyInstaller hook does NOT auto-bundle the native liblsl, and at runtime
pylsl looks for it via the ``PYLSL_LIB`` env var. The .spec bundles the library
next to the app; here we set ``PYLSL_LIB`` to it (only when frozen) so the very
first ``import pylsl`` finds it. Runs before the main script.
"""
import os
import sys

if getattr(sys, "frozen", False):
    base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    for name in ("liblsl.dll", "liblsl64.dll", "liblsl.dylib", "liblsl.so", "liblsl.1.dylib"):
        candidate = os.path.join(base, name)
        if os.path.exists(candidate):
            os.environ.setdefault("PYLSL_LIB", candidate)
            break
