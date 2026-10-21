; Inno Setup script for SwiftCopy.
; Built by the GitHub Actions workflow:  ISCC /DMyAppVersion=1.0.0 installer\SwiftCopy.iss
; Installs per user (no admin rights needed).

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppName "SwiftCopy"
#define MyAppExe "SwiftCopy.exe"

[Setup]
AppId={{6F2B9C41-7E35-4A8D-9C0B-5D21A7E4F3B8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=Yasmany
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=SwiftCopy-Setup-{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "sendto"; Description: "Add SwiftCopy to the right-click ""Send to"" menu"; GroupDescription: "Explorer:"

[Files]
Source: "..\dist\SwiftCopy\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; clear out files from an older version before installing the new one
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon
Name: "{usersendto}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: sendto

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Open SwiftCopy now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{usersendto}\{#MyAppName}.lnk"
