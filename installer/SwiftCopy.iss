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
CloseApplications=no
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "defaultcopier"; Description: "Make SwiftCopy the default copier (Ctrl+V in File Explorer uses SwiftCopy)"; GroupDescription: "Windows integration:"
Name: "startup"; Description: "Start SwiftCopy with Windows (in the tray)"; GroupDescription: "Windows integration:"
Name: "contextmenu"; Description: "Add ""Paste with SwiftCopy"" to the right-click menu"; GroupDescription: "Windows integration:"
Name: "sendto"; Description: "Add SwiftCopy to the right-click ""Send to"" menu"; GroupDescription: "Windows integration:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\SwiftCopy\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; clear out files from an older version before installing the new one
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon
Name: "{usersendto}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: sendto

[Registry]
; SwiftCopy's own setting for the Ctrl+V takeover (read by the app)
Root: HKCU; Subkey: "Software\SwiftCopy\SwiftCopy"; ValueType: string; ValueName: "intercept_paste"; ValueData: "true"; Tasks: defaultcopier
Root: HKCU; Subkey: "Software\SwiftCopy\SwiftCopy"; ValueType: string; ValueName: "intercept_paste"; ValueData: "false"; Tasks: not defaultcopier
Root: HKCU; Subkey: "Software\SwiftCopy\SwiftCopy"; ValueType: string; ValueName: "keep_in_tray"; ValueData: "true"; Tasks: defaultcopier or startup
Root: HKCU; Subkey: "Software\SwiftCopy"; Flags: uninsdeletekeyifempty
; start with Windows
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "SwiftCopy"; ValueData: """{app}\{#MyAppExe}"" --tray"; Tasks: startup
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "SwiftCopy"; Flags: deletevalue uninsdeletevalue; Tasks: not startup
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "SwiftCopy"; Flags: uninsdeletevalue
; right-click "Paste with SwiftCopy" (folder background, folders, drives)
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\SwiftCopy.Paste"; ValueType: string; ValueName: ""; ValueData: "Paste with SwiftCopy"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\SwiftCopy.Paste"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Paste with SwiftCopy"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\SwiftCopy.Paste"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExe}"",0"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\SwiftCopy.Paste\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExe}"" --paste ""%V"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\SwiftCopy.Paste"; ValueType: string; ValueName: ""; ValueData: "Paste with SwiftCopy"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\SwiftCopy.Paste"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Paste with SwiftCopy"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\SwiftCopy.Paste"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExe}"",0"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\SwiftCopy.Paste\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExe}"" --paste ""%1"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Drive\shell\SwiftCopy.Paste"; ValueType: string; ValueName: ""; ValueData: "Paste with SwiftCopy"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Drive\shell\SwiftCopy.Paste"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Paste with SwiftCopy"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Drive\shell\SwiftCopy.Paste"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExe}"",0"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Drive\shell\SwiftCopy.Paste\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExe}"" --paste ""%1"""; Tasks: contextmenu
; always clean these up on uninstall, even if they were turned on later from the app
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\SwiftCopy.Paste"; Flags: uninsdeletekey dontcreatekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\SwiftCopy.Paste"; Flags: uninsdeletekey dontcreatekey
Root: HKCU; Subkey: "Software\Classes\Drive\shell\SwiftCopy.Paste"; Flags: uninsdeletekey dontcreatekey

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Open SwiftCopy now"; Flags: nowait postinstall skipifsilent
; installed without the window? still start it in the tray so Ctrl+V works right away
Filename: "{app}\{#MyAppExe}"; Parameters: "--tray"; Flags: nowait runasoriginaluser skipifnotsilent

[UninstallDelete]
Type: files; Name: "{usersendto}\{#MyAppName}.lnk"

[UninstallRun]
; SwiftCopy may be running in the tray - close it so its files can be removed
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#MyAppExe}"; Flags: runhidden; RunOnceId: "StopSwiftCopy"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  { close a running SwiftCopy (e.g. in the tray) before updating its files }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/f /im {#MyAppExe}', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
