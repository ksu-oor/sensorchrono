"""Load committed device profiles (``profiles/*.yaml``) and expose the two
things the orchestration + post-processing layers need from them:

1. **Fallback lag constants** keyed by *canonical* stream name — used when a
   session skips/under-runs the in-situ keyboard calibration block, so
   ``analysis.postprocess.run(..., profile_lag_ms=...)`` still has values.
2. **Bridge defaults** (sampling rate, mode, baud) the adapters seed their
   subprocess flags from.

The profile YAML stores cross-modality lags under descriptive keys like
``Audio_BRIO_via_USB`` and ``VideoFrames_BRIO_via_USB``; this module maps them
back to the canonical :class:`~sensorchrono.contract.StreamName` values so the
rest of the app only ever deals in canonical names.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from sensorchrono.contract import StreamName

# profiles/ lives at the repo root, one level up from this package.
PROFILES_DIR: Path = Path(__file__).resolve().parents[1] / "profiles"


class ProfileError(ValueError):
    """Raised when a profile is missing or cannot be parsed."""


@dataclass(frozen=True, slots=True)
class Profile:
    """Parsed view of one ``profiles/*.yaml``."""

    profile_id: str
    path: Path
    raw: dict[str, Any]  # full parsed YAML — escape hatch for rare fields
    fallback_lag_ms: dict[StreamName, float | None]
    drift_median_ppm: float | None
    bridge_defaults: dict[str, dict[str, Any]]
    streams_emitted: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def lag_ms(self, name: str | StreamName) -> float | None:
        """Fallback lag for a canonical stream (``None`` if unmeasured)."""
        return self.fallback_lag_ms.get(StreamName(name))


def _canonical_lag_key(raw_key: str) -> StreamName | None:
    """Map a profile lag key to a canonical stream name.

    Handles both exact canonical keys (``"ShimmerECG"``) and the descriptive
    cross-modality keys (``"Audio_BRIO_via_USB"`` -> ``Audio``,
    ``"VideoFrames_BRIO_via_USB"`` -> ``VideoFrames``). Returns ``None`` for
    keys that don't correspond to any known stream."""
    try:
        return StreamName(raw_key)
    except ValueError:
        pass
    # Longest canonical name that prefixes the key wins (so "VideoFrames" beats
    # a hypothetical "Video"); guards against partial collisions.
    for member in sorted(StreamName, key=lambda m: len(m.value), reverse=True):
        if raw_key == member.value or raw_key.startswith(member.value + "_"):
            return member
    return None


def _to_float(value: Any, where: str) -> float:
    """Coerce a hand-edited YAML scalar to float, or raise a *catchable*
    ProfileError (not a bare ValueError/TypeError) with the offending key."""
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ProfileError(f"{where} = {value!r} is not a number") from exc


def _extract_lags(calibration: dict[str, Any], path: Path) -> dict[StreamName, float | None]:
    lags: dict[StreamName, float | None] = {}
    # Sections are processed direct-first, so a direct measured value wins over
    # a descriptive one. The precedence rule below ("fill if empty, or upgrade a
    # None placeholder to a real value") means a direct ``null`` no longer
    # clobbers a real measurement that lives under lag_ms_other_modalities.
    for section in ("lag_ms", "lag_ms_other_modalities"):
        for raw_key, value in (calibration.get(section) or {}).items():
            canon = _canonical_lag_key(str(raw_key))
            if canon is None:
                continue
            parsed = None if value is None else _to_float(value, f"{path}: {section}.{raw_key}")
            if canon not in lags or (lags[canon] is None and parsed is not None):
                lags[canon] = parsed
    return lags


def _profile_path(profile_id_or_path: str | Path) -> Path:
    p = Path(profile_id_or_path)
    if p.suffix in {".yaml", ".yml"} and p.exists():
        return p
    candidate = PROFILES_DIR / f"{profile_id_or_path}.yaml"
    if candidate.exists():
        return candidate
    raise ProfileError(
        f"profile {profile_id_or_path!r} not found in {PROFILES_DIR} "
        f"(available: {', '.join(list_profiles()) or 'none'})"
    )


def load_profile(profile_id_or_path: str | Path) -> Profile:
    """Load and parse a device profile by id (``shimmer3_exg_sr47-5-1``) or
    explicit path. Tolerant of profiles that omit ``calibration`` /
    ``bridges`` (e.g. the keyboard/camera profiles)."""
    path = _profile_path(profile_id_or_path)
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - corrupt file
        raise ProfileError(f"could not parse {path}: {exc}") from exc

    calibration = raw.get("calibration") or {}
    drift = (calibration.get("drift_ppm_observed") or {}).get("median_ppm")
    bridges = raw.get("bridges") or {}

    return Profile(
        profile_id=str(raw.get("profile_id", path.stem)),
        path=path,
        raw=raw,
        fallback_lag_ms=_extract_lags(calibration, path),
        drift_median_ppm=None if drift is None else _to_float(drift, f"{path}: drift median_ppm"),
        # ``(v or {})`` tolerates a half-finished ``bridges:\n  exg:`` (null body)
        # which pyyaml parses as None — the loader promises this tolerance.
        bridge_defaults={k: ((v or {}).get("defaults") or {}) for k, v in bridges.items()},
        streams_emitted={k: ((v or {}).get("streams_emitted") or []) for k, v in bridges.items()},
    )


def list_profiles() -> list[str]:
    """Profile ids (YAML stems) available under ``profiles/``. Globs both
    ``*.yaml`` and ``*.yml`` so it agrees with what :func:`load_profile`
    accepts (otherwise a ``foo.yml`` profile loads but fails validation)."""
    if not PROFILES_DIR.is_dir():
        return []
    stems = {p.stem for p in PROFILES_DIR.glob("*.yaml")} | {
        p.stem for p in PROFILES_DIR.glob("*.yml")
    }
    return sorted(stems)
