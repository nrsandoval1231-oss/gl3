import hashlib
from decimal import Decimal
from types import SimpleNamespace

from gridlens.integrations.intelligence_provider import ProviderResponseError
from gridlens.intelligence.intelligence_jobs import (
    _cost_bound,
    _openai_output_bound,
    _provider_error_quarantine_details,
    _serialized_request_bytes,
)
from gridlens.intelligence.titles import (
    MAX_OUTPUT_TOKENS,
    _activity_options,
    _assert_preloaded_evidence_sources_enabled,
    _role_options,
    title_request_payload,
    validate_title,
)
from gridlens.settings import settings


def sample_evidence():
    return {
        "evidence-a": {
            "id": "evidence-a",
            "title": "Cobalt Data Center expansion",
            "excerpt": (
                "Description: Not construction approved yet.\n"
                "Activity: Building substations for the Cobalt Data Center."
            ),
            "url": "https://example.test/source",
            "publisher": "City permits",
            "organization": "Cobalt Energy",
            "relationship_role": "asset_operator",
        },
        "evidence-b": {
            "id": "evidence-b",
            "title": "Cobalt Energy contractor filing",
            "excerpt": "The electrical contractor is Northstar Electric.",
            "url": "https://example.test/contractor",
            "publisher": "City permits",
            "organization": "Northstar Electric",
            "relationship_role": "contractor_construction",
        },
    }


def test_title_uses_cited_source_lines_and_source_role_labels():
    evidence = sample_evidence()
    roles = _role_options(evidence)
    activities = _activity_options(evidence)
    role_id = next(key for key, item in roles.items() if item["role"] == "asset_operator")
    activity_id = next(
        key for key, item in activities.items() if item["quote"].startswith("Description:")
    )
    result, citations = validate_title(
        {"role_option_id": role_id, "activity_option_id": activity_id},
        evidence,
        roles,
        activities,
        "Cobalt Data Center expansion",
    )
    assert result["title"] == (
        "Cobalt Data Center expansion - Cobalt Energy - asset operator - "
        "Description: Not construction approved yet."
    )
    assert any(item["quote"] == "Description: Not construction approved yet." for item in citations)


def test_generic_municipal_permit_identifier_is_not_preserved_as_project_name():
    evidence = {
        "evidence-a": {
            **sample_evidence()["evidence-a"],
            "title": "Austin permit 2026-127192 EP",
        }
    }
    activities = _activity_options(evidence)
    activity_id = next(
        key for key, option in activities.items() if option["quote"].startswith("Activity:")
    )
    result, citations = validate_title(
        {"role_option_id": None, "activity_option_id": activity_id},
        evidence,
        {},
        activities,
        "Austin permit 2026-127192 EP",
    )
    assert result["title"] == activities[activity_id]["quote"]
    assert all(item["quote"] != "Austin permit 2026-127192 EP" for item in citations)


def test_title_activity_options_exclude_identifier_metadata_and_keep_complete_long_description():
    long_description = (
        "Description: Construct a new manufacturing building with production floors,"
        " utility yards, electrical rooms, foundations, structural steel, distribution"
        " equipment, and commissioning before occupancy."
    )
    evidence = {
        "metadata": {
            **sample_evidence()["evidence-a"],
            "title": "Austin permit 2026-127192 EP",
            "excerpt": (
                "Permit number: 2026-127192 EP\n"
                "Address: 1212 Example Street, Austin, TX\n"
                "Phone: (512) 555-0100\n"
                f"{long_description}"
            ),
        }
    }
    activities = _activity_options(evidence)
    assert len(activities) == 1
    quote = next(iter(activities.values()))["quote"]
    assert quote == long_description
    assert len(quote) > 180
    assert "distribution equipment, and commissioning before occupancy" in quote


def test_title_activity_option_over_240_chars_is_omitted_without_cropping():
    quote = "Activity: " + "Build a new manufacturing facility and install power equipment. " * 5
    assert len(quote) > 240
    evidence = {"evidence-a": {**sample_evidence()["evidence-a"], "excerpt": quote}}
    assert _activity_options(evidence) == {}


def test_title_activity_options_preserve_full_negated_description():
    evidence = {
        "evidence-a": {
            **sample_evidence()["evidence-a"],
            "excerpt": "Description: Construction is not approved and no work is authorized.",
        }
    }
    activities = _activity_options(evidence)
    assert [option["quote"] for option in activities.values()] == [
        "Description: Construction is not approved and no work is authorized."
    ]


def test_unsupported_role_and_activity_ids_are_rejected():
    evidence = sample_evidence()
    roles, activities = _role_options(evidence), _activity_options(evidence)
    try:
        validate_title(
            {"role_option_id": "invented", "activity_option_id": None}, evidence, roles, activities
        )
    except ValueError as exc:
        assert str(exc) == "unknown_role_option"
    else:
        raise AssertionError("invented organization role was accepted")
    try:
        validate_title(
            {"role_option_id": None, "activity_option_id": "invented"}, evidence, roles, activities
        )
    except ValueError as exc:
        assert str(exc) == "unknown_activity_option"
    else:
        raise AssertionError("invented activity citation was accepted")


def test_owner_operator_option_is_required_over_a_contractor_option():
    evidence = sample_evidence()
    roles, activities = _role_options(evidence), _activity_options(evidence)
    contractor = next(key for key, item in roles.items() if item["role"].startswith("contractor"))
    try:
        validate_title(
            {"role_option_id": contractor, "activity_option_id": None}, evidence, roles, activities
        )
    except ValueError as exc:
        assert str(exc) == "role_not_preferred"
    else:
        raise AssertionError("contractor was selected despite a source-backed owner/operator")


def test_exact_request_builder_includes_full_quote_options_and_strict_schema():
    evidence = sample_evidence()
    activities = _activity_options(evidence)
    request = title_request_payload({"title": "Cobalt Data Center"}, evidence)
    request_text = request["input"][1]["content"][0]["text"]
    assert "Not construction approved yet." in request_text
    assert "activity_options" in request_text
    assert request["text"]["format"]["strict"] is True
    assert request["max_output_tokens"] == 240
    assert activities


def test_title_reservation_uses_the_canonical_request_and_full_output_ceiling(monkeypatch):
    evidence = sample_evidence()
    payload = {
        "title": {"title": "Cobalt Data Center"},
        "evidence": evidence,
        "roles": _role_options(evidence),
        "activities": _activity_options(evidence),
    }
    monkeypatch.setattr(
        settings, "intelligence_openai_reasoning_input_usd_per_million", Decimal("2")
    )
    monkeypatch.setattr(
        settings, "intelligence_openai_reasoning_output_usd_per_million", Decimal("8")
    )
    request = title_request_payload(
        payload["title"], evidence, payload["roles"], payload["activities"]
    )
    expected = (
        Decimal(_serialized_request_bytes(request)) * Decimal("2") + Decimal(240 * 8)
    ) / Decimal(1_000_000)
    assert _cost_bound("openai", "POWER_NEED_TITLE", payload) == expected
    assert _openai_output_bound("POWER_NEED_TITLE") == MAX_OUTPUT_TOKENS


def test_title_provider_error_quarantines_usage_above_its_request_limit(monkeypatch):
    monkeypatch.setattr(settings, "intelligence_openai_reasoning_max_output_tokens", 700)
    response = {
        "id": "resp-title-too-large",
        "model": settings.openai_brief_model,
        "usage": {"input_tokens": 100, "output_tokens": MAX_OUTPUT_TOKENS + 1},
        "output": [],
    }
    error = ProviderResponseError(
        "synthetic provider response",
        response_received=True,
        raw_response=response,
        reported_model=response["model"],
        reported_usage=response["usage"],
    )
    details = _provider_error_quarantine_details(
        error,
        provider="openai",
        task_type="POWER_NEED_TITLE",
        expected_model=settings.openai_brief_model,
    )
    assert details and details["reason"] == "ENFORCED_OUTPUT_BOUND_EXCEEDED"


def test_projection_source_gate_uses_preloaded_state_and_requires_exact_full_quote():
    _assert_preloaded_evidence_sources_enabled(
        {"evidence-a": {}},
        {"source-a": SimpleNamespace(enabled=True, registry_enabled=True)},
        {"evidence-a": "source-a"},
    )
    try:
        _assert_preloaded_evidence_sources_enabled(
            {"evidence-a": {}},
            {"source-a": SimpleNamespace(enabled=False, registry_enabled=True)},
            {"evidence-a": "source-a"},
        )
    except Exception as exc:
        from gridlens.intelligence.briefs import BriefUnavailable

        assert isinstance(exc, BriefUnavailable)
    else:
        raise AssertionError("disabled evidence source was allowed in projection")

    quote = "Owner/operator: Synthetic Grid LLC."
    key = f"buying-chain:chain-a:{hashlib.sha256(quote.encode()).hexdigest()[:12]}"
    _assert_preloaded_evidence_sources_enabled(
        {key: {"excerpt": quote}},
        {"source-a": SimpleNamespace(enabled=True, registry_enabled=True)},
        {},
        {
            "chain-a": {
                "retained_evidence_id": "retained-a",
                "source_id": "source-a",
                "public_research_provenance": False,
            }
        },
    )
    _assert_preloaded_evidence_sources_enabled(
        {key: {"excerpt": quote}},
        {},
        {},
        {
            "chain-a": {
                "retained_evidence_id": None,
                "source_id": None,
                "public_research_provenance": True,
            }
        },
    )

    evidence = sample_evidence()
    overlong = {
        **evidence,
        "evidence-a": {
            **evidence["evidence-a"],
            "organization": "Cobalt " + "x" * 200,
        },
    }
    long_roles, long_activities = _role_options(overlong), _activity_options(overlong)
    long_role_id = next(key for key, item in long_roles.items() if item["role"] == "asset_operator")
    long_activity_id = next(
        key for key, item in long_activities.items() if item["quote"].startswith("Description:")
    )
    result, citations = validate_title(
        {"role_option_id": long_role_id, "activity_option_id": long_activity_id},
        overlong,
        long_roles,
        long_activities,
        "Cobalt Data Center expansion",
    )
    exact_activity = long_activities[long_activity_id]["quote"]
    assert result["title"] == exact_activity
    assert any(citation["quote"] == exact_activity for citation in citations)
    assert "x" * 100 not in result["title"]
