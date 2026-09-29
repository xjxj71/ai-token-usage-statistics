; Inno Setup script — AI 用量统计 (ai-token-usage)
; Build: iscc /DAppVersion=0.1.2 build\installer.iss
; AppMutex must match backend.tray_app.MUTEX_NAME / APP_MUTEX_NAME.
; The version MUST be passed explicitly so installer stamps never drift from
; pyproject.toml — build_exe.py reads it and passes /DAppVersion automatically.

#ifndef AppVersion
  #error "Pass the version: iscc /DAppVersion=x.y.z build\installer.iss (build_exe.py does this)"
#endif

[Setup]
AppId={{8F3C2A10-5B6E-4D2A-9C11-A1B2C3D4E5F6}
AppName=AI 用量统计
AppVersion={#AppVersion}
AppPublisher=ai-token-usage-statistics
DefaultDirName={localappdata}\Programs\ai-token-usage
DefaultGroupName=AI 用量统计
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\build\output
OutputBaseFilename=AI-Token-Usage-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Same bare name as CreateMutexW "Local\AiTokenUsageStatistics"
AppMutex=AiTokenUsageStatistics
CloseApplications=yes
RestartApplications=no

[Languages]
; No official Simplified Chinese .isl in the stock installer; wizard UI is English.
; Product name and shortcut labels below stay Chinese.
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"; GroupDescription: "Additional icons:"
; Registered with --minimized so logging in does not pop a browser panel.
Name: "startup"; Description: "Start with Windows"; GroupDescription: "Startup:"
Name: "deletedata"; Description: "Delete user data when uninstalling"; GroupDescription: "Uninstall:"; Flags: unchecked

[Files]
; PyInstaller onedir output (default --distpath is <repo>/dist)
Source: "..\dist\ai-token-usage\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AI 用量统计"; Filename: "{app}\ai-token-usage.exe"
Name: "{autodesktop}\AI 用量统计"; Filename: "{app}\ai-token-usage.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueData: """{app}\ai-token-usage.exe"" --minimized"; \
  Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\ai-token-usage.exe"; Description: "Launch AI Token Usage now"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only when the deletedata task was selected at install time (stored in registry by Inno).
Type: filesandordirs; Name: "{userappdata}\ai-token-usage"; Tasks: deletedata
