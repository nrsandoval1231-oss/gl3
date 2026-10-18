import json
from uuid import uuid4

import pytest
from pydantic import SecretStr

from gridlens.integrations import intelligence_provider
from gridlens.intelligence.intelligence_jobs import (
    MAX_CONTEXT_BYTES,
    _bound_grounded_payload,
    _cost_bound,
    _enabled,
    _type_safe_result,
    legacy_paid_path_block_reason,
)
from gridlens.intelligence.jev_contracts import CONTRACTS
from gridlens.settings import settings


@pytest.mark.parametrize("contract_id", sorted(CONTRACTS))
def test_typesafe_choice_results_require_exact_typed_probabilities(contract_id):
    choices = CONTRACTS[contract_id].choices
    probabilities = {choice: 1 / len(choices) for choice in choices}
    subject_key = (
        "candidate_id"
        if contract_id == "MATCH_ADVISORY_V1"
        else "party_id"
        if contract_id == "BUYER_ROLE_HINT_V1"
        else None
    )
    subject_id = str(uuid4())
    answer = {
        "type": "choice",
        "choice": choices[0],
        "confidence": 1 / len(choices),
        "probabilities": probabilities,
    }
    task_payload = None
    answers = {"answer": answer}
    if subject_key:
        answers = {subject_id: answer}
        context_key = (
            "deterministic_candidates" if contract_id == "MATCH_ADVISORY_V1" else "party_candidates"
        )
        task_payload = {"task_context": {context_key: [{subject_key: subject_id}]}}
    result, actual_model, input_tokens, output_tokens = _type_safe_result(
        {
            "model": "pinned-fixture-model",
            "answers": answers,
            "usage": {"input_tokens": 9, "output_tokens": 4},
        },
        contract_id,
        task_payload,
    )
    assert result["authority"] == "ADVISORY_ONLY"
    if subject_key:
        key = "match_advisories" if contract_id == "MATCH_ADVISORY_V1" else "buyer_role_advisories"
        result_subject_key = (
            "candidate_project_id" if contract_id == "MATCH_ADVISORY_V1" else "party_id"
        )
        assert result[key] == [
            {
                result_subject_key: subject_id,
                "choice": choices[0],
                "confidence": 1 / len(choices),
                "probabilities": probabilities,
            }
        ]
    else:
        assert result["answer"]["choice"] == choices[0]
    assert (actual_model, input_tokens, output_tokens) == ("pinned-fixture-model", 9, 4)


def test_typesafe_choice_rejects_wrong_keys_and_missing_usage():
    with pytest.raises(ValueError, match="shape"):
        _type_safe_result(
            {"model": "m", "answers": {"answer": {"type": "choice", "choice": "SAME"}}},
            "SOURCE_RELEVANCE_V1",
        )
    with pytest.raises(ValueError, match="probabilities"):
        _type_safe_result(
            {
                "model": "m",
                "answers": {
                    "answer": {
                        "type": "choice",
                        "choice": "SAME",
                        "confidence": 1.0,
                        "probabilities": {"SAME": 1.0},
                    }
                },
                "usage": {},
            },
            "SOURCE_RELEVANCE_V1",
        )


def test_match_advisory_requires_exact_uuid_answer_set_and_keeps_negative_candidate():
    first, second = str(uuid4()), str(uuid4())
    candidates = [
        {"candidate_id": first, "deterministic_decision": "REJECTED"},
        {"candidate_id": second, "deterministic_decision": "CANDIDATE"},
    ]
    payload = {"task_context": {"deterministic_candidates": candidates}}
    answer = {
        "type": "choice",
        "choice": "DIFFERENT",
        "confidence": 0.8,
        "probabilities": {"SAME": 0.1, "DIFFERENT": 0.8, "UNRESOLVED": 0.1},
    }
    good = {"model": "m", "answers": {first: answer, second: answer}}
    result, *_ = _type_safe_result(good, "MATCH_ADVISORY_V1", payload)
    assert [item["candidate_project_id"] for item in result["match_advisories"]] == sorted(
        (first, second)
    )
    for malformed in (
        {"model": "m", "answers": {first: answer}},
        {"model": "m", "answers": {first: answer, second: answer, str(uuid4()): answer}},
    ):
        with pytest.raises(ValueError, match="exactly match"):
            _type_safe_result(malformed, "MATCH_ADVISORY_V1", payload)


def test_typesafe_probabilities_accept_official_rounded_approximation():
    result, *_ = _type_safe_result(
        {
            "model": "fixture-model",
            "answers": {
                "answer": {
                    "type": "choice",
                    "choice": "RELEVANT",
                    "confidence": 0.33,
                    "probabilities": {"RELEVANT": 0.33, "IRRELEVANT": 0.33, "UNCERTAIN": 0.33},
                }
            },
        },
        "SOURCE_RELEVANCE_V1",
    )
    assert result["answer"]["choice"] == "RELEVANT"


def test_openai_transport_uses_bounded_completed_structured_output(monkeypatch):
    evidence_id = str(uuid4())
    output = {
        "candidates": [],
        "hypotheses": [],
        "contradictions": [],
        "unresolved_questions": [],
        "candidate_orgs": [],
        "proposed_queries": [],
        "suggested_pursuit": None,
    }
    captured = {}

    def fake_post(url, *, headers, payload):
        captured.update(url=url, headers=headers, payload=payload)
        return (
            {
                "status": "completed",
                "model": "pinned-openai-fixture",
                "output": [{"content": [{"type": "output_text", "text": json.dumps(output)}]}],
                "usage": {"input_tokens": 18, "output_tokens": 2},
            },
            "req-fixture",
            37,
        )

    monkeypatch.setattr(intelligence_provider, "_post_json", fake_post)
    response = intelligence_provider.call_openai(
        api_key="fixture-only",
        model="pinned-openai-fixture",
        instructions="Only use retained evidence.",
        input_payload={"evidence_id": evidence_id},
        max_output_tokens=1200,
    )
    assert captured["url"].endswith("/v1/responses")
    assert captured["payload"]["store"] is False
    assert captured["payload"]["tools"] == []
    assert captured["payload"]["max_output_tokens"] == 1200
    assert captured["payload"]["text"]["format"]["strict"] is True
    assert response["provider_response_id"] == "req-fixture"
    assert response["latency_ms"] == 37
    assert response["output"] == output


def test_openai_noncompleted_response_is_conclusive_not_a_valid_result(monkeypatch):
    monkeypatch.setattr(
        intelligence_provider,
        "_post_json",
        lambda *args, **kwargs: ({"status": "incomplete", "output": []}, "req-incomplete", 2),
    )
    with pytest.raises(intelligence_provider.ProviderResponseError) as error:
        intelligence_provider.call_openai(
            api_key="fixture-only",
            model="fixture",
            instructions="Do not browse.",
            input_payload={},
            max_output_tokens=100,
        )
    assert error.value.request_id == "req-incomplete"
    assert error.value.conclusive is True


def test_legacy_paid_gate_tracks_global_disabled_state(monkeypatch):
    monkeypatch.setattr(settings, "intelligence_enabled", False)
    assert legacy_paid_path_block_reason() == "INTELLIGENCE_DISABLED"
    monkeypatch.setattr(settings, "intelligence_enabled", True)
    monkeypatch.setattr(settings, "intelligence_mode", "advisory")
    monkeypatch.setattr(settings, "intelligence_max_active_calls", 1)
    monkeypatch.setattr(settings, "intelligence_max_call_usd", 1)
    assert legacy_paid_path_block_reason() is None


def test_bounded_routing_requires_evaluated_policy_authorization_and_contract(monkeypatch):
    for name, value in {
        "intelligence_enabled": True,
        "intelligence_mode": "bounded_routing",
        "intelligence_typesafe_enabled": True,
        "intelligence_enabled_contracts": "LLM_ROUTE_V1",
        "intelligence_routing_policy_id": "evaluated-policy-v1",
        "intelligence_routing_policy_evaluated": True,
        "intelligence_bounded_routing_authorized": True,
        "jev_enabled": True,
        "typesafe_api_key": SecretStr("fixture-only"),
        "intelligence_typesafe_model": "pinned-fixture-model",
        "intelligence_typesafe_priced_model_id": "pinned-fixture-model",
        "intelligence_typesafe_pricing_verified": True,
        "intelligence_typesafe_input_usd_per_million": 1,
        "intelligence_typesafe_output_usd_per_million": 0,
        "intelligence_typesafe_max_output_tokens": 0,
        "intelligence_typesafe_output_limit_verified": False,
    }.items():
        monkeypatch.setattr(settings, name, value)
    assert _enabled("LLM_ROUTE_V1")[0] is True
    assert _enabled("SOURCE_RELEVANCE_V1")[3] == "CONTRACT_DISABLED"
    monkeypatch.setattr(settings, "intelligence_typesafe_input_usd_per_million", 0)
    assert _enabled("LLM_ROUTE_V1")[3] == "TYPESAFE_INPUT_PRICING_OR_MODEL_MISSING"
    monkeypatch.setattr(settings, "intelligence_typesafe_input_usd_per_million", 1)
    monkeypatch.setattr(settings, "intelligence_routing_policy_evaluated", False)
    assert _enabled("LLM_ROUTE_V1")[3] == "ROUTING_POLICY_NOT_EVALUATED_OR_AUTHORIZED"


def test_pairwise_match_dispatch_is_disabled_without_candidate_context(monkeypatch):
    monkeypatch.setattr(settings, "intelligence_enabled_contracts", "MATCH_ADVISORY_V1")
    assert _enabled("MATCH_ADVISORY_V1")[3] == "MATCH_CONTEXT_INCOMPLETE"


def test_typesafe_cost_bound_prices_exact_jev_request_input_only(monkeypatch):
    from decimal import Decimal

    from gridlens.intelligence.signal_adjudication import jev_request_payload

    monkeypatch.setattr(settings, "intelligence_typesafe_model", "pinned-fixture-model")
    monkeypatch.setattr(settings, "intelligence_typesafe_input_usd_per_million", Decimal("2"))
    monkeypatch.setattr(settings, "intelligence_typesafe_output_usd_per_million", Decimal("99"))
    state = dict.fromkeys(
        [
            "title",
            "abstract",
            "url",
            "published_at",
            "source_id",
            "source_family",
            "publisher",
            "event_date",
            "event_date_label",
            "project_name",
            "location",
            "asset_type",
            "lifecycle_state",
        ],
        "Bounded fixture",
    )
    state["title"] = "Fixture"
    request = jev_request_payload(state, model="pinned-fixture-model")
    expected_bytes = len(
        json.dumps(
            request,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    )
    actual = _cost_bound(
        "typesafe",
        "SIGNAL_ADJUDICATION",
        {"state": state, "model": "pinned-fixture-model", "contract": "signal-display-v2"},
    )
    assert actual == Decimal(expected_bytes * 2) / Decimal(1_000_000)


def test_grounding_context_keeps_four_kb_and_marks_bounded_thirty_kb_partial():
    evidence = {
        "id": str(uuid4()),
        "content_hash": "a" * 64,
        "title": "Retained source",
        "abstract": "x" * 4000,
        "publisher": "Fixture",
    }
    base = {"task_type": "GROUNDED_DOSSIER", "need": {}, "question": {}, "evidence": [evidence]}
    small = _bound_grounded_payload(base)
    assert small["evidence"][0]["abstract"] == evidence["abstract"]
    assert small["context_truncation"] == {"partial": False, "text_bytes_removed": 0}

    large = {
        **base,
        "evidence": [{**evidence, "abstract": "y" * 30_000}],
        "need": {"accepted_source_claims": "z" * 20_000},
    }
    bounded = _bound_grounded_payload(large)
    encoded = json.dumps(bounded, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    assert len(encoded) <= MAX_CONTEXT_BYTES
    assert bounded["evidence"][0]["text_truncated"] is True
    assert bounded["evidence"][0]["retained_text_status"] == "partial_retained_excerpt"
    assert bounded["context_truncation"]["partial"] is True
    assert 0 < len(bounded["evidence"][0]["abstract"]) < 30_000


def test_grounded_response_schema_requires_explicit_unit_date_and_attribution_fields():
    schema = intelligence_provider._grounded_schema()
    candidate = schema["properties"]["candidates"]["items"]
    assert {
        "original_value",
        "original_unit",
        "precision",
        "date_precision",
        "speaker",
        "speaker_organization",
        "speaker_role",
    } <= set(candidate["required"])
    assert candidate["additionalProperties"] is False
