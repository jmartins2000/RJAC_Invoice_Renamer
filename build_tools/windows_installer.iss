; Inno Setup script for the Windows installer.
; Installs per-user (no admin rights needed) and supports silent updates from inside the app.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "RJAC Invoice Renamer"
#define AppExe "RJAC Invoice Renamer.exe"

[Setup]
; Never change AppId: it is how updates find the existing installation.
AppId={{6F3C2B9E-4A71-4C1D-9B2E-52A8D1E7C0F4}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=RJAC
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=RJAC-Invoice-Renamer-Setup-{#AppVersion}
SetupIconFile=..\assets\RJAC-logo.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove files from the previous version before copying the new ones.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Runs after a normal install (checkbox) and also after a silent in-app update.
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName}"; Flags: nowait postinstall
