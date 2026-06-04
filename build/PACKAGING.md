# Packaging SensorChrono

Goal: a one-click Windows installer that bundles the app, the Qt runtime, the
native `liblsl`, the capture bridges, the `analysis/` pipeline, and (optionally)
a LabRecorder build — so a non-technical operator just double-clicks.

## Why one-folder + an installer (not one-file)

PyInstaller **one-file** mode unpacks to a temp dir at launch and **breaks
PySide6's Qt plugins** (`platforms/qwindows.dll` etc. aren't found reliably).
So we build **one-folder** (`dist\SensorChrono\`) and wrap it in an **Inno
Setup** installer. The user still gets a single `SensorChrono-x.y.z-setup.exe`.

## The two non-obvious bundling facts

1. **`liblsl` is NOT auto-bundled by pylsl's PyInstaller hook.** pylsl finds the
   native library at runtime via the `PYLSL_LIB` env var. The spec bundles the
   DLL next to the app and `build/rthook_pylsl.py` (a runtime hook) sets
   `PYLSL_LIB` to it *before the first `import pylsl`*. Point `LIBLSL_PATH` at
   the DLL when building (the build script falls back to the one inside the
   pylsl wheel).

2. **A frozen `sys.executable` is the app exe, not Python.** The post-process
   step runs as a subprocess; in dev that's `python -m
   sensorchrono.orchestration.postprocess_runner`, but a frozen exe can't do
   `-m`. So `build/sensorchrono_main.py` self-dispatches: if the first arg is
   `--run-postprocess` it runs the pipeline, else it launches the GUI — and
   `postprocess_runner.build_command()` emits `--run-postprocess` when frozen.

## Build (Windows, in the project venv)

```powershell
# optional: point at a real liblsl and a LabRecorder folder
$env:LIBLSL_PATH    = "C:\path\to\liblsl.dll"
$env:LABRECORDER_DIR = "C:\path\to\LabRecorder"   # folder with LabRecorder.exe

powershell -ExecutionPolicy Bypass -File build\build_windows.ps1
# -> dist\SensorChrono\SensorChrono.exe
```

Then compile `build\installer.iss` with **Inno Setup** →
`SensorChrono-1.0.0-setup.exe`.

## What gets bundled (see `build/sensorchrono.spec`)

| Item | How | Located at runtime |
|---|---|---|
| App + sensorchrono package | `collect_submodules("sensorchrono")` | frozen import |
| Qt runtime + plugins | PySide6's PyInstaller hooks | one-folder |
| `liblsl` native lib | `LIBLSL_PATH` → `binaries` | `PYLSL_LIB` via rthook |
| Device profiles | `profiles/*.yaml` → `datas` | `profiles/` next to exe |
| Capture bridges | `*_lsl_bridge.py` → `datas` (repo root) | spawned as subprocess |
| `analysis/` pipeline | `*.py` → `datas` + hidden imports | postprocess subprocess |
| LabRecorder (optional) | `LABRECORDER_DIR` → `datas` under `LabRecorder/` | `sys._MEIPASS/LabRecorder` |

## Windows Defender note

A freshly-built, unsigned PyInstaller exe is frequently flagged by SmartScreen /
Defender on first run ("Windows protected your PC"). For an internal lab tool,
click *More info → Run anyway*, or add a Defender exclusion for the install dir.
Code-signing the installer removes this but is out of scope for v1.

## Validation

- **Dev (any OS):** `pyinstaller --noconfirm build/sensorchrono.spec` should
  analyse and COLLECT without error; the frozen `SensorChrono` launches the GUI.
  (Validated on macOS during Phase 4 — the spec, hidden imports, runtime hook,
  and frozen entry are correct; only the Windows-specific `liblsl.dll` /
  `LabRecorder.exe` and the Inno installer need a Windows host.)
- **Windows (Phase 5):** install via the Inno `setup.exe`, run one real session,
  confirm the staging gate, `.xdf`+`.mp4`, and a Stage-5 residual ≈ 0 ms.
