# Build SensorChrono (one-folder) on Windows, in the project venv.
#   powershell -ExecutionPolicy Bypass -File build\build_windows.ps1
param(
    [string]$LiblslPath = $env:LIBLSL_PATH,
    [string]$LabRecorderDir = $env:LABRECORDER_DIR,
    [string]$Python = ".venv\Scripts\python.exe"
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $root

# Fall back to the liblsl that ships inside the pylsl wheel.
if (-not $LiblslPath) {
    $guess = & $Python -c "import os,pylsl;d=os.path.dirname(pylsl.__file__);print(next((os.path.join(r,f) for r,_,fs in os.walk(d) for f in fs if f.lower() in ('lsl.dll','liblsl.dll','liblsl64.dll')), ''))"
    if ($guess -and (Test-Path $guess)) { $LiblslPath = $guess }
}

$env:SENSORCHRONO_ROOT = $root
$env:LIBLSL_PATH = $LiblslPath
$env:LABRECORDER_DIR = $LabRecorderDir
Write-Host "liblsl:      $env:LIBLSL_PATH"
Write-Host "LabRecorder: $env:LABRECORDER_DIR"

& $Python -m pip install --upgrade pyinstaller
& $Python -m PyInstaller --noconfirm --clean build\sensorchrono.spec

Write-Host "Built one-folder app at: $root\dist\SensorChrono\SensorChrono.exe"
Write-Host "Next: compile build\installer.iss with Inno Setup to produce the installer."
