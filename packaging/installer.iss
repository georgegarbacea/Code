; Inno Setup script for LumiBeat Studio (free, https://jrsoftware.org/isinfo.php)
; Build:  ISCC.exe packaging\installer.iss   (after PyInstaller produced dist\LumiBeat Studio\)

#define AppName "LumiBeat Studio"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppExe "LumiBeat Studio.exe"

[Setup]
AppId={{6E1C4B7A-3F2D-4C59-9A0E-8B5D2F7C1A44}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=LumiBeat
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=LumiBeat-Studio-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardImageFile=..\assets\installer_side.bmp
WizardSmallImageFile=..\assets\installer_small.bmp
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
PrivilegesRequired=admin
CloseApplications=yes
RestartApplications=no

[Languages]
#if FileExists(SourcePath + "Romanian.isl")
Name: "ro"; MessagesFile: "Romanian.isl"
#endif
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
desktop=Pictogramă pe desktop
autostart=Pornește LumiBeat Studio odată cu Windows (minimizat în tray)
firewall=Permite controlul de pe telefon în rețeaua privată (regulă Windows Firewall)
launch=Pornește LumiBeat Studio
extras=Opțiuni suplimentare:

[Tasks]
Name: "desktopicon"; Description: "{cm:desktop}"; GroupDescription: "{cm:extras}"
Name: "autostart"; Description: "{cm:autostart}"; GroupDescription: "{cm:extras}"; Flags: unchecked
Name: "firewall"; Description: "{cm:firewall}"; GroupDescription: "{cm:extras}"

[Files]
Source: "..\dist\LumiBeat Studio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\docs\MANUAL.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\SP801E.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Manual de instalare și calibrare"; Filename: "{app}\docs\MANUAL.md"
Name: "{group}\Dezinstalează {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; \
  ValueData: """{app}\{#AppExe}"" --minimized"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
; inbound rule limited to PRIVATE networks: phone remote (TCP) + ArtPollReply (UDP 6454)
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName}"""; Flags: runhidden; Tasks: firewall
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#AppName}"" dir=in action=allow program=""{app}\{#AppExe}"" enable=yes profile=private"; Flags: runhidden; Tasks: firewall
Filename: "{app}\{#AppExe}"; Description: "{cm:launch}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName}"""; Flags: runhidden; RunOnceId: "DelFirewallRule"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
