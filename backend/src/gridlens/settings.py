from datetime import time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    test_database_url: str = ""
    editorial_reviews_path: str = ""
    app_password_hash: str
    session_secret: str
    cookie_secure: bool = True
    session_hours: int = 12
    trusted_origins: str = ""
    trusted_proxy_cidrs: str = ""
    login_window_seconds: int = Field(default=60, ge=10, le=600)
    login_client_limit: int = Field(default=5, ge=1, le=100)
    login_global_limit: int = Field(default=500, ge=10, le=10000)
    login_client_bucket_cap: int = Field(default=10000, ge=100, le=100000)
    worker_auto_refresh: bool = True
    pursuits_daily_fetch_limit: int = 160
    pursuits_daily_model_limit: int = 8
    typesafe_api_key: SecretStr | None = None
    jev_enabled: bool = False
    jev_shadow_mode: bool = True
    jev_shadow_batch_limit: int = 20
    jev_shadow_daily_limit: int = 20
    jev_shadow_timeout_seconds: int = 90
    openai_api_key: SecretStr | None = None
    openai_brief_model: str = "gpt-4.1-mini"
    briefs_daily_request_limit: int = 8
    openai_newsletter_model: str = "gpt-4.1-mini"
    newsletter_daily_request_limit: int = Field(default=30, ge=0, le=500)
    autonomous_research_enabled: bool = True
    autonomous_research_daily_questions: int = Field(default=8, ge=0, le=100)
    autonomous_research_max_searches: int = Field(default=3, ge=0, le=5)
    autonomous_research_max_urls: int = Field(default=10, ge=1, le=15)
    autonomous_research_max_document_bytes: int = Field(default=750_000, ge=1_000, le=750_000)
    autonomous_research_max_documents: int = Field(default=5, ge=1, le=8)
    autonomous_research_timeout_seconds: int = Field(default=180, ge=10, le=350)
    firecrawl_api_key: SecretStr | None = None
    autonomous_research_max_cost_usd: Decimal = Field(default=Decimal("0"), ge=0, le=2)
    firecrawl_search_cost_usd: Decimal | None = Field(default=None, gt=0, le=2)
    firecrawl_scrape_cost_usd: Decimal | None = Field(default=None, gt=0, le=2)
    schedule_timezone: str = "America/Chicago"
    schedule_anchor_time: str = "07:00:00"
    ntfy_url: str = ""
    ntfy_token: SecretStr | None = None

    @field_validator("schedule_timezone")
    @classmethod
    def _valid_schedule_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("schedule timezone must be a valid IANA zone") from exc
        return value

    @field_validator("schedule_anchor_time")
    @classmethod
    def _valid_schedule_anchor(cls, value: str) -> str:
        try:
            parsed = time.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("schedule anchor must be a local clock time") from exc
        if parsed.tzinfo is not None:
            raise ValueError("schedule anchor must not carry a timezone")
        return parsed.isoformat()

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env", extra="ignore"
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Build settings on first use so importing this module does not read the environment."""
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]  # Required fields come from the environment.
    return _settings


class _SettingsProxy:
    """Forward attribute access to get_settings() so existing imports stay lazy."""

    def __getattr__(self, name: str):
        return getattr(get_settings(), name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(get_settings(), name, value)


settings = _SettingsProxy()
