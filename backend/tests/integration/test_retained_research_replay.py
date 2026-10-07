"""Retained-first replay preserves immutable evidence and acquisition provenance."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from test_pursuit_evidence import research_db as _isolated_research_db
from test_pursuit_evidence import seed

from gridlens.domain.project_research import VERSION
from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.intelligence.project_state import current_research_state
from gridlens.intelligence.research_evidence import (
    replay_retained_research,
    retain_research_document,
)
from gridlens.persistence.models import Evidence, Interpretation, Observation, PowerNeed, Project


@pytest.fixture
def research_db():
    yield from _isolated_research_db.__wrapped__()


def document():
    return PublicDocument(
        "https://www.federalregister.gov/documents/orion/",
        "Orion Data Center project update",
        "Orion Data Center at 811 Clayton Ln, Austin, TX construction is underway.",
        datetime.now(UTC).date(),
        datetime.now(UTC),
        "public project update",
    )


def test_reviewed_official_context_replay_preserves_evidence(research_db):
    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        original = document()
        first = retain_research_document(session, project, need, original)
        assert first["disposition"] == "ACCEPTED", first
        evidence = session.get(Evidence, first["evidence_id"])
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == evidence.observation_id)
        )
        # Simulate complete retained input interpreted under the previous parser.
        interpretation.evaluator_version = "project-research-claims-v1"
        original_fields = (
            evidence.id,
            evidence.content_hash,
            evidence.observed_at,
            evidence.abstract,
        )
        before = session.scalar(select(func.count()).select_from(Evidence))
        assert current_research_state(session, project.id, need.id) == {}
        receipts = replay_retained_research(session, project, need)
        replay = next(r for r in receipts if r.get("retained_replay"))
        assert replay["evidence_id"] == str(evidence.id)
        assert replay["duplicate"] and replay["disposition"] == "ACCEPTED"
        assert interpretation.evaluator_version == VERSION
        assert session.scalar(select(func.count()).select_from(Evidence)) == before
        assert original_fields == (
            evidence.id,
            evidence.content_hash,
            evidence.observed_at,
            evidence.abstract,
        )
        assert (
            current_research_state(session, project.id, need.id)[str(need.id)]["phase"]["value"]
            == "construction_active"
        )
        assert need.tier == "Signal" and need.required_mw is None
        again = replay_retained_research(session, project, need)
        assert any(r.get("retained_replay") and r["duplicate"] for r in again)
        assert session.scalar(select(func.count()).select_from(Evidence)) == before


def test_excerpt_and_native_context_not_relabelled_complete(research_db):
    from dataclasses import replace

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        original = replace(document(), text=document().text + "\n" + "Other source detail. " * 300)
        first = retain_research_document(session, project, need, original)
        assert first["disposition"] == "ACCEPTED"
        evidence = session.get(Evidence, first["evidence_id"])
        before = session.scalar(select(func.count()).select_from(Evidence))
        receipts = replay_retained_research(session, project, need)
        assert receipts and all(r["disposition"] == "UNRESOLVED" for r in receipts)
        assert not any(r.get("retained_replay") for r in receipts)
        assert session.scalar(select(func.count()).select_from(Evidence)) == before
        assert len(evidence.abstract) <= 4000


@pytest.mark.parametrize(
    "url",
    [
        "https://www.federalregister.gov.evil.example/orion/",
        "https://unreviewed.gov/orion/",
    ],
)
def test_official_context_is_exact_reviewed_host_not_government_wildcard(research_db, url):
    from dataclasses import replace

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        result = retain_research_document(session, project, need, replace(document(), url=url))
        assert result["disposition"] == "QUARANTINED"
        assert need.tier == "Signal"


def test_legacy_capture_marker_blocks_replay_and_current_relationship_until_refresh(research_db):
    from types import SimpleNamespace

    from gridlens.ingestion.adapters.buying_chain_public import CAPTURE_VERSION
    from gridlens.intelligence.autonomous_research import _current_support
    from gridlens.intelligence.buying_chain import _retained_evidence_current_for_project

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        page = PublicDocument(
            "https://acme.com/projects/orion",
            "Acme Orion Data Center project team",
            "Acme is the electrical contractor for Orion Data Center "
            "at 811 Clayton Ln, Austin, TX.\n"
            "Alice Smith is Project Manager at Acme.\n"
            "Alice Smith can be reached at +1 (312) 555-0123.",
            datetime.now(UTC).date(),
        )
        first = retain_research_document(session, project, need, page)
        assert first["disposition"] == "ACCEPTED"
        evidence = session.get(Evidence, first["evidence_id"])
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == evidence.observation_id)
        )
        assert _retained_evidence_current_for_project(session, project, evidence)
        interpretation.assessment = {
            k: v for k, v in interpretation.assessment.items() if k != "acquisition_capture_version"
        }
        session.flush()
        assert not _retained_evidence_current_for_project(session, project, evidence)
        observation = session.get(Observation, evidence.observation_id)
        question = SimpleNamespace(project_id=project.id, need_id=need.id)
        assert not _current_support(session, question, evidence, observation, {})
        old_history = interpretation.assessment
        receipts = replay_retained_research(session, project, need)
        assert not any(r.get("retained_replay") for r in receipts)
        assert interpretation.assessment == old_history
        fresh = retain_research_document(session, project, need, page)
        assert fresh["evidence_id"] == first["evidence_id"]
        assert interpretation.assessment["acquisition_capture_version"] == CAPTURE_VERSION
        assert _retained_evidence_current_for_project(session, project, evidence)
        assert any(
            "acquisition_capture_version" not in prior
            for prior in interpretation.assessment["previous_decisions"]
        )
