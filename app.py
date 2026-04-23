import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import traceback
import uuid
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
import yt_dlp


def _resource_path(relative: str) -> str:
    """Return absolute path to a resource — works in dev and inside a PyInstaller .exe."""
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, relative)


def _app_dir() -> Path:
    """Return a writable directory next to the executable (or CWD in dev)."""
    if getattr(sys, "frozen", False):          # running as PyInstaller .exe
        return Path(sys.executable).parent
    return Path(os.path.abspath("."))


app = Flask(
    __name__,
    template_folder=_resource_path("templates"),
)
CORS(app)

# Downloads folder: writable location next to the .exe (or CWD when developing)
DOWNLOAD_DIR = _app_dir() / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Track active downloads
active_downloads = {}


@app.route("/")
def index():
    try:
        return render_template("index.html")
    except Exception:
        return f"<pre>{traceback.format_exc()}</pre>", 500


@app.errorhandler(500)
def internal_error(error):
    return f"<h1>Internal Server Error</h1><pre>{traceback.format_exc()}</pre>", 500

FORMATS = {
    "mp3": {
        "ext": "mp3",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "format": "bestaudio/best",
    },
    "mp4": {
        "ext": "mp4",
        "format": "best",
    },
    "webm": {
        "ext": "webm",
        "format": "best",
    },
    "ogg": {
        "ext": "ogg",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "vorbis",
        }],
        "format": "bestaudio/best",
    },
    "wav": {
        "ext": "wav",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
        }],
        "format": "bestaudio/best",
    },
    "m4a": {
        "ext": "m4a",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "m4a",
        }],
        "format": "bestaudio[ext=m4a]/bestaudio/best",
    },
}

# Browsers to try cookies from, in priority order (Windows)
# Edge is first because its cookie DB is less likely to be locked when Chrome is running.
BROWSERS_TO_TRY = ["edge", "chrome", "firefox", "brave", "opera", "chromium"]

# Default paths for the cookies database on Windows (for pre-copy workaround)
BROWSER_COOKIE_PATHS = {
    "chrome": Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data" / "Default" / "Network" / "Cookies",
    "edge"  : Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "User Data" / "Default" / "Network" / "Cookies",
    "brave" : Path(os.environ.get("LOCALAPPDATA", "")) / "BraveSoftware" / "Brave-Browser" / "User Data" / "Default" / "Network" / "Cookies",
    "opera" : Path(os.environ.get("APPDATA", "")) / "Opera Software" / "Opera Stable" / "Network" / "Cookies",
    "chromium": Path(os.environ.get("LOCALAPPDATA", "")) / "Chromium" / "User Data" / "Default" / "Network" / "Cookies",
}

# Realistic browser User-Agent to reduce bot-detection blocks
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def _copy_locked_db(db_path: Path) -> str | None:
    """
    Try to make a readable copy of a locked SQLite database (e.g. Chrome Cookies).
    On Windows, Chromium-based browsers lock the file while running.
    We open it with SQLite's immutable URI mode (read-only, ignores lock)
    and dump every table into a fresh in-memory DB saved to a temp file.
    Returns path to the temp copy, or None if copy fails.
    """
    if not db_path.exists():
        return None
    tmp = tempfile.NamedTemporaryFile(suffix="_cookies.db", delete=False)
    tmp_path = tmp.name
    tmp.close()
    try:
        # Try plain copy first (works when browser is closed or not locking)
        shutil.copy2(str(db_path), tmp_path)
        return tmp_path
    except Exception:
        pass
    try:
        # Fallback: use SQLite immutable URI — bypasses shared-cache lock
        src_uri = f"file:{db_path.as_posix()}?immutable=1"
        src_conn = sqlite3.connect(src_uri, uri=True)
        dst_conn = sqlite3.connect(tmp_path)
        with dst_conn:
            for line in src_conn.iterdump():
                try:
                    dst_conn.execute(line)
                except sqlite3.Error:
                    pass
        src_conn.close()
        dst_conn.close()
        return tmp_path
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return None


def build_ydl_opts(fmt_config: dict, output_template: str, progress_hook,
                   cookies_from_browser=None, cookiefile: str | None = None) -> dict:
    """Build a yt-dlp options dict, optionally attaching browser cookies."""
    opts = {
        "outtmpl": output_template,
        "format": fmt_config["format"],
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "http_headers": {
            "User-Agent": USER_AGENT,
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        },
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
    }

    if fmt_config.get("ext") in ("mp4", "webm"):
        opts["merge_output_format"] = fmt_config["ext"]

    if "postprocessors" in fmt_config:
        opts["postprocessors"] = fmt_config["postprocessors"]

    if cookiefile:
        # Explicit cookies.txt file — most reliable, bypasses any browser lock
        opts["cookiefile"] = cookiefile
    elif cookies_from_browser:
        # Tuple form: (browser_name,) — profile/keyring/container all left as defaults
        opts["cookiesfrombrowser"] = (cookies_from_browser,)

    return opts


def _needs_auth(error_msg: str) -> bool:
    keywords = ["sign in", "login", "age", "private", "members", "cookie", "confirm your age"]
    return any(kw in error_msg.lower() for kw in keywords)


def _friendly_error(raw: str) -> str:
    """Convert a raw yt-dlp error into user-friendly Portuguese."""
    lower = raw.lower()
    if "sign in" in lower or "login" in lower:
        return (
            "O YouTube exige que você esteja logado para acessar este vídeo. "
            "Faça login no YouTube no seu navegador (Chrome ou Edge) e tente novamente."
        )
    if "age" in lower or "confirm your age" in lower:
        return (
            "Este vídeo tem restrição de idade. "
            "Faça login no YouTube no seu navegador e tente novamente."
        )
    if "private" in lower:
        return "Este vídeo é privado e não pode ser baixado."
    if "members" in lower:
        return "Este vídeo é exclusivo para membros do canal."
    if "unavailable" in lower or "not available" in lower:
        return "Vídeo indisponível ou já foi removido do YouTube."
    if "ffmpeg" in lower:
        return (
            "FFmpeg não encontrado. Instale o FFmpeg e adicione-o ao PATH "
            "do sistema para converter áudio."
        )
    if any(k in lower for k in ("urlopen", "network", "connection refused", "timed out")):
        return "Erro de rede. Verifique sua conexão com a internet."
    if "could not copy" in lower or "cookies database" in lower or "could not find" in lower:
        return (
            "Não foi possível ler os cookies do navegador (banco de dados bloqueado pelo Chrome). "
            "Feche o Chrome/Edge completamente e tente novamente, "
            "ou use a opção de arquivo cookies.txt."
        )
    # Strip common prefixes and return as-is
    return raw.replace("ERROR: ", "").replace("[youtube]", "").strip()


def do_download(task_id: str, url: str, fmt: str, cookiefile: str | None = None):
    tmp_cookie_copies: list[str] = []  # temp files to clean up at the end
    try:
        active_downloads[task_id]["status"] = "downloading"
        active_downloads[task_id]["progress"] = 0

        fmt_config = FORMATS[fmt]
        output_template = str(DOWNLOAD_DIR / f"{task_id}.%(ext)s")

        def progress_hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)
                if total > 0:
                    pct = int(downloaded / total * 100)
                    active_downloads[task_id]["progress"] = pct
            elif d["status"] == "finished":
                active_downloads[task_id]["progress"] = 100

        info = None
        last_error = None

        # ── Strategy 0: automatic or user-supplied cookies.txt ─────────────
        # Check for cookies.txt in the app directory if not explicitly provided
        if not cookiefile:
            auto_cookies = _app_dir() / "cookies.txt"
            if auto_cookies.exists():
                cookiefile = str(auto_cookies)
                print(f"DEBUG: Detectado arquivo de cookies em: {cookiefile}")

        if cookiefile and Path(cookiefile).exists():
            print(f"DEBUG: Tentando download com cookies: {cookiefile}")
            try:
                opts = build_ydl_opts(fmt_config, output_template, progress_hook,
                                      cookiefile=cookiefile)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
            except yt_dlp.utils.DownloadError as exc:
                last_error = str(exc)
                print(f"DEBUG: Erro Strategy 0 (cookies): {last_error}")
                if not _needs_auth(last_error):
                    active_downloads[task_id]["status"] = "error"
                    active_downloads[task_id]["error"] = _friendly_error(last_error)
                    return
                # fall through to browser-cookie strategies below

        # ── Strategy 1: no cookies (works for most public videos) ────────────
        if info is None:
            try:
                opts = build_ydl_opts(fmt_config, output_template, progress_hook)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)

            except yt_dlp.utils.DownloadError as exc:
                last_error = str(exc)

                if not _needs_auth(last_error):
                    active_downloads[task_id]["status"] = "error"
                    active_downloads[task_id]["error"] = _friendly_error(last_error)
                    return

                # ── Strategy 2: browser cookies with pre-copy workaround ─────
                active_downloads[task_id]["progress"] = 0
                auth_error = last_error

                for browser in BROWSERS_TO_TRY:
                    # Pre-copy the cookies DB to bypass Chrome's file lock
                    db_path = BROWSER_COOKIE_PATHS.get(browser)
                    if db_path and db_path.exists():
                        tmp_copy = _copy_locked_db(db_path)
                        if tmp_copy:
                            tmp_cookie_copies.append(tmp_copy)

                    try:
                        opts = build_ydl_opts(
                            fmt_config, output_template, progress_hook,
                            cookies_from_browser=browser,
                        )
                        with yt_dlp.YoutubeDL(opts) as ydl:
                            info = ydl.extract_info(url, download=True)
                        last_error = None  # success
                        break
                    except Exception as be:
                        err_str = str(be)
                        _lower = err_str.lower()
                        # Skip browsers not installed on this machine
                        if ("could not find" in _lower or "no such file" in _lower
                                or "cookies database" in _lower) and "could not copy" not in _lower:
                            continue
                        auth_error = err_str
                        last_error = err_str
                        continue

                if last_error:
                    active_downloads[task_id]["status"] = "error"
                    active_downloads[task_id]["error"] = _friendly_error(auth_error)
                    return

        # ── Locate the downloaded file ────────────────────────────────────────
        title = sanitize_filename(info.get("title", "video"))
        downloaded_file = None
        for f in DOWNLOAD_DIR.iterdir():
            if f.stem == task_id:
                downloaded_file = f
                break

        if downloaded_file and downloaded_file.exists():
            active_downloads[task_id]["status"] = "done"
            active_downloads[task_id]["filename"] = downloaded_file.name
            active_downloads[task_id]["title"] = title
            active_downloads[task_id]["progress"] = 100
        else:
            active_downloads[task_id]["status"] = "error"
            active_downloads[task_id]["error"] = "Arquivo não encontrado após o download."

    except Exception as exc:
        active_downloads[task_id]["status"] = "error"
        active_downloads[task_id]["error"] = _friendly_error(str(exc))
    finally:
        # Clean up any temporary cookie DB copies we made
        for tmp in tmp_cookie_copies:
            try:
                os.unlink(tmp)
            except Exception:
                pass

@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.get_json()
    url = (data.get("url") or "").strip()
    fmt = (data.get("format") or "mp4").lower()

    if not url:
        return jsonify({"error": "URL não informada."}), 400
    if fmt not in FORMATS:
        return jsonify({"error": f"Formato '{fmt}' não suportado."}), 400

    task_id = str(uuid.uuid4())
    active_downloads[task_id] = {
        "status": "queued",
        "progress": 0,
        "filename": None,
        "title": None,
        "error": None,
    }

    thread = threading.Thread(
        target=do_download, args=(task_id, url, fmt), daemon=True
    )
    thread.start()

    return jsonify({"task_id": task_id})


@app.route("/api/status/<task_id>")
def get_status(task_id):
    task = active_downloads.get(task_id)
    if not task:
        return jsonify({"error": "Task não encontrada."}), 404
    return jsonify(task)


@app.route("/api/file/<task_id>")
def download_file(task_id):
    task = active_downloads.get(task_id)
    if not task or task["status"] != "done":
        return jsonify({"error": "Arquivo não disponível."}), 404

    filepath = DOWNLOAD_DIR / task["filename"]
    if not filepath.exists():
        return jsonify({"error": "Arquivo removido do servidor."}), 404

    return send_file(
        filepath,
        as_attachment=True,
        download_name=f"{task['title']}.{filepath.suffix.lstrip('.')}",
    )


@app.route("/api/open-folder/<task_id>")
def open_folder(task_id):
    task = active_downloads.get(task_id)
    if not task or task["status"] != "done":
        return jsonify({"error": "Arquivo não disponível."}), 404

    filepath = (DOWNLOAD_DIR / task["filename"]).absolute()
    if not filepath.exists():
        return jsonify({"error": "Arquivo não encontrado."}), 404

    try:
        # Opens explorer and selects the file
        import subprocess
        subprocess.run(["explorer", "/select,", str(filepath)])
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # Dev mode: run with Flask's built-in server
    app.run(debug=True, port=5000)
