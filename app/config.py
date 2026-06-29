from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "ToGo115"
    secret_key: str = "change-me-in-production"
    data_dir: Path = Path("data")
    database_path: Path = Path("data/togo115.sqlite3")
    session_cookie: str = "togo115_session"
    monitor_interval_seconds: int = 60

    class Config:
        env_prefix = "TOGO115_"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
