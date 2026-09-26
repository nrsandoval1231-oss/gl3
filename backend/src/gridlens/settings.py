from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    test_database_url: str = ""
    app_password_hash: str
    session_secret: str
    cookie_secure: bool = True
    session_hours: int = 12
    trusted_origins: str = ""
    worker_auto_refresh: bool = True
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env", extra="ignore"
    )


settings = Settings()  # type: ignore[call-arg]  # Environment fields are supplied by local or deployment configuration.
