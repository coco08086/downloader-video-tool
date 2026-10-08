; Inno Setup 安裝檔設定（由 build.ps1 呼叫，DistDir / OutDir / AppVersion 由命令列傳入）
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef DistDir
  #define DistDir "_build\dist\VideoDownloader"
#endif
#ifndef OutDir
  #define OutDir "..\pro"
#endif
#define AppName "影片下載器"
#define AppExe "VideoDownloader.exe"

[Setup]
AppId={{8C2F4E61-7A3B-4D5E-9F10-2B6C8D4A1E37}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={autopf}\VideoDownloader
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; 預設只裝給目前使用者（不需要系統管理員權限），安裝時也可以改成裝給所有使用者
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#OutDir}
OutputBaseFilename=影片下載器_安裝版_v{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
; ultra64 的字典是 1 GB，32 位元的編譯器會記憶體不足；ultra（64 MB）已足夠
Compression=lzma2/ultra
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
CloseApplications=yes

[Languages]
Name: "cht"; MessagesFile: "ChineseTraditional.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\解除安裝 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
// 介面靠 Microsoft Edge WebView2 顯示。Windows 11 都有內建；少數 Windows 10 可能沒有，先提醒
function HasWebView2(): Boolean;
var
  V: String;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', V) or
    RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', V);
  Result := Result and (V <> '') and (V <> '0.0.0.0');
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not HasWebView2() then
    MsgBox('這台電腦似乎沒有安裝 Microsoft Edge WebView2 Runtime，程式介面可能無法顯示。' + #13#10 + #13#10 +
           '請到 https://go.microsoft.com/fwlink/p/?LinkId=2124703 下載安裝後再開啟程式。',
           mbInformation, MB_OK);
end;
