; StarForge Windows 安装包（Inno Setup 6，LZMA2 solid）。
;
; 只做“解压 + 快捷方式”，不下载任何额外组件：PySide6、numpy、unicorn、
; 内置游戏数据以及 agent 的独立 Python 运行时都在 dist\starforge 里。
;
; 本地构建：
;   iscc /DAppVersion=0.16.0 installer\starforge.iss
; CI 会从 tag 去掉前缀后传入 AppVersion。
#ifndef AppVersion
  #define AppVersion "0.16.0"
#endif

#define AppName "StarForge"
#define AppExe "starforge.exe"
#define AppPublisher "StarForge"
#define AppURL "https://github.com/MaroD1M/starforge"
#define AppId "{{6F0C2B7E-6E5A-4E4B-9D0E-2A7B5C1F3A42}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={localappdata}\Programs\StarForge
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=starforge-{#AppVersion}-win64-setup
SetupIconFile=..\assets\starforge.ico
UninstallDisplayIcon={app}\{#AppExe}
LicenseFile=..\LICENSE
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
MinVersion=10.0
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\starforge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName}（安全模式）"; Filename: "{app}\{#AppExe}"; Parameters: "app --safe"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\agent-runtime"
