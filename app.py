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

# Dynamically inject %APPDATA%/YouTubeDownloader/lib into sys.path before importing yt_dlp
import updater
updater.setup_dynamic_path()

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

# Concurrency controls and active cancellation track
downloads_lock = threading.Lock()
cancelled_tasks = set()

# Track active downloads
active_downloads = {}

from concurrent.futures import ThreadPoolExecutor
# Concurrency thread pool to limit active parallel downloads
download_executor = ThreadPoolExecutor(max_workers=3)

# Secure uuid API Isolation token
API_TOKEN = os.environ.get("API_TOKEN", "default-dev-token")

@app.before_request
def verify_api_token():
    # Bypasses static layouts and main frame requests
    if request.path in ("/", "/favicon.ico") or request.path.startswith("/static/"):
        return
    token = request.headers.get("X-API-Token")
    if token != API_TOKEN:
        return jsonify({"error": "Acesso não autorizado (Invalid API Nonce Token)."}), 403


def _get_db_path() -> Path:
    return updater.get_app_dir() / "db.sqlite"


def init_db():
    """Initialize the relational SQLite schema."""
    try:
        db_path = _get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS downloads (
                    task_id TEXT PRIMARY KEY,
                    url TEXT,
                    format TEXT,
                    resolution TEXT,
                    audio_bitrate TEXT,
                    status TEXT,
                    title TEXT,
                    filename TEXT,
                    progress INTEGER,
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
        conn.close()
    except Exception as e:
        print(f"DATABASE: Falha ao inicializar o banco: {e}")


def get_setting_from_db(key: str, default: str = "") -> str:
    """Get a setting key's value from the relational database."""
    try:
        db_path = _get_db_path()
        if not db_path.exists():
            return default
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else default
    except Exception as e:
        print(f"DATABASE: Falha ao obter setting {key}: {e}")
        return default


def save_setting_to_db(key: str, value: str):
    """Insert or replace a setting key's value in the relational database."""
    try:
        db_path = _get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        with conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        conn.close()
    except Exception as e:
        print(f"DATABASE: Falha ao salvar setting {key}: {e}")


def save_task_to_db(task_id: str, task: dict, url: str = "", fmt: str = "", resolution: str = "", audio_bitrate: str = ""):
    """Insert or replace download task metadata in local sqlite database."""
    try:
        db_path = _get_db_path()
        conn = sqlite3.connect(str(db_path))
        with conn:
            conn.execute("""
                INSERT OR REPLACE INTO downloads 
                (task_id, url, format, resolution, audio_bitrate, status, title, filename, progress, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task_id,
                url or task.get("url", ""),
                fmt or task.get("format", ""),
                resolution or task.get("resolution", ""),
                audio_bitrate or task.get("audio_bitrate", ""),
                task.get("status", ""),
                task.get("title", ""),
                task.get("filename", ""),
                task.get("progress", 0),
                task.get("error", "")
            ))
        conn.close()
    except Exception as e:
        print(f"DATABASE: Falha ao salvar no banco SQLite: {e}")


def load_tasks_from_db():
    """Load historical downloads in active downloads dictionary."""
    try:
        db_path = _get_db_path()
        if not db_path.exists():
            return
        
        init_db()
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT task_id, url, format, resolution, audio_bitrate, status, title, filename, progress, error FROM downloads ORDER BY created_at ASC")
        rows = cursor.fetchall()
        with downloads_lock:
            for row in rows:
                task_id, url, fmt, resolution, audio_bitrate, status, title, filename, progress, error = row
                # Remap dynamic queued/downloading to cancelled
                restored_status = status
                if status in ("downloading", "queued"):
                    restored_status = "cancelled"
                    
                active_downloads[task_id] = {
                    "status": restored_status,
                    "progress": progress if restored_status != "cancelled" else 0,
                    "filename": filename,
                    "title": title,
                    "error": error,
                    "url": url,
                    "format": fmt,
                    "resolution": resolution,
                    "audio_bitrate": audio_bitrate
                }
        conn.close()
    except Exception as e:
        print(f"DATABASE: Falha ao carregar historico do SQLite: {e}")


def _cleanup_partial_files(task_id: str):
    """
    Safely delete any partial or temporary files left in the download directory
    associated with the given task_id (useful for cleanups on error/cancel).
    """
    try:
        if not DOWNLOAD_DIR.exists():
            return
        prefix = f"{task_id}."
        for f in DOWNLOAD_DIR.iterdir():
            if f.name.startswith(prefix) or f.stem == task_id:
                try:
                    if f.is_file():
                        f.unlink()
                except Exception:
                    pass
    except Exception as e:
        print(f"DEBUG: Falha na limpeza atômica da task {task_id}: {e}")


def cleanup_old_temporary_files():
    """
    Run in a background thread on startup to purge any partial download remains
    (.part and .ytdl files) older than 24 hours in the downloads directory.
    """
    import time
    try:
        if not DOWNLOAD_DIR.exists():
            return
        now = time.time()
        cutoff = now - (24 * 3600)  # 24 hours
        
        for f in DOWNLOAD_DIR.iterdir():
            if f.is_file() and f.suffix in (".part", ".ytdl"):
                try:
                    st = f.stat()
                    if st.st_mtime < cutoff:
                        f.unlink()
                        print(f"CLEANER: Purged old partial file: {f.name}")
                except Exception:
                    pass
    except Exception as e:
        print(f"CLEANER: Falha ao rodar limpeza de temporários: {e}")


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


def _get_ffmpeg_path() -> str | None:
    """
    Return the path to the portable FFmpeg directory if found.
    Checks temp _MEIPASS (extracted binary) or local bin directory,
    falling back to None if not present (which relies on system's PATH).
    """
    local_bin = _resource_path("bin")
    if os.path.exists(local_bin):
        # On Windows, look for ffmpeg.exe
        exe_path = os.path.join(local_bin, "ffmpeg.exe")
        if os.path.exists(exe_path):
            return local_bin
        # Non-windows fallback
        unix_path = os.path.join(local_bin, "ffmpeg")
        if os.path.exists(unix_path):
            return local_bin
    return None


def build_ydl_opts(fmt_config: dict, output_template: str, progress_hook,
                   cookies_from_browser=None, cookiefile: str | None = None,
                   resolution: str | None = None, audio_bitrate: str | None = None) -> dict:
    """Build a yt-dlp options dict, optionally attaching browser cookies, quality settings, and FFmpeg path."""
    opts = {
        "outtmpl": output_template,
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "http_headers": {
            "User-Agent": USER_AGENT,
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        },
        "retries": 10,
        "fragment_retries": 15,
        "retry_sleep": "exponential",
        "extractor_retries": 5,
    }

    # 1. Configurar FFmpeg portátil se disponível
    ffmpeg_dir = _get_ffmpeg_path()
    has_ffmpeg = (ffmpeg_dir is not None) or (shutil.which("ffmpeg") is not None)
    
    if ffmpeg_dir:
        opts["ffmpeg_location"] = ffmpeg_dir
        print(f"DEBUG: Usando FFmpeg portátil localizado em: {ffmpeg_dir}")
    else:
        print(f"DEBUG: FFmpeg portátil não encontrado. Usando busca de PATH padrão (Tem FFmpeg no sistema: {has_ffmpeg})")

    # 2. Configurar formato dinâmico de áudio/vídeo
    ext = fmt_config.get("ext")
    
    if ext in ("mp4", "webm"):
        opts["merge_output_format"] = ext
        
        # Se selecionado resolução em alta qualidade e temos o FFmpeg ativo
        if resolution and resolution != "720" and has_ffmpeg:
            height = resolution
            if ext == "mp4":
                opts["format"] = f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}][ext=mp4]/best"
            else:
                opts["format"] = f"bestvideo[height<={height}][ext=webm]+bestaudio[ext=webm]/best[height<={height}][ext=webm]/best"
            print(f"DEBUG: Formato dinâmico de alta resolução configurado: {opts['format']}")
        else:
            if resolution and resolution != "720" and not has_ffmpeg:
                print("WARNING: Download em alta resolução solicitado mas FFmpeg não está disponível! Aplicando fallback para 720p.")
            opts["format"] = fmt_config["format"]
    else:
        opts["format"] = fmt_config["format"]

    # 3. Configurar bitrate de áudio dinâmico
    postprocessors = fmt_config.get("postprocessors")
    if postprocessors:
        import copy
        opts["postprocessors"] = copy.deepcopy(postprocessors)
        
        if ext == "mp3" and audio_bitrate:
            for pp in opts["postprocessors"]:
                if pp.get("key") == "FFmpegExtractAudio" and pp.get("preferredcodec") == "mp3":
                    pp["preferredquality"] = str(audio_bitrate)
                    print(f"DEBUG: Bitrate do MP3 configurado para: {audio_bitrate} kbps")
    
    if cookiefile:
        opts["cookiefile"] = cookiefile
    elif cookies_from_browser:
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


def do_download(task_id: str, url: str, fmt: str, cookiefile: str | None = None,
                resolution: str | None = None, audio_bitrate: str | None = None):
    tmp_cookie_copies: list[str] = []  # temp files to clean up at the end
    try:
        with downloads_lock:
            active_downloads[task_id]["status"] = "downloading"
            active_downloads[task_id]["progress"] = 0
            save_task_to_db(task_id, active_downloads[task_id])

        fmt_config = FORMATS[fmt]
        output_template = str(DOWNLOAD_DIR / f"{task_id}.%(ext)s")

        def progress_hook(d):
            if task_id in cancelled_tasks:
                raise Exception("DOWNLOAD_CANCELLED_BY_USER")

            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)
                if total > 0:
                    pct = int(downloaded / total * 100)
                    with downloads_lock:
                        active_downloads[task_id]["progress"] = pct
            elif d["status"] == "finished":
                with downloads_lock:
                    active_downloads[task_id]["progress"] = 100

        info = None
        last_error = None

        # ── Strategy 0: automatic or user-supplied cookies.txt ─────────────
        # Check for cookies.txt in the AppData directory or app directory if not explicitly provided
        if not cookiefile:
            # Priority 1: User-uploaded cookies in AppData
            appdata_cookies = updater.get_cookies_file()
            if appdata_cookies.exists():
                cookiefile = str(appdata_cookies)
                print(f"DEBUG: Detectado arquivo de cookies no AppData: {cookiefile}")
            else:
                # Priority 2: local fallback cookies
                auto_cookies = _app_dir() / "cookies.txt"
                if auto_cookies.exists():
                    cookiefile = str(auto_cookies)
                    print(f"DEBUG: Detectado arquivo de cookies local: {cookiefile}")

        if cookiefile and Path(cookiefile).exists():
            print(f"DEBUG: Tentando download com cookies: {cookiefile}")
            try:
                opts = build_ydl_opts(fmt_config, output_template, progress_hook,
                                      cookiefile=cookiefile, resolution=resolution, audio_bitrate=audio_bitrate)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
            except Exception as exc:
                last_error = str(exc)
                print(f"DEBUG: Erro Strategy 0 (cookies): {last_error}")
                if "DOWNLOAD_CANCELLED_BY_USER" in last_error or task_id in cancelled_tasks:
                    with downloads_lock:
                        active_downloads[task_id]["status"] = "cancelled"
                        save_task_to_db(task_id, active_downloads[task_id])
                    _cleanup_partial_files(task_id)
                    return
                if not _needs_auth(last_error):
                    with downloads_lock:
                        active_downloads[task_id]["status"] = "error"
                        active_downloads[task_id]["error"] = _friendly_error(last_error)
                        save_task_to_db(task_id, active_downloads[task_id])
                    _cleanup_partial_files(task_id)
                    return
                # fall through to browser-cookie strategies below

        # ── Strategy 1: no cookies (works for most public videos) ────────────
        if info is None:
            try:
                opts = build_ydl_opts(fmt_config, output_template, progress_hook,
                                      resolution=resolution, audio_bitrate=audio_bitrate)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)

            except Exception as exc:
                last_error = str(exc)
                if "DOWNLOAD_CANCELLED_BY_USER" in last_error or task_id in cancelled_tasks:
                    with downloads_lock:
                        active_downloads[task_id]["status"] = "cancelled"
                        save_task_to_db(task_id, active_downloads[task_id])
                    _cleanup_partial_files(task_id)
                    return

                if not _needs_auth(last_error):
                    with downloads_lock:
                        active_downloads[task_id]["status"] = "error"
                        active_downloads[task_id]["error"] = _friendly_error(last_error)
                        save_task_to_db(task_id, active_downloads[task_id])
                    _cleanup_partial_files(task_id)
                    return

                # ── Strategy 2: browser cookies with pre-copy workaround ─────
                with downloads_lock:
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
                            resolution=resolution,
                            audio_bitrate=audio_bitrate
                        )
                        with yt_dlp.YoutubeDL(opts) as ydl:
                            info = ydl.extract_info(url, download=True)
                        last_error = None  # success
                        break
                    except Exception as be:
                        err_str = str(be)
                        if "DOWNLOAD_CANCELLED_BY_USER" in err_str or task_id in cancelled_tasks:
                            with downloads_lock:
                                active_downloads[task_id]["status"] = "cancelled"
                                save_task_to_db(task_id, active_downloads[task_id])
                            _cleanup_partial_files(task_id)
                            return
                        _lower = err_str.lower()
                        # Skip browsers not installed on this machine
                        if ("could not find" in _lower or "no such file" in _lower
                                or "cookies database" in _lower) and "could not copy" not in _lower:
                            continue
                        auth_error = err_str
                        last_error = err_str
                        continue

                if last_error:
                    with downloads_lock:
                        active_downloads[task_id]["status"] = "error"
                        active_downloads[task_id]["error"] = _friendly_error(auth_error)
                        save_task_to_db(task_id, active_downloads[task_id])
                    _cleanup_partial_files(task_id)
                    return

        # ── Locate the downloaded file ────────────────────────────────────────
        title = sanitize_filename(info.get("title", "video"))
        downloaded_file = None
        for f in DOWNLOAD_DIR.iterdir():
            if f.stem == task_id:
                downloaded_file = f
                break

        if downloaded_file and downloaded_file.exists():
            with downloads_lock:
                active_downloads[task_id]["status"] = "done"
                active_downloads[task_id]["filename"] = downloaded_file.name
                active_downloads[task_id]["title"] = title
                active_downloads[task_id]["progress"] = 100
                save_task_to_db(task_id, active_downloads[task_id])
        else:
            if task_id in cancelled_tasks:
                with downloads_lock:
                    active_downloads[task_id]["status"] = "cancelled"
                    save_task_to_db(task_id, active_downloads[task_id])
                _cleanup_partial_files(task_id)
            else:
                with downloads_lock:
                    active_downloads[task_id]["status"] = "error"
                    active_downloads[task_id]["error"] = "Arquivo não encontrado após o download."
                    save_task_to_db(task_id, active_downloads[task_id])
                _cleanup_partial_files(task_id)

    except Exception as exc:
        if "DOWNLOAD_CANCELLED_BY_USER" in str(exc) or task_id in cancelled_tasks:
            with downloads_lock:
                active_downloads[task_id]["status"] = "cancelled"
                save_task_to_db(task_id, active_downloads[task_id])
            _cleanup_partial_files(task_id)
        else:
            with downloads_lock:
                active_downloads[task_id]["status"] = "error"
                active_downloads[task_id]["error"] = _friendly_error(str(exc))
                save_task_to_db(task_id, active_downloads[task_id])
            _cleanup_partial_files(task_id)
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
    resolution = data.get("resolution")  # Opcional (ex: "1080", "720", "2160")
    audio_bitrate = data.get("audio_bitrate")  # Opcional (ex: "320", "192", "128")

    if not url:
        return jsonify({"error": "URL não informada."}), 400
    if fmt not in FORMATS:
        return jsonify({"error": f"Formato '{fmt}' não suportado."}), 400

    task_id = str(uuid.uuid4())
    with downloads_lock:
        active_downloads[task_id] = {
            "status": "queued",
            "progress": 0,
            "filename": None,
            "title": None,
            "error": None,
            "url": url,
            "format": fmt,
            "resolution": resolution,
            "audio_bitrate": audio_bitrate
        }

    # Persist the queued state immediately
    save_task_to_db(task_id, active_downloads[task_id])

    # Submit task to ThreadPool instead of spawning random raw thread
    download_executor.submit(do_download, task_id, url, fmt, None, resolution, audio_bitrate)

    return jsonify({"task_id": task_id})


@app.route("/api/status/<task_id>")
def get_status(task_id):
    with downloads_lock:
        task = active_downloads.get(task_id)
        if not task:
            return jsonify({"error": "Task não encontrada."}), 404
        return jsonify(task.copy())


@app.route("/api/downloads")
def get_all_downloads():
    with downloads_lock:
        return jsonify(active_downloads.copy())


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


@app.route("/api/cookies/upload", methods=["POST"])
def upload_cookies():
    if "file" not in request.files:
        return jsonify({"error": "Nenhum arquivo enviado."}), 400
    
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Nenhum arquivo selecionado."}), 400
    
    if not file.filename.endswith(".txt"):
        return jsonify({"error": "O arquivo deve ser um arquivo de texto (.txt)."}), 400

    try:
        cookies_dest = updater.get_cookies_file()
        cookies_dest.parent.mkdir(parents=True, exist_ok=True)
        file.save(str(cookies_dest))
        return jsonify({"success": True, "message": "Cookies importados com sucesso!"})
    except Exception as e:
        return jsonify({"error": f"Falha ao salvar cookies: {str(e)}"}), 500


@app.route("/api/updater/info")
def updater_info():
    version = updater.get_current_ytdl_version()
    return jsonify({
        "version": version
    })


@app.route("/api/cancel/<task_id>", methods=["POST"])
def cancel_download(task_id):
    with downloads_lock:
        task = active_downloads.get(task_id)
        if not task:
            return jsonify({"error": "Task não encontrada."}), 404
        
        status = task.get("status")
        if status in ("queued", "downloading"):
            cancelled_tasks.add(task_id)
            task["status"] = "cancelled"
            task["progress"] = 0
            save_task_to_db(task_id, task)
            # Run immediate background thread to clean up partial files
            threading.Thread(target=_cleanup_partial_files, args=(task_id,), daemon=True).start()
            return jsonify({"success": True, "message": "Cancelamento solicitado com sucesso."})
        
        return jsonify({"error": f"Não é possível cancelar um download com status '{status}'."}), 400


@app.route("/api/settings", methods=["GET"])
def get_settings():
    theme = get_setting_from_db("theme", "escuro")
    font_scale = get_setting_from_db("fontScale", "1.0")
    return jsonify({
        "theme": theme,
        "fontScale": font_scale
    })


@app.route("/api/settings", methods=["POST"])
def save_settings():
    data = request.get_json() or {}
    theme = data.get("theme")
    font_scale = data.get("fontScale")
    
    if theme is not None:
        save_setting_to_db("theme", theme)
    if font_scale is not None:
        save_setting_to_db("fontScale", font_scale)
        
    return jsonify({"success": True})


# Start background check on initialization
if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
    init_db()
    load_tasks_from_db()
    threading.Thread(target=updater.check_and_update_ytdl, daemon=True).start()
    threading.Thread(target=cleanup_old_temporary_files, daemon=True).start()


if __name__ == "__main__":
    # Dev mode: run with Flask's built-in server
    app.run(debug=True, port=5000)
