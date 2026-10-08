"""下載核心：包裝 yt-dlp，透過 emit(event, data) 把進度回報給介面。

與介面無關，GUI（pywebview）或其他前端都可以共用。
"""

import collections
import glob
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from urllib.parse import parse_qs, urlparse

import yt_dlp
from yt_dlp.postprocessor import PostProcessor
from yt_dlp.utils import DownloadCancelled

HAS_FFMPEG = shutil.which("ffmpeg") is not None

VIDEO_QUALITIES = [
    {"id": "best", "label": "最高", "hint": "自動", "height": None},
    {"id": "4320", "label": "8K", "hint": "4320p", "height": 4320},
    {"id": "2160", "label": "4K", "hint": "2160p", "height": 2160},
    {"id": "1440", "label": "2K", "hint": "1440p", "height": 1440},
    {"id": "1080", "label": "1080p", "hint": "Full HD", "height": 1080},
    {"id": "720", "label": "720p", "hint": "HD", "height": 720},
    {"id": "480", "label": "480p", "hint": "SD", "height": 480},
    {"id": "360", "label": "360p", "hint": "低", "height": 360},
    {"id": "240", "label": "240p", "hint": "更低", "height": 240},
    {"id": "144", "label": "144p", "hint": "最低", "height": 144},
]

# q 為 ffmpeg 參數："0" = VBR 最高品質
AUDIO_QUALITIES = [
    {"id": "320", "label": "320", "hint": "kbps · 最高", "q": "320"},
    {"id": "vbr", "label": "VBR", "hint": "最佳 · 較小", "q": "0"},
    {"id": "256", "label": "256", "hint": "kbps", "q": "256"},
    {"id": "192", "label": "192", "hint": "kbps", "q": "192"},
    {"id": "160", "label": "160", "hint": "kbps", "q": "160"},
    {"id": "128", "label": "128", "hint": "kbps", "q": "128"},
    {"id": "96", "label": "96", "hint": "kbps", "q": "96"},
    {"id": "64", "label": "64", "hint": "kbps", "q": "64"},
]

BROWSERS = [
    {"id": "", "label": "不使用"},
    {"id": "chrome", "label": "Chrome"},
    {"id": "edge", "label": "Edge"},
    {"id": "firefox", "label": "Firefox"},
    {"id": "brave", "label": "Brave"},
    {"id": "opera", "label": "Opera"},
]

PP_LABELS = {
    "Merger": "合併影音中…",
    "FFmpegExtractAudio": "轉換 MP3 中…",
    "FFmpegEmbedSubtitle": "嵌入字幕中…",
    "FFmpegVideoRemuxer": "轉換封裝中…",
}

_VQ = {q["id"]: q for q in VIDEO_QUALITIES}
_AQ = {q["id"]: q for q in AUDIO_QUALITIES}

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def ytdlp_version():
    return yt_dlp.version.__version__


def _http_get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "VideoDownloader"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def update_ytdlp(zip_path=None):
    """更新 yt-dlp，回傳 (成功與否, 給使用者看的訊息, 詳細記錄)。

    zip_path 為 None（直接執行 .py）：用 pip 更新。
    否則（打包後的程式沒有 pip）：從 GitHub 下載官方 yt-dlp（本身就是 zip 格式的 Python 程式），
    驗證 SHA-256 後存到 zip_path，下次啟動時優先載入。
    """
    if zip_path is None:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]", "deno"],
            capture_output=True, text=True, creationflags=NO_WINDOW)
        ok = r.returncode == 0
        return ok, "更新完成，重新開啟程式即可套用" if ok else "更新失敗，請查看記錄", (r.stdout or r.stderr).strip()

    try:
        tag = json.loads(_http_get("https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest", 20))["tag_name"]
        if tag == ytdlp_version():
            return True, f"已經是最新版（{tag}）", f"yt-dlp {tag} 已是最新版"
        base = f"https://github.com/yt-dlp/yt-dlp/releases/download/{tag}/"
        data = _http_get(base + "yt-dlp")
        sums = _http_get(base + "SHA2-256SUMS", 20).decode()
        expected = next((ln.split()[0] for ln in sums.splitlines() if ln.split()[-1:] == ["yt-dlp"]), None)
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            return False, "下載的檔案驗證失敗，已放棄更新", f"SHA-256 不符：預期 {expected}，實際 {actual}"
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            z.getinfo("yt_dlp/__init__.py")  # 確認是可以載入的 yt-dlp
        os.makedirs(os.path.dirname(zip_path), exist_ok=True)
        tmp = zip_path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, zip_path)
        return True, f"已下載 yt-dlp {tag}，重新開啟程式即可套用", f"yt-dlp {tag} 已存到 {zip_path}（SHA-256 {actual}）"
    except Exception as e:  # noqa: BLE001 — 網路、GitHub 等各種錯誤都回報給使用者
        return False, "更新失敗，請查看記錄", f"更新 yt-dlp 失敗：{e}"


def fmt_bytes(n):
    if not n:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_time(sec):
    if sec is None:
        return ""
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


MIX_LIMIT = 25  # 直接貼 YouTube 合輯（Mix）網址時最多抓幾部，合輯沒有盡頭


def playlist_opts(url, full_playlist):
    """決定播放清單怎麼處理。

    網址同時指向「一部影片」和「清單」（例如 watch?v=…&list=…）時，預設只抓那部影片；
    純清單網址（playlist?list=…、頻道）一律整份下載。
    YouTube 自動產生的合輯／電台（list=RD…）永遠不整份下載。
    """
    q = parse_qs(urlparse(url).query)
    lst = (q.get("list") or [""])[0]
    if lst.startswith("RD"):
        return {"noplaylist": True, "playlistend": MIX_LIMIT}
    return {"noplaylist": not full_playlist}


def build_format(params):
    if params["type"] == "mp3":
        return "ba/b"
    h = _VQ.get(params.get("quality"), _VQ["best"])["height"]
    lim = f"[height<={h}]" if h else ""
    if not HAS_FFMPEG:
        # 沒有 ffmpeg 無法合併影音，只能抓已合併好的單一檔案
        return f"b{lim}/b"
    # 優先選 AAC 音軌（MP4 相容性最好），沒有再退而求其次
    return f"bv*{lim}+ba[ext=m4a]/bv*{lim}+ba/b{lim}/b"


class _BeforeDownload(PostProcessor):
    """格式選好、開始下載前呼叫，此時 info 含 requested_formats 等完整資訊。"""

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def run(self, info):
        self._callback(info)
        return [], info


class _Logger:
    def __init__(self, dl):
        self.dl = dl

    def debug(self, msg):
        if not msg.startswith(("[debug]", "[download]")):
            self.dl.emit("log", {"level": "info", "text": msg})

    def info(self, msg):
        self.debug(msg)

    def warning(self, msg):
        self.dl.emit("log", {"level": "warn", "text": msg})

    def error(self, msg):
        self.dl.emit("log", {"level": "error", "text": msg})
        self.dl._on_error(msg)


class Downloader:
    """依序處理下載工作；下載中也能繼續加入新網址。"""

    def __init__(self, emit):
        self.emit = emit
        self.lock = threading.Lock()
        self.jobs = collections.deque()
        self.worker = None
        self.cancel_flag = threading.Event()
        self.seq = 0
        self.stats = {"ok": 0, "fail": 0}
        # 目前工作的狀態（只在 worker 執行緒使用）
        self.placeholder = None
        self.items = {}
        self.cur_item = None
        self.last_error = ""
        self.last_emit = 0.0

    # ---------- 公開方法 ----------
    def add(self, urls, params):
        with self.lock:
            for url in urls:
                self.seq += 1
                key = f"job{self.seq}"
                self.jobs.append((key, url, dict(params)))
                self.emit("item", {"key": key, "title": url, "url": url, "state": "queued",
                                   "text": "排隊中", "kind": params["type"], "pct": 0})
            if self.worker is None:
                self.stats = {"ok": 0, "fail": 0}
                self.worker = threading.Thread(target=self._run, daemon=True)
                self.worker.start()

    def cancel(self):
        with self.lock:
            dropped = list(self.jobs)
            self.jobs.clear()
            busy = self.worker is not None
        for key, _, _ in dropped:
            self.emit("item", {"key": key, "state": "canceled", "text": "已取消"})
        if busy:
            self.cancel_flag.set()

    # ---------- worker ----------
    def _run(self):
        while True:
            with self.lock:
                if not self.jobs:
                    self.worker = None
                    break
                key, url, params = self.jobs.popleft()
            self.cancel_flag.clear()
            self._process(key, url, params)
        self.emit("idle", dict(self.stats))

    def _build_opts(self, url, params):
        audio = params["type"] == "mp3"
        opts = {
            "format": build_format(params),
            "outtmpl": os.path.join(params["outdir"], "%(title).150B [%(id)s].%(ext)s"),
            **playlist_opts(url, params.get("playlist_full", False)),
            "progress_hooks": [self._hook],
            "postprocessor_hooks": [self._pp_hook],
            "logger": _Logger(self),
            "noprogress": True,
            "ignoreerrors": True,  # 播放清單中單一影片失敗不中斷整個清單
            "windowsfilenames": True,
            "concurrent_fragment_downloads": 4,
            "retries": 10,
        }
        if audio and HAS_FFMPEG:
            q = _AQ.get(params.get("quality"), AUDIO_QUALITIES[0])["q"]
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio",
                                       "preferredcodec": "mp3", "preferredquality": q}]
        elif HAS_FFMPEG:
            opts["merge_output_format"] = "mp4"
        if params.get("subs"):
            opts.update(writesubtitles=True, subtitleslangs=["zh.*", "en.*"])
            if HAS_FFMPEG and not audio:
                opts.setdefault("postprocessors", []).append({"key": "FFmpegEmbedSubtitle"})
        if params.get("browser"):
            opts["cookiesfrombrowser"] = (params["browser"],)
        return opts

    def _run_ydl(self, url, params):
        try:
            os.makedirs(params["outdir"], exist_ok=True)
            with yt_dlp.YoutubeDL(self._build_opts(url, params)) as ydl:
                ydl.add_post_processor(_BeforeDownload(self._on_video), when="before_dl")
                ydl.download([url])
        except DownloadCancelled:
            pass
        except Exception as e:  # noqa: BLE001 — 任何錯誤都要回報給介面
            self._on_error(str(e))

    def _process(self, key, url, params):
        self.placeholder = key
        self.items = {}
        self.cur_item = None
        self.last_error = ""
        self.job_key = key
        self.kind = params["type"]
        self.emit("item", {"key": key, "state": "active", "text": "解析網址中…"})
        self._run_ydl(url, params)
        # 瀏覽器開著時 cookie 資料庫常被鎖住而讀不到；這時改用不登入的方式再試一次
        if (self.placeholder and params.get("browser") and "cookie" in self.last_error.lower()
                and not self.cancel_flag.is_set()):
            self.emit("toast", {"text": f"讀不到 {params['browser']} 的登入資料（瀏覽器開著時會被鎖住），改用不登入的方式下載"})
            self.emit("item", {"key": key, "text": "改用不登入的方式重試…"})
            self.last_error = ""
            self._run_ydl(url, dict(params, browser=""))

        canceled = self.cancel_flag.is_set()
        if self.placeholder:  # 一部影片都沒抓到
            state, text = ("canceled", "已取消") if canceled else ("error", self._short(self.last_error) or "找不到可下載的影片")
            self.emit("item", {"key": self.placeholder, "state": state, "text": text})
            if not canceled:
                self.stats["fail"] += 1
        for vkey, st in self.items.items():
            if canceled and st["state"] == "active":
                self._remove_partials(params["outdir"], vkey.split(":", 1)[1])
            if st["state"] in ("active", "processing"):
                st["state"] = "canceled" if canceled else "error"
                self.emit("item", {"key": vkey, "state": st["state"],
                                   "text": "已取消" if canceled else (self._short(self.last_error) or "失敗")})
                if not canceled:
                    self.stats["fail"] += 1

    @staticmethod
    def _remove_partials(outdir, vid):
        """取消時刪掉這部影片下載到一半的暫存檔。"""
        pattern = os.path.join(glob.escape(outdir), f"*[[]{glob.escape(vid)}[]]*")
        for f in glob.glob(pattern):
            if f.endswith((".part", ".ytdl")) or ".part-Frag" in f:
                try:
                    os.remove(f)
                except OSError:
                    pass

    @staticmethod
    def _short(msg):
        msg = msg.replace("ERROR: ", "").strip()
        if "] " in msg and msg.startswith("["):
            msg = msg.split(": ", 1)[-1] if ": " in msg else msg
        return msg[:160]

    def _on_error(self, msg):
        self.last_error = msg
        st = self.items.get(self.cur_item)
        if st and st["state"] in ("active", "processing"):
            st["state"] = "error"
            self.stats["fail"] += 1
            self.emit("item", {"key": self.cur_item, "state": "error", "text": self._short(msg)})

    def _vkey(self, info):
        return f"{self.job_key}:{info.get('id')}"

    def _on_video(self, info):
        vkey = self._vkey(info)
        fmts = info.get("requested_formats") or [info]
        sizes = [f.get("filesize") or f.get("filesize_approx") or 0 for f in fmts]
        self.items[vkey] = {
            "fmts": [f.get("format_id") for f in fmts],
            "sizes": sizes,
            "frac": [0.0] * len(fmts),
            "state": "active",
        }
        self.cur_item = vkey

        meta = []
        if info.get("uploader"):
            meta.append(info["uploader"])
        if self.kind == "mp4" and info.get("height"):
            meta.append(f"{info['height']}p")
        if info.get("duration"):
            meta.append(fmt_time(info["duration"]))
        total = sum(sizes)
        if total and all(sizes):
            meta.append(f"約 {fmt_bytes(total)}")

        replace, self.placeholder = self.placeholder, None
        self.emit("item", {
            "key": vkey, "replace": replace, "title": info.get("title") or info.get("id"),
            "thumb": info.get("thumbnail"), "meta": " · ".join(meta), "kind": self.kind,
            "state": "active", "pct": 0, "text": "開始下載…",
        })

    def _hook(self, d):
        if self.cancel_flag.is_set():
            raise DownloadCancelled("使用者取消")
        info = d.get("info_dict") or {}
        vkey = self._vkey(info)
        st = self.items.get(vkey)
        if not st:
            return
        fid = info.get("format_id")
        i = st["fmts"].index(fid) if fid in st["fmts"] else 0

        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            if total:
                st["sizes"][i] = total
                st["frac"][i] = min(done / total, 1.0)
            now = time.monotonic()
            if now - self.last_emit < 0.15:
                return
            self.last_emit = now
            parts = []
            if d.get("speed"):
                parts.append(f"{fmt_bytes(d['speed'])}/s")
            if d.get("eta") is not None:
                parts.append(f"剩 {fmt_time(d['eta'])}")
            if len(st["fmts"]) > 1:
                parts.append(f"串流 {i + 1}/{len(st['fmts'])}")
            self.emit("item", {"key": vkey, "pct": self._overall(st), "text": " · ".join(parts) or "下載中…"})
        elif d["status"] == "finished":
            st["frac"][i] = 1.0
            self.emit("item", {"key": vkey, "pct": self._overall(st)})

    @staticmethod
    def _overall(st):
        w = st["sizes"] if all(st["sizes"]) else [1] * len(st["sizes"])
        return round(sum(a * b for a, b in zip(w, st["frac"])) / sum(w) * 100, 1)

    def _pp_hook(self, d):
        info = d.get("info_dict") or {}
        vkey = self._vkey(info)
        st = self.items.get(vkey)
        if not st or st["state"] == "error":
            return
        name = d.get("postprocessor")
        if d["status"] == "started" and name in PP_LABELS:
            st["state"] = "processing"
            self.emit("item", {"key": vkey, "state": "processing", "pct": 100, "text": PP_LABELS[name]})
        elif d["status"] == "finished" and name == "MoveFiles":
            st["state"] = "done"
            self.stats["ok"] += 1
            path = info.get("filepath") or ""
            size = os.path.getsize(path) if path and os.path.exists(path) else 0
            self.emit("item", {"key": vkey, "state": "done", "pct": 100, "path": path,
                               "text": "已完成" + (f" · {fmt_bytes(size)}" if size else "")})
