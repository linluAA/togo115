from pathlib import Path

from pydantic_settings import SettingsConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TOGO115_")

    app_name: str = "ToGo115"
    secret_key: str = "change-me-in-production"
    data_dir: Path = Path("data")
    database_path: Path = Path("data/togo115.sqlite3")
    session_cookie: str = "togo115_session"
    monitor_interval_seconds: int = 60
    # Periodic full rescan of active subscriptions (Telegram history + RSS/site fallback).
    # Set to 0 to disable. Default 30 minutes.
    subscription_rescan_interval_seconds: int = 1800


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
