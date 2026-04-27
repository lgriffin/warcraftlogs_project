; Inno Setup script for WarcraftLogs Analyzer

[Setup]
AppName=WarcraftLogs Analyzer
AppVersion=3.2.0
AppPublisher=WarcraftLogs Analyzer
DefaultDirName={autopf}\WarcraftLogs Analyzer
DefaultGroupName=WarcraftLogs Analyzer
OutputBaseFilename=WarcraftLogsAnalyzer-3.2.0-Setup
OutputDir=installer_output
Compression=lzma2
SolidCompression=yes
SetupIconFile=logo.ico
UninstallDisplayIcon={app}\WarcraftLogsAnalyzer.exe
PrivilegesRequired=lowest
WizardStyle=modern

[Files]
Source: "dist\WarcraftLogsAnalyzer\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\WarcraftLogs Analyzer"; Filename: "{app}\WarcraftLogsAnalyzer.exe"
Name: "{group}\Uninstall WarcraftLogs Analyzer"; Filename: "{uninstallexe}"
Name: "{autodesktop}\WarcraftLogs Analyzer"; Filename: "{app}\WarcraftLogsAnalyzer.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional options:"

[Run]
Filename: "{app}\WarcraftLogsAnalyzer.exe"; Description: "Launch WarcraftLogs Analyzer"; Flags: nowait postinstall skipifsilent
