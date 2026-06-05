"""Compute the next release version from existing git tags + the committed floor.

Used by ``.github/workflows/release.yml`` on every merge to ``main`` to pick the
next version with no human in the loop. The pure rule lives in
``next_version(tags, floor)`` (unit-tested in ``tests/test_next_version.py``);
``main()`` does the I/O — reads ``git tag`` and the ``__version__`` floor from
``sensorchrono/__init__.py`` — and prints the next version with **no** leading ``v``.

The rule (see docs/superpowers/specs/2026-06-05-auto-release-versioning-design.md):
  * no stable tags        -> the floor              (first release)
  * floor above newest tag-> the floor              (manual minor/major jump)
  * otherwise             -> newest stable tag, patch + 1
It never returns a version <= an existing stable tag.

STDLIB ONLY. This runs in the workflow *before* dependencies are installed, so it
must not import the ``sensorchrono`` package (which pulls PySide6/pylsl/etc.).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

# A *stable* tag: exactly vMAJOR.MINOR.PATCH (optional leading v). Anchored at the
# end so prerelease tags (v1.0.0-rc1) and junk (nightly, latest) are excluded.
_STABLE_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
# The floor: vMAJOR.MINOR.PATCH with an optional semver prerelease suffix (-dev,
# -rc1) that is tolerated and dropped — the floor expresses the release line, not a
# prerelease. Anchored at the end so a malformed __version__ (e.g. "1.0.0garbage")
# fails loudly here rather than silently releasing off a mangled number.
_FLOOR = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.]+)?$")
# The committed version assignment in sensorchrono/__init__.py.
_VERSION_LINE = re.compile(r'^__version__ = "([^"]+)"', re.MULTILINE)


def _stable_tuples(tags):
    """(major, minor, patch) tuples for the stable release tags, junk dropped."""
    out = []
    for tag in tags:
        m = _STABLE_TAG.match(tag.strip())
        if m:
            out.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    return out


def _floor_tuple(floor):
    m = _FLOOR.match(floor.strip())
    if not m:
        raise ValueError(f"unparseable floor version: {floor!r}")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def next_version(tags, floor):
    """Return the next release version as ``"X.Y.Z"`` (no leading ``v``).

    ``tags`` is any iterable of tag names (with or without a ``v`` prefix);
    non-stable tags are ignored. ``floor`` is the committed ``__version__``.
    """
    f = _floor_tuple(floor)
    stable = _stable_tuples(tags)
    if not stable:
        return "%d.%d.%d" % f
    latest = max(stable)
    if f > latest:
        return "%d.%d.%d" % f
    return "%d.%d.%d" % (latest[0], latest[1], latest[2] + 1)


def floor_from_source(text):
    """Parse ``__version__ = "X.Y.Z"`` out of an ``__init__.py``'s text."""
    m = _VERSION_LINE.search(text)
    if not m:
        raise ValueError("no __version__ assignment found in source")
    return m.group(1)


def _git_tags():
    out = subprocess.run(
        ["git", "tag", "--list"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def main(argv=None):
    root = Path(__file__).resolve().parent.parent
    init = root / "sensorchrono" / "__init__.py"
    floor = floor_from_source(init.read_text(encoding="utf-8"))
    print(next_version(_git_tags(), floor))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
