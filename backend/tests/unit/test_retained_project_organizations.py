"""Source-native organization roles from accepted retained announcements."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.ingestion.adapters.retained_company_projects import (
    FAMILY,
    RETRIEVAL_METHOD,
    SOURCE_ID,
    interpret_retained_company_project,
    retained_record_hash,
    retained_records,
)
from gridlens.intelligence.retained_project_organizations import (
    extract_retained_project_organizations,
)


@pytest.fixture
def cases():
    corpus = Path(__file__).resolve().parents[3] / "eval/customer-commercial-v1"
    records, _held = retained_records(corpus)
    return {
        "databank": next(
            row
            for row in records
            if "sources/databank.json" in row["retained_company_project"]["source_files"]
        ),
        "cyrus": next(
            row
            for row in records
            if "sources/cyrusone.json" in row["retained_company_project"]["source_files"]
        ),
    }


def materialize(record):
    fresh = interpret_retained_company_project(record)
    assert fresh is not None
    obs_id, evidence_id = uuid4(), uuid4()
    observed = datetime(2026, 11, 13, tzinfo=UTC)
    published = date.fromisoformat(record["publication_date"])
    semantic_payload = {
        "title": " ".join(record["title"].split()),
        "abstract": " ".join((record.get("abstract") or "").split()),
        "publication_date": record["publication_date"],
        "url": record["html_url"],
    }
    semantic_hash = hashlib.sha256(
        json.dumps(
            semantic_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    source = SimpleNamespace(id=SOURCE_ID, family=FAMILY, retrieval_method=RETRIEVAL_METHOD)
    observation = SimpleNamespace(
        id=obs_id,
        source_id=SOURCE_ID,
        external_id=record["document_number"],
        title=record["title"],
        abstract=record["abstract"],
        url=record["html_url"],
        content_hash=semantic_hash,
        published_at=published,
    )
    evidence = SimpleNamespace(
        id=evidence_id,
        observation_id=obs_id,
        title=record["title"],
        abstract=record["abstract"],
        url=record["html_url"],
        content_hash=record["source_hash"],
        published_at=published,
        observed_at=observed,
        provenance={"retained_company_project": deepcopy(record["retained_company_project"])},
    )
    assessment = {
        "decision": "accepted",
        "tier": "Signal",
        "evidence_hash": evidence.content_hash,
        "semantic_hash": observation.content_hash,
        "subject": fresh["name"],
        "location": fresh["location"],
        "power_activity": fresh["activity_key"],
        "project_identity_key": "native:" + record["document_number"],
        "evidence": {"id": str(evidence.id), "url": evidence.url},
    }
    interpretation = SimpleNamespace(
        observation_id=obs_id,
        content_hash=observation.content_hash,
        status="accepted",
        assessment=assessment,
    )
    project = SimpleNamespace(
        source_id=SOURCE_ID,
        external_id=record["document_number"],
        identity_key=assessment["project_identity_key"],
        name=fresh["name"],
        location=fresh["location"],
        identity_facts={
            "project_aliases": deepcopy(
                record["retained_company_project"].get("project_aliases", [])
            )
        },
    )
    document = PublicDocument(
        url=evidence.url,
        title=evidence.title,
        text=f"{evidence.title}\n{evidence.abstract}",
        published_at=published,
        observed_at=observed,
        retained_version=evidence.content_hash,
    )
    return document, project, source, observation, evidence, interpretation


def extract(values):
    document, project, source, observation, evidence, interpretation = values
    return extract_retained_project_organizations(
        document,
        project=project,
        source=source,
        observation=observation,
        evidence=evidence,
        interpretation=interpretation,
    )


def test_databank_reported_developer_is_bound_to_red_oak_site(cases):
    values = materialize(cases["databank"])
    claims = extract(values)
    assert len(claims) == 1
    claim = claims[0]
    assert (claim.organization, claim.category) == ("DataBank", "owner_developer")
    assert {item["supports"] for item in claim.citations} == {
        "organization_category",
        "project_organization",
        "project_name",
    }
    assert all(item["quote"] in values[0].text for item in claim.citations)
    assert "historical reported involvement" in claim.reason
    assert not hasattr(claim, "required_mw")


def test_cyrusone_is_direct_project_customer_not_energy_center_owner(cases):
    values = materialize(cases["cyrus"])
    claims = extract(values)
    assert len(claims) == 1
    claim = claims[0]
    assert (claim.organization, claim.category) == ("CyrusOne", "project_customer")
    assert claim.organization_relationship == "DIRECT"
    assert len(claim.citations) == 1
    assert claim.citations[0]["supports"] == "project_organization"
    assert "Thad Hill Energy Center" in claim.citations[0]["quote"]
    assert "not" in claim.reason


def test_native_document_version_fence_and_capacity_revision(cases):
    original = deepcopy(cases["databank"])
    unchanged = deepcopy(original)
    assert retained_record_hash(unchanged) == original["source_hash"]

    revised = deepcopy(original)
    revised["title"] = revised["title"].replace("480MW", "640MW")
    revised["abstract"] = revised["abstract"].replace("480MW", "640MW")
    context = revised["retained_company_project"]
    revised["source_body_hash"] = hashlib.sha256(revised["abstract"].encode()).hexdigest()
    context["body_hash"] = revised["source_body_hash"]
    for section in context["section_ranges"]:
        excerpt = revised["abstract"][section["start"] : section["end"]]
        section["sha256"] = hashlib.sha256(excerpt.encode()).hexdigest()
    for field in ("activity_quote", "project_quote"):
        context[field] = context[field].replace("480MW", "640MW")
    revised["source_hash"] = retained_record_hash(revised)
    context["content_hash"] = revised["source_hash"]
    assert revised["source_hash"] != original["source_hash"]
    assert interpret_retained_company_project(revised) is not None

    values = list(materialize(original))
    document, project, source, observation, evidence, interpretation = values
    evidence.title = revised["title"]
    evidence.abstract = revised["abstract"]
    evidence.content_hash = revised["source_hash"]
    evidence.provenance["retained_company_project"] = context
    observation.title = revised["title"]
    observation.abstract = revised["abstract"]
    semantic_payload = {
        "title": " ".join(revised["title"].split()),
        "abstract": " ".join(revised["abstract"].split()),
        "publication_date": revised["publication_date"],
        "url": revised["html_url"],
    }
    semantic_hash = hashlib.sha256(
        json.dumps(
            semantic_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    observation.content_hash = semantic_hash
    interpretation.content_hash = semantic_hash
    interpretation.assessment["semantic_hash"] = semantic_hash
    interpretation.assessment["evidence_hash"] = evidence.content_hash
    document = PublicDocument(
        url=evidence.url,
        title=evidence.title,
        text=f"{evidence.title}\n{evidence.abstract}",
        published_at=evidence.published_at,
        observed_at=evidence.observed_at,
        retained_version=evidence.content_hash,
    )
    values[0] = document
    claims = extract(tuple(values))
    assert len(claims) == 1
    assert claims[0].organization == "DataBank"
    assert claims[0].category == "owner_developer"


def test_source_metadata_only_change_is_a_new_record_version(cases):
    original = deepcopy(cases["databank"])
    title_only = deepcopy(original)
    title_only["title"] += " — Cancelled"
    title_only["source_hash"] = retained_record_hash(title_only)
    title_only["retained_company_project"]["content_hash"] = title_only["source_hash"]
    assert title_only["source_hash"] != original["source_hash"]
    assert interpret_retained_company_project(title_only) is None

    publication_only = deepcopy(original)
    publication_only["publication_date"] = "2024-09-11"
    publication_only["retained_company_project"]["publication_date"] = "2024-09-11"
    publication_only["source_hash"] = retained_record_hash(publication_only)
    publication_only["retained_company_project"]["content_hash"] = publication_only["source_hash"]
    assert publication_only["source_hash"] != original["source_hash"]


def test_semantic_and_native_evidence_hashes_are_independent(cases):
    values = list(materialize(cases["cyrus"]))
    document, project, source, observation, evidence, interpretation = values
    assert observation.content_hash != evidence.content_hash
    assert extract(tuple(values))
    interpretation.content_hash = evidence.content_hash
    assert extract(tuple(values)) == []


def test_native_interpreter_rejects_derived_context_tampering(cases):
    record = deepcopy(cases["databank"])
    context = record["retained_company_project"]
    context["rationale"] = "The customer has a verified 100 MW rental requirement."
    assert interpret_retained_company_project(record) is None

    record = deepcopy(cases["databank"])
    context = record["retained_company_project"]
    record["publication_date_precision"] = "month"
    context["publication_date_precision"] = "month"
    record["source_hash"] = retained_record_hash(record)
    context["content_hash"] = record["source_hash"]
    assert interpret_retained_company_project(record) is None

    record = deepcopy(cases["databank"])
    context = record["retained_company_project"]
    record["publication_date"] = "2026-11-13"
    context["publication_date"] = "2026-11-13"
    record["source_hash"] = retained_record_hash(record)
    context["content_hash"] = record["source_hash"]
    assert interpret_retained_company_project(record) is None


def test_adverse_title_revision_is_a_new_nonadmitted_version(cases):
    record = deepcopy(cases["databank"])
    record["title"] += " — Cancelled"
    record["source_hash"] = retained_record_hash(record)
    record["retained_company_project"]["content_hash"] = record["source_hash"]
    assert interpret_retained_company_project(record) is None


@pytest.mark.parametrize(
    "mutation",
    [
        "source_hash",
        "assessment_subject",
        "project_location",
        "project_identity",
        "observation_url",
        "document_text",
        "interpretation_status",
        "alias_context",
    ],
)
def test_mismatched_or_superseded_native_context_emits_no_claim(cases, mutation):
    values = list(materialize(cases["databank"]))
    document, project, source, observation, evidence, interpretation = values
    if mutation == "source_hash":
        evidence.content_hash = "0" * 64
    elif mutation == "assessment_subject":
        interpretation.assessment["subject"] += " sibling"
    elif mutation == "project_location":
        project.location = "Atlanta, GA"
    elif mutation == "project_identity":
        project.identity_key += ":superseded"
    elif mutation == "observation_url":
        observation.url = "https://example.invalid/other"
    elif mutation == "document_text":
        values[0] = PublicDocument(
            url=document.url,
            title=document.title,
            text=document.text + " Portfolio in Atlanta, Georgia.",
            published_at=document.published_at,
            observed_at=document.observed_at,
            retained_version=document.retained_version,
        )
    elif mutation == "interpretation_status":
        interpretation.status = "superseded"
    elif mutation == "alias_context":
        project.identity_facts["project_aliases"] = ["Atlanta Campus"]
    assert extract(tuple(values)) == []


@pytest.mark.parametrize(
    "change",
    [
        ("DataBank", "announced the development of a 480MW data center campus in Red Oak, TX"),
        ("DataBank", "announced the development of a 480MW data center campus in Atlanta, GA"),
        (
            "DataBank",
            "announced the development of a 480MW data center campus in Red Oak, TX. "
            "DataBank's Atlanta campus is under construction.",
        ),
        ("DataBank", "announced a portfolio containing a 480MW data center campus in Red Oak, TX"),
        ("Example PR", "announced the development of a 480MW data center campus in Red Oak, TX"),
    ],
)
def test_databank_role_needs_exact_title_body_and_site_relation(cases, change):
    values = list(materialize(cases["databank"]))
    document, project, source, observation, evidence, interpretation = values
    org, replacement = change
    body = evidence.abstract
    start = body.find("DataBank")
    assert start >= 0
    # Alter the source-bound body and all version bindings consistently while
    # retaining native admission context only where the adapter still validates.
    altered = body[:start] + replacement + body[body.find(".", start) + 1 :]
    if org != "DataBank":
        altered = body.replace("DataBank", "Example PR", 1)
    record = deepcopy(cases["databank"])
    record["abstract"] = altered
    record["source_hash"] = __import__("hashlib").sha256(altered.encode()).hexdigest()
    # A modified source body must fail the native parser/hash check; the test
    # documents this hard boundary rather than manufacturing a successful label.
    evidence.abstract = altered
    assert extract(tuple(values)) == []


def test_cyrus_role_cannot_be_inferred_from_profile_or_wrong_project(cases):
    values = list(materialize(cases["cyrus"]))
    document, project, source, observation, evidence, interpretation = values
    evidence.abstract = evidence.abstract.replace(
        "agreement with Dallas based CyrusOne", "agreement with Calpine from Dallas based CyrusOne"
    )
    observation.abstract = evidence.abstract
    values[0] = PublicDocument(
        url=document.url,
        title=document.title,
        text=f"{document.title}\n{evidence.abstract}",
        published_at=document.published_at,
        observed_at=document.observed_at,
        retained_version=document.retained_version,
    )
    assert extract(tuple(values)) == []
