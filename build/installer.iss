; Inno Setup script — AI 用量统计 (ai-token-usage)
; Build: iscc /DAppVersion=0.1.0 build\installer.iss
; AppMutex must match backend.tray_app.MUTEX_NAME / APP_MUTEX_NAME.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{8F3C2A10-5B6E-4D2A-9C11-A1B2C3D4E5F6}
AppName=AI 用量统计
AppVersion={#AppVersion}
AppPublisher=ai-token-usage-statistics
DefaultDirName={localappdata}\Programs\ai-token-usage
DefaultGroupName=AI 用量统计
DisableProgramGroupPage=yes
PrivilegesRequired=dynamic
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
Name: "chinesesimplified"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"
Name: "startup"; Description: "开机自启"; GroupDescription: "启动方式:"
Name: "deletedata"; Description: "卸载时同时删除用户数据"; GroupDescription: "卸载:"; Flags: unchecked

[Files]
; PyInstaller onedir output: build/dist/ai-token-usage/**
Source: "dist\ai-token-usage\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AI 用量统计"; Filename: "{app}\ai-token-usage.exe"
Name: "{autodesktop}\AI 用量统计"; Filename: "{app}\ai-token-usage.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "AiTokenUsageStatistics"; ValueData: "{app}\ai-token-usage.exe"; \
  Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\ai-token-usage.exe"; Description: "立即运行 AI 用量统计"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only when the deletedata task was selected at install time (stored in registry by Inno).
Type: filesandordirs; Name: "{userappdata}\ai-token-usage"; Tasks: deletedata
