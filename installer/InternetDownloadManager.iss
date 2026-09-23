#define AppName "Internet Download Manager"
#define AppVersion "1.5.2"
#define AppPublisher "Mirha Zulfiqar"
#define AppExeName "InternetDownloadManager.exe"
[Setup]
AppId={{7D18D4B1-7E6D-4D12-9A8D-5E8F1A5D1520}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Internet Download Manager
DefaultGroupName={#AppName}
OutputDir=..\installer-output
OutputBaseFilename=InternetDownloadManager_Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
Uninstallable=yes
DisableProgramGroupPage=yes
WizardStyle=modern
[Files]
Source: "..\dist\InternetDownloadManager\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\browser_extension\*"; DestDir: "{app}\browser_extension"; Flags: recursesubdirs ignoreversion
Source: "..\INSTALL_BROWSER_INTEGRATION.bat"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"
[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
Filename: "{sys}\cmd.exe"; Parameters: "/c ""{app}\INSTALL_BROWSER_INTEGRATION.bat"""; Description: "Register browser integration"; Flags: runhidden waituntilterminated skipifsilent
[UninstallDelete]
Type: filesandordirs; Name: "{app}\browser_extension"
