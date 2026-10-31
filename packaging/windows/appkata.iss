; Inno Setup script: AppKata-<version>-setup.exe (requirements 1.6, 15.10).
; For the current user by default, with no UAC prompt; /ALLUSERS (or the dialog) installs for
; everyone into Program Files. /RELAUNCH=1 starts AppKata again when Setup finishes, even when
; silent: AppKata's own updates use it (requirement 2.11.5).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; AppKata finds its own Uninstall entry by this id ("{8E3B…}_is1"): don't change it.
AppId={{8E3B9C51-6A2D-4F7E-B1C4-3D5A7E9F0B12}
AppName=AppKata
AppVersion={#AppVersion}
AppVerName=AppKata {#AppVersion}
AppPublisher=AppKata
AppPublisherURL=https://github.com/MojoKata/AppKata
AppComments=A FOSS app store built on git
DefaultDirName={autopf}\AppKata
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19045
OutputDir=..\..\releases
OutputBaseFilename=AppKata-{#AppVersion}-setup
SetupIconFile=appkata.ico
UninstallDisplayIcon={app}\appkata.exe
UninstallDisplayName=AppKata
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no

[Files]
; the build's folder, LICENSE.txt and THIRD-PARTY-NOTICES.txt beside appkata.exe (scripts/third_party_notices.py)
Source: "..\..\build\windows\dist\AppKata\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
; files of an older version that this one doesn't have
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\AppKata"; Filename: "{app}\appkata.exe"; Comment: "A FOSS app store built on git"; AppUserModelID: "AppKata.AppKata"

[Registry]
; appkata://add/<url> opens Add source (requirement 11.3, 15.14). HKA: HKCU for the current user, HKLM for everyone.
Root: HKA; Subkey: "Software\Classes\appkata"; ValueType: string; ValueName: ""; ValueData: "URL:AppKata link"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\appkata"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\appkata\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\appkata.exe"",0"
Root: HKA; Subkey: "Software\Classes\appkata\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\appkata.exe"" ""%1"""

[Run]
; after a self-update (requirement 2.11.5): start the new version as the user who ran Setup
Filename: "{app}\appkata.exe"; Flags: nowait runasoriginaluser; Check: WantRelaunch
Filename: "{app}\appkata.exe"; Description: "Open AppKata"; Flags: postinstall nowait skipifsilent runasoriginaluser; Check: not WantRelaunch

[Code]
function WantRelaunch: Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usUninstall then
    { the "Start in the tray at login" entry (requirement 1.7.4, 15.14) }
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'AppKata');
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{localappdata}\AppKata');
    if DirExists(Data) and not UninstallSilent then
      if MsgBox('Also delete your AppKata data?' #13#10#13#10 +
                'Your Sources, Trusts, settings and the Audit are in' #13#10 + Data + #13#10#13#10 +
                'Keep them if you might install AppKata again.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Data, True, True, True);
    if not UninstallSilent then
      MsgBox('AppKata is uninstalled.' #13#10#13#10 +
             'The apps it installed are still installed. Reinstall AppKata to update or ' +
             'remove them.', mbInformation, MB_OK);
  end;
end;
