from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.workbook_import import ImportPreview, ImportRow
from gridlens.intelligence.external_imports import (
    import_history,
    rollback_import,
    stage_import,
)
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BuyingChainEvidence,
    BuyingChainRun,
    CompanyIdentity,
    CompanyProjectMembership,
    Evidence,
    ExternalImportActivation,
    ExternalImportBatch,
    ExternalImportEvent,
    ExternalImportRow,
    IdentityIdentifier,
    Interpretation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def import_db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and (target.database == "test" or target.database.endswith("_test")), (
        "Refusing destructive setup without an explicit *_test database"
    )
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _preview(rows: list[ImportRow], digest: str = "a" * 64) -> ImportPreview:
    return ImportPreview(
        filename="sourced.xlsx",
        content_hash=digest,
        rows=rows,
        report={"processed_rows": len(rows)},
    )


def _seed_matchable(session):
    source = Source(
        id="external-import-test",
        publisher="Synthetic",
        endpoint="https://example.test",
        family="test",
        geography="TX",
        industries=[],
        retrieval_method="fixture",
    )
    session.add(source)
    session.flush()
    project = Project(
        identity_key="test-site-1",
        name="North Campus",
        location="Austin, TX",
        source_id=source.id,
        external_id="source-project-1",
    )
    observation = Observation(
        source_id=source.id,
        external_id="evidence-1",
        title="Identity source",
        abstract="Synthetic identity corroboration",
        url="https://example.test/1",
        content_hash="b" * 64,
    )
    session.add_all([project, observation])
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        content_hash=observation.content_hash,
        title=observation.title,
        abstract=observation.abstract,
        url=observation.url,
        extraction_location="test excerpt",
        provenance={},
    )
    session.add(evidence)
    session.flush()
    retained = BuyingChainEvidence(
        project_id=project.id,
        retained_evidence_id=None,
        url=observation.url,
        title=observation.title,
        excerpt=observation.abstract,
        content_hash=observation.content_hash,
        extraction_location="test excerpt",
        published_at=None,
        observed_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        project_match_reason="synthetic test seed",
    )
    identity = CompanyIdentity()
    session.add_all(
        [
            retained,
            identity,
            Interpretation(
                observation_id=observation.id,
                content_hash=observation.content_hash,
                assessment={
                    "decision": "accepted",
                    "evidence_hash": observation.content_hash,
                    "project_identity_key": project.identity_key,
                },
                status="accepted",
            ),
        ]
    )
    session.flush()
    session.add(
        BuyingChainRun(
            project_id=project.id,
            input_hash="d" * 64,
            evidence_ids=[str(retained.id)],
            claim_ids=[],
            policy_version="test",
            status="complete",
            documents_checked=1,
            candidates_added=0,
            unresolved=[],
        )
    )
    session.flush()
    session.add_all(
        [
            IdentityIdentifier(
                entity_type="company",
                company_identity_id=identity.id,
                identifier_type="domain",
                normalized_value="acme.example",
                source_evidence_id=retained.id,
                source_version_hash=observation.content_hash,
                reason="synthetic exact domain fixture",
            ),
            CompanyProjectMembership(
                company_identity_id=identity.id,
                project_id=project.id,
                role="owner",
                organization_name="Acme Energy",
                source_id=source.id,
                source_evidence_id=evidence.id,
                source_version_hash=observation.content_hash,
                decision_basis="test fixture",
                operator_number="",
            ),
        ]
    )
    session.flush()
    return project, identity


def test_stage_is_replay_safe_explainable_and_reversible_without_canonical_writes(import_db):
    with import_db.begin() as session:
        project, identity = _seed_matchable(session)
        preview = _preview(
            [
                ImportRow(
                    sheet="Accounts",
                    row_number=2,
                    raw={"Company": "Acme Energy", "Site": "North Campus"},
                    normalized={
                        "company_name": "Acme Energy",
                        "domain": "https://www.acme.example",
                        "project_name": "North Campus",
                        "city": "Austin",
                        "state": "TX",
                        "contact_name": "Unverified Contact",
                        "email": "person@acme.example",
                        "demand_mw": "12",
                        "supply_mw": None,
                    },
                    errors=[],
                ),
                ImportRow(
                    sheet="Accounts",
                    row_number=3,
                    raw={"Company": "Acme Energy"},
                    normalized={"company_name": "Acme Energy"},
                    errors=[],
                ),
                ImportRow(
                    sheet="Accounts",
                    row_number=4,
                    raw={"Company": "Acme Energy", "Site": "North Campus"},
                    normalized={
                        "company_name": "Acme Energy",
                        "project_name": "North Campus",
                        "city": "Austin",
                        "state": "TX",
                    },
                    errors=[],
                ),
            ]
        )
        first = stage_import(session, preview, actor="operator@example.test")
        replay = stage_import(session, preview, actor="operator@example.test")
        changed_mapping = _preview(
            [
                ImportRow(
                    sheet="Accounts",
                    row_number=2,
                    raw={"Company": "Acme Energy"},
                    normalized={"company_name": "Different mapped value"},
                    errors=[],
                )
            ]
        )
        with pytest.raises(ValueError, match="different normalized preview"):
            stage_import(session, changed_mapping, actor="operator@example.test")
        assert first["batch_id"] == replay["batch_id"]
        assert first["row_count"] == replay["row_count"] == 3
        assert first["matched_count"] == 2
        assert first["unmatched_count"] == 1
        assert first["rows"][0]["company_match"]["candidate_id"] == str(identity.id)
        assert first["rows"][0]["project_match"]["candidate_id"] == str(project.id)
        assert "exact registered domain" in first["rows"][0]["company_match"]["reasons"]
        assert first["rows"][1]["company_match"]["status"] == "unmatched"
        assert first["rows"][2]["company_match"]["candidate_id"] == str(identity.id)
        assert first["rows"][2]["project_match"]["candidate_id"] == str(project.id)
        assert (
            "independent exact project name and site location"
            in first["rows"][2]["company_match"]["reasons"]
        )
        assert session.scalar(select(func.count()).select_from(ExternalImportBatch)) == 1
        assert session.scalar(select(func.count()).select_from(ExternalImportRow)) == 3
        assert session.scalar(select(func.count()).select_from(Project)) == 1
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        retained = session.scalar(
            select(ExternalImportRow).where(ExternalImportRow.row_number == 2)
        )
        assert retained.normalized["demand_mw"] == "12"
        assert retained.normalized["supply_mw"] is None
        assert retained.normalized["contact_name"] == "Unverified Contact"

        rolled = rollback_import(session, first["batch_id"], actor="operator@example.test")
        again = rollback_import(session, first["batch_id"], actor="operator@example.test")
        assert rolled["status"] == again["status"] == "rolled_back"
        assert rolled["active_count"] == again["active_count"] == 0
        assert session.scalar(select(func.count()).select_from(ExternalImportRow)) == 3
        assert session.scalar(select(func.count()).select_from(ExternalImportEvent)) == 2
        assert all(
            not activation.active
            for activation in session.scalars(select(ExternalImportActivation))
        )
        assert import_history(session)[0]["batch_id"] == first["batch_id"]


def test_name_only_and_conflicting_project_signals_remain_proposals(import_db):
    with import_db.begin() as session:
        _seed_matchable(session)
        conflicting = Project(
            identity_key="test-site-2",
            name="North Campus",
            location="Austin, TX",
            source_id="external-import-test",
            external_id="source-project-2",
        )
        session.add(conflicting)
        session.flush()
        preview = _preview(
            [
                ImportRow(
                    sheet="Sites",
                    row_number=2,
                    raw={},
                    normalized={
                        "company_name": "Acme Energy",
                        "project_name": "North Campus",
                        "city": "Austin",
                        "state": "TX",
                    },
                    errors=[],
                ),
                ImportRow(
                    sheet="Sites",
                    row_number=3,
                    raw={},
                    normalized={"project_name": "North Campus"},
                    errors=[],
                ),
            ],
            "d" * 64,
        )
        result = stage_import(session, preview, actor="reviewer")
        assert result["rows"][0]["company_match"]["status"] == "matched"
        assert result["rows"][0]["project_match"]["status"] == "ambiguous"
        assert result["rows"][1]["project_match"]["status"] == "unmatched"
        assert result["matched_count"] == 0
        assert session.scalar(select(func.count()).select_from(Project)) == 2


def test_state_conflict_vetoes_company_membership_project_match(import_db):
    with import_db.begin() as session:
        _project, _identity = _seed_matchable(session)
        preview = _preview(
            [
                ImportRow(
                    sheet="Sites",
                    row_number=2,
                    raw={},
                    normalized={
                        "company_name": "Acme Energy",
                        "domain": "acme.example",
                        "project_name": "North Campus",
                        "city": "Austin",
                        "state": "OK",
                    },
                    errors=[],
                ),
            ],
            "c" * 64,
        )
        result = stage_import(session, preview, actor="reviewer")
        assert result["rows"][0]["company_match"]["status"] == "matched"
        assert result["rows"][0]["project_match"]["status"] == "unmatched"
        assert result["matched_count"] == 0


def test_summary_rows_are_retained_but_never_activated(import_db):
    with import_db.begin() as session:
        preview = _preview(
            [
                ImportRow(
                    sheet="Contacts",
                    row_number=2,
                    row_kind="summary",
                    raw={"Total records": 35},
                    normalized={},
                    errors=[],
                ),
            ],
            "b" * 64,
        )
        result = stage_import(session, preview, actor="reviewer")
        assert result["rows"][0]["status"] == "ignored"
        assert result["rows"][0]["row_kind"] == "summary"
        assert result["rows"][0]["active"] is False
        assert result["metrics"]["ignored_rows"] == 1


def test_stale_identifier_and_membership_evidence_never_drive_company_matches(import_db):
    with import_db.begin() as session:
        _seed_matchable(session)
        identifier = session.scalar(select(IdentityIdentifier))
        identifier.source_version_hash = "f" * 64
        membership = session.scalar(select(CompanyProjectMembership))
        membership.source_version_hash = "f" * 64
        result = stage_import(
            session,
            _preview(
                [
                    ImportRow(
                        sheet="Accounts",
                        row_number=2,
                        raw={},
                        normalized={"company_name": "Acme Energy", "domain": "acme.example"},
                        errors=[],
                    ),
                    ImportRow(
                        sheet="Accounts",
                        row_number=3,
                        raw={},
                        normalized={
                            "company_name": "Acme Energy",
                            "project_name": "North Campus",
                            "city": "Austin",
                            "state": "TX",
                        },
                        errors=[],
                    ),
                ],
                "9" * 64,
            ),
            actor="reviewer",
        )
        assert result["rows"][0]["company_match"]["status"] == "unmatched"
        assert result["rows"][1]["company_match"]["status"] == "unmatched"
        assert result["matched_count"] == 0


def test_staging_guard_rejects_arbitrary_database(import_db):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    production_shaped = create_engine("postgresql+psycopg://user:pass@localhost/gridlens")
    try:
        from gridlens.intelligence.external_imports import _assert_staging_session

        with Session(production_shaped) as session, pytest.raises(RuntimeError, match="restricted"):
            _assert_staging_session(session)
    finally:
        production_shaped.dispose()


def test_truncated_preview_is_rejected_before_any_write(import_db):
    with import_db.begin() as session:
        preview = _preview([], "f" * 64)
        preview.report["truncated"] = True
        with pytest.raises(ValueError, match="truncated"):
            stage_import(session, preview, actor="reviewer")
        assert session.scalar(select(func.count()).select_from(ExternalImportBatch)) == 0


def test_25k_rows_are_staged_in_bounded_chunks_and_return_bounded_summary(import_db):
    rows = [
        ImportRow(
            sheet="Accounts",
            row_number=index + 2,
            raw={"Account": f"Company {index}"},
            normalized={"company_name": f"Company {index}", "facility_demand_mw": "100"},
            errors=[],
        )
        for index in range(25_000)
    ]
    with import_db.begin() as session:
        result = stage_import(session, _preview(rows, "e" * 64), actor="reviewer")
        assert result["row_count"] == 25_000
        assert result["rows_truncated"] is True
        assert len(result["rows"]) == 100
        assert result["metrics"]["rows_with_power_assertions"] == 25_000
        assert session.scalar(select(func.count()).select_from(ExternalImportRow)) == 25_000
