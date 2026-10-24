; Inno Setup script for Simple-Chat.
; Built with: iscc packaging\windows\installer.iss
; Expects dist\Simple-Chat\ (PyInstaller onedir output) to already
; exist, and the version passed in via /DAppVersion=x.y.z (the release
; workflow does this so the .iss file never has to be hand-edited per
; release).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Simple-Chat"
#define RepoRoot AddBackslash(SourcePath) + "..\.."

[Setup]
AppId={{7C5F9CF4-8B83-409F-8E16-53F6E2A41D87}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Mike Hellyer
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\Simple-Chat.exe
OutputDir={#RepoRoot}\dist
OutputBaseFilename=Simple-Chat-{#AppVersion}-Windows-Setup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile={#RepoRoot}\packaging\icons\icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#RepoRoot}\dist\Simple-Chat\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\Simple-Chat.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Simple-Chat.exe"; Tasks: desktopicon

[Run]
; Let other machines' messages in without Windows Firewall asking on
; first run (the installer already runs as administrator).
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName}"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#AppName}"" dir=in action=allow program=""{app}\Simple-Chat.exe"" enable=yes profile=private,domain"; Flags: runhidden
Filename: "{app}\Simple-Chat.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName}"""; Flags: runhidden; RunOnceId: "RemoveFirewallRule"

[Code]
// "Start when I log in" lives in the user's HKCU Run key, written by the
// app; take it away with the app so Windows doesn't try to start a
// program that's gone.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}');
end;
