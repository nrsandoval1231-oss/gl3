"""Real retained Taylor source; review fields are test-only editorial judgments."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from gridlens.domain.editorial import evaluate_feed

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def example():
    from gridlens.ingestion.adapters.taylor_newsflash import _article

    r = _article(
        (FIXTURES / "taylor-newsflash-2079-3442.html").read_bytes(),
        "https://taylortx.gov/m/NewsFlash/Archive/Item/2079?arcId=3442",
        "2079",
        "3442",
    )
    source = SimpleNamespace(
        id="taylor-development-newsflash",
        publisher="City of Taylor",
        family="municipal-development-notice",
    )
    observation = SimpleNamespace(
        id="observation-1", source_id=source.id, first_seen_at=datetime(2026, 8, 15, tzinfo=UTC)
    )
    evidence = SimpleNamespace(
        id="evidence-1",
        content_hash="a" * 64,
        title=r["title"],
        abstract=r.get("abstract", ""),
        url=r["html_url"],
        published_at=date.fromisoformat(r["publication_date"]),
    )
    review = dict(
        evidenceId=evidence.id,
        evidenceHash=evidence.content_hash,
        title=r["title"],
        publicationEligibility="approved-public",
        geography="United States / Texas / Taylor",
        industry="infrastructure",
        eventClassification="permitting",
        whatChanged=r["title"],
        verifiedFacts=[r["title"]],
        unknowns=["Power requirement is not established."],
        interpretations=["Withdrawal changes the status of the hearing notice."],
        hypotheses=[],
        commercialSignificance="Check the current planning status before relying on this notice.",
        editorialAngles=["What a withdrawn notice establishes and what it does not."],
        whyNow="A dated change to an official planning notice.",
        technicalImplications="No electrical design or supply claim is established.",
        recommendedArticleType="research-brief",
        evidenceQuality="primary",
        confidence="medium",
        review={
            "reviewer": "test-editor",
            "reviewedAt": "2026-08-15T00:00:00Z",
            "classificationVerified": True,
            "publicOnly": True,
            "readerValue": 3,
            "specificity": 3,
            "significance": 2,
            "originality": 2,
            "technicalRelevance": 2,
        },
    )
    return review, (observation, evidence, source)


def run(review, record, now=date(2026, 8, 20), recent=()):
    return evaluate_feed([review], {record[1].id: record}, now=now, recent_ids=recent)


def test_real_source_provenance_and_no_pursuit_fields():
    review, record = example()
    result = run(review, record)
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["sourceUrl"] == record[1].url
    assert item["publishedAt"] == record[1].published_at.isoformat()
    assert item["lastMaterialChangeAt"] is None
    assert item["verifiedFacts"][0]["evidenceIds"] == ["evidence-1"]
    assert "customer" not in json.dumps(item).lower()


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ({"publicationEligibility": "confidential"}, "publication_restricted"),
        ({"evidenceHash": "b" * 64}, "evidence_changed"),
        ({"verifiedFacts": ["Customer needs 20 MW of rental power."]}, "unsupported_fact"),
        ({"geography": "Sweden"}, "unrelated_market"),
        ({"customer": "private account"}, "invalid_review"),
    ],
)
def test_fail_closed(mutation, reason):
    review, record = example()
    review.update(mutation)
    result = run(review, record)
    assert result["items"] == []
    assert result["rejected"][0]["reason"] == reason


def test_stale_and_duplicate_do_not_become_new_on_export():
    review, record = example()
    assert run(review, record, now=date(2026, 10, 15))["items"] == []
    accepted = run(review, record)["items"][0]
    assert run(review, record, recent=[accepted["id"]])["items"] == []
    result = evaluate_feed([review, review], {record[1].id: record}, now=date(2026, 8, 20))
    assert len(result["items"]) == 1
    assert result["rejected"][0]["reason"] == "duplicate"


def test_real_bad_n8n_records_cannot_enter_as_approved_intelligence():
    rows = json.loads((FIXTURES / "editorial-rejected-feed.json").read_text())["items"]
    result = evaluate_feed(rows, {}, now=date(2026, 10, 15))
    assert result["items"] == []
    assert len(result["rejected"]) == len(rows)
    assert all(r["reason"] == "invalid_review" for r in result["rejected"])


def test_export_route_requires_session():
    from fastapi.testclient import TestClient

    from gridlens.api.app import app

    assert TestClient(app).get("/api/editorial/candidates").status_code == 401


def test_serialized_contract_matches_consumers_fixture():
    review, record = example()
    fixture = json.loads((FIXTURES / "editorial-approved-test.json").read_text())
    assert run(review, record)["items"] == fixture["items"]


def test_public_url_cannot_carry_access_credentials():
    review, record = example()
    record[1].url += "&access_token=synthetic-test-only"
    assert run(review, record)["items"] == []


def test_editorial_judgment_and_classification_are_required():
    review, record = example()
    review["review"]["classificationVerified"] = False
    assert run(review, record)["items"] == []
    review["review"]["classificationVerified"] = True
    review["review"]["significance"] = 1
    assert run(review, record)["rejected"][0]["reason"] == "insufficient_editorial_value"
