from pathlib import Path

from pydantic import SecretStr
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
    pursuits_daily_fetch_limit: int = 160
    pursuits_daily_model_limit: int = 8
    typesafe_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    openai_brief_model: str = "gpt-4.1-mini"
    briefs_daily_request_limit: int = 8
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env", extra="ignore"
    )


settings = Settings()  # type: ignore[call-arg]  # Environment fields are supplied by local or deployment configuration.
