#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef AppExe
  #error AppExe is required
#endif
#ifndef AppGuid
  #define AppGuid "ED640D97-5583-4823-94E9-049D7CB27CA8"
#endif
#ifndef AppTitle
  #define AppTitle "ValorantToxicTamer"
#endif
#define AppKey "Software\Microsoft\Windows\CurrentVersion\Uninstall\{" + AppGuid + "}_is1"

[Setup]
AppId={{{#AppGuid}}
AppName={#AppTitle}
AppVersion={#AppVersion}
AppPublisher=TimeseekerKK
DefaultDirName={autopf}\ValorantToxicTamer
DisableDirPage=no
AppendDefaultDirName=no
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
AppMutex=Local\ValorantToxicTamer
CloseApplications=yes
RestartApplications=no
OutputDir=..\dist
OutputBaseFilename=ValorantToxicTamer-Setup-v{#AppVersion}
SetupIconFile=..\valorant_toxic_tamer\assets\app.ico
UninstallDisplayIcon={app}\ValorantToxicTamer.exe
WizardStyle=modern
Compression=lzma2/fast
SolidCompression=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked

[Files]
Source: "{#AppExe}"; DestDir: "{app}"; DestName: "ValorantToxicTamer.exe"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppTitle}"; Filename: "{app}\ValorantToxicTamer.exe"
Name: "{autodesktop}\{#AppTitle}"; Filename: "{app}\ValorantToxicTamer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ValorantToxicTamer.exe"; Description: "启动 ValorantToxicTamer"; Flags: nowait postinstall skipifsilent

[Code]
var
  MigrationPage: TInputOptionWizardPage;
  MigrationSource, PreviousDir: String;
  DeletePersonalData: Boolean;
  NormalizingDir: Boolean;

function GetFileAttributesW(lpFileName: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function SetFileAttributesW(lpFileName: String; dwFileAttributes: LongWord): Boolean;
  external 'SetFileAttributesW@kernel32.dll stdcall';

function NormalizeAppDir(Value: String): String;
begin
  Value := RemoveBackslashUnlessRoot(Trim(Value));
  if CompareText(ExtractFileName(Value), 'ValorantToxicTamer') <> 0 then
    Value := AddBackslash(Value) + 'ValorantToxicTamer';
  Result := Value;
end;

function HasReparseParent(Value: String): Boolean;
var Attr: Integer;
begin
  Result := False;
  Value := RemoveBackslashUnlessRoot(Value);
  while Length(Value) > 3 do begin
    Attr := GetFileAttributesW(Value);
    if (Attr <> -1) and ((Attr and $400) <> 0) then begin
      Result := True;
      Exit;
    end;
    Value := ExtractFileDir(Value);
  end;
end;

procedure DirChanged(Sender: TObject);
begin
  if NormalizingDir then Exit;
  NormalizingDir := True;
  WizardForm.DirEdit.Text := NormalizeAppDir(WizardForm.DirEdit.Text);
  NormalizingDir := False;
end;

procedure UpdateMigrationSource;
begin
  MigrationSource := ExpandConstant('{param:DATASOURCE|}');
  if (MigrationSource = '') and (PreviousDir <> '') then
    MigrationSource := AddBackslash(PreviousDir) + 'data';
  if (MigrationSource = '') or not DirExists(MigrationSource) then
    MigrationSource := ExpandConstant('{localappdata}\ValorantToxicTamer\data');
  MigrationPage.SubCaptionLabel.Caption := '旧数据位置：' + MigrationSource;
end;

procedure InitializeWizard;
begin
  if IsAdminInstallMode then
    RegQueryStringValue(HKLM64, '{#AppKey}', 'Inno Setup: App Path', PreviousDir)
  else
    RegQueryStringValue(HKCU64, '{#AppKey}', 'Inno Setup: App Path', PreviousDir);
  MigrationPage := CreateInputOptionPage(wpSelectDir, '迁移个人数据',
    '是否迁移旧版的消息和设置？',
    '迁移并校验成功后，删除已迁移的旧数据。目标 data 已有数据时不会覆盖。', False, False);
  MigrationPage.Add('迁移旧数据，成功后删除源数据');
  MigrationPage.Values[0] := ExpandConstant('{param:MIGRATEDATA|0}') = '1';
  WizardForm.DirEdit.OnExit := @DirChanged;
  DirChanged(nil);
  UpdateMigrationSource;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpSelectDir then begin
    DirChanged(nil);
    if HasReparseParent(WizardDirValue) then begin
      MsgBox('安装位置不能包含目录链接或联接，请选择实际文件夹。', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    UpdateMigrationSource;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  DirChanged(nil);
  UpdateMigrationSource;
  if HasReparseParent(WizardDirValue) then
    Result := '安装位置不能包含目录链接或联接，请选择实际文件夹。';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = MigrationPage.ID) and
    (not DirExists(MigrationSource) or
     (CompareText(RemoveBackslashUnlessRoot(MigrationSource), AddBackslash(WizardDirValue) + 'data') = 0));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
  ErrorText: AnsiString;
  StartupCommand: String;
begin
  if CurStep = ssPostInstall then begin
    SaveStringToFile(ExpandConstant('{app}\.vtt-install'), '{#AppGuid}', False);
    if not ShouldSkipPage(MigrationPage.ID) and not MigrationPage.Values[0] then
      SaveStringToFile(ExpandConstant('{app}\.vtt-migration-skipped'), '1', False);
    if MigrationPage.Values[0] and not ShouldSkipPage(MigrationPage.ID) then begin
      if not Exec(ExpandConstant('{app}\ValorantToxicTamer.exe'),
        '--migrate-data "' + MigrationSource + '" "' + ExpandConstant('{app}\data') + '"',
        ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then begin
        ErrorText := '数据迁移未完成，未覆盖已有数据。请检查源数据后重试。';
        LoadStringFromFile(ExpandConstant('{app}\migration-error.txt'), ErrorText);
        MsgBox(UTF8Decode(ErrorText), mbError, MB_OK);
      end;
    end;
#ifndef TestBuild
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run',
      'ValorantToxicTamer', StartupCommand) then
      RegWriteStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run',
        'ValorantToxicTamer', '"' + ExpandConstant('{app}\ValorantToxicTamer.exe') + '"');
#endif
  end;
end;

function InitializeUninstall: Boolean;
var
  Form: TSetupForm;
  DeleteOption, KeepOption: TNewRadioButton;
  LabelText: TNewStaticText;
  Button: TNewButton;
  Marker: AnsiString;
begin
  Result := False;
  DeletePersonalData := False;
  if HasReparseParent(ExpandConstant('{app}')) or
     (CompareText(ExtractFileName(ExpandConstant('{app}')), 'ValorantToxicTamer') <> 0) or
     not LoadStringFromFile(ExpandConstant('{app}\.vtt-install'), Marker) or
     (Marker <> '{#AppGuid}') then begin
    MsgBox('无法确认软件安装目录，已停止卸载以避免误删。', mbError, MB_OK);
    Exit;
  end;
  if UninstallSilent then begin
    if ExpandConstant('{param:KEEPDATA|}') = '1' then Result := True
    else if ExpandConstant('{param:KEEPDATA|}') = '0' then begin
      DeletePersonalData := True;
      Result := True;
    end;
    Exit;
  end;
  Form := CreateCustomForm(ScaleX(520), ScaleY(255), False, True);
  try
    Form.Caption := '卸载 ValorantToxicTamer';
    Form.ClientWidth := ScaleX(520);
    Form.ClientHeight := ScaleY(255);
    LabelText := TNewStaticText.Create(Form);
    LabelText.Parent := Form;
    LabelText.SetBounds(ScaleX(20), ScaleY(16), ScaleX(480), ScaleY(85));
    LabelText.AutoSize := False;
    LabelText.WordWrap := True;
    LabelText.Caption := '卸载位置：' + ExpandConstant('{app}') + #13#10#13#10 +
      '选择“不保留个人数据”会删除整个安装目录，包括您手动放入的其他文件。';
    DeleteOption := TNewRadioButton.Create(Form);
    DeleteOption.Parent := Form;
    DeleteOption.SetBounds(ScaleX(20), ScaleY(115), ScaleX(480), ScaleY(25));
    DeleteOption.Caption := '不保留个人数据（删除整个安装目录）';
    DeleteOption.Checked := True;
    KeepOption := TNewRadioButton.Create(Form);
    KeepOption.Parent := Form;
    KeepOption.SetBounds(ScaleX(20), ScaleY(150), ScaleX(480), ScaleY(25));
    KeepOption.Caption := '保留个人数据（留下 data 文件夹）';
    Button := TNewButton.Create(Form);
    Button.Parent := Form;
    Button.SetBounds(ScaleX(300), ScaleY(205), ScaleX(90), ScaleY(28));
    Button.Caption := '继续卸载';
    Button.ModalResult := mrOK;
    Button := TNewButton.Create(Form);
    Button.Parent := Form;
    Button.SetBounds(ScaleX(405), ScaleY(205), ScaleX(90), ScaleY(28));
    Button.Caption := '取消';
    Button.ModalResult := mrCancel;
    Button.Cancel := True;
    Button.Default := True;
    Result := Form.ShowModal = mrOK;
    DeletePersonalData := Result and DeleteOption.Checked;
  finally
    Form.Free;
  end;
end;

function RemoveTreeWithoutFollowingLinks(const Directory: String): Boolean;
var
  Find: TFindRec;
  Path: String;
begin
  Result := True;
  if FindFirst(AddBackslash(Directory) + '*', Find) then begin
    try
      repeat
        if (Find.Name <> '.') and (Find.Name <> '..') then begin
          Path := AddBackslash(Directory) + Find.Name;
          if (Find.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then begin
            if (Find.Attributes and $400) <> 0 then begin
              if not RemoveDir(Path) then Result := False;
            end else if not RemoveTreeWithoutFollowingLinks(Path) then Result := False;
          end else begin
            if (Find.Attributes and $1) <> 0 then
              SetFileAttributesW(Path, Find.Attributes and not $1);
            if not DeleteFile(Path) then Result := False;
          end;
        end;
      until not FindNext(Find);
    finally
      FindClose(Find);
    end;
  end;
  if not RemoveDir(Directory) then Result := False;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var Command: String;
begin
  if CurUninstallStep = usPostUninstall then begin
#ifndef TestBuild
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run',
      'ValorantToxicTamer', Command) and
      (Pos(Lowercase(AddBackslash(ExpandConstant('{app}'))), Lowercase(Command)) > 0) then
      RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'ValorantToxicTamer');
#endif
    if DeletePersonalData then begin
      if HasReparseParent(ExpandConstant('{app}')) or
         not RemoveTreeWithoutFollowingLinks(ExpandConstant('{app}')) then
        MsgBox('部分文件无法删除，请退出占用程序后检查安装目录。', mbError, MB_OK);
    end else begin
      DeleteFile(ExpandConstant('{app}\.vtt-install'));
      DeleteFile(ExpandConstant('{app}\.vtt-migration-skipped'));
      DeleteFile(ExpandConstant('{app}\migration-error.txt'));
    end;
  end;
end;
