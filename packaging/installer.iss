; Inno Setup script for Utter (optional — BUILD_PLAN §11).
; Compile with:  iscc packaging\installer.iss
; Expects the GPU bundle at dist\utter (run PyInstaller first).
; NOTE: Inno section entries must be single lines — no continuation character exists.

#define AppName "Utter"
#define AppVersion "0.1.0"
#define AppPublisher "Ahmed Haque"
#define AppURL "https://github.com/afhaque/Utter"

[Setup]
AppId={{B7E8B7D4-6C1D-4E3B-9A5B-3A0F2C41D7E9}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppSupportURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\utterd.exe
; the CUDA DLL set makes this a large install — lzma2 helps but expect ~2 GB
Compression=lzma2
SolidCompression=yes
OutputDir=..\dist
OutputBaseFilename=utter-setup
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "startup"; Description: "Launch Utter when Windows starts"; Flags: unchecked

[Files]
Source: "..\dist\utter\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Utter"; Filename: "{app}\utterd.exe"
Name: "{group}\Utter Dashboard"; Filename: "{app}\utter.exe"; Parameters: "dashboard"
Name: "{group}\Uninstall Utter"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Utter"; ValueData: """{app}\utterd.exe"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\utterd.exe"; Description: "Start Utter now"; Flags: nowait postinstall skipifsilent
