"""WS2a: live Jev authority, abstention, fail-closed behaviour, pinning and passages.

No test here reaches a provider; callers are fakes and the network guards stay in force.
"""

import inspect
import json

import pytest

from gridlens.integrations.typesafe_evidence_judge import (
    QUESTIONS,
    SCHEMA_VERSION,
    TypesafeEvidenceJudge,
    parse_typesafe_answers,
)
from gridlens.intelligence import jev_live
from gridlens.intelligence.evidence_judge import (
    Choice,
    InvalidJudgment,
    Judgment,
)
from gridlens.intelligence.jev_live import (
    AUTHORITY_FIELDS,
    LABEL_FIELDS,
    Authority,
    Corroboration,
    LiveLabel,
    abstained_record,
    accepted_labels,
    corroborating_keys,
    derive_live_record,
    live_authorities,
    validate_live_record,
)
from gridlens.intelligence.jev_passages import WRAPPER_RESERVE_BYTES, bound_passage
from gridlens.intelligence.signal_adjudication import (
    _signal_questions,
    jev_request_payload,
    map_dimensions,
    validated_dimensions,
)
from gridlens.settings import Settings, settings

MODEL = "jev-1.13.0"


def _live(monkeypatch, *authorities):
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "jev_live_mode", True)
    for authority in authorities:
        monkeypatch.setattr(settings, f"jev_live_{authority}", True)


def _judgment(**overrides):
    values = {
        "relevant": "YES",
        "same_project": "YES",
        "event_type": "construction",
        "material_change": "YES",
        "power_relevance": "HIGH",
        "needs_deep_enrichment": "NO",
        "driver": "ELECTRIC",
        "novelty": "NEW",
        "side": "DEMAND",
        "lifecycle_phase": "permitted",
        "new_large_load": "YES",
        "document_route": "narrative",
    }
    values.update(overrides)
    return Judgment.model_validate(values)


def _probs(value=0.97, **overrides):
    names = [
        "relevant",
        "same_project",
        "event_type",
        "material_change",
        "power_relevance",
        "needs_deep_enrichment",
        "driver",
        "novelty",
        "side",
        "lifecycle_phase",
        "new_large_load",
        "document_route",
    ]
    probabilities = dict.fromkeys(names, value)
    probabilities.update(overrides)
    return probabilities


def _labels(record):
    return {item["field"]: item for item in record["labels"]}


# ---------------------------------------------------------------- settings


def _settings(**overrides):
    base = {"database_url": "x", "app_password_hash": "x", "session_secret": "x"}
    return Settings(_env_file=None, **{**base, **overrides})


def test_every_live_setting_defaults_off_and_pinned():
    configured = _settings()
    assert configured.jev_live_mode is False
    for name in ("routing", "labels", "materiality", "triage", "matching"):
        assert getattr(configured, f"jev_live_{name}") is False
    assert configured.jev_model == MODEL
    assert configured.jev_shadow_mode is True
    assert configured.jev_abstain_probability == 0.80
    assert configured.jev_match_probability == 0.95


@pytest.mark.parametrize(
    "overrides",
    [
        {"jev_live_routing": True},  # authority without live mode
        {"jev_live_mode": True},  # live without JEV_ENABLED
        {"jev_live_mode": True, "jev_enabled": True, "jev_model": "jev-latest"},
        {
            "jev_live_mode": True,
            "jev_enabled": True,
            "intelligence_typesafe_model": "jev-1.12.0",
        },
        {
            "jev_live_mode": True,
            "jev_enabled": True,
            "intelligence_typesafe_model": MODEL,
            "jev_abstain_probability": 0.9,
            "jev_match_probability": 0.8,
        },
        {  # input ceiling cannot hold overhead + reserve + a minimum passage
            "jev_live_mode": True,
            "jev_enabled": True,
            "intelligence_typesafe_model": MODEL,
            "intelligence_typesafe_max_total_billable_input_tokens": 5_000,
        },
    ],
)
def test_live_settings_validation_rejects_unsafe_combinations(overrides):
    with pytest.raises(ValueError):
        _settings(**overrides)


def test_probability_ordering_is_only_enforced_when_live_mode_is_on():
    shadow_only = _settings(jev_abstain_probability=0.9, jev_match_probability=0.8)
    assert shadow_only.jev_live_mode is False


def test_valid_live_configuration_is_accepted():
    configured = _settings(
        jev_enabled=True,
        jev_live_mode=True,
        jev_live_routing=True,
        intelligence_typesafe_model=MODEL,
    )
    assert configured.jev_live_routing is True


# ---------------------------------------------------------------- authority


def test_nothing_acts_when_live_mode_or_authorities_are_off(monkeypatch):
    monkeypatch.setattr(settings, "jev_enabled", True)
    assert live_authorities() == ()
    record = derive_live_record(_judgment(), _probs(), MODEL)
    assert record["labels"] == [] and record["authorities"] == []
    # Live mode on but no authority granted: still nothing acts.
    monkeypatch.setattr(settings, "jev_live_mode", True)
    assert derive_live_record(_judgment(), _probs(), MODEL)["labels"] == []
    assert accepted_labels({"live": record}) == {}


def test_each_authority_only_writes_its_own_fields(monkeypatch):
    _live(monkeypatch, "routing")
    labels = _labels(derive_live_record(_judgment(), _probs(), MODEL))
    assert set(labels) == {"document_route"}
    assert labels["document_route"]["outcome"] == "accepted"
    assert labels["document_route"]["effective_value"] == "narrative"
    assert labels["document_route"]["model"] == MODEL
    assert labels["document_route"]["probability"] == pytest.approx(0.97)

    _live(monkeypatch, "labels", "materiality", "triage")
    labels = _labels(derive_live_record(_judgment(), _probs(), MODEL))
    assert set(labels) == {
        "document_route",
        "event_type",
        "lifecycle_phase",
        "driver",
        "novelty",
        "side",
        "material_change",
        "new_large_load",
        "relevant",
    }
    assert "same_project" not in labels  # matching was not granted


def test_below_abstain_probability_and_unknown_answers_become_unknown(monkeypatch):
    _live(monkeypatch, "labels")
    record = derive_live_record(
        _judgment(driver="COMBUSTION", novelty="UNKNOWN"),
        _probs(driver=0.79, event_type=0.80),
        MODEL,
    )
    labels = _labels(record)
    assert labels["driver"]["outcome"] == "abstained"
    assert labels["driver"]["reason"] == "BELOW_ABSTAIN_PROBABILITY"
    assert labels["driver"]["effective_value"] == "UNKNOWN"
    assert labels["event_type"]["outcome"] == "accepted"  # exactly at the threshold acts
    assert labels["novelty"]["outcome"] == "abstained"
    assert labels["novelty"]["reason"] == "MODEL_ANSWERED_UNKNOWN"
    assert "driver" not in accepted_labels({"live": record})


def test_missing_probability_abstains(monkeypatch):
    _live(monkeypatch, "routing")
    record = derive_live_record(_judgment(), {}, MODEL)
    assert _labels(record)["document_route"]["reason"] == "PROBABILITY_MISSING"
    assert accepted_labels({"live": record}) == {}


def test_matching_requires_probability_and_a_deterministic_key(monkeypatch):
    _live(monkeypatch, "matching")
    keyed = Corroboration(("permit_number",))
    # High probability and a non-county key agree: acts.
    accepted = _labels(derive_live_record(_judgment(), _probs(same_project=0.96), MODEL, keyed))
    assert accepted["same_project"]["outcome"] == "accepted"
    assert accepted["same_project"]["corroboration"] == ["permit_number"]
    # County is only a supporting key: with a strong key it is recorded, alone it never acts.
    both = Corroboration(("county", "substation"))
    both_labels = _labels(derive_live_record(_judgment(), _probs(same_project=0.96), MODEL, both))
    assert both_labels["same_project"]["corroboration"] == ["county", "substation"]
    county_only = _labels(
        derive_live_record(
            _judgment(), _probs(same_project=0.99), MODEL, Corroboration(("county",))
        )
    )
    assert county_only["same_project"]["outcome"] == "abstained"
    assert county_only["same_project"]["reason"] == "NO_DETERMINISTIC_KEY_AGREES"
    assert county_only["same_project"]["effective_value"] == "UNKNOWN"
    # High probability, no deterministic key: UNKNOWN.
    no_key = _labels(derive_live_record(_judgment(), _probs(same_project=0.99), MODEL))
    assert no_key["same_project"]["outcome"] == "abstained"
    assert no_key["same_project"]["reason"] == "NO_DETERMINISTIC_KEY_AGREES"
    assert no_key["same_project"]["effective_value"] == "UNKNOWN"
    # Key agrees but probability is below the (higher) match threshold: UNKNOWN.
    low = _labels(derive_live_record(_judgment(), _probs(same_project=0.90), MODEL, keyed))
    assert low["same_project"]["reason"] == "BELOW_MATCH_PROBABILITY"
    # A NO or UNKNOWN answer never acts as a match decision.
    for value in ("NO", "UNKNOWN"):
        other = _labels(
            derive_live_record(
                _judgment(same_project=value), _probs(same_project=0.99), MODEL, keyed
            )
        )
        assert other["same_project"]["outcome"] == "abstained"


def test_corroborating_keys_never_agree_from_missing_or_inferred_data():
    project = {"county": "Travis", "substation": "Hutto North", "permit_number": "NSR-123456"}
    assert corroborating_keys(project, {}, "").keys == ()
    assert corroborating_keys({}, {"county": "Travis"}, "Travis County").keys == ()
    # County must be the evidence's own field, not found in prose.
    assert corroborating_keys(project, {}, "A site in Travis county").keys == ()
    agreed = corroborating_keys(
        project, {"county": " travis "}, "Permit NSR-123456 near the Hutto North substation"
    )
    assert set(agreed.keys) == {"county", "substation", "permit_number"}
    near = corroborating_keys(
        {"latitude": 30.27, "longitude": -97.74}, {"lat": 30.271, "lon": -97.739}
    )
    far = corroborating_keys({"latitude": 30.27, "longitude": -97.74}, {"lat": 31.0, "lon": -97.0})
    assert near.keys == ("coordinates",) and far.keys == ()
    # Too-short tokens are never matched against prose.
    assert corroborating_keys({"substation": "A1"}, {}, "substation A1").keys == ()


# ------------------------------------------------- structure: labels only


def test_live_label_cannot_carry_values_or_unauthorized_fields():
    good = {
        "authority": Authority.LABELS,
        "field": "driver",
        "jev_value": "ELECTRIC",
        "probability": 0.9,
        "model": MODEL,
        "outcome": "accepted",
        "reason": "x",
    }
    assert LiveLabel(**good).effective_value == "ELECTRIC"
    for bad in (
        {"field": "mw"},
        {"field": "quantity"},
        {"field": "demand_amount"},
        {"field": "same_project"},  # belongs to MATCHING, not LABELS
        {"jev_value": "150"},
        {"jev_value": "150 MW"},
        {"probability": 1.5},
        {"probability": float("nan")},
        {"model": "jev-latest"},
        {"outcome": "guessed"},
        {"jev_value": "UNKNOWN"},  # UNKNOWN can never be accepted
    ):
        with pytest.raises(ValueError):
            LiveLabel(**{**good, **bad})
    with pytest.raises(ValueError):
        LiveLabel(
            authority=Authority.MATCHING,
            field="same_project",
            jev_value="YES",
            probability=0.99,
            model=MODEL,
            outcome="accepted",
            reason="x",
        )  # corroborated tier cannot be accepted without a deterministic key


def test_label_fields_are_closed_vocabularies_and_a_value_cannot_be_expressed():
    from enum import StrEnum

    for authority, fields in AUTHORITY_FIELDS.items():
        for name, vocabulary in fields.items():
            assert issubclass(vocabulary, StrEnum), (authority, name)
            assert all(not str(item.value).replace(".", "").isdigit() for item in vocabulary)
            assert name in Judgment.model_fields
    forbidden = {"mw", "megawatts", "quantity", "rating", "units", "hp", "demand_mw", "amount"}
    assert not forbidden & set(Judgment.model_fields)
    assert not forbidden & LABEL_FIELDS
    # The parser rejects a number or a quantity smuggled in as a "choice".
    for smuggled in ("150", "150 MW", "12.5"):
        data = _response()
        data["answers"]["driver"].update(choice=smuggled, probabilities={smuggled: 1.0})
        with pytest.raises(InvalidJudgment):
            parse_typesafe_answers(data, expected_model=MODEL)


def test_live_module_has_no_path_to_values_or_canonical_rows():
    import ast

    tree = ast.parse(inspect.getsource(jev_live))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not {name for name in imported if "persistence" in name or "sqlalchemy" in name}
    assert not {name for name in imported if "equipment" in name or "evidence_package" in name}


def test_validate_live_record_rejects_value_bearing_or_unknown_keys(monkeypatch):
    _live(monkeypatch, "routing")
    record = derive_live_record(_judgment(), _probs(), MODEL)
    assert validate_live_record(record) is record
    with pytest.raises(ValueError):
        validate_live_record({**record, "equipment": {"mw": 20}})
    with pytest.raises(ValueError):
        validate_live_record({**record, "labels": [{**record["labels"][0], "mw": 20}]})
    with pytest.raises(ValueError):
        validate_live_record({**record, "labels": [{**record["labels"][0], "field": "mw"}]})


def test_accepted_labels_require_a_decided_pinned_record(monkeypatch):
    _live(monkeypatch, "routing")
    record = derive_live_record(_judgment(), _probs(), MODEL)
    assert accepted_labels({"live": record}) == {"document_route": "narrative"}
    assert accepted_labels({"live": {**record, "model": "jev-latest"}}) == {}
    assert accepted_labels({"live": abstained_record("PROVIDER_TIMEOUT", MODEL)}) == {}
    assert accepted_labels({}) == {} and accepted_labels(None) == {}


def test_accepted_labels_are_withdrawn_when_live_mode_or_the_authority_is_switched_off(
    monkeypatch,
):
    _live(monkeypatch, "routing", "labels")
    record = derive_live_record(_judgment(), _probs(), MODEL)
    stored = {"live": record}
    assert {"document_route", "driver"} <= set(accepted_labels(stored))
    # One authority off: only its labels are withdrawn.
    monkeypatch.setattr(settings, "jev_live_labels", False)
    assert set(accepted_labels(stored)) == {"document_route"}
    # Rollback (JEV_LIVE_MODE=false): every stored decision is withdrawn at once.
    monkeypatch.setattr(settings, "jev_live_mode", False)
    assert accepted_labels(stored) == {}
    monkeypatch.setattr(settings, "jev_live_mode", True)
    assert set(accepted_labels(stored)) == {"document_route"}
    # A stored decision from a different model than the current pin is not honoured.
    monkeypatch.setattr(settings, "jev_model", "jev-1.14.0")
    assert accepted_labels(stored) == {}


def test_derive_abstains_on_unpinned_model_and_on_too_short_passages(monkeypatch):
    _live(monkeypatch, "routing", "labels")
    record = derive_live_record(_judgment(), _probs(), "jev-1.14.0")
    assert record["outcome"] == "abstained" and record["labels"] == []
    for bounds in (
        {"abstract": {"chars_total": 5_000, "chars_sent": 0, "truncated": True}},
        {"abstract": {"chars_total": 5_000, "chars_sent": 150, "truncated": True}},
    ):
        record = derive_live_record(_judgment(), _probs(), MODEL, None, bounds)
        assert record["outcome"] == "abstained"
        assert record["reason"] == "PASSAGE_TRUNCATED_BELOW_MIN"
        assert record["labels"] and all(
            item["reason"] == "PASSAGE_TRUNCATED_BELOW_MIN" and item["outcome"] == "abstained"
            for item in record["labels"]
        )
        assert accepted_labels({"live": record}) == {}
    # A cut at or above the floor, or no cut at all, still decides.
    ok = {"abstract": {"chars_total": 5_000, "chars_sent": 200, "truncated": True}}
    assert derive_live_record(_judgment(), _probs(), MODEL, None, ok)["outcome"] == "decided"
    whole = {"abstract": {"chars_total": 40, "chars_sent": 40, "truncated": False}}
    assert derive_live_record(_judgment(), _probs(), MODEL, None, whole)["outcome"] == "decided"


def test_request_overhead_floor_covers_the_real_question_set():
    from gridlens.intelligence.jev_passages import REQUEST_OVERHEAD_FLOOR_BYTES

    assert len(json.dumps(QUESTIONS)) < REQUEST_OVERHEAD_FLOOR_BYTES // 2


def test_abstained_record_is_visible_and_empty(monkeypatch):
    _live(monkeypatch, "routing")
    record = abstained_record("LegacyCallBlocked:cap exhausted", MODEL)
    assert record["outcome"] == "abstained" and record["labels"] == []
    assert record["reason"].startswith("LegacyCallBlocked")
    assert record["authorities"] == ["routing"]


# ---------------------------------------------------- pinning and questions


def _response(model=MODEL):
    answers = {}
    for name, value in {
        "relevant": "YES",
        "same_project": "YES",
        "event_type": "construction",
        "material_change": "YES",
        "power_relevance": "HIGH",
        "needs_deep_enrichment": "NO",
        "driver": "ELECTRIC",
        "novelty": "NEW",
        "side": "DEMAND",
        "lifecycle_phase": "permitted",
        "new_large_load": "YES",
        "document_route": "narrative",
    }.items():
        answers[name] = {
            "type": "choice",
            "choice": value,
            "confidence": 0.9,
            "probabilities": {value: 0.9, "UNKNOWN": 0.1},
        }
    return {"model": model, "answers": answers, "usage": {"input_tokens": 9, "output_tokens": 1}}


def test_parser_returns_probability_of_each_chosen_label_and_enforces_pin():
    parsed = parse_typesafe_answers(_response(), expected_model=MODEL)
    assert parsed.model == MODEL
    assert parsed.probabilities["driver"] == pytest.approx(0.9)
    assert set(parsed.probabilities) == set(QUESTIONS)
    with pytest.raises(InvalidJudgment):
        parse_typesafe_answers(_response("jev-latest"), expected_model=MODEL)


def test_both_paths_default_to_the_pinned_model(monkeypatch):
    assert TypesafeEvidenceJudge("k").model == MODEL
    request = TypesafeEvidenceJudge.build_request({}, {}, [])
    assert request["model"] == MODEL
    assert jev_request_payload(_signal_state())["model"] == settings.jev_model == MODEL
    monkeypatch.setattr(settings, "jev_model", "jev-1.14.0")
    assert jev_request_payload(_signal_state())["model"] == "jev-1.14.0"
    assert SCHEMA_VERSION == "evidence-judge-v2"


def test_questions_are_about_demand_not_temporary_power():
    judge_text = json.dumps(QUESTIONS).casefold()
    signal_text = json.dumps(_signal_questions()).casefold()
    for text in (judge_text, signal_text):
        assert "temporary power" not in text
        assert "temporary_power" not in text
        assert "bridge" not in text
        assert "rental" not in text
    assert {"driver", "novelty", "side", "lifecycle_phase", "new_large_load"} <= set(QUESTIONS)
    assert {"electric_driver", "combustion_driver", "supply_side", "new_large_load"} <= set(
        _signal_questions()
    )
    # Questions never ask for a number.
    assert "temporary_power_hint" not in QUESTIONS


def test_stored_decisions_from_the_earlier_question_set_still_validate_and_map():
    # Results stored by evidence-judge-v1 carry temporary_power_hint and no demand labels.
    legacy = {
        "relevant": "YES",
        "same_project": "UNKNOWN",
        "event_type": "construction",
        "material_change": "UNKNOWN",
        "power_relevance": "MEDIUM",
        "temporary_power_hint": "UNKNOWN",
        "needs_deep_enrichment": "YES",
    }
    stored = Judgment.model_validate(legacy)
    assert stored.driver.value == "UNKNOWN" and stored.document_route.value == "UNKNOWN"
    legacy_dimensions = {
        "model": MODEL,
        "answers": {
            name: {"type": "noul", "noul": 0.9}
            for name in (
                "physical_project_event",
                "meaningful_new_activity",
                "commercial_relevance",
                "temporary_power_relevance",
                "routine_maintenance",
                "transient_event",
            )
        },
    }
    legacy_dimensions["answers"]["routine_maintenance"]["noul"] = 0.05
    legacy_dimensions["answers"]["transient_event"]["noul"] = 0.05
    dims = validated_dimensions(legacy_dimensions)
    assert map_dimensions(dims) == "SHOW"


def test_demand_dimensions_drive_the_display_policy():
    base = {
        "physical_project_event": 0.95,
        "meaningful_new_activity": 0.95,
        "new_large_load": 0.9,
        "electric_driver": 0.9,
        "combustion_driver": 0.1,
        "supply_side": 0.05,
        "routine_maintenance": 0.05,
        "transient_event": 0.02,
    }
    assert map_dimensions(base) == "SHOW"
    # Pure supply-side filings are not a demand signal: abstain to REVIEW, never SHOW.
    assert map_dimensions({**base, "supply_side": 0.95, "new_large_load": 0.4}) == "REVIEW"
    assert map_dimensions({**base, "new_large_load": 0.5}) == "REVIEW"
    assert map_dimensions({**base, "transient_event": 0.9}) == "HOLD"


# ---------------------------------------------------------------- passages


def _signal_state(abstract="An excerpt"):
    return {
        "title": "A retained event",
        "abstract": abstract,
        "url": "https://example.test/event",
        "published_at": "2026-09-29",
        "source_id": "test-source",
        "source_family": "news",
        "publisher": "Test publisher",
        "event_date": "unknown",
        "event_date_label": "unknown",
        "project_name": "Test project",
        "location": "Austin, TX",
        "asset_type": "data center",
        "lifecycle_state": "construction",
    }


def test_full_passages_are_sent_beyond_the_old_character_cuts():
    passage = ("The facility will add four electric chillers. " * 200).strip()
    assert len(passage) > 8_000
    signal = jev_request_payload(_signal_state(passage))
    assert signal["state"]["abstract"] == passage
    assert "passage_bounds" not in signal["state"]
    judged = TypesafeEvidenceJudge.build_request({}, {"abstract": passage}, [])
    assert judged["state"]["evidence"]["abstract"] == passage
    assert judged["state"]["evidence"]["passage_bounds"]["abstract"]["truncated"] is False


def test_typesafe_request_omits_party_graph_and_preserves_source_provenance():
    evidence = {
        "id": "evidence-1",
        "hash": "sha256:abc123",
        "url": "https://agency.example/permit/42",
        "abstract": "The facility will install four electric chillers.",
        "published_at": "2026-10-01",
    }
    request = TypesafeEvidenceJudge.build_request(
        {
            "project_id": "project-1",
            "state": {"lifecycle": "planned", "power_need": "unknown"},
            "organizations_and_roles": [
                {"person": "Jordan Example", "phone": "512-555-0123"},
                {"organization": "Northstar Grid LLC"},
            ],
        },
        evidence,
        [
            {
                "project_id": "project-2",
                "name": "Northstar Grid LLC",
                "contact_email": "ops@example.com",
            }
        ],
    )
    serialized = json.dumps(request)
    for private in ("Jordan Example", "512-555-0123", "ops@example.com", "Northstar Grid LLC"):
        assert private not in serialized
    assert request["state"]["evidence"]["hash"] == evidence["hash"]
    assert request["state"]["evidence"]["url"] == evidence["url"]
    assert request["state"]["evidence"]["abstract"] == evidence["abstract"]
    assert request["state"]["candidate_projects"] == [{"project_id": "project-2"}]


def test_typesafe_request_fails_closed_on_contact_inside_source_evidence():
    from gridlens.intelligence.provider_privacy import ProviderPrivacyError

    with pytest.raises(ProviderPrivacyError, match="sensitive or ambiguous"):
        TypesafeEvidenceJudge.build_request(
            {}, {"abstract": "Contact: Jordan Example at jordan@example.com."}, []
        )


def test_signal_request_fails_closed_without_rewriting_abstract():
    from gridlens.intelligence.provider_privacy import ProviderPrivacyError

    state = _signal_state("Contact: Jordan Example at jordan@example.com.")
    with pytest.raises(ProviderPrivacyError, match="sensitive or ambiguous"):
        jev_request_payload(state)


def test_signal_provider_boundary_withholds_unsafe_queued_evidence(monkeypatch):
    from gridlens.intelligence import signal_adjudication
    from gridlens.intelligence.provider_privacy import ProviderPrivacyError

    sent = []
    monkeypatch.setattr(
        signal_adjudication.intelligence_provider,
        "call_typesafe",
        lambda **kwargs: sent.append(kwargs),
    )
    with pytest.raises(ProviderPrivacyError):
        signal_adjudication._jev_call(
            _signal_state("Applicant: Jordan Example, jordan@example.com"),
            "unused-test-key",
            max_attempts=1,
        )
    assert sent == []
    assert signal_adjudication.failure_status(ProviderPrivacyError("safe generic message")) == (
        "privacy_withheld"
    )


def test_passages_respect_the_documented_ceiling_and_report_truncation(monkeypatch):
    passage = "Sentence about a new load. " * 2_000
    monkeypatch.setattr(settings, "jev_passage_max_bytes", 5_000)
    judged = TypesafeEvidenceJudge.build_request({}, {"abstract": passage}, [])
    bounds = judged["state"]["evidence"]["passage_bounds"]["abstract"]
    sent = judged["state"]["evidence"]["abstract"]
    assert bounds["truncated"] is True and bounds["chars_total"] == len(passage)
    assert bounds["chars_sent"] == len(sent) <= 5_000
    assert sent.endswith(". ") or sent.endswith(" ")  # cut on a boundary
    signal = jev_request_payload(_signal_state(passage))
    assert signal["state"]["passage_bounds"]["abstract"]["truncated"] is True


def test_total_input_ceiling_bounds_the_whole_request(monkeypatch):
    monkeypatch.setattr(settings, "jev_passage_max_bytes", 200_000)
    monkeypatch.setattr(settings, "intelligence_typesafe_max_total_billable_input_tokens", 12_000)
    passage = "x " * 100_000
    request = TypesafeEvidenceJudge.build_request({}, {"abstract": passage}, [])
    size = len(json.dumps(request, separators=(",", ":"), ensure_ascii=True).encode())
    assert size <= 12_000 - WRAPPER_RESERVE_BYTES + 600  # bounds metadata is small and fixed
    assert request["state"]["evidence"]["passage_bounds"]["abstract"]["truncated"] is True


def test_estimate_policy_request_is_within_the_limit_and_not_blocked(monkeypatch):
    from test_intelligence_processing import (
        _estimated_signal_configuration,
        _estimated_signal_payload,
    )

    from gridlens.intelligence import intelligence_jobs
    from gridlens.intelligence.intelligence_jobs import (
        TYPESAFE_SIGNAL_REQUEST_MAX_BYTES,
        _estimated_signal_policy_block_reason,
        _serialized_request_bytes,
    )

    observation_id = _estimated_signal_configuration(monkeypatch)
    for abstract in ("y " * 40_000, "short filing text", 'é"\\' * 20_000):
        payload = _estimated_signal_payload(observation_id)
        payload["state"]["abstract"] = abstract
        assert _estimated_signal_policy_block_reason(payload) == ""
        request = jev_request_payload(payload["state"], model="jev-1.13.0")
        assert _serialized_request_bytes(request) <= TYPESAFE_SIGNAL_REQUEST_MAX_BYTES
    assert intelligence_jobs._estimated_signal_policy_selected()
    # The cut is visible to the model and reported.
    long_request = jev_request_payload(
        {**_estimated_signal_payload(observation_id)["state"], "abstract": "y " * 40_000}
    )
    assert long_request["state"]["passage_bounds"]["abstract"]["truncated"] is True


def test_bound_passage_is_unicode_safe_and_reports_sizes():
    text = "é" * 500
    cut, meta = bound_passage(text, 100)
    assert meta["truncated"] is True and meta["chars_total"] == 500
    assert len(json.dumps(cut, ensure_ascii=True)) - 2 <= 100
    whole, meta = bound_passage("short", 100)
    assert whole == "short" and meta["truncated"] is False


# --------------------------------------------------------------- fail closed


def test_provider_errors_never_become_a_judgment():
    import httpx

    def timeout(*args, **kwargs):
        raise httpx.TimeoutException("bounded request timed out")

    judge = TypesafeEvidenceJudge("fixture-key", caller=timeout)
    with pytest.raises(httpx.TimeoutException):
        judge.judge({}, {"abstract": "x"}, [])

    class Malformed:
        def raise_for_status(self):
            pass

        def json(self):
            data = _response()
            data["answers"]["driver"]["probabilities"] = {"ELECTRIC": 0.2}
            return data

    judge = TypesafeEvidenceJudge("fixture-key", caller=lambda *a, **k: Malformed())
    with pytest.raises(InvalidJudgment):
        judge.judge({}, {"abstract": "x"}, [])


def test_choice_unknown_is_never_zero_or_a_guess():
    assert Choice.UNKNOWN.value == "UNKNOWN"
