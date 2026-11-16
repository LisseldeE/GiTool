#define MyAppName "GiTool"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0.0"
#endif
#define MyAppPublisher "Lisselde_E"
#define MyAppExeName "GiTool.exe"
#ifndef MyAppSrcDir
  #define MyAppSrcDir "..\..\..\nuitka\dist\GiTool.dist"
#endif
#ifndef MyOutputDir
  #define MyOutputDir "..\..\..\nuitka\dist"
#endif
#ifndef MyLicenseFile
  #define MyLicenseFile "..\..\..\LICENSE"
#endif
#ifndef MySetupIcon
  #define MySetupIcon "..\..\..\icon.ico"
#endif
#define MyAppId "{{3A43697A-9F5F-4A8E-B296-2FD2ED4C3B27}"
#define MyAppIdKey "{3A43697A-9F5F-4A8E-B296-2FD2ED4C3B27}_is1"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoDescription={#MyAppName} 安装程序
VersionInfoOriginalFilename=GiTool_Setup.exe
DefaultDirName={autopf}\GiTool
UsePreviousAppDir=yes
UsePreviousTasks=no
UsePreviousGroup=no
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile={#MyLicenseFile}
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
PrivilegesRequired=lowest
OutputDir={#MyOutputDir}
OutputBaseFilename=GiTool_Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

SetupIconFile={#MySetupIcon}

ArchitecturesAllowed=x64compatible

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.CreateDesktopIcon=Create a desktop shortcut
english.AdditionalIcons=Additional shortcuts:
english.LaunchProgram=Run %1
chinesesimp.CreateDesktopIcon=创建桌面快捷方式
chinesesimp.AdditionalIcons=附加快捷方式:
chinesesimp.LaunchProgram=运行 %1
english.OldUninstallFailed=Failed to remove the old version. Setup stopped to avoid mixing old and new files. Please close any running instance of the app and run this installer again.
chinesesimp.OldUninstallFailed=卸载旧版本失败，安装已中止以避免新旧文件混用。请关闭正在运行的程序后重新运行本安装程序。

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#MyAppSrcDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall

[Code]
const
  UninstallParams = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART';

var
  PreviousDir: String;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpSelectDir) and (PreviousDir = '') then
    PreviousDir := RemoveBackslash(WizardForm.DirEdit.Text);
end;

function QueryUninstaller(const RootKey: Integer; const SubKey: String): String;
var
  Value: String;
  P: Integer;
begin
  Result := '';
  if not RegQueryStringValue(RootKey, SubKey, 'UninstallString', Value) then Exit;
  Value := Trim(Value);
  if (Length(Value) > 1) and (Value[1] = '"') then
  begin
    P := Pos('"', Copy(Value, 2, Length(Value) - 1));
    if P > 0 then Value := Copy(Value, 2, P - 1);
  end
  else
  begin
    P := Pos(' ', Value);
    if P > 0 then Value := Copy(Value, 1, P - 1);
  end;
  Result := Value;
end;

function FindUninstallerInDir(const Dir: String): String;
var
  Candidate: String;
  I: Integer;
begin
  Result := '';
  for I := 0 to 99 do
  begin
    Candidate := Dir + '\unins' + Format('%.3d', [I]) + '.exe';
    if FileExists(Candidate) then Result := Candidate;
  end;
end;

function QueryAppUninstaller(const AppKey: String): String;
var
  Key: String;
begin
  Key := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + AppKey;
  Result := QueryUninstaller(HKCU, Key);
  if (Result = '') or not FileExists(Result) then
    Result := QueryUninstaller(HKLM, Key);
  if (Result = '') or not FileExists(Result) then
    Result := QueryUninstaller(HKLM32, Key);
end;

function FindUninstaller(const OldDir: String): String;
begin
  Result := QueryAppUninstaller('{#MyAppIdKey}');
  if (Result = '') or not FileExists(Result) then
    Result := FindUninstallerInDir(OldDir);
end;

function RemoveInstallation(const Dir, Uninstaller: String): Boolean;
var
  ResultCode, WaitCount: Integer;
begin
  Result := False;
  if not Exec(Uninstaller, UninstallParams, '', SW_HIDE, ewWaitUntilTerminated,
              ResultCode) then Exit;
  if ResultCode <> 0 then Exit;
  WaitCount := 0;
  while FileExists(Dir + '\{#MyAppExeName}') do
  begin
    Sleep(250);
    WaitCount := WaitCount + 1;
    if WaitCount >= 40 then Exit;
  end;
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  OldDir, Uninstaller: String;
  ResultCode: Integer;
begin
  Result := '';
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#MyAppExeName}', '',
       SW_HIDE, ewWaitUntilTerminated, ResultCode);

  if PreviousDir <> '' then
    OldDir := PreviousDir
  else
    OldDir := RemoveBackslash(ExpandConstant('{app}'));
  if ExtractFileName(OldDir) = '' then Exit;

  Uninstaller := FindUninstaller(OldDir);
  if (Uninstaller <> '') and
     FileExists(ExtractFilePath(Uninstaller) + '{#MyAppExeName}') then
  begin
    if not RemoveInstallation(RemoveBackslash(ExtractFilePath(Uninstaller)),
                              Uninstaller) then
      Result := ExpandConstant('{cm:OldUninstallFailed}');
  end;
end;

