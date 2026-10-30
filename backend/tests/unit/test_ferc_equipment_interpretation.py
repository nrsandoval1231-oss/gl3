"""Native admission verifies the exact source and physical-site proposal independently."""

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from gridlens.domain.ferc_equipment_interpretation import (
    assess_ferc_equipment,
    govinfo_document_identity,
    is_ferc_equipment_candidate,
)
from gridlens.domain.signal_admission import admit_standalone, admitted_from_source
from gridlens.ingestion.adapters.govinfo_pdf import retrieve_companion

FIXTURES = Path(__file__).parents[1] / "fixtures" / "govinfo-complete-notice"


@pytest.fixture
def notice():
    metadata = json.loads((FIXTURES / "provenance.json").read_text())
    raw = (FIXTURES / "FR-2024-12869.pdf").read_bytes()
    record = {
        "document_number": metadata["document_number"],
        "title": metadata["official_title"],
        "publication_date": metadata["publication_date"],
        "pdf_url": metadata["source_url"],
    }
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=raw, headers={"content-type": "application/pdf"})
        )
    ) as client:
        citation = retrieve_companion(record, client)[0]
    evidence = SimpleNamespace(
        id=uuid4(),
        title=record["title"],
        abstract=citation["abstract"],
        content_hash=hashlib.sha256(raw).hexdigest(),
        url=record["pdf_url"],
        published_at=date(2024, 6, 12),
        observed_at=datetime(2026, 10, 30, tzinfo=UTC),
    )
    assessment = assess_ferc_equipment(evidence.title, evidence.abstract)
    assert assessment is not None
    assessment.update(
        evidence_hash=evidence.content_hash,
        source_document_number=record["document_number"],
        evidence={"id": str(evidence.id), "url": evidence.url},
    )
    source = SimpleNamespace(
        id="federal-register-eis", family="structured-government", retrieval_method="json-api"
    )
    return record, evidence, assessment, source


def test_real_notice_admits_one_site_without_quantifying_or_resolving_company(notice):
    record, evidence, assessment, source = notice
    assert is_ferc_equipment_candidate(record)
    assert assessment["decision"] == "accepted"
    assert assessment["subject"] == "Compressor Station 302"
    assert assessment["location"] == "Montgomery County, Texas"
    assert assessment["native_equipment"]["company_identity"] == "UNKNOWN"
    assert assessment["native_equipment"]["current_status"] == "UNKNOWN"
    body = assessment["native_equipment"]["body_applicant_attribution"]
    assert evidence.abstract[body["start"] : body["end"]] == body["quote"]
    assert "Pipeline" not in body["value"]
    assert "Pipeline" in assessment["native_equipment"]["company_attribution"]["value"]
    assert admitted_from_source(source, assessment, evidence).admitted
    assert "required_mw" not in assessment and "start_window" not in assessment


@pytest.mark.parametrize(
    "field,value",
    [
        ("url", "https://www.govinfo.gov/content/pkg/FR-2024-06-12/pdf/2024-12870.pdf"),
        ("content_hash", "0" * 64),
        ("id", uuid4()),
        ("published_at", date(2026, 11, 1)),
    ],
)
def test_changed_source_binding_cannot_retain_admission(notice, field, value):
    _, evidence, assessment, source = notice
    setattr(evidence, field, value)
    assert not admitted_from_source(source, assessment, evidence).admitted


def test_tampered_site_and_source_metadata_cannot_retain_admission(notice):
    _, evidence, assessment, source = notice
    assessment["location"] = "Liberty County, Texas"
    assert not admitted_from_source(source, assessment, evidence).admitted
    assessment["location"] = "Montgomery County, Texas"
    source.family = "news"
    assert not admitted_from_source(source, assessment, evidence).admitted


def test_multisite_new_demand_and_duplicate_headings_abstain(notice):
    _, evidence, _, _ = notice
    second = "Re-wheel existing electric motor driven compressor Units 9 and 10."
    modified = evidence.abstract.replace(
        second, "Install one new electric motor driven compressor unit with a rating of 100 hp."
    )
    assert modified != evidence.abstract
    assert assess_ferc_equipment(evidence.title, modified)["decision"] == "unknown"
    duplicate = evidence.abstract.replace("343 in Liberty County", "302 in Montgomery County")
    assert assess_ferc_equipment(evidence.title, duplicate)["decision"] == "unknown"


@pytest.mark.parametrize("suffix", ["?", "#", ";other", "?token=x", "#fragment"])
def test_noncanonical_pdf_identity_is_rejected(suffix):
    url = "https://www.govinfo.gov/content/pkg/FR-2024-06-12/pdf/2024-12869.pdf"
    assert govinfo_document_identity(url + suffix, date(2024, 6, 12)) is None


def test_generic_federal_register_source_is_still_context_only(notice):
    _, evidence, _, source = notice
    assert not admit_standalone(
        source_id=source.id,
        family=source.family,
        retrieval_method=source.retrieval_method,
        accepted=True,
        activity="facility-expansion",
        title=evidence.title,
        abstract=evidence.abstract,
        dated=True,
        citation_url=evidence.url,
        identified_project=True,
    ).admitted
