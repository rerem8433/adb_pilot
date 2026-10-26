; Installateur Windows d'ADB Pilot (Inno Setup 6.3+)
; Compilation : iscc /DAppVersion=1.3.0 /DArch=x64   /DSrcDir=..\..\dist\ADB-Pilot-x64   adbpilot.iss
;               iscc /DAppVersion=1.3.0 /DArch=arm64 /DSrcDir=..\..\dist\ADB-Pilot-arm64 adbpilot.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef Arch
  #define Arch "x64"
#endif
#ifndef SrcDir
  #define SrcDir "..\..\dist\ADB-Pilot-" + Arch
#endif

[Setup]
AppId={{6F2B8C41-5D3A-4E7B-9A62-0ADB1A5C0001}
AppName=ADB Pilot
AppVersion={#AppVersion}
AppVerName=ADB Pilot {#AppVersion}
AppPublisher=ParadoxXx Squad
AppPublisherURL=https://github.com/rerem8433/adb_pilot
AppSupportURL=https://github.com/rerem8433/adb_pilot/issues
AppUpdatesURL=https://github.com/rerem8433/adb_pilot/releases
DefaultDirName={autopf}\ADB Pilot
DefaultGroupName=ADB Pilot
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=ADB-Pilot-{#AppVersion}-windows-{#Arch}-setup
SetupIconFile={#SrcDir}\adbpilot.ico
UninstallDisplayIcon={app}\ADB Pilot.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Installation pour tous (admin) ou seulement pour l'utilisateur courant, au choix
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
MinVersion=10.0.17763
CloseApplications=yes
#if Arch == "arm64"
ArchitecturesAllowed=arm64
ArchitecturesInstallIn64BitMode=arm64
InfoBeforeFile=arm64_note.txt
#else
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#endif

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
french.OpenWith=Proposer ADB Pilot dans « Ouvrir avec » pour les fichiers APK (sans en faire l'application par défaut)
english.OpenWith=Offer ADB Pilot in "Open with" for APK files (without making it the default app)

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; Pas d'association automatique des .apk : option décochée, l'utilisateur décide
Name: "openwith"; Description: "{cm:OpenWith}"; Flags: unchecked

[Files]
Source: "{#SrcDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\ADB Pilot"; Filename: "{app}\ADB Pilot.exe"
Name: "{autodesktop}\ADB Pilot"; Filename: "{app}\ADB Pilot.exe"; Tasks: desktopicon

[Registry]
; Option « openwith » : ADB Pilot apparaît dans « Ouvrir avec », sans devenir l'application par défaut
Root: HKA; Subkey: "Software\Classes\Applications\ADB Pilot.exe\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\ADB Pilot.exe"" ""%1"""; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\ADB Pilot.exe\SupportedTypes"; ValueType: string; ValueName: ".apk"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\ADB Pilot.exe\SupportedTypes"; ValueType: string; ValueName: ".apks"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\ADB Pilot.exe\SupportedTypes"; ValueType: string; ValueName: ".xapk"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\ADB Pilot.exe\SupportedTypes"; ValueType: string; ValueName: ".apkm"; ValueData: ""; Tasks: openwith

[Run]
Filename: "{app}\ADB Pilot.exe"; Description: "{cm:LaunchProgram,ADB Pilot}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\tools\platform-tools\adb.exe"; Parameters: "kill-server"; Flags: runhidden skipifdoesntexist; RunOnceId: "KillAdb"

[Code]
// Le serveur adb verrouille adb.exe : on l'arrête avant une mise à jour
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  if FileExists(ExpandConstant('{app}\tools\platform-tools\adb.exe')) then
    Exec(ExpandConstant('{app}\tools\platform-tools\adb.exe'), 'kill-server', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;
