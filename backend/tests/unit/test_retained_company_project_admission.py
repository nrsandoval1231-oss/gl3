"""Source admission replays native retained text; context flags are not authority."""

from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from gridlens.domain.signal_admission import admit_standalone, admitted_from_source
from gridlens.ingestion.adapters.retained_company_projects import (
    FAMILY,
    RETRIEVAL_METHOD,
    SOURCE_ID,
    interpret_retained_company_project,
    retained_records,
)


@pytest.fixture
def native_record():
    corpus = Path(__file__).resolve().parents[3] / "eval/customer-commercial-v1"
    records, _held = retained_records(corpus)
    assert records, "Real source cohort must admit at least one source-bound site."
    return records[0]


def standalone(record, **overrides):
    fresh = interpret_retained_company_project(record)
    arguments = {
        "source_id": SOURCE_ID,
        "family": FAMILY,
        "retrieval_method": RETRIEVAL_METHOD,
        "accepted": True,
        "activity": fresh["activity_key"] if fresh else "construction",
        "title": record["title"],
        "abstract": record["abstract"],
        "dated": bool(record.get("publication_date")),
        "citation_url": record["html_url"],
        "identified_project": True,
        "retained_record": record,
    }
    return admit_standalone(**(arguments | overrides))


def test_native_retained_source_admits_activity_without_rental_amount(native_record):
    admission = standalone(native_record)
    assert admission.admitted
    assert "rental demand is unknown" in admission.reason
    assert "required_mw" not in interpret_retained_company_project(native_record)


@pytest.mark.parametrize(
    "override",
    [
        {"source_id": "different-publisher"},
        {"family": "news"},
        {"accepted": False},
        {"identified_project": False},
        {"dated": False},
        {"retained_record": None},
        {"citation_url": "https://example.invalid/borrowed"},
        {"activity": "temporary-power"},
    ],
)
def test_standalone_retained_contract_cannot_be_borrowed(native_record, override):
    assert not standalone(native_record, **override).admitted


def persisted(record):
    fresh = interpret_retained_company_project(record)
    assert fresh
    evidence = SimpleNamespace(
        id=uuid4(),
        url=record["html_url"],
        title=record["title"],
        abstract=record["abstract"],
        content_hash=record["source_hash"],
        published_at=date.fromisoformat(record["publication_date"]),
        observed_at=datetime(2026, 11, 13, tzinfo=UTC),
        provenance={"retained_company_project": deepcopy(record["retained_company_project"])},
    )
    assessment = {
        "decision": "accepted",
        "tier": "Signal",
        "subject": fresh["name"],
        "location": fresh["location"],
        "power_activity": fresh["activity_key"],
        "evidence_hash": evidence.content_hash,
        "evidence": {"id": str(evidence.id), "url": evidence.url},
    }
    source = SimpleNamespace(id=SOURCE_ID, family=FAMILY, retrieval_method=RETRIEVAL_METHOD)
    return source, assessment, evidence


def test_persisted_admission_reparses_exact_native_evidence(native_record):
    assert admitted_from_source(*persisted(native_record)).admitted


@pytest.mark.parametrize(
    "mutation",
    ["body", "hash", "subject", "location", "activity", "citation", "future", "context"],
)
def test_persisted_admission_refuses_stale_or_foreign_binding(native_record, mutation):
    source, assessment, evidence = persisted(native_record)
    if mutation == "body":
        evidence.abstract += "\nChanged source text."
    elif mutation == "hash":
        evidence.content_hash = "0" * 64
    elif mutation in {"subject", "location"}:
        assessment[mutation] = "Another site"
    elif mutation == "activity":
        assessment["power_activity"] = "temporary-power"
    elif mutation == "citation":
        assessment["evidence"]["id"] = str(uuid4())
    elif mutation == "future":
        evidence.observed_at = datetime(2000, 1, 1, tzinfo=UTC)
    elif mutation == "context":
        evidence.provenance["retained_company_project"]["project_name"] = "Another site"
    assert not admitted_from_source(source, assessment, evidence).admitted
