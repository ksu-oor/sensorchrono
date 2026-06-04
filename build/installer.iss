; Inno Setup script for SensorChrono.
; Wraps the one-folder PyInstaller build (dist\SensorChrono\) into a single
; installer so deployment feels like one double-click.
;   1) build\build_windows.ps1   -> dist\SensorChrono\
;   2) compile this script in Inno Setup -> SensorChrono-<ver>-setup.exe

#define AppName "SensorChrono"
#define AppVersion "1.0.0"
#define AppPublisher "Kennesaw State University"
#define DistDir "..\dist\SensorChrono"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputBaseFilename=SensorChrono-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\SensorChrono.exe"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\SensorChrono.exe"

[Run]
Filename: "{app}\SensorChrono.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
