; Inno Setup script for WarcraftLogs Analyzer
;
; The release workflow passes the tag's version: ISCC /DAppVersion=4.6.0 installer.iss
; The default below keeps a plain local build working; build_release.sh and tests/test_windows_release.py keep it
; equal to warcraftlogs_client/version.py.
;
; Every release upgrades the same install in place: AppId never changes (it is the AppName the first releases used
; by default), and the in-app updater runs the new Setup.exe with /VERYSILENT (warcraftlogs_client/updater.py).
; User data lives in %APPDATA%\WarcraftLogsAnalyzer, outside {app}, so an upgrade or uninstall never touches it.

#ifndef AppVersion
  #define AppVersion "4.5.0"
#endif

[Setup]
AppId=WarcraftLogs Analyzer
AppName=WarcraftLogs Analyzer
AppVersion={#AppVersion}
AppVerName=WarcraftLogs Analyzer {#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher=WarcraftLogs Analyzer
DefaultDirName={autopf}\WarcraftLogs Analyzer
DefaultGroupName=WarcraftLogs Analyzer
OutputBaseFilename=WarcraftLogsAnalyzer-{#AppVersion}-Setup
OutputDir=installer_output
Compression=lzma2
SolidCompression=yes
SetupIconFile=logo.ico
UninstallDisplayIcon={app}\WarcraftLogsAnalyzer.exe
PrivilegesRequired=lowest
WizardStyle=modern
; Per-user install (%LOCALAPPDATA%\Programs) so updates need no administrator prompt.
UsePreviousAppDir=yes
CloseApplications=yes
RestartApplications=no

[InstallDelete]
; Drop the previous release's libraries so a removed module cannot linger after an upgrade.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\WarcraftLogsAnalyzer\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\WarcraftLogs Analyzer"; Filename: "{app}\WarcraftLogsAnalyzer.exe"
Name: "{group}\Uninstall WarcraftLogs Analyzer"; Filename: "{uninstallexe}"
Name: "{autodesktop}\WarcraftLogs Analyzer"; Filename: "{app}\WarcraftLogsAnalyzer.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional options:"

[Run]
Filename: "{app}\WarcraftLogsAnalyzer.exe"; Description: "Launch WarcraftLogs Analyzer"; Flags: nowait postinstall skipifsilent
