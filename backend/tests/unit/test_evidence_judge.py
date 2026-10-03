import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from gridlens.integrations.typesafe_evidence_judge import (
    TypesafeEvidenceJudge,
    parse_typesafe_response,
)
from gridlens.intelligence.evidence_evaluation import (
    completed_or_pending_case_ids,
    persist_benchmark_results,
    score_fixture_results,
)
from gridlens.intelligence.evidence_judge import InvalidJudgment


def response():
    choices = {
        "relevant": "YES",
        "same_project": "UNKNOWN",
        "event_type": "construction",
        "material_change": "UNKNOWN",
        "power_relevance": "MEDIUM",
        "temporary_power_hint": "UNKNOWN",
        "needs_deep_enrichment": "YES",
    }
    return {
        "model": "jev-latest",
        "answers": {
            key: {
                "type": "choice",
                "choice": value,
                "confidence": 0.7,
                "probabilities": {value: 1.0},
            }
            for key, value in choices.items()
        },
        "usage": {"input_tokens": 50, "output_tokens": 12},
    }


def test_typesafe_choice_contract_accepts_strict_enums_and_reports_usage():
    judgment, model, input_tokens, output_tokens = parse_typesafe_response(response())
    assert judgment.relevant.value == "YES"
    assert judgment.same_project.value == "UNKNOWN"
    assert judgment.event_type.value == "construction"
    assert (model, input_tokens, output_tokens) == ("jev-latest", 50, 12)


@pytest.mark.parametrize(
    "edit",
    [
        lambda payload: payload["answers"].update(
            extra={"type": "choice", "choice": "YES", "confidence": 1}
        ),
        lambda payload: payload["answers"]["event_type"].update(choice="YES"),
        lambda payload: payload["answers"]["relevant"].update(choice="LIKELY"),
        lambda payload: payload["answers"]["relevant"].update(confidence=float("nan")),
        lambda payload: payload["answers"]["relevant"].update(probabilities={"MAYBE": 1.0}),
        lambda payload: payload["usage"].update(input_tokens=True),
        lambda payload: payload["usage"].update(output_tokens=-1),
    ],
)
def test_typesafe_parser_rejects_unbounded_or_malformed_provider_output(edit):
    payload = response()
    edit(payload)
    with pytest.raises(InvalidJudgment):
        parse_typesafe_response(payload)


def test_provider_timeout_is_visible_to_shadow_fallback_caller():
    def timeout(*args, **kwargs):
        raise httpx.TimeoutException("bounded request timed out")

    judge = TypesafeEvidenceJudge("test-key", caller=timeout)
    with pytest.raises(httpx.TimeoutException):
        judge.judge({}, {}, [])


def test_provider_request_serializes_nested_state_dates_and_uuids_before_transport():
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return response()

    def caller(url, **kwargs):
        # json.dumps without a default handler proves serialization completed pre-HTTP.
        captured["body"] = json.dumps(kwargs["json"], allow_nan=False)
        captured["url"] = url
        return Response()

    judge = TypesafeEvidenceJudge("fixture-key", caller=caller)
    judgment, _ = judge.judge(
        {
            "project_id": uuid4(),
            "state": {"utility_service": {"date": date(2027, 1, 2)}},
            "organizations_and_roles": [],
        },
        {"published_at": date(2026, 10, 1), "retrieved_at": datetime(2026, 10, 2)},
        [],
    )
    assert judgment.relevant.value == "YES"
    assert captured["url"] == "https://api.typesafe.ai/v1/systemone"
    assert '"project_id": "' in captured["body"]
    assert "2027-01-02" in captured["body"]


def test_evaluation_excludes_unknown_fixture_labels_from_denominators():
    cases = [
        {
            "case_id": "known",
            "evidence_id": "e1",
            "labels": {"relevant": "YES", "same_project": "YES"},
        },
        {
            "case_id": "unknown",
            "evidence_id": "e2",
            "labels": {"relevant": "UNKNOWN", "same_project": "UNKNOWN"},
        },
    ]
    rows = [
        SimpleNamespace(
            evidence_id="e1",
            result={
                "relevant": "YES",
                "same_project": "YES",
                "material_change": "UNKNOWN",
                "power_relevance": "UNKNOWN",
                "temporary_power_hint": "UNKNOWN",
                "needs_deep_enrichment": "NO",
            },
            status="valid",
            started_at=1,
            latency_ms=40,
            input_tokens=10,
            output_tokens=3,
        ),
        SimpleNamespace(
            evidence_id="e2",
            result={"relevant": "NO", "same_project": "NO"},
            status="valid",
            started_at=2,
            latency_ms=80,
            input_tokens=9,
            output_tokens=3,
        ),
    ]
    result = score_fixture_results(cases, rows)
    assert result["relevance"]["recall"] == {"value": 1.0, "denominator": 1}
    assert result["agreement"]["same_project"] == {"matched": 1, "denominator": 1, "value": 1.0}


def test_evaluation_counts_unknown_predictions_as_abstentions_not_successes():
    cases = [
        {
            "case_id": "abstain",
            "labels": {"relevant": "YES", "same_project": "YES", "needs_deep_enrichment": "YES"},
        },
        {
            "case_id": "unknown-label",
            "labels": {
                "relevant": "UNKNOWN",
                "same_project": "UNKNOWN",
                "needs_deep_enrichment": "UNKNOWN",
            },
        },
        {"case_id": "enrichment-no", "labels": {"relevant": "NO", "needs_deep_enrichment": "NO"}},
    ]
    rows = [
        SimpleNamespace(
            case_id="abstain",
            evidence_id=None,
            result={
                "relevant": "UNKNOWN",
                "same_project": "UNKNOWN",
                "needs_deep_enrichment": "YES",
            },
            status="valid",
            started_at=1,
            latency_ms=10,
            input_tokens=1,
            output_tokens=1,
        ),
        SimpleNamespace(
            case_id="unknown-label",
            evidence_id=None,
            result={"relevant": "YES", "same_project": "YES", "needs_deep_enrichment": "YES"},
            status="valid",
            started_at=2,
            latency_ms=10,
            input_tokens=1,
            output_tokens=1,
        ),
        SimpleNamespace(
            case_id="enrichment-no",
            evidence_id=None,
            result={"relevant": "NO", "needs_deep_enrichment": "NO"},
            status="valid",
            started_at=3,
            latency_ms=10,
            input_tokens=1,
            output_tokens=1,
        ),
    ]
    result = score_fixture_results(cases, rows)
    assert result["relevance"]["recall"] == {"value": 0.0, "denominator": 1}
    assert result["relevance"]["labeled_denominator"] == 2
    assert result["relevance"]["unknown_predictions"] == 1
    assert result["relevance"]["coverage"] == 0.5
    assert result["agreement"]["same_project"]["denominator"] == 1
    assert result["agreement"]["same_project"]["matched"] == 0
    assert result["deep_enrichment_yield"] == {
        "value": 1.0,
        "useful_yes": 1,
        "recommended_yes": 1,
        "labeled_cases": 2,
    }


def test_research_recommendation_is_deterministic_and_advisory():
    from gridlens.intelligence.research_recommendation import research_recommended

    inputs = {
        "material_change": True,
        "relevant": "YES",
        "power_relevance": "HIGH",
        "missing_facts": ["utility date"],
        "timing_known": False,
        "buyer_accessible": False,
    }
    assert research_recommended(**inputs) is True
    assert research_recommended(**{**inputs, "relevant": "UNKNOWN"}) is False
    assert research_recommended(**{**inputs, "missing_facts": []}) is False


def test_recommendation_requires_nested_timing_and_a_public_buyer_contact():
    from gridlens.intelligence.research_recommendation import recommend_from_context

    judgment = {
        "material_change": "YES",
        "relevant": "YES",
        "power_relevance": "HIGH",
    }
    state = {
        "state": {
            "power_need": {
                "status": "SUPPORTED",
                "value": [{
                    "activity": {"status": "SUPPORTED", "value": "construction"},
                    "tier": {"status": "SUPPORTED", "value": "Prospect"},
                    "mw": {"status": "SUPPORTED", "value": "42 MW"},
                    "timing": {"status": "UNKNOWN", "value": None},
                    "duration": {"status": "SUPPORTED", "value": "6 months"},
                    "supply": {"status": "SUPPORTED", "value": "Reported constraint"},
                }],
            },
            "utility_service": {"status": "UNKNOWN", "value": None},
            "lifecycle": {"status": "SUPPORTED"},
            "activity": {"status": "SUPPORTED"},
        },
        "organizations_and_roles": [
            {
                "category": "owner",
                "organization": "Atlas Owner LLC",
                "public_contacts": [],
            }
        ],
    }
    assert recommend_from_context(judgment, state) is True
    state["organizations_and_roles"][0]["public_contacts"] = [
        {"kind": "email", "value": "buyer@example.test"}
    ]
    state["state"]["power_need"]["value"][0]["timing"] = {
        "status": "SUPPORTED",
        "value": "Q2 2027",
    }
    assert recommend_from_context(judgment, state) is False


def test_research_missing_fact_labels_are_stable_across_multiple_needs():
    from gridlens.intelligence.research_recommendation import _missing_facts

    supported = {"status": "SUPPORTED", "value": "known"}
    construction = {
        "activity": {"status": "SUPPORTED", "value": "construction"},
        "tier": supported,
        "mw": {"status": "CONFLICT", "value": None},
        "timing": supported,
        "duration": supported,
        "supply": supported,
    }
    temporary = {
        "activity": {"status": "SUPPORTED", "value": "temporary-power"},
        "tier": supported,
        "mw": supported,
        "timing": {"status": "UNKNOWN", "value": None},
        "duration": {"status": "UNKNOWN", "value": None},
        "supply": supported,
    }
    fields = {
        "power_need": {"status": "SUPPORTED", "value": [temporary, construction]},
        "utility_service": supported,
        "lifecycle": supported,
        "activity": supported,
    }
    expected = [
        "power_need[construction].mw",
        "power_need[temporary-power].duration",
        "power_need[temporary-power].timing",
    ]
    assert _missing_facts(fields) == expected
    fields["power_need"]["value"] = [construction, temporary]
    assert _missing_facts(fields) == expected


def test_benchmark_persists_pending_attempt_and_resume_does_not_repeat(tmp_path: Path):
    results_path = tmp_path / "results.json"
    document = {
        "results": [{"case_id": "call-may-have-started", "status": "pending", "result": None}]
    }
    persist_benchmark_results(document, results_path)
    loaded = __import__("json").loads(results_path.read_text(encoding="utf-8"))
    assert completed_or_pending_case_ids(loaded) == {"call-may-have-started"}


def test_benchmark_failure_rows_keep_latency_and_failure_classification():
    cases = [
        {"case_id": "timeout", "labels": {"relevant": "YES"}},
        {"case_id": "invalid", "labels": {"relevant": "NO"}},
    ]
    rows = [
        SimpleNamespace(
            case_id="timeout",
            evidence_id=None,
            result=None,
            status="timeout",
            latency_ms=12000,
            input_tokens=None,
            output_tokens=None,
        ),
        SimpleNamespace(
            case_id="invalid",
            evidence_id=None,
            result=None,
            status="invalid",
            latency_ms=2,
            input_tokens=None,
            output_tokens=None,
        ),
    ]
    scored = score_fixture_results(cases, rows)
    assert scored["cases_without_provider_result"] == 2
    assert scored["timeout_count"] == 1
    assert scored["invalid_count"] == 1


def test_benchmark_missing_usage_stays_unknown_instead_of_becoming_zero():
    scored = score_fixture_results(
        [{"case_id": "usage", "labels": {"relevant": "YES"}}],
        [
            SimpleNamespace(
                case_id="usage",
                evidence_id=None,
                result={"relevant": "YES"},
                status="valid",
                started_at=1,
                latency_ms=4,
                input_tokens=None,
                output_tokens=8,
            )
        ],
    )
    assert scored["usage"] == {
        "input_tokens": "UNKNOWN",
        "input_tokens_known_subtotal": "UNKNOWN",
        "input_tokens_unknown_cases": 1,
        "output_tokens": 8,
        "output_tokens_known_subtotal": 8,
        "output_tokens_unknown_cases": 0,
        "cost": "UNKNOWN",
    }
