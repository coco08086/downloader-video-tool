# 影片下載器 打包腳本：在 pro\ 產生「安裝版」與「免安裝版」
# 用法：在 PowerShell 執行  .\packaging\build.ps1
# 需要：Python（已裝 pyinstaller、pywebview、yt-dlp[default]、deno、pillow）、Inno Setup 6
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Pkg = $PSScriptRoot
$Root = Split-Path $Pkg
$Out = Join-Path $Root "pro"
$Work = Join-Path $Pkg "_build"     # 中間檔（可以整個刪掉）
$Cache = Join-Path $Pkg "_cache"    # 下載過的 ffmpeg，避免每次重抓
$Version = (Select-String -Path "$Root\video_downloader.py" -Pattern 'APP_VERSION = "(.+)"').Matches[0].Groups[1].Value
$Iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { throw "找不到 Inno Setup 6（ISCC.exe），請先安裝：winget install JRSoftware.InnoSetup" }

function Step($msg) { Write-Host "`n== $msg ==" -ForegroundColor Cyan }

Step "版本 $Version"
New-Item -ItemType Directory -Force $Out, $Work, $Cache | Out-Null

Step "1/5 準備 ffmpeg 與 deno"
$ffZip = Join-Path $Cache "ffmpeg-win64-gpl-shared.zip"
if (-not (Test-Path $ffZip)) {
    Invoke-WebRequest "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl-shared.zip" -OutFile $ffZip
}
$ffDir = Join-Path $Work "ffmpeg"
Remove-Item -Recurse -Force $ffDir -ErrorAction SilentlyContinue
Expand-Archive $ffZip $ffDir
$ffBin = Get-ChildItem $ffDir -Recurse -Directory -Filter bin | Select-Object -First 1
$Bin = Join-Path $Work "bin"
Remove-Item -Recurse -Force $Bin -ErrorAction SilentlyContinue
New-Item -ItemType Directory $Bin | Out-Null
Copy-Item "$($ffBin.FullName)\ffmpeg.exe", "$($ffBin.FullName)\ffprobe.exe", "$($ffBin.FullName)\*.dll" $Bin   # 不需要 ffplay
Copy-Item (Get-ChildItem $ffDir -Recurse -Filter LICENSE.txt | Select-Object -First 1).FullName (Join-Path $Bin "FFMPEG_LICENSE.txt")
$deno = (Get-Command deno -ErrorAction Stop).Source
Copy-Item $deno (Join-Path $Bin "deno.exe")
& (Join-Path $Bin "ffmpeg.exe") -hide_banner -version | Select-Object -First 1
& (Join-Path $Bin "deno.exe") --version | Select-Object -First 1

Step "2/5 產生圖示"
python "$Pkg\make_icon.py"
if ($LASTEXITCODE) { throw "圖示產生失敗" }

Step "3/5 PyInstaller 打包"
$env:VD_BIN = $Bin
python -m PyInstaller --noconfirm --clean --log-level WARN --distpath "$Work\dist" --workpath "$Work\pyi" "$Pkg\VideoDownloader.spec"
if ($LASTEXITCODE) { throw "PyInstaller 失敗" }
$Dist = Join-Path $Work "dist\VideoDownloader"
Copy-Item "$Pkg\THIRD_PARTY_NOTICES.txt" $Dist

Step "4/5 免安裝版"
$name = "影片下載器_免安裝版_v$Version"
$stage = Join-Path $Work "portable\$name"
Remove-Item -Recurse -Force (Join-Path $Work "portable") -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $stage | Out-Null
Copy-Item "$Dist\*" $stage -Recurse
Set-Content (Join-Path $stage "portable.txt") -Encoding utf8 -Value @(
    "這個檔案代表「免安裝版」：設定、記錄與更新後的 yt-dlp 都會存在這個資料夾。",
    "刪掉這個檔案的話，程式會改把資料存在 %APPDATA%\VideoDownloader。",
    "",
    "開啟方式：執行 VideoDownloader.exe")
$zip = Join-Path $Out "$name.zip"
python -c "import shutil,sys; shutil.make_archive(sys.argv[1][:-4], 'zip', sys.argv[2], sys.argv[3])" $zip (Join-Path $Work "portable") $name
if ($LASTEXITCODE) { throw "壓縮免安裝版失敗" }

Step "5/5 安裝版"
& $Iscc /Q "/DAppVersion=$Version" "/DDistDir=$Dist" "/DOutDir=$Out" "$Pkg\installer.iss"
if ($LASTEXITCODE) { throw "Inno Setup 失敗" }

Step "完成"
Get-ChildItem $Out | Select-Object Name, @{ n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } } | Format-Table -AutoSize
