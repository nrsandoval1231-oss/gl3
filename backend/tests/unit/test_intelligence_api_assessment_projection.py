from copy import deepcopy
from uuid import uuid4

import pytest

from gridlens.api import intelligence
from gridlens.intelligence.commercial_assessment import digest, validate_assessment
from gridlens.intelligence.evidence_packages import build_package, validate_package
from gridlens.persistence.models import (
    Evidence,
    EvidencePackage,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)


def _projection_fixture(monkeypatch):
    need_id, project_id, package_id = uuid4(), uuid4(), uuid4()
    evidence_id, observation_id, logical_call_id = uuid4(), uuid4(), uuid4()
    content = "Application stage: Permit application"
    source = Source(
        id="fixture-source",
        publisher="Fixture publisher",
        endpoint="https://example.test/source",
        family="permit",
        geography="Austin",
        industries=[],
        retrieval_method="fixture",
        health={"collection_status": "PARTIAL"},
    )
    project = Project(
        id=project_id,
        source_id=source.id,
        external_id="fixture-project",
        name="Fixture project",
        location="Austin, TX",
        identity_key="fixture-project",
        identity_facts={},
        region_status="ELIGIBLE",
    )
    need = PowerNeed(
        id=need_id,
        project_id=project_id,
        activity_key="construction",
        tier="Signal",
        rationale="Fixture need",
        supply="Unknown",
    )
    observation = Observation(
        id=observation_id,
        source_id=source.id,
        external_id=project.external_id,
        title="Fixture title",
        abstract=content,
        url="https://example.test/source",
        content_hash="a" * 64,
    )
    evidence = Evidence(
        id=evidence_id,
        observation_id=observation_id,
        content_hash="a" * 64,
        title=observation.title,
        abstract=content,
        url=observation.url,
        extraction_location="title and abstract",
        provenance={},
    )

    class Results:
        def all(self):
            return [need]

    class Session:
        def __init__(self):
            self.scalar_count = 0
            self.rows = {
                (Evidence, evidence_id): evidence,
                (Observation, observation_id): observation,
                (Source, source.id): source,
                (Project, project_id): project,
                (PowerNeed, need_id): need,
            }

        def get(self, model, row_id):
            return self.rows.get((model, row_id))

        def scalar(self, _query):
            self.scalar_count += 1
            return project if self.scalar_count == 1 else uuid4()

        def scalars(self, _query):
            return Results()

    session = Session()
    package, *_ = build_package(session, evidence_id, processing_status="PREPARED")
    package["processing_status"] = "COMPLETE_ADVISORY"
    package["logical_call_id"] = str(logical_call_id)
    package["advisory"] = {
        "source": "jev",
        "model": "jev-1.13.0",
        "logical_call_id": str(logical_call_id),
    }
    validate_package(package, evidence_fields={"title": evidence.title, "abstract": content})
    package_row = EvidencePackage(
        id=package_id,
        package_key=package["package_key"],
        schema_version=package["schema_version"],
        evidence_id=evidence_id,
        observation_id=observation_id,
        project_id=project_id,
        need_id=need_id,
        evidence_hash=evidence.content_hash,
        extractor_version=package["extractor_version"],
        question_contract=package["question_contract"],
        provider=package["provider"],
        model=package["model"],
        processing_status="COMPLETE_ADVISORY",
        payload=package,
    )
    session.rows[(EvidencePackage, package_id)] = package_row
    facts = [{**fact, "fact_id": f"f-{digest(fact)[:16]}"} for fact in package["facts"]]
    package_context = {
        "id": str(package_id),
        "package_key": package["package_key"],
        "schema_version": package["schema_version"],
        "processing_status": package["processing_status"],
        "payload_digest": digest(package),
        "document_coverage": package["document_coverage"],
        "source_collection_status": package["source_collection_status"],
        "facts": facts,
        "missing_fields": package["missing_fields"],
        "source_references": deepcopy(package["source_references"]),
        "source_id": source.id,
        "source_health": source.health,
        "source_enabled": True,
        "source_registry_enabled": True,
    }
    fact_id = facts[0]["fact_id"]
    required = {
        "disposition": "UNRESOLVED",
        "reason_code": "EXCERPT_INSUFFICIENT",
        "selected_fact_ids": [fact_id],
        "research_dimensions": ["REQUIRED_MW", "BUYER_AUTHORITY"],
        "next_question_id": "TEMP_LOAD_MW",
    }
    validated = validate_assessment(
        required,
        package=package_context | {"project_id": str(project_id), "need_id": str(need_id)},
        need_id=str(need_id),
        project_id=str(project_id),
    )
    checkpoint = {
        "validation_outcome": "VALIDATED",
        "request_digest": "prior-request",
        "result": validated,
        "payload": {
            "need": {"need_id": str(need_id), "project_id": str(project_id)},
            "project": {"project_id": str(project_id)},
            "package": package_context,
        },
    }
    session.rows[(NeedObservation, observation_id)] = NeedObservation(
        need_id=need_id, observation_id=observation_id
    )
    session.scalar_count = 1

    def stale_payload(*_args):
        raise ValueError("source context changed")

    monkeypatch.setattr(intelligence, "_current_payload", stale_payload)
    return session, need_id, checkpoint, fact_id, content


def test_saved_m4_projection_returns_exact_historical_citation(monkeypatch):
    session, need_id, checkpoint, fact_id, excerpt = _projection_fixture(monkeypatch)

    projection = intelligence._commercial_assessment_support(
        session, need_id=need_id, checkpoint=checkpoint, job_status="completed"
    )

    assert projection["status"] == "saved"
    assert projection["document_coverage"] == "RECORD_EXCERPT"
    assert projection["source_collection_status"] == "PARTIAL"
    assert projection["selected_facts"][0]["fact_id"] == fact_id
    citation = projection["selected_facts"][0]["citation"]
    assert citation["excerpt"] == excerpt[excerpt.index("Permit") :]
    assert citation["source_url"] == "https://example.test/source"
    assert citation["field"] == "abstract"


def test_m4_projection_labels_support_current_only_when_saved_request_matches(monkeypatch):
    session, need_id, checkpoint, _fact_id, _excerpt = _projection_fixture(monkeypatch)
    current_payload = {"current_request": "exact"}
    monkeypatch.setattr(intelligence, "_current_payload", lambda *_args: current_payload)
    checkpoint["request_digest"] = intelligence._digest(current_payload)

    projection = intelligence._commercial_assessment_support(
        session, need_id=need_id, checkpoint=checkpoint, job_status="completed"
    )

    assert projection["status"] == "current"
    assert projection["selected_facts"][0]["support_status"] == "current"


@pytest.mark.parametrize("variant", ["selected_id", "hash", "url", "span", "need_id"])
def test_m4_projection_fails_closed_on_mismatched_selected_citation(monkeypatch, variant):
    session, need_id, checkpoint, _fact_id, _excerpt = _projection_fixture(monkeypatch)
    package = checkpoint["payload"]["package"]
    fact = package["facts"][0]
    if variant == "selected_id":
        checkpoint["result"]["selected_fact_ids"] = ["f-invented"]
    elif variant == "hash":
        fact["citation"]["evidence_hash"] = "c" * 64
    elif variant == "url":
        package["source_references"][0]["url"] = "javascript:alert(1)"
    elif variant == "span":
        fact["citation"]["excerpt_location"]["end"] += 20
    else:
        checkpoint["payload"]["need"]["need_id"] = str(uuid4())

    projection = intelligence._commercial_assessment_support(
        session, need_id=need_id, checkpoint=checkpoint, job_status="completed"
    )

    assert projection["status"] == "unavailable"
    assert projection["selected_facts"] == []


def test_unknown_m4_job_has_no_assessment_or_citation(monkeypatch):
    session, need_id, checkpoint, _fact_id, _excerpt = _projection_fixture(monkeypatch)

    projection = intelligence._commercial_assessment_support(
        session, need_id=need_id, checkpoint=checkpoint, job_status="unknown"
    )

    assert projection["status"] == "unavailable"
    assert projection["selected_facts"] == []
