import json
from uuid import uuid4

import pytest
from pydantic import SecretStr

from gridlens.integrations import intelligence_provider
from gridlens.intelligence.intelligence_jobs import (
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
    result, actual_model, input_tokens, output_tokens = _type_safe_result(
        {
            "model": "pinned-fixture-model",
            "answers": {
                "answer": {
                    "type": "choice",
                    "choice": choices[0],
                    "confidence": 1 / len(choices),
                    "probabilities": probabilities,
                }
            },
            "usage": {"input_tokens": 9, "output_tokens": 4},
        },
        contract_id,
    )
    assert result["authority"] == "ADVISORY_ONLY"
    assert result["answer"]["choice"] == choices[0]
    assert (actual_model, input_tokens, output_tokens) == ("pinned-fixture-model", 9, 4)


def test_typesafe_choice_rejects_wrong_keys_and_missing_usage():
    with pytest.raises(ValueError, match="shape"):
        _type_safe_result(
            {"model": "m", "answers": {"answer": {"type": "choice", "choice": "SAME"}}},
            "MATCH_ADVISORY_V1",
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
            "MATCH_ADVISORY_V1",
        )


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


def test_legacy_paid_routes_stay_blocked_until_migrated(monkeypatch):
    monkeypatch.setattr(settings, "intelligence_enabled", False)
    assert legacy_paid_path_block_reason() == "INTELLIGENCE_DISABLED"
    monkeypatch.setattr(settings, "intelligence_enabled", True)
    assert legacy_paid_path_block_reason() == "SHARED_LEDGER_MIGRATION_REQUIRED"


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
        "intelligence_typesafe_max_output_tokens": 100,
        "intelligence_typesafe_output_limit_verified": True,
    }.items():
        monkeypatch.setattr(settings, name, value)
    assert _enabled("LLM_ROUTE_V1")[0] is True
    assert _enabled("SOURCE_RELEVANCE_V1")[3] == "CONTRACT_DISABLED"
    monkeypatch.setattr(settings, "intelligence_typesafe_input_usd_per_million", 0)
    assert _enabled("LLM_ROUTE_V1")[3] == "TYPESAFE_OUTPUT_BOUND_OR_MODEL_PRICING_MISSING"
    monkeypatch.setattr(settings, "intelligence_typesafe_input_usd_per_million", 1)
    monkeypatch.setattr(settings, "intelligence_routing_policy_evaluated", False)
    assert _enabled("LLM_ROUTE_V1")[3] == "ROUTING_POLICY_NOT_EVALUATED_OR_AUTHORIZED"
