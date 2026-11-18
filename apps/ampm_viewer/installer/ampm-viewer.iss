; Inno Setup script for AMPM Viewer's Windows setup.
;
; Don't compile this by hand: `just installer` (installer/build_installer.py)
; builds the app first and passes the version, architecture and folders below
; with /D. Needs Inno Setup 6.3 or later (https://jrsoftware.org/isinfo.php).
;
; What the setup does (decided for 2.0.1):
; - Installs for the current user only, without administrator rights, to
;   %LOCALAPPDATA%\Programs\AMPM Viewer.
; - Upgrades in place: one install, whatever the version. The AppId below
;   must never change, or Windows sees a different program. The old
;   _internal folder is removed first so no file of an older version stays.
; - A Start-menu shortcut; a desktop shortcut if ticked (off by default);
;   .ampmplot files open in the app if ticked (on by default).
; - Offers to start the app at the end.
; - Uninstalling leaves the user's settings, macros and plots
;   (%APPDATA%\AMPM) alone.

#ifndef AppVersion
  #error Run installer/build_installer.py (just installer): it passes the version and folders.
#endif
#if VER < EncodeVer(6, 3, 0)
  #error Inno Setup 6.3 or later is needed (x64compatible / arm64 architectures).
#endif

#if AppArch == "arm64"
  #define ArchId "arm64"
#else
  #define ArchId "x64compatible"
#endif

[Setup]
AppId={{9A17E715-545F-4475-BA2B-AF543A030839}
AppName=AMPM Viewer
AppVersion={#AppVersion}
AppVerName=AMPM Viewer {#AppVersion}
AppPublisher={#Publisher}
AppCopyright=All rights reserved
VersionInfoVersion={#VersionNumbers}
VersionInfoProductName=AMPM Viewer
VersionInfoDescription=AMPM Viewer setup
PrivilegesRequired=lowest
DefaultDirName={autopf}\AMPM Viewer
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
ArchitecturesAllowed={#ArchId}
ArchitecturesInstallIn64BitMode={#ArchId}
MinVersion=10.0
CloseApplications=yes
RestartApplications=no
ChangesAssociations=yes
UninstallDisplayName=AMPM Viewer
UninstallDisplayIcon={app}\{#ExeName}.exe
SetupIconFile={#IconFile}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
LZMAUseSeparateProcess=yes
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBase}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "assocplot"; Description: "Open plot library files (.ampmplot) with AMPM Viewer"; GroupDescription: "File types:"

[InstallDelete]
; An upgrade starts from a clean program folder (the user's data is elsewhere).
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; The AppUserModelID matches the one the app gives itself (shell/app.py), so
; the shortcut, the running app and a pinned taskbar icon are one item.
Name: "{autoprograms}\AMPM Viewer"; Filename: "{app}\{#ExeName}.exe"; AppUserModelID: "AMPM.AMPMViewer"
Name: "{autodesktop}\AMPM Viewer"; Filename: "{app}\{#ExeName}.exe"; AppUserModelID: "AMPM.AMPMViewer"; Tasks: desktopicon

[Registry]
; Per user (HKA is HKCU for a per-user install).
Root: HKA; Subkey: "Software\Classes\.ampmplot"; ValueType: string; ValueName: ""; ValueData: "AMPMViewer.Plot"; Flags: uninsdeletevalue; Tasks: assocplot
Root: HKA; Subkey: "Software\Classes\.ampmplot\OpenWithProgids"; ValueType: string; ValueName: "AMPMViewer.Plot"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assocplot
Root: HKA; Subkey: "Software\Classes\AMPMViewer.Plot"; ValueType: string; ValueName: ""; ValueData: "AMPM Viewer plot"; Flags: uninsdeletekey; Tasks: assocplot
Root: HKA; Subkey: "Software\Classes\AMPMViewer.Plot\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#ExeName}.exe,0"; Tasks: assocplot
Root: HKA; Subkey: "Software\Classes\AMPMViewer.Plot\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#ExeName}.exe"" ""%1"""; Tasks: assocplot
Root: HKA; Subkey: "Software\Classes\Applications\{#ExeName}.exe\SupportedTypes"; ValueType: string; ValueName: ".ampmplot"; ValueData: ""; Flags: uninsdeletekey; Tasks: assocplot

[Run]
Filename: "{app}\{#ExeName}.exe"; Description: "{cm:LaunchProgram,AMPM Viewer}"; Flags: nowait postinstall skipifsilent
