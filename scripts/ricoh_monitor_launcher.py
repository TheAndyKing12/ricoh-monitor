from pathlib import Path
import logging
import os
import shutil
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return _app_root()


def _runtime_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = os.getenv("PROGRAMDATA") or os.getenv("LOCALAPPDATA") or str(_app_root())
        return Path(base) / "Ricoh Monitor"
    return _app_root()


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _configure_logging(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / "RicohMonitor.log"
    try:
        logging.basicConfig(
            filename=str(log_path),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            force=True,
        )
    except OSError:
        fallback_dir = Path(os.getenv("TEMP", str(Path.home())))
        logging.basicConfig(
            filename=str(fallback_dir / "RicohMonitor.log"),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            force=True,
        )


def _is_default_sqlite_url(value: str | None) -> bool:
    if not value:
        return True
    normalized = value.replace("\\", "/").lower()
    return normalized in {"sqlite:///./ricoh.db", "sqlite:///ricoh.db"}


def _prepare_runtime_storage(root: Path, data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = data_dir / "backend" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    db_path = data_dir / "ricoh.db"
    seed_db = root / "ricoh.db"
    if not db_path.exists() and seed_db.exists():
        shutil.copy2(seed_db, db_path)

    if getattr(sys, "frozen", False):
        if _is_default_sqlite_url(os.getenv("DATABASE_URL")):
            os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
        if not os.getenv("CACHE_DIR") or not Path(os.getenv("CACHE_DIR", "")).is_absolute():
            os.environ["CACHE_DIR"] = str(cache_dir)
    else:
        os.environ.setdefault("DATABASE_URL", f"sqlite:///{(root / 'ricoh.db').as_posix()}")
        os.environ.setdefault("CACHE_DIR", str(root / "backend" / "cache"))


def main() -> None:
    root = _app_root()
    data_dir = _runtime_data_dir()
    _configure_logging(data_dir)
    logging.info("Starting Ricoh Monitor desktop launcher")
    os.chdir(root)

    backend_dir = root / "backend"
    bundled_backend_dir = _bundle_root() / "backend"
    _load_env_file(bundled_backend_dir / ".env")
    _load_env_file(backend_dir / ".env")
    _load_env_file(root / ".env")

    _prepare_runtime_storage(root, data_dir)
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{browser_host}:{port}/frontend/dashboard.html"

    import uvicorn
    from app.main import app

    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="info", log_config=None)
    )
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    health_url = f"http://{browser_host}:{port}/health"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and server_thread.is_alive():
        try:
            urllib.request.urlopen(health_url, timeout=1).close()
            logging.info("Backend is ready at %s", health_url)
            break
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)

    import webview

    window = webview.create_window(
        "Ricoh Monitor",
        url,
        width=1280,
        height=800,
        min_size=(1024, 640),
    )

    def _stop_server() -> None:
        server.should_exit = True

    window.events.closed += _stop_server
    webview.start()
    server.should_exit = True
    server_thread.join(timeout=5)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _configure_logging(_runtime_data_dir())
        logging.error("Fatal launcher error:\n%s", traceback.format_exc())
        raise
