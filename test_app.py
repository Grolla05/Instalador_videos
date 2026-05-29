import sys
import os
import json
import time
import shutil
import io
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

# Define unique API isolation token in the environment BEFORE importing app
API_TOKEN = "test-nonce-token-12345"
os.environ["API_TOKEN"] = API_TOKEN

# Add current dir to path to import app
sys.path.append(os.path.abspath("."))
from app import (
    app,
    init_db,
    save_task_to_db,
    load_tasks_from_db,
    active_downloads,
    downloads_lock,
    DOWNLOAD_DIR,
    _cleanup_partial_files,
    cleanup_old_temporary_files,
    build_ydl_opts,
    FORMATS
)
import app as app_module
import updater

client = app.test_client()

# Helper headers
HEADERS = {"X-API-Token": API_TOKEN}

def run_tests():
    # ── 1. Static and Base layouts bypass verification ──
    print("Testing / (Should pass without API Token)")
    response = client.get("/")
    assert response.status_code == 200
    assert b"YouTube Downloader" in response.data
    print("OK")

    # ── 2. Security isolation tests (X-API-Token) ──
    print("Testing security verification (No token -> 403)")
    response = client.get("/api/downloads")
    assert response.status_code == 403
    data = json.loads(response.data)
    assert "error" in data
    assert "Acesso não autorizado" in data["error"]
    print("OK")

    print("Testing security verification (Bad token -> 403)")
    response = client.get("/api/downloads", headers={"X-API-Token": "wrong-token"})
    assert response.status_code == 403
    data = json.loads(response.data)
    assert "error" in data
    assert "Acesso não autorizado" in data["error"]
    print("OK")

    print("Testing security verification (Valid token -> 200)")
    response = client.get("/api/downloads", headers=HEADERS)
    assert response.status_code == 200
    print("OK")

    # ── 3. Basic active downloads lists ──
    print("Testing /api/downloads (empty list validation)")
    with downloads_lock:
        active_downloads.clear()
    response = client.get("/api/downloads", headers=HEADERS)
    assert response.status_code == 200
    data = json.loads(response.data)
    assert isinstance(data, dict)
    assert len(data) == 0
    print("OK")

    print("Testing invalid /api/download")
    response = client.post("/api/download", json={"url": "", "format": "mp4"}, headers=HEADERS)
    assert response.status_code == 400
    data = json.loads(response.data)
    assert "error" in data
    print("OK")

    # ── 4. Updater and Cookies file ──
    print("Testing /api/updater/info")
    response = client.get("/api/updater/info", headers=HEADERS)
    assert response.status_code == 200
    data = json.loads(response.data)
    assert "version" in data
    print("OK (Version:", data["version"], ")")

    print("Testing /api/cookies/upload - No file")
    response = client.post("/api/cookies/upload", headers=HEADERS)
    assert response.status_code == 400
    data = json.loads(response.data)
    assert "error" in data
    print("OK")

    print("Testing /api/cookies/upload - Invalid extension")
    data = {"file": (io.BytesIO(b"fake cookies"), "cookies.png")}
    response = client.post("/api/cookies/upload", data=data, content_type="multipart/form-data", headers=HEADERS)
    assert response.status_code == 400
    data = json.loads(response.data)
    assert "error" in data
    print("OK")

    print("Testing /api/cookies/upload - Valid .txt upload")
    cookies_file = updater.get_cookies_file()
    if cookies_file.exists():
        cookies_file.unlink()

    data = {"file": (io.BytesIO(b"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tFALSE\t0\tGPS\t1"), "cookies.txt")}
    response = client.post("/api/cookies/upload", data=data, content_type="multipart/form-data", headers=HEADERS)
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["success"] is True
    
    assert cookies_file.exists()
    with open(cookies_file, "r") as f:
        content = f.read()
    assert "Netscape HTTP Cookie File" in content
    
    cookies_file.unlink()
    print("OK")

    # ── 5. Formats and dynamic resolution tests ──
    print("Testing build_ydl_opts - Dynamic Resolution 1080p")
    original_which = shutil.which
    shutil.which = lambda cmd: "/usr/bin/ffmpeg" if cmd == "ffmpeg" else original_which(cmd)
    
    fmt_config = FORMATS["mp4"]
    opts = build_ydl_opts(fmt_config, "test_template", lambda d: None, resolution="1080")
    assert "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]" in opts["format"]
    
    shutil.which = original_which
    print("OK")

    print("Testing build_ydl_opts - Dynamic MP3 Bitrate 320")
    fmt_config = FORMATS["mp3"]
    opts = build_ydl_opts(fmt_config, "test_template", lambda d: None, audio_bitrate="320")
    mp3_pp = [pp for pp in opts["postprocessors"] if pp.get("preferredcodec") == "mp3"][0]
    assert mp3_pp["preferredquality"] == "320"
    print("OK")

    # ── 6. Task cancellation tests ──
    print("Testing /api/cancel/<task_id> - Invalid ID")
    response = client.post("/api/cancel/invalid-id-123", headers=HEADERS)
    assert response.status_code == 404
    print("OK")

    print("Testing /api/cancel/<task_id> - Active queued task cancellation")
    test_id = "test-cancel-id-999"
    with downloads_lock:
        active_downloads[test_id] = {
            "status": "queued",
            "progress": 0,
            "filename": None,
            "title": "Test Video",
            "error": None,
        }
    response = client.post(f"/api/cancel/{test_id}", headers=HEADERS)
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["success"] is True
    with downloads_lock:
        assert active_downloads[test_id]["status"] == "cancelled"
        del active_downloads[test_id]
    print("OK")

    # ── 7. File cleaning routines ──
    print("Testing _cleanup_partial_files & cleanup_old_temporary_files")
    dummy_file = DOWNLOAD_DIR / "dummy_task_123.part"
    with open(dummy_file, "w") as f:
        f.write("partial content")
    assert dummy_file.exists()
    
    _cleanup_partial_files("dummy_task_123")
    assert not dummy_file.exists()
    
    old_file = DOWNLOAD_DIR / "old_remain_999.part"
    with open(old_file, "w") as f:
        f.write("old partial content")
    
    backdate = time.time() - (30 * 3600)
    os.utime(str(old_file), (backdate, backdate))
    
    cleanup_old_temporary_files()
    assert not old_file.exists()
    print("OK")

    # ── 8. SQLite Relational Persistence Tests ──
    print("Testing SQLite Relational Database Operations")
    # Initialize DB
    init_db()
    db_path = app_module._get_db_path()
    assert db_path.exists()

    # Save a done task to SQLite
    task_id_db = "db-test-task-111"
    task_data = {
        "status": "done",
        "progress": 100,
        "filename": "video111.mp4",
        "title": "Database Test Video",
        "error": None,
        "url": "https://www.youtube.com/watch?v=db111",
        "format": "mp4",
        "resolution": "1080",
        "audio_bitrate": None
    }
    save_task_to_db(task_id_db, task_data)

    # Save a transient task to SQLite (queued/downloading)
    task_id_transient = "db-test-task-222"
    transient_data = {
        "status": "downloading",
        "progress": 45,
        "filename": "video222.mp4",
        "title": "Transient Test Video",
        "error": None,
        "url": "https://www.youtube.com/watch?v=db222",
        "format": "mp4",
        "resolution": "720",
        "audio_bitrate": None
    }
    save_task_to_db(task_id_transient, transient_data)

    # Check connection directly to verify values are correctly placed in sqlite tables
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT task_id, status, progress, title FROM downloads WHERE task_id IN (?, ?)", (task_id_db, task_id_transient))
    rows = dict((row[0], row[1:]) for row in cursor.fetchall())
    conn.close()

    assert task_id_db in rows
    assert rows[task_id_db][0] == "done"
    assert rows[task_id_db][1] == 100
    assert rows[task_id_db][2] == "Database Test Video"

    assert task_id_transient in rows
    assert rows[task_id_transient][0] == "downloading"
    assert rows[task_id_transient][1] == 45
    assert rows[task_id_transient][2] == "Transient Test Video"

    # Test load_tasks_from_db auto-restores to dictionary
    with downloads_lock:
        active_downloads.clear()
    
    load_tasks_from_db()

    with downloads_lock:
        # Done task should load as-is
        assert task_id_db in active_downloads
        assert active_downloads[task_id_db]["status"] == "done"
        assert active_downloads[task_id_db]["progress"] == 100

        # Transient tasks (queued or downloading) must load safely mapped to "cancelled"
        assert task_id_transient in active_downloads
        assert active_downloads[task_id_transient]["status"] == "cancelled"
        assert active_downloads[task_id_transient]["progress"] == 0
    
    print("OK")

    # ── 9. Queue & ThreadPool Concurrency Limits (Max 3 parallel) ──
    print("Testing Rate Limiting & ThreadPoolExecutor limits (max 3 concurrent)")
    
    # Mock yt_dlp.YoutubeDL to block/delay and simulate a download duration
    class MockYoutubeDL:
        def __init__(self, opts=None):
            self.opts = opts
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def extract_info(self, url, download=True):
            # Sleep 0.4s to let tests check concurrency status states
            time.sleep(0.4)
            # Create a mock file in CWD downloads to satisfy file existence checks
            task_id = Path(self.opts["outtmpl"]).stem
            mock_file = DOWNLOAD_DIR / f"{task_id}.mp4"
            with open(mock_file, "w") as f:
                f.write("mocked video output")
            return {"title": "Mock Video Thread", "id": "mock_id_thread"}

    # Back up original and inject our Mock
    original_yt_dlp_ydl = app_module.yt_dlp.YoutubeDL
    app_module.yt_dlp.YoutubeDL = MockYoutubeDL

    try:
        with downloads_lock:
            active_downloads.clear()

        task_ids = []
        # Dispatch 5 download requests in rapid succession
        for i in range(5):
            response = client.post(
                "/api/download",
                json={
                    "url": f"https://www.youtube.com/watch?v=concurrency{i}",
                    "format": "mp4"
                },
                headers=HEADERS
            )
            assert response.status_code == 200
            task_ids.append(json.loads(response.data)["task_id"])

        # Allow threads to start and pick up tasks (takes a few milliseconds)
        time.sleep(0.15)

        # Inspect the state of active downloads under lock
        with downloads_lock:
            downloading_count = sum(1 for tid in task_ids if active_downloads.get(tid, {}).get("status") == "downloading")
            queued_count = sum(1 for tid in task_ids if active_downloads.get(tid, {}).get("status") == "queued")

            print(f"DEBUG Queue: Active 'downloading': {downloading_count}, In queue 'queued': {queued_count}")
            # The ThreadPoolExecutor is capped at max_workers=3.
            # Thus, at most 3 tasks can run simultaneously, and at least 2 must remain in the queue.
            assert downloading_count <= 3
            assert queued_count >= 2
            assert downloading_count + queued_count == 5

        # Wait for all mock threads to finish processing
        time.sleep(0.8)

        # Check that they all eventually finish successfully
        with downloads_lock:
            done_count = sum(1 for tid in task_ids if active_downloads.get(tid, {}).get("status") == "done")
            print(f"DEBUG Post-Queue: Completed 'done': {done_count}")
            assert done_count == 5

        # Cleanup mocked files in DOWNLOAD_DIR
        for tid in task_ids:
            mock_file = DOWNLOAD_DIR / f"{tid}.mp4"
            if mock_file.exists():
                mock_file.unlink()

        print("OK")
    finally:
        # Restore original YoutubeDL mock reference
        app_module.yt_dlp.YoutubeDL = original_yt_dlp_ydl

    # ── 10. Accessibility Settings Persistence Tests ──
    print("Testing Accessibility Settings API (/api/settings)")
    response = client.post(
        "/api/settings",
        json={"theme": "sepia", "fontScale": "1.15"},
        headers=HEADERS
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["success"] is True

    response = client.get("/api/settings", headers=HEADERS)
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["theme"] == "sepia"
    assert data["fontScale"] == "1.15"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", ("theme",))
    row_theme = cursor.fetchone()
    cursor.execute("SELECT value FROM settings WHERE key = ?", ("fontScale",))
    row_scale = cursor.fetchone()
    conn.close()

    assert row_theme is not None and row_theme[0] == "sepia"
    assert row_scale is not None and row_scale[0] == "1.15"
    print("OK")

    print("All backend tests passed successfully!")

if __name__ == "__main__":
    run_tests()
