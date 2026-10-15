"""Synthetic transport responses test the bounded model boundary, not live judgment."""

from types import SimpleNamespace

from pydantic import SecretStr

from gridlens.intelligence.editorial_clearance import assess


def record():
    return dict(
        eligibilityReason=None,
        evidenceId="retained-1",
        evidenceHash="a" * 64,
        title="A retained source title",
        text="A retained excerpt.",
        publishedAt="2026-10-15",
        sourceUrl="https://example.org/source",
    )


def test_no_model_access_is_explicit_and_never_approves():
    result = assess(record(), SimpleNamespace(openai_api_key=None))
    assert result["status"] == "unavailable"
    assert "assessment" not in result


def test_ineligible_record_never_calls_provider():
    result = assess({**record(), "eligibilityReason": "stale"}, SimpleNamespace())
    assert result == {"status": "ineligible", "reason": "stale"}


def test_real_citation_does_not_allow_invented_fact():
    import json

    response = dict(
        whatHappened="Invented 900 MW customer demand",
        whatChanged="A retained excerpt.",
        whyItMatters="Could this affect timing?",
        audiences=["Utilities"],
        powerGapAngle="What timing should readers verify?",
        linkedInAngle="Who should investigate this?",
        evidenceGaps=["Verify timing"],
        recommendation="high-priority",
        reason="Could this matter to readers?",
        evidenceIds=["retained-1"],
        premiseQuotes=["A retained excerpt."],
    )

    def caller(url, **kwargs):
        assert url == "https://api.openai.com/v1/chat/completions"
        assert "private_customer" not in str(kwargs)
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"choices": [{"message": {"content": json.dumps(response)}}]},
        )

    settings = SimpleNamespace(
        openai_api_key=SecretStr("test-only"), openai_brief_model="existing-model"
    )
    assert assess(record(), settings, caller)["status"] == "unavailable"
    response["whatHappened"] = "A retained source title"
    result = assess(record(), settings, caller)
    assert result["status"] == "available"
    assert result["interpretationOnly"] is True
    assert "clearance" not in result
    response["whyItMatters"] = "Could the customer need 900 MW tomorrow?"
    assert assess(record(), settings, caller)["status"] == "unavailable"
    response["whyItMatters"] = "Could this affect timing?"
    response["premiseQuotes"] = ["An invented source claim"]
    assert assess(record(), settings, caller)["status"] == "unavailable"
