"""Planned developer roles remain source-bound and project-scoped."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.ingestion.adapters.retained_company_projects import (
    FAMILY,
    RETRIEVAL_METHOD,
    SOURCE_ID,
    interpret_retained_company_project,
    retained_records,
)
from gridlens.intelligence.retained_project_organizations import (
    _planned_native_developer_claim,
    extract_retained_project_organizations,
)


def _switch_values():
    corpus = Path(__file__).resolve().parents[3] / "eval/customer-commercial-v1"
    records, _held = retained_records(corpus)
    record = next(
        row
        for row in records
        if "sources/switch.json" in row["retained_company_project"]["source_files"]
    )
    native = interpret_retained_company_project(record)
    assert native is not None
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
    observation_id, evidence_id = uuid4(), uuid4()
    source = SimpleNamespace(id=SOURCE_ID, family=FAMILY, retrieval_method=RETRIEVAL_METHOD)
    observation = SimpleNamespace(
        id=observation_id,
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
        observation_id=observation_id,
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
        "subject": native["name"],
        "location": native["location"],
        "power_activity": native["activity_key"],
        "project_identity_key": "native:" + record["document_number"],
        "evidence": {"id": str(evidence.id), "url": evidence.url},
    }
    interpretation = SimpleNamespace(
        observation_id=observation_id,
        content_hash=observation.content_hash,
        status="accepted",
        assessment=assessment,
    )
    project = SimpleNamespace(
        source_id=SOURCE_ID,
        external_id=record["document_number"],
        identity_key=assessment["project_identity_key"],
        name=native["name"],
        location=native["location"],
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
    return record, document, project, source, observation, evidence, interpretation


def test_switch_planned_builder_role_uses_native_site_and_literal_citations():
    _record, document, project, source, observation, evidence, interpretation = _switch_values()
    claims = extract_retained_project_organizations(
        document,
        project=project,
        source=source,
        observation=observation,
        evidence=evidence,
        interpretation=interpretation,
    )

    assert len(claims) == 1
    claim = claims[0]
    assert (claim.organization, claim.category) == ("Switch", "owner_developer")
    assert claim.organization_relationship == "DIRECT"
    assert {item["supports"] for item in claim.citations} == {
        "organization_category",
        "project_organization",
        "project_name",
    }
    assert all(item["quote"] in document.text for item in claim.citations)
    assert any("will allow Switch to construct" in item["quote"] for item in claim.citations)
    assert "planned developer" in claim.reason
    assert "legal ownership" in claim.reason
    assert not hasattr(claim, "required_mw")
    assert all(
        "Dell" not in item["quote"] or "will allow Switch" in item["quote"]
        for item in claim.citations
    )


def test_planned_builder_role_rejects_mismatched_publisher_host_and_actor():
    _record, document, project, source, observation, evidence, interpretation = _switch_values()
    context = evidence.provenance["retained_company_project"]
    body = evidence.abstract

    changed_link = body.replace("https://www.switch.com/", "https://www.sp00fer.com/")
    spoofed_link_document = PublicDocument(
        url=document.url,
        title=document.title,
        text=f"{document.title}\n{changed_link}",
        published_at=document.published_at,
    )
    assert _planned_native_developer_claim(spoofed_link_document, context, changed_link) is None

    mismatch = body.replace("will allow Switch to construct", "will allow Dell to construct")
    mismatch_document = PublicDocument(
        url=document.url,
        title=document.title,
        text=f"{document.title}\n{mismatch}",
        published_at=document.published_at,
    )
    assert _planned_native_developer_claim(mismatch_document, context, mismatch) is None
