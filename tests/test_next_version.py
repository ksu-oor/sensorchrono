"""Unit tests for the release version computation (build/next_version.py).

The pure ``next_version(tags, floor)`` is the version authority used by the
release workflow on every merge to ``main``. These tests pin the rule:
auto-patch off the highest stable tag, with the committed ``__version__`` acting
as a manual minor/major floor — and never regress below an existing tag.
"""
import importlib.util
from pathlib import Path

import pytest

# Load build/next_version.py by path — it lives under build/, not an importable
# package, and (by design) must stay stdlib-only / not import sensorchrono.
_MOD_PATH = Path(__file__).resolve().parent.parent / "build" / "next_version.py"
_spec = importlib.util.spec_from_file_location("next_version", _MOD_PATH)
next_version_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(next_version_mod)
next_version = next_version_mod.next_version
floor_from_source = next_version_mod.floor_from_source


def test_first_release_uses_floor_when_no_tags():
    assert next_version([], "1.0.0") == "1.0.0"


def test_normal_patch_bump():
    assert next_version(["v1.0.0"], "1.0.0") == "1.0.1"


def test_picks_highest_then_bumps_patch():
    assert next_version(["v1.0.0", "v1.0.1", "v1.0.2"], "1.0.0") == "1.0.3"


def test_highest_is_numeric_not_lexical():
    # v1.0.10 > v1.0.9 numerically (lexical sort would wrongly pick v1.0.9).
    assert next_version(["v1.0.9", "v1.0.10"], "1.0.0") == "1.0.11"


def test_picks_max_across_minor_lines():
    assert next_version(["v1.0.5", "v1.1.2", "v1.0.9"], "1.0.0") == "1.1.3"


def test_manual_minor_jump_via_floor():
    assert next_version(["v1.0.2"], "1.1.0") == "1.1.0"


def test_manual_major_jump_via_floor():
    assert next_version(["v1.2.5"], "2.0.0") == "2.0.0"


def test_resumes_patch_after_minor_jump_is_tagged():
    # Once v1.1.0 exists, floor 1.1.0 is no longer *above* it -> patch bump.
    assert next_version(["v1.1.0"], "1.1.0") == "1.1.1"


def test_never_regresses_below_latest_tag():
    # Floor lags the real release line -> still bump off the tag, not the floor.
    assert next_version(["v1.2.3"], "1.0.0") == "1.2.4"


def test_prerelease_and_garbage_tags_are_ignored():
    tags = ["v1.0.0", "v1.0.1-rc1", "v2.0.0-beta", "nightly", "latest", ""]
    assert next_version(tags, "1.0.0") == "1.0.1"


def test_tolerates_tags_without_v_prefix():
    assert next_version(["1.0.0", "1.0.1"], "1.0.0") == "1.0.2"


def test_floor_may_carry_a_semver_prerelease_suffix():
    assert next_version(["v1.0.0"], "1.1.0-dev") == "1.1.0"


def test_bad_floor_raises():
    with pytest.raises(ValueError):
        next_version([], "not-a-version")


def test_floor_with_malformed_suffix_raises():
    # A typo'd __version__ must fail loudly, not silently release off "1.0.0".
    with pytest.raises(ValueError):
        next_version([], "1.0.0garbage")


def test_floor_from_source_parses_init_assignment():
    text = '"""docstring"""\n\n__version__ = "3.4.5"\n'
    assert floor_from_source(text) == "3.4.5"


def test_floor_from_source_raises_without_assignment():
    with pytest.raises(ValueError):
        floor_from_source("# no version here\n")


def test_floor_matches_the_real_package_version():
    # The committed floor must be parseable by the same regex the workflow uses,
    # so a release can always be computed from sensorchrono/__init__.py.
    init = Path(__file__).resolve().parent.parent / "sensorchrono" / "__init__.py"
    floor = floor_from_source(init.read_text(encoding="utf-8"))
    # round-trips through the version rule (no tags -> the floor itself)
    assert next_version([], floor) == floor
