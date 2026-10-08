"""影片下載器。

介面：ui/index.html（pywebview + WebView2 顯示）
下載：core.py（yt-dlp）
打包：packaging/build.ps1（PyInstaller + Inno Setup）
"""

import importlib.machinery
import json
import os
import shutil
import subprocess
import sys

APP_NAME = "VideoDownloader"
APP_VERSION = "1.0.0"

# 打包後（PyInstaller）與直接執行 .py 時，檔案位置不同
FROZEN = getattr(sys, "frozen", False)
APP_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))
RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)  # ui、bin（ffmpeg / deno）所在
# 免安裝版旁邊會有 portable.txt：設定存在程式資料夾；安裝版存在 %APPDATA%（Program Files 不能寫入）
PORTABLE = FROZEN and os.path.exists(os.path.join(APP_DIR, "portable.txt"))
DATA_DIR = APP_DIR if (PORTABLE or not FROZEN) else os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME)
os.makedirs(DATA_DIR, exist_ok=True)

# 沒有主控台（pythonw / 打包後）時，把輸出導到檔案，避免寫入時出錯，也方便除錯
if sys.stdout is None or sys.stderr is None:
    sys.stdout = sys.stderr = open(os.path.join(DATA_DIR, "error.log"), "a", encoding="utf-8", buffering=1)

# 打包內附的 ffmpeg、deno
_BIN = os.path.join(RES_DIR, "bin")
if os.path.isdir(_BIN):
    os.environ["PATH"] = _BIN + os.pathsep + os.environ.get("PATH", "")

# 打包後無法用 pip 更新 yt-dlp：改成下載官方的 yt-dlp（zip 格式）放在資料夾，啟動時優先載入它
YTDLP_ZIP = os.path.join(DATA_DIR, "yt-dlp.zip")


class _YtdlpOverride:
    """讓 import yt_dlp 先找 YTDLP_ZIP，而不是打包在程式裡的舊版。"""

    def find_spec(self, name, path=None, target=None):
        # 子模組也要從 zip 載入（path 是上層套件在 zip 裡的路徑），否則會新舊版混用
        if name == "yt_dlp" or name.startswith("yt_dlp."):
            return importlib.machinery.PathFinder.find_spec(name, [YTDLP_ZIP] if name == "yt_dlp" else path)
        return None


if FROZEN and os.path.exists(YTDLP_ZIP):
    sys.meta_path.insert(0, _YtdlpOverride())

try:
    import webview
    import yt_dlp  # noqa: F401
except ImportError:
    if FROZEN:
        raise
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "pywebview", "yt-dlp[default]", "deno"])
    import webview

import core

SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
DEFAULT_SETTINGS = {
    "outdir": os.path.join(os.path.expanduser("~"), "Downloads"),
    "playlist_full": False,  # 網址同時含影片與清單時，是否整份清單都下載
    "subs": False,
    "browser": "",
}


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            s.update({k: v for k, v in json.load(f).items() if k in DEFAULT_SETTINGS})
    except (OSError, ValueError):
        pass
    return s


def clipboard_text():
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(ptr) if ptr else ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def round_corners(form):
    """Windows 11 的圓角與深色外框（舊版 Windows 會自動忽略）。"""
    import ctypes
    from ctypes import wintypes

    hwnd = wintypes.HWND(form.Handle.ToInt64())
    for attr, value in ((33, 2), (20, 1)):  # 圓角、深色模式
        v = ctypes.c_int(value)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))


class Api:
    """給網頁介面呼叫的方法（底線開頭的屬性不會暴露給 JS）。"""

    def __init__(self):
        self._window = None
        self._maximized = False
        self._dl = core.Downloader(self._emit)

    def _emit(self, event, data):
        w = self._window
        if not w:
            return
        js = f"window.onEvent({json.dumps(event)}, {json.dumps(data, ensure_ascii=False)})"
        try:
            w.run_js(js)
        except Exception:  # noqa: BLE001 — 視窗關閉中等情況，忽略即可
            pass

    # ---------- 設定 ----------
    def get_config(self):
        return {
            "version": core.ytdlp_version(),
            "has_ffmpeg": core.HAS_FFMPEG,
            "video": [{k: q[k] for k in ("id", "label", "hint")} for q in core.VIDEO_QUALITIES],
            "audio": [{k: q[k] for k in ("id", "label", "hint")} for q in core.AUDIO_QUALITIES],
            "browsers": core.BROWSERS,
            "settings": load_settings(),
        }

    def save_settings(self, settings):
        s = load_settings()
        s.update({k: v for k, v in settings.items() if k in DEFAULT_SETTINGS})
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)

    # ---------- 下載 ----------
    def start(self, urls, params):
        self._dl.add(urls, params)

    def cancel(self):
        self._dl.cancel()

    def update_ytdlp(self):
        ok, msg, out = core.update_ytdlp(YTDLP_ZIP if FROZEN else None)
        self._emit("log", {"level": "info" if ok else "error", "text": out})
        return {"ok": ok, "msg": msg}

    # ---------- 系統 ----------
    def paste(self):
        try:
            return clipboard_text()
        except Exception:  # noqa: BLE001
            return ""

    def choose_dir(self, current):
        folder = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        start = current if current and os.path.isdir(current) else ""
        result = self._window.create_file_dialog(folder, directory=start)
        return result[0] if result else None

    def open_path(self, path):
        if path and os.path.exists(path):
            os.startfile(path)

    def reveal(self, path):
        if path and os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif path:
            self.open_path(os.path.dirname(path))

    # ---------- 視窗 ----------
    def minimize(self):
        self._window.minimize()

    def toggle_maximize(self):
        if self._maximized:
            self._window.restore()
        else:
            self._window.maximize()
        self._maximized = not self._maximized

    def close(self):
        self._dl.cancel()
        self._window.destroy()


def selftest(url, outdir, kind):
    """不開視窗，直接下載一次並把結果寫成 selftest.json（給打包後驗證用）。"""
    import threading

    done = threading.Event()
    events = []

    def emit(event, data):
        if event != "log":
            events.append([event, data])
        if event == "idle":
            done.set()

    os.makedirs(outdir, exist_ok=True)
    core.Downloader(emit).add([url], {"type": kind, "quality": "best" if kind == "mp4" else "320", "outdir": outdir})
    done.wait(600)
    result = {
        "app": APP_VERSION, "frozen": FROZEN, "portable": PORTABLE, "data_dir": DATA_DIR,
        "ytdlp": core.ytdlp_version(), "ytdlp_from": os.path.dirname(core.yt_dlp.__file__),
        "ffmpeg": shutil.which("ffmpeg"), "deno": shutil.which("deno"),
        "last_events": events[-3:], "files": sorted(os.listdir(outdir)),
    }
    with open(os.path.join(outdir, "selftest.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "mp4")
        return

    api = Api()
    api._window = webview.create_window(
        "影片下載器",
        url=os.path.join(RES_DIR, "ui", "index.html"),
        js_api=api,
        width=1120,
        height=780,
        min_size=(900, 640),
        frameless=True,
        easy_drag=False,
        background_color="#0a0a0a",
    )

    def on_loaded(window):
        try:
            round_corners(window.native)
        except Exception:  # noqa: BLE001 — 只是外觀，失敗不影響使用
            pass

    api._window.events.loaded += on_loaded
    webview.start()


if __name__ == "__main__":
    main()
