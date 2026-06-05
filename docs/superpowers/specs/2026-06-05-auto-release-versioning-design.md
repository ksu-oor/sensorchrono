# Auto-release versioning — design

**Date:** 2026-06-05
**Status:** Approved (Windows-only, auto-patch-per-merge)

## Goal

Make the repo cut a downloadable Windows binary on GitHub **automatically on every
merge to `main`**, with the version number incremented per merge — no human pushing
tags by hand. Users download the installer directly from the GitHub Releases page.

## Scope decisions (settled)

- **Platforms:** Windows only. Live capture is Windows-only hardware; macOS/Linux
  builds would be analysis-only and were explicitly declined. No build matrix.
- **Cadence:** Every merge to `main` auto-bumps the **patch** and publishes a Release.
- **Version authority:** the latest `v*.*.*` **git tag**, incremented. The committed
  `__version__` in `sensorchrono/__init__.py` is a **floor** (manual minor/major
  override), not auto-rewritten — no bot commits to `main`, no CI loops.
- **Escape hatches preserved:** manual `workflow_dispatch` (test artifact, no publish)
  and a manually pushed `v*.*.*` tag (release at that exact version).

## Versioning rule

`next_version(tags, floor)` (pure function in `build/next_version.py`):

1. Keep only **stable** tags matching `^v?\d+\.\d+\.\d+$` (prerelease/garbage ignored).
2. `floor = parse(__version__)` from `sensorchrono/__init__.py` (regex, no import).
3. If no stable tags → return `floor` (first release at the committed version).
4. `latest = max(stable tags)`.
5. If `floor > latest` (tuple compare) → return `floor` (honor a manual minor/major jump).
6. Else → return `latest` with **patch + 1**.

Monotonic by construction: never emits a version `<=` an existing tag.

### Behavior timeline

| Event | Latest tag | Committed `__version__` | Released |
|---|---|---|---|
| Merge (normal) | _none_ | `1.0.0` | `v1.0.0` |
| Merge (normal) | `v1.0.0` | `1.0.0` | `v1.0.1` |
| Merge (normal) | `v1.0.1` | `1.0.0` | `v1.0.2` |
| Merge that sets `__version__="1.1.0"` | `v1.0.2` | `1.1.0` | `v1.1.0` |
| Merge (normal) | `v1.1.0` | `1.1.0` | `v1.1.1` |

The committed floor legitimately sits *below* the latest release between minor bumps;
that is expected. The frozen `.exe` is stamped with the resolved version at build time
(existing behavior), so installed apps always report the real release number.

## Workflow architecture (`.github/workflows/release.yml`)

One workflow, three triggers, one build path:

- `push` to `main` → **auto-compute** next patch → build → publish Release + create tag.
- `push` of a `v*.*.*` tag → release at that exact version (manual override).
- `workflow_dispatch` (version input) → build a downloadable artifact, **no publish**.

Changes vs. today:

1. **Trigger:** add `push: branches:[main]`, keep `tags:["v*.*.*"]` and `workflow_dispatch`.
2. **Checkout `fetch-depth: 0`** so `next_version.py` can read all tags.
3. **Resolve step** branches on `github.event_name`: tag → from ref; dispatch → input;
   push-to-main → `python build/next_version.py`. The strict semver validation regex is
   unchanged and still runs on every path.
4. **Concurrency** `group: release, cancel-in-progress: false` so concurrent merges
   serialize instead of racing for the same number.
5. **`[skip release]`** in the head commit message skips the build (job-level `if`),
   for trivial/docs-only merges. Default is still: every merge releases.
6. **Publish step** now runs on `github.event_name != 'workflow_dispatch'` (both push-to-
   main and tag push), passes `tag_name: v<version>` (creates the tag on main-push),
   `generate_release_notes: true`, and `name: SensorChrono v<version>`.

### Why no double-fire / loop

The Release step creates the `v<version>` tag via the default `GITHUB_TOKEN`. GitHub's
loop-prevention means events raised by `GITHUB_TOKEN` do **not** trigger new workflow
runs, so the created tag never re-fires the workflow. A *human*-pushed tag still fires
it (manual override path). Verified intent, documented here so it isn't "fixed" later.

### Known, accepted tradeoff

With `cancel-in-progress: false`, GitHub keeps one running + one pending run per group;
a burst of rapid merges can coalesce intermediate pending runs. Each published release
still contains **all** merged code up to its commit — only some intermediate version
numbers may be skipped under simultaneous merges. Acceptable for a low-traffic repo.

## New testable piece

- `build/next_version.py` — `next_version(tags, floor)` pure function + `main()` that
  reads `git tag` (subprocess) and the floor (regex on `__init__.py`), prints the result.
  **Stdlib only** (runs before deps are installed in the workflow; must not import the
  `sensorchrono` package, which pulls heavy deps).
- `tests/test_next_version.py` — first release, normal patch bump, manual minor & major
  jumps, prerelease/garbage tags ignored, never-goes-backward, `v`-prefix tolerance.

## Out of scope

macOS/Linux builds, build matrix, `ci.yml` changes, code signing, PyPI publishing,
committing the version back to `main`, `pyproject.toml` version (none exists).

## Verification (local)

- `pytest -q` passes incl. the new `test_next_version.py`.
- `python build/next_version.py` against the real repo (no tags) prints `1.0.0`.
- YAML parses; trigger/permission/concurrency blocks reviewed.
- End-to-end release can only be confirmed after the workflow runs on `main` (GitHub).
