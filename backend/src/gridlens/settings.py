from datetime import time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    test_database_url: str = ""
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
    # Retained evidence analysis and bounded zero-cost research are part of the
    # autonomous product loop. Paid/model dispatch remains separately gated by
    # explicit contracts, configured prices, budgets and keys below.
    opportunity_enrichment_enabled: bool = True
    worker_auto_refresh: bool = True
    monitoring_enabled: bool = False
    monitoring_plan_batch_limit: int = Field(default=20, ge=1, le=100)
    monitoring_max_active_jobs: int = Field(default=4, ge=1, le=100)
    monitoring_max_active_per_host: int = Field(default=2, ge=1, le=20)
    monitoring_max_active_per_source: int = Field(default=1, ge=1, le=20)
    saved_browse_enabled: bool = False
    pursuits_daily_fetch_limit: int = 160
    pursuits_daily_model_limit: int = 8
    typesafe_api_key: SecretStr | None = None
    jev_enabled: bool = False
    intelligence_enabled: bool = False
    intelligence_mode: str = "disabled"
    intelligence_routing_policy_id: str = ""
    intelligence_routing_policy_evaluated: bool = False
    intelligence_bounded_routing_authorized: bool = False
    intelligence_openai_enabled: bool = False
    intelligence_typesafe_enabled: bool = False
    intelligence_research_enabled: bool = False
    intelligence_enabled_contracts: str = ""
    intelligence_global_daily_calls: int = Field(default=0, ge=0, le=1_000_000)
    intelligence_global_monthly_calls: int = Field(default=0, ge=0, le=1_000_000)
    intelligence_global_daily_usd: Decimal = Field(default=Decimal("0"), ge=0, le=100000)
    intelligence_global_monthly_usd: Decimal = Field(default=Decimal("0"), ge=0, le=100000)
    intelligence_provider_daily_calls: int = Field(default=0, ge=0, le=1_000_000)
    intelligence_provider_monthly_calls: int = Field(default=0, ge=0, le=1_000_000)
    intelligence_provider_daily_usd: Decimal = Field(default=Decimal("0"), ge=0, le=100000)
    intelligence_provider_monthly_usd: Decimal = Field(default=Decimal("0"), ge=0, le=100000)
    intelligence_model_daily_calls: int = Field(default=0, ge=0, le=1_000_000)
    intelligence_model_monthly_calls: int = Field(default=0, ge=0, le=1_000_000)
    intelligence_model_daily_usd: Decimal = Field(default=Decimal("0"), ge=0, le=100000)
    intelligence_model_monthly_usd: Decimal = Field(default=Decimal("0"), ge=0, le=100000)
    intelligence_source_daily_calls: int = Field(default=0, ge=0, le=1_000_000)
    intelligence_source_monthly_calls: int = Field(default=0, ge=0, le=1_000_000)
    intelligence_source_daily_usd: Decimal = Field(default=Decimal("0"), ge=0, le=100000)
    intelligence_source_monthly_usd: Decimal = Field(default=Decimal("0"), ge=0, le=100000)
    intelligence_project_daily_calls: int = Field(default=0, ge=0, le=1_000_000)
    intelligence_project_monthly_calls: int = Field(default=0, ge=0, le=1_000_000)
    intelligence_project_daily_usd: Decimal = Field(default=Decimal("0"), ge=0, le=100000)
    intelligence_project_monthly_usd: Decimal = Field(default=Decimal("0"), ge=0, le=100000)
    intelligence_max_active_calls: int = Field(default=0, ge=0, le=100_000)
    intelligence_max_call_usd: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    intelligence_financial_budget_mode: str = "finite"
    intelligence_financial_authorization_ref: str = ""
    intelligence_unlimited_contracts: str = ""
    intelligence_unlimited_providers: str = ""
    intelligence_openai_model: str = ""
    intelligence_openai_fast_model: str = ""
    intelligence_openai_reasoning_model: str = ""
    intelligence_openai_fast_priced_model_id: str = ""
    intelligence_openai_fast_pricing_verified: bool = False
    intelligence_openai_fast_input_usd_per_million: Decimal = Field(
        default=Decimal("0"), ge=0, le=100000
    )
    intelligence_openai_fast_output_usd_per_million: Decimal = Field(
        default=Decimal("0"), ge=0, le=100000
    )
    intelligence_openai_fast_max_output_tokens: int = Field(default=0, ge=0, le=100000)
    intelligence_openai_reasoning_priced_model_id: str = ""
    intelligence_openai_reasoning_pricing_verified: bool = False
    intelligence_openai_reasoning_input_usd_per_million: Decimal = Field(
        default=Decimal("0"), ge=0, le=100000
    )
    intelligence_openai_reasoning_output_usd_per_million: Decimal = Field(
        default=Decimal("0"), ge=0, le=100000
    )
    intelligence_openai_reasoning_max_output_tokens: int = Field(default=0, ge=0, le=100000)
    intelligence_ocr_enabled: bool = False
    intelligence_ocr_preflight_enabled: bool = False
    intelligence_ocr_preflight_cost_bound_verified: bool = False
    intelligence_ocr_preflight_cost_reference: str = ""
    intelligence_ocr_vision_enabled: bool = False
    intelligence_ocr_retention_source_ids: str = ""
    intelligence_ocr_retention_reference: str = ""
    intelligence_ocr_model: str = ""
    intelligence_ocr_priced_model_id: str = ""
    intelligence_ocr_pricing_verified: bool = False
    intelligence_ocr_input_usd_per_million: Decimal = Field(default=Decimal("0"), ge=0, le=100000)
    intelligence_ocr_output_usd_per_million: Decimal = Field(default=Decimal("0"), ge=0, le=100000)
    intelligence_ocr_max_output_tokens: int = Field(default=0, ge=0, le=100000)
    intelligence_ocr_detail: str = "auto"
    intelligence_ocr_preflight_max_cost_usd: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    intelligence_ocr_max_call_usd: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    intelligence_typesafe_priced_model_id: str = ""
    intelligence_typesafe_pricing_verified: bool = False
    intelligence_typesafe_input_usd_per_million: Decimal = Field(
        default=Decimal("0"), ge=0, le=100000
    )
    intelligence_typesafe_output_usd_per_million: Decimal = Field(
        default=Decimal("0"), ge=0, le=100000
    )
    intelligence_typesafe_max_output_tokens: int = Field(default=0, ge=0, le=100000)
    intelligence_typesafe_output_limit_verified: bool = False
    intelligence_typesafe_model: str = ""
    intelligence_typesafe_billing_mode: str = "unknown"
    intelligence_typesafe_billing_model_id: str = ""
    intelligence_typesafe_billing_contract_id: str = ""
    intelligence_typesafe_billing_policy_id: str = ""
    intelligence_typesafe_billing_reference: str = ""
    intelligence_typesafe_billing_verified: bool = False
    intelligence_typesafe_max_total_billable_input_tokens: int = Field(
        default=0, ge=0, le=10_000_000
    )
    intelligence_typesafe_total_input_bound_verified: bool = False
    jev_shadow_mode: bool = True
    jev_shadow_batch_limit: int = 20
    jev_shadow_daily_limit: int = 20
    jev_shadow_timeout_seconds: int = 90
    intelligence_typesafe_estimated_reservation_usd: Decimal = Field(
        default=Decimal("0"), ge=0, le=100
    )
    intelligence_typesafe_estimate_observation_ids: str = ""
    openai_api_key: SecretStr | None = None
    openai_brief_model: str = "gpt-4.1-mini"
    briefs_daily_request_limit: int = 8
    power_need_titles_enabled: bool = False
    autonomous_research_enabled: bool = True
    buying_chain_public_research_enabled: bool = False
    # Enable source-verified public business contact refresh by default. Provider
    # search still requires the independent intelligence ledger authorization.
    company_contact_discovery_enabled: bool = True
    rrc_well_research_enabled: bool = True
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
    operational_receipt_file: str = ""

    @field_validator("schedule_timezone")
    @classmethod
    def _valid_schedule_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("schedule timezone must be a valid IANA zone") from exc
        return value

    @field_validator("intelligence_mode")
    @classmethod
    def _valid_intelligence_mode(cls, value: str) -> str:
        if value not in {"disabled", "evaluation", "advisory", "bounded_routing"}:
            raise ValueError("intelligence_mode must be a supported operating mode")
        return value

    @field_validator("intelligence_financial_budget_mode")
    @classmethod
    def _valid_financial_budget_mode(cls, value: str) -> str:
        if value not in {"finite", "owner_unlimited"}:
            raise ValueError("intelligence_financial_budget_mode must be finite or owner_unlimited")
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
