import json
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from gridlens.integrations import intelligence_provider
from gridlens.intelligence.intelligence_jobs import (
    MAX_CONTEXT_BYTES,
    _billing_policy_identity,
    _bound_grounded_payload,
    _cost_bound,
    _enabled,
    _provider_error_quarantine_details,
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
    raw = {
        "status": "incomplete",
        "model": "fixture",
        "usage": {"input_tokens": 17, "output_tokens": 2},
        "output": [],
    }
    monkeypatch.setattr(
        intelligence_provider,
        "_post_json",
        lambda *args, **kwargs: (raw, "req-incomplete", 2),
    )
    with pytest.raises(intelligence_provider.ProviderResponseError) as error:
        intelligence_provider.call_openai_request(
            api_key="fixture-only", request={"model": "fixture"}
        )
    assert error.value.request_id == "req-incomplete"
    assert error.value.conclusive is True
    assert error.value.response_received is True
    assert error.value.response_status is None
    assert error.value.raw_response is raw
    assert error.value.reported_model == "fixture"
    assert error.value.reported_usage == raw["usage"]


def test_provider_transport_recursion_error_keeps_received_response_metadata(monkeypatch):
    class Response:
        status_code = 200
        headers = {"x-request-id": "req-recursive-raw"}
        request = httpx.Request("POST", "https://provider.invalid")
        stream = httpx.ByteStream(b"{}")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def iter_bytes(self):
            yield from self.stream

    class Client:
        def __init__(self, *, timeout):
            del timeout
            self._transport = type("Transport", (), {"_pool": type("Pool", (), {})()})()
            self._mounts = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def stream(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(intelligence_provider.httpx, "Client", Client)
    monkeypatch.setattr(
        intelligence_provider.json, "loads", lambda _body: (_ for _ in ()).throw(RecursionError())
    )
    with pytest.raises(intelligence_provider.ProviderResponseError) as error:
        intelligence_provider._post_json("https://provider.invalid", headers={}, payload={})
    assert error.value.response_received is True
    assert error.value.response_status == 200
    assert error.value.request_id == "req-recursive-raw"
    assert error.value.raw_response_size == 2
    assert error.value.raw_response_sha256 is not None


def test_openai_structured_output_recursion_error_keeps_received_response_metadata(monkeypatch):
    raw = {
        "id": "resp-recursive-structured",
        "status": "completed",
        "model": "fixture",
        "usage": {"input_tokens": 17, "output_tokens": 2},
        "output": [{"content": [{"type": "output_text", "text": "[" * 1500}]}],
    }
    monkeypatch.setattr(
        intelligence_provider,
        "_post_json",
        lambda *args, **kwargs: (raw, "req-recursive-structured", 2),
    )
    with pytest.raises(intelligence_provider.ProviderResponseError) as error:
        intelligence_provider.call_openai_request(
            api_key="fixture-only", request={"model": "fixture"}
        )
    assert error.value.response_received is True
    assert error.value.raw_response is raw
    assert error.value.reported_model == "fixture"
    assert error.value.reported_usage == raw["usage"]


@pytest.mark.parametrize("usage", ["invalid", [], 0, False])
def test_openai_present_nondict_usage_is_received_metadata_error(monkeypatch, usage):
    raw = {
        "id": "resp-invalid-usage",
        "status": "completed",
        "model": "fixture",
        "usage": usage,
        "output": [{"content": [{"type": "output_text", "text": "{}"}]}],
    }
    monkeypatch.setattr(
        intelligence_provider,
        "_post_json",
        lambda *args, **kwargs: (raw, "req-invalid-usage", 2),
    )
    with pytest.raises(intelligence_provider.ProviderResponseError) as error:
        intelligence_provider.call_openai_request(
            api_key="fixture-only", request={"model": "fixture"}
        )
    assert error.value.response_received is True
    assert error.value.raw_response is raw
    assert error.value.reported_usage is None


@pytest.mark.parametrize("usage_field", [{}, {"usage": None}])
def test_openai_missing_or_null_usage_keeps_valid_structured_result(monkeypatch, usage_field):
    raw = {
        "status": "completed",
        "model": "fixture",
        "output": [{"content": [{"type": "output_text", "text": "{}"}]}],
        **usage_field,
    }
    monkeypatch.setattr(
        intelligence_provider, "_post_json", lambda *args, **kwargs: (raw, "req-null-usage", 2)
    )
    result = intelligence_provider.call_openai_request(
        api_key="fixture-only", request={"model": "fixture"}
    )
    assert result["output"] == {}
    assert result["input_tokens"] is None and result["output_tokens"] is None


def test_openai_nondict_structured_output_is_received_metadata_error(monkeypatch):
    raw = {
        "status": "completed",
        "model": "fixture",
        "usage": {"input_tokens": 17, "output_tokens": 2},
        "output": [{"content": [{"type": "output_text", "text": "[]"}]}],
    }
    monkeypatch.setattr(
        intelligence_provider, "_post_json", lambda *args, **kwargs: (raw, "req-list-output", 2)
    )
    with pytest.raises(intelligence_provider.ProviderResponseError) as error:
        intelligence_provider.call_openai_request(
            api_key="fixture-only", request={"model": "fixture"}
        )
    assert error.value.response_received is True
    assert error.value.reported_model == "fixture"
    assert error.value.reported_usage == raw["usage"]


def test_oversized_received_response_retains_raw_and_request_identity_metadata():
    raw = {
        "id": "resp-oversized",
        "model": "pinned-openai-fixture",
        "usage": {"input_tokens": 17, "output_tokens": 2},
        "output": "x" * 70_000,
    }
    error = intelligence_provider.ProviderResponseError(
        "synthetic oversized response",
        request_id="req-oversized",
        response_received=True,
        raw_response=raw,
        reported_model=raw["model"],
        reported_usage=raw["usage"],
        raw_response_sha256="a" * 64,
        raw_response_size=70_100,
    )
    details = _provider_error_quarantine_details(
        error,
        provider="openai",
        task_type="OCR_EXTRACTION",
        expected_model="pinned-openai-fixture",
    )
    assert details and details["reason"] == "RESPONSE_TOO_LARGE"
    response = details["response_payload"]
    assert response["omitted"] == "MAX_RESULT_BYTES"
    assert response["provider_response_id"] == "resp-oversized"
    assert response["provider_request_id"] == "req-oversized"
    assert response["raw_response_sha256"] == "a" * 64
    assert response["raw_response_bytes"] == 70_100
    assert "identity_sha256" in response


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
        "intelligence_typesafe_billing_mode": "input_only",
        "intelligence_typesafe_billing_model_id": "pinned-fixture-model",
        "intelligence_typesafe_billing_contract_id": "systemone-v1",
        "intelligence_typesafe_billing_policy_id": "typesafe-total-input-ceiling-v1",
        "intelligence_typesafe_billing_reference": "synthetic://fixture/typesafe-input-only-total-input-ceiling",
        "intelligence_typesafe_billing_verified": True,
        "intelligence_typesafe_max_total_billable_input_tokens": 10_000,
        "intelligence_typesafe_total_input_bound_verified": True,
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


def test_typesafe_cost_bound_reserves_full_attested_total_input_ceiling(monkeypatch):
    monkeypatch.setattr(settings, "intelligence_typesafe_model", "pinned-fixture-model")
    monkeypatch.setattr(settings, "intelligence_typesafe_input_usd_per_million", Decimal("2"))
    monkeypatch.setattr(settings, "intelligence_typesafe_output_usd_per_million", Decimal("0"))
    monkeypatch.setattr(settings, "intelligence_typesafe_billing_mode", "input_only")
    monkeypatch.setattr(settings, "intelligence_typesafe_billing_model_id", "pinned-fixture-model")
    monkeypatch.setattr(settings, "intelligence_typesafe_billing_contract_id", "systemone-v1")
    monkeypatch.setattr(
        settings,
        "intelligence_typesafe_billing_policy_id",
        "typesafe-total-input-ceiling-v1",
    )
    monkeypatch.setattr(
        settings,
        "intelligence_typesafe_billing_reference",
        "synthetic://fixture/typesafe-input-only-total-input-ceiling-123456",
    )
    monkeypatch.setattr(settings, "intelligence_typesafe_billing_verified", True)
    monkeypatch.setattr(settings, "intelligence_typesafe_max_total_billable_input_tokens", 123_456)
    monkeypatch.setattr(settings, "intelligence_typesafe_total_input_bound_verified", True)
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
    actual = _cost_bound(
        "typesafe",
        "SIGNAL_ADJUDICATION",
        {"state": state, "model": "pinned-fixture-model", "contract": "signal-display-v2"},
    )
    assert actual == Decimal(123_456 * 2) / Decimal(1_000_000)


def test_typesafe_output_charge_and_numeric_output_cap_do_not_pass_without_transport_bound(
    monkeypatch,
):
    monkeypatch.setattr(settings, "intelligence_enabled", True)
    monkeypatch.setattr(settings, "intelligence_mode", "advisory")
    monkeypatch.setattr(settings, "intelligence_enabled_contracts", "SIGNAL_ADJUDICATION")
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "intelligence_typesafe_enabled", True)
    monkeypatch.setattr(settings, "typesafe_api_key", SecretStr("synthetic-fixture-only"))
    monkeypatch.setattr(settings, "intelligence_typesafe_model", "pinned-fixture-model")
    monkeypatch.setattr(settings, "intelligence_typesafe_priced_model_id", "pinned-fixture-model")
    monkeypatch.setattr(settings, "intelligence_typesafe_pricing_verified", True)
    monkeypatch.setattr(settings, "intelligence_typesafe_input_usd_per_million", Decimal("2"))
    monkeypatch.setattr(settings, "intelligence_typesafe_output_usd_per_million", Decimal("99"))
    monkeypatch.setattr(settings, "intelligence_typesafe_max_output_tokens", 500)
    monkeypatch.setattr(settings, "intelligence_typesafe_output_limit_verified", True)
    monkeypatch.setattr(settings, "intelligence_typesafe_billing_mode", "input_only")
    monkeypatch.setattr(settings, "intelligence_typesafe_billing_model_id", "pinned-fixture-model")
    monkeypatch.setattr(settings, "intelligence_typesafe_billing_contract_id", "systemone-v1")
    monkeypatch.setattr(
        settings,
        "intelligence_typesafe_billing_policy_id",
        "typesafe-total-input-ceiling-v1",
    )
    monkeypatch.setattr(
        settings,
        "intelligence_typesafe_billing_reference",
        "synthetic://fixture/typesafe-input-only-total-input-ceiling-10000",
    )
    monkeypatch.setattr(settings, "intelligence_typesafe_billing_verified", True)
    monkeypatch.setattr(settings, "intelligence_typesafe_max_total_billable_input_tokens", 10_000)
    monkeypatch.setattr(settings, "intelligence_typesafe_total_input_bound_verified", True)
    assert _enabled("SIGNAL_ADJUDICATION")[3] == "TYPESAFE_OUTPUT_BOUND_UNVERIFIED"
    assert _cost_bound("typesafe", "SIGNAL_ADJUDICATION", {"state": {}}) == 0


def test_typesafe_missing_billing_attestation_fails_closed_and_identity_tracks_proof(monkeypatch):
    for name, value in {
        "intelligence_enabled": True,
        "intelligence_mode": "advisory",
        "intelligence_enabled_contracts": "SIGNAL_ADJUDICATION",
        "jev_enabled": True,
        "intelligence_typesafe_enabled": True,
        "typesafe_api_key": SecretStr("synthetic-fixture-only"),
        "intelligence_typesafe_model": "pinned-fixture-model",
        "intelligence_typesafe_priced_model_id": "pinned-fixture-model",
        "intelligence_typesafe_pricing_verified": True,
        "intelligence_typesafe_input_usd_per_million": Decimal("2"),
        "intelligence_typesafe_output_usd_per_million": Decimal("0"),
        "intelligence_typesafe_billing_mode": "unknown",
        "intelligence_typesafe_billing_model_id": "",
        "intelligence_typesafe_billing_contract_id": "",
        "intelligence_typesafe_billing_policy_id": "",
        "intelligence_typesafe_billing_reference": "",
        "intelligence_typesafe_billing_verified": False,
        "intelligence_typesafe_max_total_billable_input_tokens": 0,
        "intelligence_typesafe_total_input_bound_verified": False,
        "intelligence_typesafe_max_output_tokens": 500,
        "intelligence_typesafe_output_limit_verified": True,
    }.items():
        monkeypatch.setattr(settings, name, value)
    assert (
        _enabled("SIGNAL_ADJUDICATION")[3]
        == "TYPESAFE_BILLING_OR_INPUT_BOUND_PROOF_MISSING_OR_MISMATCHED"
    )

    monkeypatch.setattr(settings, "intelligence_typesafe_billing_mode", "input_only")
    monkeypatch.setattr(settings, "intelligence_typesafe_billing_model_id", "pinned-fixture-model")
    monkeypatch.setattr(settings, "intelligence_typesafe_billing_contract_id", "systemone-v1")
    monkeypatch.setattr(
        settings,
        "intelligence_typesafe_billing_policy_id",
        "typesafe-total-input-ceiling-v1",
    )
    monkeypatch.setattr(
        settings,
        "intelligence_typesafe_billing_reference",
        "synthetic://fixture/typesafe-input-only-total-input-ceiling-10000",
    )
    monkeypatch.setattr(settings, "intelligence_typesafe_billing_verified", True)
    monkeypatch.setattr(settings, "intelligence_typesafe_max_total_billable_input_tokens", 10_000)
    assert (
        _enabled("SIGNAL_ADJUDICATION")[3]
        == "TYPESAFE_BILLING_OR_INPUT_BOUND_PROOF_MISSING_OR_MISMATCHED"
    )
    monkeypatch.setattr(settings, "intelligence_typesafe_total_input_bound_verified", True)
    monkeypatch.setattr(settings, "intelligence_typesafe_billing_model_id", "different-model")
    assert (
        _enabled("SIGNAL_ADJUDICATION")[3]
        == "TYPESAFE_BILLING_OR_INPUT_BOUND_PROOF_MISSING_OR_MISMATCHED"
    )
    monkeypatch.setattr(settings, "intelligence_typesafe_billing_model_id", "pinned-fixture-model")
    monkeypatch.setattr(settings, "intelligence_typesafe_billing_policy_id", "stale-policy-v0")
    assert (
        _enabled("SIGNAL_ADJUDICATION")[3]
        == "TYPESAFE_BILLING_OR_INPUT_BOUND_PROOF_MISSING_OR_MISMATCHED"
    )
    monkeypatch.setattr(
        settings, "intelligence_typesafe_billing_policy_id", "typesafe-total-input-ceiling-v1"
    )
    before = _billing_policy_identity("typesafe", "pinned-fixture-model")
    assert before and before["response_guard_policy"] == "exact-model-usage-v1"
    openai_identity = _billing_policy_identity("openai", "pinned-openai-model")
    assert openai_identity and openai_identity["response_guard_policy"] == "exact-model-usage-v1"
    assert openai_identity["provider_model"] == "pinned-openai-model"
    assert openai_identity["priced_model_id"] == (
        settings.intelligence_openai_reasoning_priced_model_id
    )
    assert openai_identity["max_output_tokens"] == str(
        settings.intelligence_openai_reasoning_max_output_tokens
    )
    assert _billing_policy_identity("openai", "other-openai-model") != _billing_policy_identity(
        "openai", "pinned-openai-model"
    )
    openai_before_rate_change = _billing_policy_identity(
        "openai", "pinned-openai-model", "GROUNDED_DOSSIER"
    )
    monkeypatch.setattr(
        settings,
        "intelligence_openai_reasoning_input_usd_per_million",
        settings.intelligence_openai_reasoning_input_usd_per_million + Decimal("0.01"),
    )
    assert openai_before_rate_change != _billing_policy_identity(
        "openai", "pinned-openai-model", "GROUNDED_DOSSIER"
    )
    monkeypatch.setattr(
        settings, "intelligence_typesafe_billing_reference", "synthetic://fixture/changed-proof"
    )
    after = _billing_policy_identity("typesafe", "pinned-fixture-model")
    assert before != after


def test_missing_typesafe_proof_blocks_legacy_call_before_provider_invocation(monkeypatch):
    from gridlens.integrations.legacy_calls import LegacyCallBlocked, perform_legacy_call

    monkeypatch.setattr(settings, "intelligence_enabled", True)
    monkeypatch.setattr(settings, "intelligence_mode", "advisory")
    monkeypatch.setattr(settings, "intelligence_enabled_contracts", "SIGNAL_ADJUDICATION")
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "intelligence_typesafe_enabled", True)
    monkeypatch.setattr(settings, "typesafe_api_key", SecretStr("synthetic-fixture-only"))
    monkeypatch.setattr(settings, "intelligence_typesafe_model", "pinned-fixture-model")
    monkeypatch.setattr(settings, "intelligence_typesafe_priced_model_id", "pinned-fixture-model")
    monkeypatch.setattr(settings, "intelligence_typesafe_pricing_verified", True)
    monkeypatch.setattr(settings, "intelligence_typesafe_input_usd_per_million", 2)
    monkeypatch.setattr(settings, "intelligence_typesafe_output_usd_per_million", 0)
    monkeypatch.setattr(settings, "intelligence_typesafe_billing_mode", "input_only")
    monkeypatch.setattr(settings, "intelligence_typesafe_billing_model_id", "pinned-fixture-model")
    monkeypatch.setattr(settings, "intelligence_typesafe_billing_contract_id", "systemone-v1")
    monkeypatch.setattr(
        settings,
        "intelligence_typesafe_billing_policy_id",
        "typesafe-total-input-ceiling-v1",
    )
    monkeypatch.setattr(
        settings,
        "intelligence_typesafe_billing_reference",
        "synthetic://fixture/typesafe-input-only-total-input-ceiling-10000",
    )
    monkeypatch.setattr(settings, "intelligence_typesafe_billing_verified", True)
    monkeypatch.setattr(settings, "intelligence_typesafe_max_total_billable_input_tokens", 10_000)
    monkeypatch.setattr(settings, "intelligence_typesafe_total_input_bound_verified", False)
    called = []
    with pytest.raises(
        LegacyCallBlocked,
        match="TYPESAFE_BILLING_OR_INPUT_BOUND_PROOF_MISSING_OR_MISMATCHED",
    ):
        perform_legacy_call(
            task_type="SIGNAL_ADJUDICATION",
            task_key="synthetic-test",
            payload={"state": {}},
            source_id=None,
            project_id=None,
            job_id=None,
            worker_id=None,
            fence_token=1,
            invoke=lambda: called.append(True),
        )
    assert called == []


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


def _estimated_signal_configuration(monkeypatch, *, observation_id=None):
    selected_id = observation_id or uuid4()
    values = {
        "intelligence_enabled": True,
        "intelligence_mode": "advisory",
        "intelligence_enabled_contracts": "SIGNAL_ADJUDICATION",
        "jev_enabled": True,
        "intelligence_typesafe_enabled": True,
        "typesafe_api_key": SecretStr("synthetic-fixture-only"),
        "intelligence_typesafe_model": "jev-1.13.0",
        "intelligence_typesafe_priced_model_id": "jev-1.13.0",
        "intelligence_typesafe_pricing_verified": True,
        "intelligence_typesafe_input_usd_per_million": Decimal("0.042"),
        "intelligence_typesafe_output_usd_per_million": Decimal("0"),
        "intelligence_typesafe_billing_mode": "input_only",
        "intelligence_typesafe_billing_model_id": "jev-1.13.0",
        "intelligence_typesafe_billing_contract_id": "systemone-v1",
        "intelligence_typesafe_billing_policy_id": "typesafe-signal-estimate-v1",
        "intelligence_typesafe_billing_reference": "https://docs.typesafe.ai/models#jev-1.13.0",
        "intelligence_typesafe_billing_verified": True,
        "intelligence_typesafe_total_input_bound_verified": False,
        "intelligence_typesafe_estimated_reservation_usd": Decimal("0.01"),
        "intelligence_typesafe_estimate_observation_ids": str(selected_id),
        "intelligence_max_call_usd": Decimal("0.1"),
    }
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)
    return selected_id


def _estimated_signal_payload(observation_id, **state_changes):
    state = {
        "title": "Fixture project event",
        "abstract": "A retained public construction filing.",
        "url": "https://example.invalid/permit",
        "published_at": "2026-10-01",
        "source_id": "fixture-source",
        "source_family": "permit",
        "publisher": "Fixture Publisher",
        "event_date": "",
        "event_date_label": "",
        "project_name": "Fixture project",
        "location": "Austin, TX",
        "asset_type": "facility",
        "lifecycle_state": "planned",
    }
    state.update(state_changes)
    return {
        "state": state,
        "observation_id": str(observation_id),
        "evidence_id": str(uuid4()),
        "evidence_hash": "a" * 64,
    }


def test_estimated_signal_policy_is_selected_scoped_and_byte_bounded(monkeypatch):
    from gridlens.intelligence.intelligence_jobs import (
        TYPESAFE_SIGNAL_REQUEST_MAX_BYTES,
        _serialized_request_bytes,
    )
    from gridlens.intelligence.signal_adjudication import jev_request_payload

    observation_id = _estimated_signal_configuration(monkeypatch)
    payload = _estimated_signal_payload(observation_id)
    assert _enabled("SIGNAL_ADJUDICATION", payload=payload) == (
        True,
        "typesafe",
        "jev-1.13.0",
        "",
    )
    assert _cost_bound("typesafe", "SIGNAL_ADJUDICATION", payload) == Decimal("0.01")
    assert not _enabled("SIGNAL_ADJUDICATION", payload=_estimated_signal_payload(uuid4()))[0]
    assert not _enabled("JEV_HEALTH_PROBE", payload=payload)[0]

    exact = _estimated_signal_payload(observation_id)
    request_bytes = _serialized_request_bytes(
        jev_request_payload(exact["state"], model="jev-1.13.0")
    )
    exact["state"]["project_name"] += "x" * (TYPESAFE_SIGNAL_REQUEST_MAX_BYTES - request_bytes)
    assert (
        _serialized_request_bytes(jev_request_payload(exact["state"], model="jev-1.13.0"))
        == TYPESAFE_SIGNAL_REQUEST_MAX_BYTES
    )
    assert _cost_bound("typesafe", "SIGNAL_ADJUDICATION", exact) == Decimal("0.01")
    exact["state"]["project_name"] += "x"
    assert _cost_bound("typesafe", "SIGNAL_ADJUDICATION", exact) == 0

    unicode_payload = _estimated_signal_payload(observation_id)
    unicode_payload["state"]["project_name"] = "é" * 8_500
    assert (
        _serialized_request_bytes(jev_request_payload(unicode_payload["state"], model="jev-1.13.0"))
        > TYPESAFE_SIGNAL_REQUEST_MAX_BYTES
    )
    assert _cost_bound("typesafe", "SIGNAL_ADJUDICATION", unicode_payload) == 0


@pytest.mark.parametrize("reservation", [Decimal("0.001"), Decimal("0.02")])
def test_estimated_signal_reservation_must_match_reviewed_amount(monkeypatch, reservation):
    from gridlens.intelligence.intelligence_jobs import _cost_bound

    observation_id = _estimated_signal_configuration(monkeypatch)
    monkeypatch.setattr(settings, "intelligence_typesafe_estimated_reservation_usd", reservation)
    payload = _estimated_signal_payload(observation_id)
    assert not _enabled("SIGNAL_ADJUDICATION", payload=payload)[0]
    assert _cost_bound("typesafe", "SIGNAL_ADJUDICATION", payload) == 0


def test_estimated_policy_snapshot_tracks_scope_and_reservation(monkeypatch):
    from gridlens.intelligence.intelligence_jobs import _billing_policy_identity

    _estimated_signal_configuration(monkeypatch)
    before = _billing_policy_identity("typesafe", "jev-1.13.0", "SIGNAL_ADJUDICATION")
    assert before is not None
    assert before["cost_basis"] == "ESTIMATE"
    assert before["hard_bound_verified"] == "false"
    assert before["max_attempts"] == "1"
    monkeypatch.setattr(
        settings, "intelligence_typesafe_estimated_reservation_usd", Decimal("0.02")
    )
    assert before != _billing_policy_identity("typesafe", "jev-1.13.0", "SIGNAL_ADJUDICATION")
    monkeypatch.setattr(
        settings, "intelligence_typesafe_estimated_reservation_usd", Decimal("0.01")
    )
    monkeypatch.setattr(settings, "intelligence_typesafe_estimate_observation_ids", str(uuid4()))
    assert before != _billing_policy_identity("typesafe", "jev-1.13.0", "SIGNAL_ADJUDICATION")


def test_estimated_usage_is_input_only_and_preserves_unknown_input():
    from gridlens.intelligence.intelligence_jobs import _estimated_cost_from_usage

    policy = {"cost_basis": "ESTIMATE", "input_rate": "0.042", "output_rate": "0"}
    assert _estimated_cost_from_usage(
        "typesafe", "SIGNAL_ADJUDICATION", 551, None, billing_policy=policy
    ) == Decimal(551) * Decimal("0.042") / Decimal(1_000_000)
    assert (
        _estimated_cost_from_usage(
            "typesafe", "SIGNAL_ADJUDICATION", None, 120, billing_policy=policy
        )
        is None
    )


def test_estimated_signal_quarantine_uses_reported_context_assumption():
    error = intelligence_provider.ProviderResponseError(
        "synthetic estimated-context response",
        response_received=True,
        raw_response={
            "model": "jev-1.13.0",
            "usage": {"input_tokens": 64_001, "output_tokens": None},
        },
        reported_model="jev-1.13.0",
        reported_usage={"input_tokens": 64_001, "output_tokens": None},
    )
    details = _provider_error_quarantine_details(
        error,
        provider="typesafe",
        task_type="SIGNAL_ADJUDICATION",
        expected_model="jev-1.13.0",
        billing_policy={
            "cost_basis": "ESTIMATE",
            "input_rate": "0.042",
            "output_rate": "0",
        },
    )
    assert details and details["reason"] == "ESTIMATED_CONTEXT_ASSUMPTION_EXCEEDED"
    assert details["conservative_exposure_usd"] == (
        Decimal(64_001) * Decimal("0.042") / Decimal(1_000_000)
    )


def test_owner_unlimited_requires_explicit_provider_contract_and_authorization(monkeypatch):
    from gridlens.intelligence.intelligence_jobs import (
        TYPESAFE_UNLIMITED_BILLING_POLICY_ID,
        _billing_policy_identity,
        _owner_unlimited_allowed,
        _typesafe_billing_block_reason,
    )

    monkeypatch.setattr(settings, "intelligence_financial_budget_mode", "owner_unlimited")
    monkeypatch.setattr(settings, "intelligence_financial_authorization_ref", "owner-approval-1")
    monkeypatch.setattr(settings, "intelligence_unlimited_providers", "typesafe,openai")
    monkeypatch.setattr(
        settings, "intelligence_unlimited_contracts", "MATERIALITY_V1,GROUNDED_DOSSIER"
    )
    assert _owner_unlimited_allowed("typesafe", "MATERIALITY_V1")
    assert _owner_unlimited_allowed("openai", "GROUNDED_DOSSIER")
    assert not _owner_unlimited_allowed("typesafe", "OTHER_CONTRACT")
    assert not _owner_unlimited_allowed("firecrawl", "MATERIALITY_V1")

    for name, value in {
        "intelligence_typesafe_billing_verified": True,
        "intelligence_typesafe_billing_mode": "input_only",
        "intelligence_typesafe_billing_model_id": "jev-1.13.0",
        "intelligence_typesafe_billing_contract_id": "systemone-v1",
        "intelligence_typesafe_billing_policy_id": TYPESAFE_UNLIMITED_BILLING_POLICY_ID,
        "intelligence_typesafe_billing_reference": "https://docs.example/typesafe-billing",
        "intelligence_typesafe_total_input_bound_verified": False,
        "intelligence_typesafe_max_total_billable_input_tokens": 0,
        "intelligence_typesafe_pricing_verified": True,
        "intelligence_typesafe_priced_model_id": "jev-1.13.0",
        "intelligence_typesafe_input_usd_per_million": Decimal("0.042"),
        "intelligence_typesafe_output_usd_per_million": Decimal("0"),
    }.items():
        monkeypatch.setattr(settings, name, value)
    assert _typesafe_billing_block_reason("jev-1.13.0", "MATERIALITY_V1") == ""
    policy = _billing_policy_identity("typesafe", "jev-1.13.0", "MATERIALITY_V1")
    assert policy and policy["policy_id"] == TYPESAFE_UNLIMITED_BILLING_POLICY_ID
    assert policy["max_total_billable_input_tokens"] == "UNBOUNDED"
    assert (
        _typesafe_billing_block_reason("jev-latest", "MATERIALITY_V1")
        == "TYPESAFE_PINNED_VERSIONED_MODEL_REQUIRED"
    )

    monkeypatch.setattr(settings, "intelligence_financial_authorization_ref", " ")
    assert not _owner_unlimited_allowed("typesafe", "MATERIALITY_V1")
    assert _typesafe_billing_block_reason("jev-1.13.0", "MATERIALITY_V1")
