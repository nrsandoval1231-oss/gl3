"""Per-provider caps tighten the shared provider scope; they never loosen anything."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import SecretStr

from gridlens.ingestion.parsers.permit_docs.proposals import PageForProposal
from gridlens.intelligence import equipment_proposer as ep
from gridlens.intelligence import intelligence_jobs as jobs
from gridlens.intelligence.spend_caps import (
    cap_fields,
    is_cap_reason,
    parse_provider_caps,
    tighten_provider_scope,
)
from gridlens.jobs import alerts
from gridlens.settings import Settings, settings

SPLIT = '{"openai": {"monthly_usd": 90, "daily_usd": "4.5"}, "typesafe": {"monthly_usd": 10}}'


def shared(monthly_usd: int = 100) -> dict[str, dict]:
    return {
        scope: {
            "daily": 100,
            "monthly": 1000,
            "daily_usd": Decimal(5),
            "monthly_usd": Decimal(monthly_usd),
        }
        for scope in ("global", "provider", "model", "source", "project")
    }


def test_parse_accepts_the_owner_split_and_nothing_else():
    caps = parse_provider_caps(SPLIT)
    assert caps["typesafe"] == {"monthly_usd": Decimal(10)}
    assert caps["openai"]["daily_usd"] == Decimal("4.5")
    assert parse_provider_caps("") == {} and parse_provider_caps("  ") == {}
    for bad in (
        "[]",
        "{not json",
        '{"OpenAI": {"monthly_usd": 1}}',
        '{"openai": {"weekly_usd": 1}}',
        '{"openai": {}}',
        '{"openai": {"monthly_usd": -1}}',
        '{"openai": {"monthly_usd": true}}',
        '{"openai": {"monthly": 1.5}}',
        '{"openai": {"monthly_usd": "NaN"}}',
        '{"openai": {"monthly_usd": 1000000}}',
    ):
        with pytest.raises(ValueError):
            parse_provider_caps(bad)


def test_settings_reject_an_invalid_provider_cap_map(monkeypatch):
    base = {
        "DATABASE_URL": "postgresql+psycopg://x:y@127.0.0.1/z",
        "APP_PASSWORD_HASH": "h",
        "SESSION_SECRET": "s" * 32,
    }
    for key, value in base.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("INTELLIGENCE_PROVIDER_CAPS", '{"openai": {"weekly_usd": 1}}')
    with pytest.raises(ValueError):
        Settings(_env_file=None)  # type: ignore[call-arg]
    monkeypatch.setenv("INTELLIGENCE_PROVIDER_CAPS", SPLIT)
    assert Settings(_env_file=None).intelligence_provider_caps == SPLIT  # type: ignore[call-arg]


def test_override_tightens_only_its_provider_and_never_loosens():
    base = shared(monthly_usd=90)
    overrides = parse_provider_caps(SPLIT)
    typesafe = tighten_provider_scope(base, "typesafe", overrides)
    openai = tighten_provider_scope(base, "openai", overrides)
    other = tighten_provider_scope(base, "firecrawl", overrides)
    assert typesafe["provider"]["monthly_usd"] == Decimal(10)
    assert openai["provider"]["monthly_usd"] == Decimal(90)
    assert openai["provider"]["daily_usd"] == Decimal("4.5")  # tightened from 5
    assert other == base
    assert base["provider"]["monthly_usd"] == Decimal(90)  # input not mutated
    # An override larger than the shared cap cannot loosen it.
    loose = tighten_provider_scope(base, "openai", {"openai": {"monthly_usd": Decimal(500)}})
    assert loose["provider"]["monthly_usd"] == Decimal(90)
    # Other scopes are never touched.
    assert typesafe["global"] == base["global"] and typesafe["model"] == base["model"]


def test_zero_override_fails_closed():
    out = tighten_provider_scope(shared(), "openai", {"openai": {"monthly": 0}})
    assert out["provider"]["monthly"] == 0


def test_provider_caps_reads_settings_and_defaults_to_shared(monkeypatch):
    for scope in ("global", "provider", "model", "source", "project"):
        monkeypatch.setattr(settings, f"intelligence_{scope}_monthly_usd", Decimal(90))
    assert settings.intelligence_provider_caps == ""
    assert jobs.provider_caps("typesafe")["provider"]["monthly_usd"] == Decimal(90)
    monkeypatch.setattr(settings, "intelligence_provider_caps", SPLIT)
    assert jobs.provider_caps("typesafe")["provider"]["monthly_usd"] == Decimal(10)
    assert jobs.provider_caps("openai")["provider"]["monthly_usd"] == Decimal(90)
    assert jobs.provider_caps("typesafe")["global"]["monthly_usd"] == Decimal(90)


def _enable_proposer(monkeypatch, *, monthly_usd: str):
    values = {
        "permit_llm_proposer_enabled": True,
        "intelligence_enabled": True,
        "intelligence_mode": "advisory",
        "intelligence_openai_enabled": True,
        "intelligence_research_enabled": True,
        "openai_api_key": SecretStr("test-key-not-real"),
        "intelligence_enabled_contracts": "EQUIPMENT_PROPOSER_V1",
        "intelligence_equipment_model": "gpt-6.1-sol",
        "intelligence_equipment_priced_model_id": "gpt-6.1-sol",
        "intelligence_equipment_pricing_verified": True,
        "intelligence_equipment_input_usd_per_million": Decimal(2),
        "intelligence_equipment_output_usd_per_million": Decimal(10),
        "intelligence_equipment_max_output_tokens": 2000,
        "intelligence_max_active_calls": 2,
        "intelligence_max_call_usd": Decimal("0.25"),
        "intelligence_provider_caps": f'{{"openai": {{"monthly_usd": {monthly_usd}}}}}',
    }
    for scope in ("global", "provider", "model", "source", "project"):
        values[f"intelligence_{scope}_daily_calls"] = 100
        values[f"intelligence_{scope}_monthly_calls"] = 1000
        values[f"intelligence_{scope}_daily_usd"] = Decimal(5)
        values[f"intelligence_{scope}_monthly_usd"] = Decimal(90)
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)
    request = ep.build_request(
        model="gpt-6.1-sol", pages=[PageForProposal(1, "text")], max_output_tokens=2000
    )
    return {"request": request}, ep.cost_bound(request)


def test_dispatch_policy_enforces_the_provider_override(monkeypatch):
    payload, cost = _enable_proposer(monkeypatch, monthly_usd="90")
    ok = jobs._dispatch_policy(
        "EQUIPMENT_PROPOSER_V1", None, "openai", "gpt-6.1-sol", payload, cost
    )
    assert ok == (True, "")
    payload, cost = _enable_proposer(monkeypatch, monthly_usd="0.001")
    blocked = jobs._dispatch_policy(
        "EQUIPMENT_PROPOSER_V1", None, "openai", "gpt-6.1-sol", payload, cost
    )
    assert blocked == (False, "PROVIDER_MONTHLY_USD_CAP_INVALID")


def test_contract_must_be_allowlisted(monkeypatch):
    payload, cost = _enable_proposer(monkeypatch, monthly_usd="90")
    monkeypatch.setattr(settings, "intelligence_enabled_contracts", "EVIDENCE_SHADOW")
    result = jobs._dispatch_policy(
        "EQUIPMENT_PROPOSER_V1", None, "openai", "gpt-6.1-sol", payload, cost
    )
    assert result == (False, "CONTRACT_DISABLED")


@pytest.mark.parametrize(
    "reason, scope, period",
    [
        ("GLOBAL_DAILY_CAP_REACHED", "global", "daily"),
        ("PROVIDER_MONTHLY_USD_CAP_REACHED", "provider", "monthly"),
        ("SOURCE_DAILY_CAP_ZERO", "source", "daily"),
        ("PROJECT_MONTHLY_USD_CAP_INVALID", "project", "monthly"),
    ],
)
def test_capped_out_is_a_typed_state(reason, scope, period):
    fields = cap_fields(reason)
    assert fields["capped_out"] is True and fields["cap_state"] == "CAPPED_OUT"
    assert (fields["cap_scope"], fields["cap_period"], fields["cap_reason"]) == (
        scope,
        period,
        reason,
    )
    assert is_cap_reason(reason)


@pytest.mark.parametrize(
    "reason", ["", None, "CONTRACT_DISABLED", "PROVIDER_BILLING_QUARANTINED", "STALE_FENCE"]
)
def test_other_reasons_are_not_capped_out(reason):
    assert cap_fields(reason) == {} and not is_cap_reason(reason)


def test_alert_lists_near_cap_and_capped_out_spend():
    spend = {
        "rows": [
            {
                "scope": "provider:typesafe",
                "period": "monthly",
                "metric": "usd",
                "used": "8.50",
                "cap": "10",
                "fraction": 0.85,
                "level": "NEAR_CAP",
            },
            {
                "scope": "global:global",
                "period": "daily",
                "metric": "usd",
                "used": "5",
                "cap": "5",
                "fraction": 1.0,
                "level": "CAPPED_OUT",
            },
        ],
        "capped_out_jobs": {"hours": 48, "jobs": 3},
    }
    health = {"sources": [], "worker_liveness": "LIVE", "collection_freshness": "FRESH"}
    title, body, urgent = alerts.summarize(health, {}, spend)
    assert urgent and title == "GridLens: 3 problem(s)"
    assert "Spend near cap: provider:typesafe monthly USD 8.50/10 (85%)" in body
    assert "Spend CAPPED OUT: global:global daily USD 5/5 (100%)" in body
    assert "Capped-out intelligence jobs in last 48h: 3" in body


def test_alert_is_unchanged_without_spend():
    health = {"sources": [], "worker_liveness": "LIVE", "collection_freshness": "FRESH"}
    assert alerts.summarize(health)[2] is False
    assert (
        alerts.summarize(health, {}, {"rows": [], "capped_out_jobs": {"hours": 48, "jobs": 0}})[2]
        is False
    )


def test_default_threshold_is_eighty_percent():
    assert settings.intelligence_spend_alert_threshold == 0.8


def test_configured_passes_are_none_while_their_settings_are_off(monkeypatch):
    from gridlens.intelligence import permit_page_ocr

    assert ep.configured_proposer(source_id="s") is None
    assert (
        permit_page_ocr.configured_stage_ocr(pdf_path="x.pdf", source_url="u", source_id="s")
        is None
    )
    monkeypatch.setattr(settings, "permit_llm_proposer_enabled", True)
    assert ep.configured_proposer(source_id="s") is not None
