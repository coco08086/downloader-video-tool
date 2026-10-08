# PyInstaller 設定（由 build.ps1 呼叫）。產生資料夾版（onedir）：啟動快，也方便做安裝檔與免安裝版。
import os

from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
BIN = os.environ["VD_BIN"]  # ffmpeg、ffprobe（含 DLL）、deno 與授權檔，由 build.ps1 準備

a = Analysis(
    [os.path.join(ROOT, "video_downloader.py")],
    pathex=[ROOT],
    # DLL 當成資料原樣複製即可，不需要 PyInstaller 分析相依性
    datas=[(os.path.join(ROOT, "ui"), "ui"), (BIN, "bin")] + collect_data_files("yt_dlp_ejs"),
    hiddenimports=["yt_dlp_ejs"],
    excludes=["tkinter", "PIL", "numpy", "pandas", "matplotlib", "IPython", "pytest", "setuptools"],
    noarchive=False,
)
# PyInstaller 會分析 bin\ffmpeg.exe 的相依 DLL，把 ffmpeg 的 DLL 再複製一份到最外層（約 186 MB）。
# bin 裡已經有了，這份是重複的，移除。
FF_DLLS = {f.lower() for f in os.listdir(BIN) if f.lower().endswith(".dll")}
a.binaries = [b for b in a.binaries if not (os.path.dirname(b[0]) == "" and b[0].lower() in FF_DLLS)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoDownloader",
    icon=os.path.join(SPECPATH, "icon.ico"),
    version=os.path.join(SPECPATH, "version_info.txt"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="VideoDownloader", upx=False)
