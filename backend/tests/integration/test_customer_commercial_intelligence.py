"""Source-bound customer facts on disposable synthetic evidence, never live coverage."""

from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select

from gridlens.intelligence.customer_intelligence import (
    persist_customer_facts,
    project_customer_facts,
)
from gridlens.persistence.models import BrowseRow, EvidencePackage

pytest_plugins = ["test_equipment_intelligence"]


def seeded(session):
    from test_equipment_intelligence import seed

    return seed(
        session,
        body=(
            "Mock Permian Compression Station has 120 MW of campus development capacity. "
            "Construction will begin in Q2 2027. Full operations are expected in 2029."
        ),
    )


def test_retained_facts_are_immutable_source_bound_and_idempotent(equipment_db):
    with equipment_db.begin() as session:
        _, project, observation, evidence, _, _ = seeded(session)
        row = persist_customer_facts(session, project_id=project.id, evidence_id=evidence.id)
        assert row is not None
        assert row.schema_version == "customer-facts-v1"
        assert row.need_id is None and row.provider == "deterministic"
        assert row.evidence_hash == evidence.content_hash
        assert row.payload["capacity_claims"][0]["value_mw"] == "120"
        provenance = row.payload["capacity_claims"][0]["source"]
        assert provenance["evidence_id"] == str(evidence.id)
        assert provenance["content_hash"] == evidence.content_hash
        assert provenance["observed_at"] == evidence.observed_at.isoformat()
        assert provenance["extracted_at"] is None
        assert (
            persist_customer_facts(session, project_id=project.id, evidence_id=evidence.id).id
            == row.id
        )
        assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 1
        original = deepcopy(row.payload)
        observation.content_hash = "f" * 64
        session.flush()
        assert project_customer_facts(session, [project.id], generation=None)[str(project.id)] == []
        assert row.payload == original


@pytest.mark.parametrize("corruption", ["hash", "identity", "rejected", "url", "relationship_only"])
def test_facts_reject_wrong_current_source_scope(equipment_db, corruption):
    with equipment_db.begin() as session:
        _, project, _, evidence, interpretation, _ = seeded(session)
        if corruption == "hash":
            interpretation.assessment = {**interpretation.assessment, "evidence_hash": "f" * 64}
        elif corruption == "identity":
            interpretation.assessment = {
                **interpretation.assessment,
                "project_identity_key": "other",
            }
        elif corruption == "rejected":
            interpretation.status = "rejected"
        elif corruption == "url":
            evidence.url = "https://example.test/different"
        else:
            interpretation.assessment = {
                **interpretation.assessment,
                "admission_status": "relationship_supplement",
            }
        session.flush()
        assert (
            persist_customer_facts(session, project_id=project.id, evidence_id=evidence.id) is None
        )
        assert project_customer_facts(session, [project.id], generation=None)[str(project.id)] == []


def test_generation_reads_frozen_facts_without_mixing_current_sources(equipment_db, monkeypatch):
    from test_equipment_intelligence import publish_test_browse

    with equipment_db.begin() as session:
        need, project, observation, _, _, _ = seeded(session)
        facts = project_customer_facts(session, [project.id], generation=None)[str(project.id)]
        assert facts[0]["capacity_claims"][0]["value_mw"] == "120"
        publish_test_browse(session, monkeypatch, [(need, project)])
        browse = session.scalar(select(BrowseRow))
        browse.compact = {**browse.compact, "customer_facts": facts}
        generation_id = browse.generation_id
        session.flush()
        observation.content_hash = "f" * 64
        session.flush()
        assert project_customer_facts(session, [project.id], generation=generation_id) == {
            str(project.id): facts
        }
        assert project_customer_facts(session, [project.id], generation=uuid4()) == {
            str(project.id): []
        }


def test_generation_build_reads_are_batched_and_do_not_write_packages(equipment_db):
    with equipment_db.begin() as session:
        _, project, _, _, _, _ = seeded(session)
        reads = []
        engine = session.get_bind()

        def count(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                reads.append(statement)

        event.listen(engine, "before_cursor_execute", count)
        try:
            result = project_customer_facts(
                session, [project.id, *[uuid4() for _ in range(50)]], generation=None
            )
        finally:
            event.remove(engine, "before_cursor_execute", count)
        assert len(reads) <= 2
        assert result[str(project.id)][0]["capacity_claims"]
        assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 0


def test_build_ignores_forged_audit_package_payload(equipment_db):
    with equipment_db.begin() as session:
        _, project, _, evidence, _, _ = seeded(session)
        receipt = persist_customer_facts(session, project_id=project.id, evidence_id=evidence.id)
        assert receipt is not None
        receipt.payload = {**receipt.payload, "capacity_claims": [{"value_mw": "999999"}]}
        session.flush()
        facts = project_customer_facts(session, [project.id], generation=None)
        assert facts[str(project.id)][0]["capacity_claims"][0]["value_mw"] == "120"


def test_direct_canonical_source_does_not_require_creating_power_need(equipment_db):
    from sqlalchemy import delete

    from gridlens.persistence.models import NeedObservation, PowerNeed

    with equipment_db.begin() as session:
        need, project, observation, evidence, _, _ = seeded(session)
        project.external_id = observation.external_id
        session.execute(delete(NeedObservation).where(NeedObservation.need_id == need.id))
        session.execute(delete(PowerNeed).where(PowerNeed.id == need.id))
        session.flush()
        receipt = persist_customer_facts(session, project_id=project.id, evidence_id=evidence.id)
        assert receipt is not None and receipt.need_id is None
        assert project_customer_facts(session, [project.id], generation=None)[str(project.id)]


@pytest.fixture
def research_db():
    from test_pursuit_evidence import research_db as isolated

    yield from isolated.__wrapped__()


@pytest.mark.parametrize(
    "kind", ["capacity", "timeline", "engineering", "wrong_project", "adverse"]
)
def test_capacity_only_research_uses_existing_admission_guards(research_db, kind):
    from datetime import UTC, date, datetime

    from test_pursuit_evidence import seed

    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.research_evidence import retain_research_document
    from gridlens.persistence.models import PowerNeed, Project

    factory, source, job_id = research_db
    need_id = seed(factory, source, job_id)
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        body = {
            "capacity": (
                "Orion Data Center at 811 Clayton Ln, Austin, TX has "
                "400 MW of campus development capacity."
            ),
            "timeline": (
                "Orion Data Center at 811 Clayton Ln, Austin, TX "
                "construction will begin in Q2 2027."
            ),
            "wrong_project": (
                "Other Data Center at 42 Main St, Dallas, TX has "
                "400 MW of campus development capacity."
            ),
            "adverse": (
                "Orion Data Center at 811 Clayton Ln, Austin, TX has "
                "400 MW of campus development capacity but the project was cancelled."
            ),
        }.get(kind, "")
        if kind == "engineering":
            import json

            body = "Orion Data Center at 811 Clayton Ln, Austin, TX commissioning test plan.\n"
            body += (
                "```json\n"
                + json.dumps(
                    {
                        "project_name": project.name,
                        "commissioning_test_plan": [
                            {
                                "project_id": str(project.id),
                                "block_id": "test-A",
                                "load_scope_id": "load-A",
                                "sequence_stage": "stage-1",
                                "rating": "2",
                                "unit": "MW",
                                "rating_basis": "electrical_output",
                                "installed_units": 4,
                                "concurrent_units": 2,
                                "test_fraction": "0.75",
                            }
                        ],
                    }
                )
                + "\n```"
            )
        receipt = retain_research_document(
            session,
            project,
            need,
            PublicDocument(
                "https://www.federalregister.gov/documents/customer-facts/",
                "Orion Data Center project update",
                body,
                date.today(),
                datetime.now(UTC),
                "synthetic primary document",
            ),
        )
        facts = project_customer_facts(session, [project.id], generation=None)[str(project.id)]
        if kind in {"capacity", "timeline", "engineering"}:
            assert receipt["disposition"] == "ACCEPTED", receipt
            assert facts
            field = {
                "capacity": "capacity_claims",
                "timeline": "timeline_claims",
                "engineering": "commissioning_inputs",
            }[kind]
            assert facts[0][field]
            assert need.required_mw is None and need.tier == "Signal"
        else:
            assert receipt["disposition"] != "ACCEPTED"
            assert not facts


def test_document_project_match_does_not_assign_another_projects_capacity(equipment_db):
    with equipment_db.begin() as session:
        _, project, observation, evidence, _, _ = seeded(session)
        evidence.abstract = observation.abstract = (
            "Mock Permian Compression Station is planned. "
            "Unrelated Campus has 999 MW of campus development capacity."
        )
        assert not project_customer_facts(session, [project.id], generation=None)[str(project.id)]


@pytest.mark.parametrize("mode", ["valid", "foreign_source", "wrong_project", "overlap"])
def test_retained_engineering_test_plan_has_runtime_scenario_path(equipment_db, mode):
    import json
    from datetime import date

    from gridlens.domain.customer_intelligence import resolve_customer_intelligence

    with equipment_db.begin() as session:
        _, project, observation, evidence, _, _ = seeded(session)
        block = {
            "project_id": str(project.id),
            "block_id": "generator-test-A",
            "load_scope_id": "electrical-path-A",
            "sequence_stage": "stage-1",
            "rating": "2",
            "unit": "MW",
            "rating_basis": "electrical_output",
            "installed_units": 4,
            "concurrent_units": 2,
            "test_fraction": "0.75",
        }
        if mode == "wrong_project":
            block["project_id"] = str(uuid4())
        elif mode == "foreign_source":
            block["evidence"] = {"rating": [{"url": "https://other.example.test/"}]}
        blocks = [block]
        if mode == "overlap":
            blocks.append({**block, "block_id": "upstream-test-B"})
        text = (
            f"{project.name} commissioning plan.\n```json\n"
            + json.dumps({"project_name": project.name, "commissioning_test_plan": blocks})
            + "\n```"
        )
        evidence.abstract = observation.abstract = text
        session.flush()
        facts = project_customer_facts(session, [project.id], generation=None)[str(project.id)]
        result = resolve_customer_intelligence(
            [{"project_id": str(project.id), "facts": facts}], as_of=date.today()
        )
        if mode == "valid":
            assert result["commissioning"]["base_mw"] == "3"
            assert result["commissioning"]["verified_customer_demand"] is False
            refs = result["commissioning"]["input_evidence"]
            assert refs and all(ref["evidence_id"] == str(evidence.id) for ref in refs)
            assert all(ref["content_hash"] == evidence.content_hash for ref in refs)
        else:
            assert result["commissioning"]["status"] == "insufficient_data"
            assert result["commissioning"]["base_mw"] is None


@pytest.mark.parametrize("conjunction", ["while", "and", "whereas", "but"])
def test_compound_project_sentence_cannot_lend_target_identity(equipment_db, conjunction):
    with equipment_db.begin() as session:
        _, project, observation, evidence, _, _ = seeded(session)
        evidence.abstract = observation.abstract = (
            f"{project.name} has 120 MW of campus development capacity {conjunction} "
            "Unrelated Campus has 999 MW of campus development capacity."
        )
        assert not project_customer_facts(session, [project.id], generation=None)[str(project.id)]


def test_complete_source_bounds_abstain_instead_of_publishing_partial_total(
    equipment_db, monkeypatch
):
    from datetime import date

    from gridlens.domain.customer_intelligence import resolve_customer_intelligence
    from gridlens.intelligence import customer_intelligence

    with equipment_db.begin() as session:
        _, project, _, _, _, _ = seeded(session)
        monkeypatch.setattr(customer_intelligence, "MAX_PROJECT_SOURCES", 0)
        facts = project_customer_facts(session, [project.id], generation=None)[str(project.id)]
        assert facts[0]["overflow"] is True
        result = resolve_customer_intelligence(
            [{"project_id": str(project.id), "facts": facts}], as_of=date.today()
        )
        assert result["capacity"]["total_mw"] is None
        assert result["commissioning"]["base_mw"] is None


@pytest.mark.parametrize(
    "unit,amount,expected",
    [
        ("MW", "100", "100"),
        ("megawatt", "100", "100"),
        ("megawatts", "100", "100"),
        ("GW", "1", "1000"),
        ("gigawatt", "1", "1000"),
        ("gigawatts", "1", "1000"),
        ("kW", "1000", "1"),
        ("kilowatt", "1000", "1"),
        ("kilowatts", "1000", "1"),
    ],
)
def test_scope_guard_supports_all_core_electrical_unit_spellings(unit, amount, expected):
    from gridlens.domain.customer_intelligence import extract_customer_facts
    from gridlens.intelligence.customer_intelligence import scope_customer_facts

    extracted = extract_customer_facts(
        f"Orion Data Center has {amount} {unit} of IT load.",
        project_id="project",
        source={"url": "https://example.test/engineering"},
    )
    scoped = scope_customer_facts(extracted, "Orion Data Center")
    assert len(scoped["capacity_claims"]) == 1
    assert scoped["capacity_claims"][0]["value_mw"] == expected
