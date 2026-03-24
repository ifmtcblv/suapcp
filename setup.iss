; Script gerado pelo Inno Setup para o SUAP-CP

[Setup]
AppName=SUAP-CP
AppVersion={#AppVersion}
AppPublisher=IFMT - Instituto Federal de Mato Grosso
AppSupportURL=https://ifmt.edu.br
AppUpdatesURL=https://ifmt.edu.br
DefaultDirName={autopf}\SUAP-CP
DefaultGroupName=SUAP-CP
OutputDir=dist
OutputBaseFilename=suap-cp-{#AppVersion}-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\suapcp.exe
LicenseFile=LICENSE
PrivilegesRequired=lowest

[Languages]
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\suapcp.exe"; DestDir: "{app}"; Flags: ignoreversion
; Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\SUAP-CP"; Filename: "{app}\suapcp.exe"
Name: "{group}\{cm:UninstallProgram,SUAP-CP}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\SUAP-CP"; Filename: "{app}\suapcp.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\suapcp.exe"; Description: "{cm:LaunchProgram,SUAP-CP}"; Flags: nowait postinstall skipifsilent
