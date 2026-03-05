; LightPhon Node Installer Script
; Requires Inno Setup: https://jrsoftware.org/isinfo.php

#define MyAppName "LightPhon Node"
#define MyAppVersion "1.0.8"
#define MyAppPublisher "AI Lightning"
#define MyAppURL "https://github.com/ddorigoddorigo/LightPhon"
#define MyAppExeName "LightPhon-Node.exe"

[Setup]
; NOTE: The value of AppId uniquely identifies this application.
AppId={{B8A3E2F1-5C4D-4E6F-9A8B-1C2D3E4F5A6B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
; Output settings
OutputDir=installer_output
OutputBaseFilename=LightPhon-Node-Setup-{#MyAppVersion}
; Compression
Compression=lzma2/ultra64
SolidCompression=yes
; Installer appearance
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
; Privileges - use lowest to install in user folder
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Windows version
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1; Check: not IsAdminInstallMode
Name: "startupicon"; Description: "Start automatically when Windows starts"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Add config files
Source: "config.ini.example"; DestDir: "{app}"; DestName: "config.ini"; Flags: onlyifdoesntexist
Source: "models_config.json"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// Check if VC++ Redistributable is installed
function IsVCRedistInstalled: Boolean;
var
  RegKey: String;
begin
  RegKey := 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64';
  Result := RegKeyExists(HKEY_LOCAL_MACHINE, RegKey);
end;

// Show warning if VC++ not installed
procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpReady then
  begin
    if not IsVCRedistInstalled then
    begin
      MsgBox('Warning: Microsoft Visual C++ Redistributable does not appear to be installed.' + #13#10 + #13#10 +
             'LightPhon requires VC++ Redistributable to run.' + #13#10 +
             'Please install it using: winget install Microsoft.VCRedist.2015+.x64' + #13#10 + #13#10 +
             'The installation will continue, but the application may not work without it.',
             mbInformation, MB_OK);
    end;
  end;
end;
