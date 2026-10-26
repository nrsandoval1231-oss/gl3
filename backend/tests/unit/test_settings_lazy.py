import pytest
from pydantic import ValidationError

from gridlens.settings import Settings, get_settings, settings


def test_get_settings_caches_one_object():
    first = get_settings()
    assert get_settings() is first
    assert settings.database_url == first.database_url
    assert settings.schedule_timezone == "America/Chicago"
    assert settings.schedule_anchor_time == "07:00:00"


def test_schedule_settings_reject_unknown_zone_and_clock(monkeypatch):
    import gridlens.settings as module

    monkeypatch.setattr(module, "_settings", None)
    monkeypatch.setenv("SCHEDULE_TIMEZONE", "Not/A_Zone")
    with pytest.raises(ValidationError, match="IANA"):
        module.get_settings()

    monkeypatch.setattr(module, "_settings", None)
    monkeypatch.delenv("SCHEDULE_TIMEZONE", raising=False)
    monkeypatch.setenv("SCHEDULE_ANCHOR_TIME", "25:90")
    with pytest.raises(ValidationError, match="local clock time"):
        module.get_settings()


def test_autonomous_research_defaults_to_free_bounded_work_with_paid_calls_disabled():
    defaults = Settings.model_construct(
        database_url="postgresql+psycopg://unused/db",
        app_password_hash="unused",
        session_secret="unused",
    )
    assert defaults.opportunity_enrichment_enabled is True
    assert defaults.company_contact_discovery_enabled is True
    assert defaults.autonomous_research_enabled is True
    assert defaults.intelligence_mode == "disabled"
    assert defaults.intelligence_research_enabled is False
    assert defaults.autonomous_research_max_cost_usd == 0
