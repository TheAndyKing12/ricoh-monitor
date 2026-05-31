from dataclasses import dataclass
from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parents[1]


def _load_env_file() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _list_env(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


_load_env_file()


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Ricoh Monitor")
    app_version: str = os.getenv("APP_VERSION", "1.0.0")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./ricoh.db")
    secret_key: str = os.getenv("APP_SECRET_KEY", "ricoh-monitor-change-me")
    emergency_admin_user: str = os.getenv("EMERGENCY_ADMIN_USER", "SuperAdmin")
    emergency_admin_password: str | None = os.getenv("EMERGENCY_ADMIN_PASSWORD")
    token_expire_hours: int = _int_env("TOKEN_EXPIRE_HOURS", 8)
    cors_origins: list[str] = None
    status_sync_interval: int = _int_env("STATUS_SYNC_INTERVAL", 5)
    counter_sync_interval: int = _int_env("COUNTER_SYNC_INTERVAL", 30)
    toner_sync_interval: int = _int_env("TONER_SYNC_INTERVAL", 10)
    notification_retention_days: int = _int_env("NOTIFICATION_RETENTION_DAYS", 30)
    alert_webhook_url: str | None = os.getenv("ALERT_WEBHOOK_URL")
    alert_webhook_timeout_seconds: int = _int_env("ALERT_WEBHOOK_TIMEOUT_SECONDS", 5)
    cache_dir: Path = Path(os.getenv("CACHE_DIR", str(BASE_DIR / "cache")))

    def __post_init__(self):
        object.__setattr__(self, "cors_origins", _list_env("CORS_ORIGINS", ["*"]))


settings = Settings()
