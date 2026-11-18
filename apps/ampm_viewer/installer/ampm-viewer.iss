; Inno Setup script for AMPM Viewer's Windows setup.
;
; Don't compile this by hand: `just installer` (installer/build_installer.py)
; builds the app first and passes the version, architecture and folders below
; with /D. Needs Inno Setup 6.6 or later (https://jrsoftware.org/isinfo.php).
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
; - Uninstalling lists what else the app left and removes the ticked items
;   (see [Code]): caches and leftovers (ticked) and settings and recent lists
;   (not ticked). Macros, saved plots and builds are always kept. A silent
;   uninstall keeps everything, unless given /TIDY (then both go).

#ifndef AppVersion
  #error Run installer/build_installer.py (just installer): it passes the version and folders.
#endif
#if VER < EncodeVer(6, 6, 0)
  #error Inno Setup 6.6 or later is needed (CreateCustomForm with a size, x64compatible / arm64).
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

[Code]
// -- Tidying up after the uninstall -----------------------------------------
// What the app leaves outside its program folder (see shell/settings.py,
// shell/crash.py): in the AMPM folder, %APPDATA%\AMPM, the settings file and
// crash reports (and the user's Macros, Plots and Builds, never touched);
// Qt's caches in %LOCALAPPDATA%\AMPM\AMPM Viewer; and the folders the 2.0.0
// one-file .exe unpacked to %TEMP%\_MEI... and left there when it crashed
// (only those holding ampm_viewer: other programs use _MEI folders too).

var
  RemoveCaches, RemoveSettings: Boolean;

function DataDir: String;
begin
  Result := ExpandConstant('{userappdata}\AMPM');
end;

function LocalDir: String;
begin
  Result := ExpandConstant('{localappdata}\AMPM');
end;

function TreeSize(const Path: String): Int64;
var
  F: TFindRec;
begin
  Result := 0;
  if FindFirst(AddBackslash(Path) + '*', F) then
  try
    repeat
      if (F.Name <> '.') and (F.Name <> '..') then
      begin
        if F.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then
          Result := Result + TreeSize(AddBackslash(Path) + F.Name)
        else
          Result := Result + Int64(F.SizeHigh) * 65536 * 65536 + F.SizeLow;
      end;
    until not FindNext(F);
  finally
    FindClose(F);
  end;
end;

function PathSize(const Path: String): Int64;
var
  F: TFindRec;
begin
  Result := 0;
  if DirExists(Path) then
    Result := TreeSize(Path)
  else if FindFirst(Path, F) then
  try
    Result := Int64(F.SizeHigh) * 65536 * 65536 + F.SizeLow;
  finally
    FindClose(F);
  end;
end;

// The 2.0.0 .exe's leftover folders in %TEMP% (the caller frees the list).
function OldUnpackFolders: TStringList;
var
  F: TFindRec;
  Temp: String;
begin
  Result := TStringList.Create;
  Temp := AddBackslash(GetTempDir);
  if FindFirst(Temp + '_MEI*', F) then
  try
    repeat
      if (F.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0)
         and DirExists(Temp + F.Name + '\ampm_viewer') then
        Result.Add(Temp + F.Name);
    until not FindNext(F);
  finally
    FindClose(F);
  end;
end;

function CacheSize: Int64;
var
  Old: TStringList;
  I: Integer;
begin
  Result := PathSize(DataDir + '\crash-reports') + PathSize(LocalDir + '\AMPM Viewer');
  Old := OldUnpackFolders;
  try
    for I := 0 to Old.Count - 1 do
      Result := Result + PathSize(Old[I]);
  finally
    Old.Free;
  end;
end;

function SettingsExist: Boolean;
begin
  Result := FileExists(DataDir + '\ampm-viewer.conf');
end;

function SizeText(Size: Int64): String;
begin
  if Size < 1024 * 1024 then
    Result := Format('%d KB', [Integer((Size + 1023) div 1024)])
  else
    Result := Format('%.1f MB', [Size / (1024.0 * 1024.0)]);
end;

function HasParam(const Name: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), Name) = 0 then
      Result := True;
end;

// One list of what can go, both items untickable; one Remove / Keep.
procedure AskWhatToRemove;
var
  Form: TSetupForm;
  Intro: TNewStaticText;
  List: TNewCheckListBox;
  RemoveButton, KeepButton: TNewButton;
  Caches: Int64;
  CacheItem, SettingsItem: Integer;
begin
  Caches := CacheSize;
  if (Caches = 0) and not SettingsExist then
    Exit;
  // Since Inno Setup 6.6 the form scales the size given itself.
  Form := CreateCustomForm(440, 210, False, False);
  try
    Form.Caption := 'Uninstall AMPM Viewer';

    Intro := TNewStaticText.Create(Form);
    Intro.Parent := Form;
    Intro.Left := ScaleX(16);
    Intro.Top := ScaleY(14);
    Intro.Width := Form.ClientWidth - ScaleX(32);
    Intro.WordWrap := True;
    Intro.AutoSize := True;
    Intro.Caption := 'Also remove these? Your macros, saved plots and builds are kept.';

    List := TNewCheckListBox.Create(Form);
    List.Parent := Form;
    List.Left := ScaleX(16);
    List.Top := Intro.Top + Intro.Height + ScaleY(10);
    List.Width := Form.ClientWidth - ScaleX(32);
    List.Height := ScaleY(96);
    List.Flat := True;
    CacheItem := List.AddCheckBox(
      'Caches and leftovers: crash reports, caches, old temporary files',
      SizeText(Caches), 0, Caches > 0, Caches > 0, False, False, nil);
    SettingsItem := List.AddCheckBox(
      'Settings and recent lists: theme, folders, recent builds, favourites',
      '', 0, False, SettingsExist, False, False, nil);

    RemoveButton := TNewButton.Create(Form);
    RemoveButton.Parent := Form;
    RemoveButton.Caption := 'Remove ticked';
    RemoveButton.Width := ScaleX(110);
    RemoveButton.Height := ScaleY(25);
    RemoveButton.Left := Form.ClientWidth - ScaleX(16) - ScaleX(110) * 2 - ScaleX(8);
    RemoveButton.Top := Form.ClientHeight - ScaleY(25) - ScaleY(12);
    RemoveButton.ModalResult := mrOk;
    RemoveButton.Default := True;

    KeepButton := TNewButton.Create(Form);
    KeepButton.Parent := Form;
    KeepButton.Caption := 'Keep all';
    KeepButton.Width := ScaleX(110);
    KeepButton.Height := ScaleY(25);
    KeepButton.Left := Form.ClientWidth - ScaleX(16) - ScaleX(110);
    KeepButton.Top := RemoveButton.Top;
    KeepButton.ModalResult := mrCancel;
    KeepButton.Cancel := True;

    if Form.ShowModal = mrOk then
    begin
      RemoveCaches := List.Checked[CacheItem];
      RemoveSettings := List.Checked[SettingsItem];
    end;
  finally
    Form.Free;
  end;
end;

procedure RemoveTidied;
var
  Old: TStringList;
  I: Integer;
begin
  if RemoveCaches then
  begin
    DelTree(DataDir + '\crash-reports', True, True, True);
    DelTree(LocalDir + '\AMPM Viewer', True, True, True);
    RemoveDir(LocalDir);   // only if now empty
    Old := OldUnpackFolders;
    try
      for I := 0 to Old.Count - 1 do
        DelTree(Old[I], True, True, True);
    finally
      Old.Free;
    end;
  end;
  if RemoveSettings then
  begin
    DeleteFile(DataDir + '\ampm-viewer.conf');
    DeleteFile(DataDir + '\ampm-viewer.conf.lock');
  end;
  if RemoveCaches or RemoveSettings then
    RemoveDir(DataDir);    // only if nothing of the user's is left in it
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if UninstallSilent then
    begin
      RemoveCaches := HasParam('/TIDY');
      RemoveSettings := RemoveCaches;
    end
    else
      AskWhatToRemove;
  end
  else if CurUninstallStep = usPostUninstall then
    RemoveTidied;
end;
