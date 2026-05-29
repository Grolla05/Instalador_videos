import os
import sys
import json
import shutil
import urllib.request
import zipfile
import tempfile
from pathlib import Path

def get_app_dir() -> Path:
    """Return the writable application data directory for user configs and runtime libraries."""
    app_data = os.environ.get("APPDATA")
    if app_data:
        path = Path(app_data) / "YouTubeDownloader"
    else:
        path = Path.home() / ".youtubedownloader"
    path.mkdir(parents=True, exist_ok=True)
    return path

def get_lib_dir() -> Path:
    """Return the dynamic library path where updated packages are stored."""
    lib_path = get_app_dir() / "lib"
    lib_path.mkdir(parents=True, exist_ok=True)
    return lib_path

def get_cookies_file() -> Path:
    """Return the path to the manual cookies.txt file in the AppData directory."""
    return get_app_dir() / "cookies.txt"

def setup_dynamic_path():
    """
    Inject the dynamic library directory to the very front of sys.path.
    This guarantees that any dynamically downloaded modules (like yt-dlp)
    are imported instead of their frozen equivalents in the executable.
    """
    lib_dir = get_lib_dir()
    lib_str = str(lib_dir.absolute())
    if lib_str not in sys.path:
        sys.path.insert(0, lib_str)

def get_current_ytdl_version() -> str:
    """Get the currently loaded yt-dlp version, or a fallback if not imported yet."""
    try:
        import yt_dlp
        return getattr(yt_dlp.version, "__version__", "Desconhecida")
    except Exception:
        return "Nenhuma"

def check_and_update_ytdl():
    """
    Check the PyPI registry for the newest version of yt-dlp.
    If a newer version is found, download its Wheel (.whl), extract the
    yt_dlp module, and place it inside the dynamic lib directory.
    """
    setup_dynamic_path()
    current_version = get_current_ytdl_version()
    print(f"UPDATER: Versão local ativa do yt-dlp: {current_version}")

    try:
        # 1. Fetch package metadata from PyPI JSON API
        url = "https://pypi.org/pypi/yt-dlp/json"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            
        latest_version = data["info"]["version"]
        print(f"UPDATER: Versão mais recente no PyPI: {latest_version}")

        # If versions match, we're already up to date
        if current_version == latest_version:
            print("UPDATER: O yt-dlp está totalmente atualizado.")
            return

        # 2. Locate the Wheel (.whl) package URL in releases
        wheel_url = None
        for release in data["urls"]:
            if release.get("packagetype") == "bdist_wheel":
                wheel_url = release.get("url")
                break

        if not wheel_url:
            print("UPDATER: Erro - Não foi possível encontrar a URL do pacote Wheel no PyPI.")
            return

        print(f"UPDATER: Nova versão disponível! Baixando Wheel de: {wheel_url}")

        # 3. Download the Wheel to a temporary file
        temp_dir = Path(tempfile.gettempdir())
        temp_zip_path = temp_dir / f"yt_dlp-{latest_version}-py3-none-any.whl"

        req_wheel = urllib.request.Request(
            wheel_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req_wheel, timeout=30) as response, open(temp_zip_path, "wb") as out_file:
            shutil.copyfileobj(response, out_file)

        print("UPDATER: Download concluído. Extraindo pacote...")

        # 4. Extract only the 'yt_dlp/' folder into our dynamic lib directory
        lib_dir = get_lib_dir()
        temp_extract_dir = lib_dir / "temp_extract"
        if temp_extract_dir.exists():
            shutil.rmtree(temp_extract_dir)
        temp_extract_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(temp_zip_path, "r") as zip_ref:
            # Only extract members under the main yt_dlp folder
            members_to_extract = [m for m in zip_ref.namelist() if m.startswith("yt_dlp/")]
            zip_ref.extractall(path=temp_extract_dir, members=members_to_extract)

        # 5. Swap the extracted directory with the active one atomically
        target_yt_dlp = lib_dir / "yt_dlp"
        temp_src_yt_dlp = temp_extract_dir / "yt_dlp"

        if target_yt_dlp.exists():
            # Rename existing to a backup directory, then delete (prevents access lock crashes)
            backup_dir = lib_dir / "yt_dlp_old"
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            target_yt_dlp.rename(backup_dir)
            
            try:
                temp_src_yt_dlp.rename(target_yt_dlp)
                shutil.rmtree(backup_dir)
            except Exception as e:
                # Rollback in case of errors
                print(f"UPDATER: Erro durante a troca de pastas, revertendo... {e}")
                if target_yt_dlp.exists():
                    shutil.rmtree(target_yt_dlp)
                backup_dir.rename(target_yt_dlp)
                raise e
        else:
            temp_src_yt_dlp.rename(target_yt_dlp)

        # Clean up temporary folders and files
        shutil.rmtree(temp_extract_dir)
        try:
            os.unlink(temp_zip_path)
        except Exception:
            pass

        print(f"UPDATER: yt-dlp atualizado com sucesso para v{latest_version}! Ativo na próxima inicialização.")

    except Exception as e:
        print(f"UPDATER: Falha ao verificar/atualizar o yt-dlp: {e}")
