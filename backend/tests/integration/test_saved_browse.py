"""Disposable PostgreSQL parity and publication safety; no external calls."""

import asyncio
import csv
import json
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from importlib import import_module
from io import StringIO
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.saved_browse import current_generation, page, rebuild
from gridlens.persistence.browse_invalidation import INPUT_TABLES, install
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseState,
    BrowseUnresolvedCustomer,
    CompanyIdentity,
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings

api = import_module("gridlens.api.app")


@pytest.fixture
def saved_db(monkeypatch):
    if not settings.test_database_url:
        pytest.skip("TEST_DATABASE_URL required for PostgreSQL generation tests")
    database = make_url(settings.test_database_url).database
    assert database and database.endswith("_test") and "corpus" not in database.lower(), (
        "An explicit disposable *_test database is required"
    )
    schema = "b1_test_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install(connection)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(settings, "saved_browse_enabled", False)
    yield factory
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    admin.dispose()


def seed(factory, count=4, histories=3):
    ids = []
    regional_sites = ("Dallas, TX", "Albuquerque, NM")
    with factory.begin() as session:
        session.add(
            Source(
                id="synthetic-permits",
                publisher="Synthetic",
                endpoint="https://example.test",
                family="construction-permits",
                geography="Test",
                industries=["construction"],
                retrieval_method="socrata-permits",
                health={},
            )
        )
        session.flush()
        for index in range(count):
            pid, nid = uuid4(), uuid4()
            ids.append(nid)
            session.add(
                Project(
                    id=pid,
                    identity_key=f"site-{index}",
                    name=f"Synthetic {index}",
                    location=regional_sites[index % len(regional_sites)],
                    source_id="synthetic-permits",
                    external_id=str(index),
                )
            )
            session.flush()
            session.add(
                PowerNeed(
                    id=nid,
                    project_id=pid,
                    activity_key="construction",
                    tier="Signal",
                    rationale="Synthetic only",
                    supply="Unknown",
                    active=True,
                )
            )
            session.flush()
            for history in range(histories):
                oid, eid = uuid4(), uuid4()
                fingerprint = f"{index * histories + history:064x}"
                session.add(
                    Observation(
                        id=oid,
                        source_id="synthetic-permits",
                        external_id=f"{index}-{history}",
                        title=f"Synthetic {index}",
                        abstract="Synthetic construction permit.",
                        url=f"https://example.test/{oid}",
                        content_hash=fingerprint,
                        published_at=date(2026, 10, 15),
                    )
                )
                session.flush()
                session.add(
                    Evidence(
                        id=eid,
                        observation_id=oid,
                        content_hash=fingerprint,
                        title=f"Synthetic {index}",
                        abstract=f"Ｆｕｌｌ history {history} cross field",
                        url=f"https://example.test/{oid}",
                        published_at=date(2026, 10, 15),
                        observed_at=datetime.now(UTC) - timedelta(days=history),
                        extraction_location="Synthetic",
                    )
                )
                session.add(
                    Interpretation(
                        observation_id=oid,
                        content_hash=fingerprint,
                        evaluator_version="fixture",
                        status="accepted",
                        assessment={
                            "semantic_hash": fingerprint,
                            "evidence_hash": fingerprint,
                            "project_identity_key": f"site-{index}",
                            "power_activity": "construction",
                            "decision": "accepted",
                            "subject": f"Synthetic {index}",
                            "location": regional_sites[index % len(regional_sites)],
                        },
                    )
                )
                session.add(NeedObservation(need_id=nid, observation_id=oid))
    return ids


def filters(**changes):
    return api._normalized_browse_filters(
        **{
            **dict.fromkeys(
                (
                    "tier",
                    "search",
                    "decision",
                    "geography",
                    "industry",
                    "activity",
                    "timing",
                    "mw_status",
                    "mw_min",
                    "mw_max",
                    "priority_segment",
                )
            ),
            **changes,
        }
    )


def test_build_saved_page_matches_canonical_and_does_no_evidence_reads(saved_db, monkeypatch):
    seed(saved_db)
    baseline_response = Response()
    expected = api.opportunities(
        response=baseline_response, sort="rank", limit=50, offset=0, cohort=None
    )
    # Generic fixtures use explicit TX/NM physical sites; out-of-region cases are
    # constructed explicitly in their focused exclusion tests.
    assert len(expected) == 4
    result = rebuild(saved_db)
    assert result["status"] == "published"
    statements = []

    def capture(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(saved_db.kw["bind"], "before_cursor_execute", capture)
    try:
        monkeypatch.setattr(settings, "saved_browse_enabled", True)
        response = Response()
        actual = api.opportunities(response=response, sort="rank", limit=50, offset=0, cohort=None)
    finally:
        event.remove(saved_db.kw["bind"], "before_cursor_execute", capture)
    assert [str(row["id"]) for row in actual] == [str(row["id"]) for row in expected]
    for actual_row, expected_row in zip(actual, expected, strict=True):
        for field in (
            "tier",
            "required_mw",
            "rank_score",
            "rank_reasons",
            "rank_version",
            "group_id",
            "group_title",
            "group_total_filtered",
            "priority_segment",
        ):
            assert actual_row[field] == expected_row[field], field
    assert response.headers["x-total-count"] == baseline_response.headers["x-total-count"]
    assert not any(
        "FROM evidence" in statement or "JOIN evidence" in statement for statement in statements
    )
    assert len(statements) <= 5


def test_saved_page_always_exposes_current_snapshot_as_of_metadata(saved_db):
    seed(saved_db)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db() as session:
        generation = current_generation(session)
        result = page(session, filters())
    assert result["generation_id"] == str(generation.id)
    assert result["as_of"] == generation.built_at.isoformat()
    assert result["built_at"] == generation.built_at.isoformat()
    assert result["valid_until"] == generation.valid_until.isoformat()
    assert result["qualification_state"] == "current"
    assert result["refresh_state"] == "current"


@pytest.mark.parametrize(
    "query", ["full history 2", "cross field", "synthetic 1", "%", "missing", ""]
)
def test_exact_historical_search(saved_db, query):
    seed(saved_db)
    expected = api.opportunities(search=query, limit=50, offset=0, cohort=None)
    rebuild(saved_db)
    with saved_db() as session:
        actual = page(session, filters(search=query))["items"]
    assert [str(row["id"]) for row in actual] == [str(row["id"]) for row in expected]


def test_committed_mutation_blocks_stale_generation_but_rollback_does_not(saved_db):
    seed(saved_db)
    rebuild(saved_db)
    with saved_db() as session:
        before = current_generation(session).id
        session.execute(text("UPDATE projects SET name = name"))
        session.rollback()
    with saved_db() as session:
        assert current_generation(session).id == before
    with saved_db.begin() as session:
        session.execute(text("UPDATE projects SET name = name"))
    with saved_db() as session, pytest.raises(HTTPException) as exc:
        current_generation(session)
    assert exc.value.status_code == 503
    assert "pending" in exc.value.detail


def test_concurrent_input_change_prevents_publication_and_restart_recovers(saved_db):
    seed(saved_db)

    def mutate():
        with saved_db.begin() as session:
            session.execute(text("UPDATE sources SET publisher = 'Changed fixture'"))

    assert rebuild(saved_db, before_publish=mutate)["status"] == "superseded"
    with saved_db() as session:
        assert session.get(BrowseState, 1).generation_id is None
    assert rebuild(saved_db)["status"] == "published"


def test_all_declared_input_tables_have_transactional_statement_triggers(saved_db):
    with saved_db() as session:
        tables = session.scalars(
            text("""
            SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=current_schema() AND t.tgname='invalidate_browse'
        """)
        ).all()
        assert set(tables) == set(INPUT_TABLES) - {
            "buying_chain_identity_links",
            "company_identities",
            "identity_identifiers",
            "company_project_memberships",
        }
        identity_triggers = session.scalars(
            text("""
            SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=current_schema() AND c.relname='buying_chain_identity_links'
                AND NOT t.tgisinternal
            """)
        ).all()
        assert set(identity_triggers) == {
            "invalidate_browse_identity_link_insert",
            "invalidate_browse_identity_link_update",
            "invalidate_browse_identity_link_delete",
            "invalidate_browse_identity_link_truncate",
        }
        for table in ("company_identities", "identity_identifiers"):
            scoped_triggers = session.scalars(
                text("""
                SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=current_schema() AND c.relname=:table
                    AND NOT t.tgisinternal
                """),
                {"table": table},
            ).all()
            assert set(scoped_triggers) == {
                "invalidate_browse_identity_entity_insert",
                "invalidate_browse_identity_entity_update",
                "invalidate_browse_identity_entity_delete",
                "invalidate_browse_identity_entity_truncate",
            }
        # Exercise every table without creating/deleting canonical evidence.
        revision = session.scalar(select(BrowseState.input_revision))
        for table in INPUT_TABLES:
            session.execute(text(f"DELETE FROM {table} WHERE false"))
        # Empty identity-link batches are no-ops; pursuit call-note writes are
        # live overlays and their TRUNCATE trigger remains conservative.
        assert (
            session.scalar(select(BrowseState.input_revision)) == revision + len(INPUT_TABLES) - 5
        )
        membership_triggers = session.scalars(
            text("""
            SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=current_schema() AND c.relname='company_project_memberships'
                AND NOT t.tgisinternal
            """)
        ).all()
        assert set(membership_triggers) == {
            "invalidate_browse_company_membership_insert",
            "invalidate_browse_company_membership_update",
            "invalidate_browse_company_membership_delete",
            "invalidate_browse_company_membership_truncate",
        }
        session.rollback()


def test_identity_churn_only_invalidates_projects_that_consume_the_identity(saved_db):
    from gridlens.intelligence.saved_browse import refresh_project_changes
    from gridlens.persistence.models import (
        BrowseDirtyProject,
        BuyingChainEvidence,
        CompanyIdentity,
        CompanyProjectMembership,
        IdentityIdentifier,
    )

    need_ids = seed(saved_db, count=1, histories=1)
    with saved_db.begin() as session:
        need = session.get(PowerNeed, need_ids[0])
        project = session.get(Project, need.project_id)
        evidence = session.scalar(
            select(Evidence)
            .join(NeedObservation, NeedObservation.observation_id == Evidence.observation_id)
            .where(NeedObservation.need_id == need.id)
        )
        observation = session.get(Observation, evidence.observation_id)
        identity = CompanyIdentity()
        identity_evidence = BuyingChainEvidence(
            project_id=project.id,
            url="https://example.test/identity-identifier",
            title="Synthetic identity identifier",
            excerpt="Synthetic only.",
            content_hash="c" * 64,
            extraction_location="Synthetic fixture",
            observed_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
            project_match_reason="Synthetic test data.",
        )
        session.add_all([identity, identity_evidence])
        session.flush()
        session.add(
            CompanyProjectMembership(
                company_identity_id=identity.id,
                project_id=project.id,
                role="asset_operator",
                organization_name="Synthetic operator",
                source_id=observation.source_id,
                source_evidence_id=evidence.id,
                source_version_hash=evidence.content_hash,
                decision_basis="synthetic_test",
                operator_number="123456",
            )
        )
        identity_id, project_id = identity.id, project.id
    assert rebuild(saved_db)["status"] == "published"

    with saved_db() as session:
        prior_full = session.get(BrowseState, 1).full_revision
        prior_input = session.get(BrowseState, 1).input_revision
    with saved_db.begin() as session:
        session.get(CompanyIdentity, identity_id).rrc_operator_number = "654321"
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.full_revision == prior_full
        assert state.input_revision == prior_input + 1
        assert set(session.scalars(select(BrowseDirtyProject.project_id))) == {project_id}
    with saved_db.begin() as session:
        identifier = IdentityIdentifier(
            entity_type="company",
            company_identity_id=identity_id,
            person_identity_id=None,
            identifier_type="test_identifier",
            normalized_value="synthetic-identity-123456",
            source_evidence_id=identity_evidence.id,
            source_version_hash=identity_evidence.content_hash,
            reason="Synthetic test fixture.",
        )
        session.add(identifier)
        session.flush()
        identifier_id = identifier.id
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.full_revision == prior_full
        assert set(session.scalars(select(BrowseDirtyProject.project_id))) == {project_id}
    with saved_db.begin() as session:
        result = refresh_project_changes(session, max_projects=None, max_needs=None)
        assert result["status"] == "published"
    with saved_db() as session:
        current_generation(session)
    with saved_db.begin() as session:
        generation_id = session.get(BrowseState, 1).generation_id
        session.add(
            BrowseCustomerMembership(
                generation_id=generation_id,
                company_identity_id=identity_id,
                project_id=project_id,
                organization_name="Synthetic operator",
                role="asset_operator",
                supporting_evidence_count=1,
                last_evidence_update=datetime.now(UTC),
            )
        )
    with saved_db.begin() as session:
        before_membership_delete_input = session.get(BrowseState, 1).input_revision
        before_membership_delete_full = session.get(BrowseState, 1).full_revision
        membership = session.scalar(
            select(CompanyProjectMembership).where(
                CompanyProjectMembership.company_identity_id == identity_id
            )
        )
        session.delete(membership)
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.input_revision == before_membership_delete_input + 1
        assert state.full_revision == before_membership_delete_full
        assert set(session.scalars(select(BrowseDirtyProject.project_id))) == {project_id}
        before_identifier_delete = session.get(BrowseState, 1).input_revision
        full_before_identifier_delete = session.get(BrowseState, 1).full_revision
        assert (
            session.scalar(
                select(func.count())
                .select_from(BrowseCustomerMembership)
                .where(
                    BrowseCustomerMembership.generation_id
                    == session.get(BrowseState, 1).generation_id,
                    BrowseCustomerMembership.company_identity_id == identity_id,
                )
            )
            == 1
        )
    with saved_db.begin() as session:
        session.delete(session.get(IdentityIdentifier, identifier_id))
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.input_revision == before_identifier_delete + 1
        assert state.full_revision == full_before_identifier_delete
        assert set(session.scalars(select(BrowseDirtyProject.project_id))) == {project_id}


def test_unreferenced_identity_reconciliation_rows_do_not_invalidate_browse(saved_db):
    from gridlens.persistence.models import BuyingChainEvidence, CompanyIdentity, IdentityIdentifier

    seed(saved_db, count=1)
    with saved_db.begin() as session:
        project = session.scalar(select(Project))
        source_evidence = BuyingChainEvidence(
            project_id=project.id,
            url="https://example.test/unlinked-identity-identifier",
            title="Synthetic unlinked identity identifier",
            excerpt="Synthetic only.",
            content_hash="f" * 64,
            extraction_location="Synthetic fixture",
            observed_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
            project_match_reason="Synthetic test data.",
        )
        session.add(source_evidence)
        session.flush()
        evidence_id = source_evidence.id
    assert rebuild(saved_db)["status"] == "published"
    with saved_db() as session:
        before = session.get(BrowseState, 1).input_revision
    with saved_db.begin() as session:
        identity = CompanyIdentity()
        session.add(identity)
        session.flush()
        session.add(
            IdentityIdentifier(
                entity_type="company",
                company_identity_id=identity.id,
                person_identity_id=None,
                identifier_type="test_identifier",
                normalized_value="unlinked-synthetic-123456",
                source_evidence_id=evidence_id,
                source_version_hash="f" * 64,
                reason="Synthetic test fixture.",
            )
        )
    with saved_db() as session:
        assert session.get(BrowseState, 1).input_revision == before
        current_generation(session)


def test_company_membership_mutations_refresh_only_old_and_new_project_owners(saved_db):
    from gridlens.intelligence.saved_browse import refresh_project_changes
    from gridlens.persistence.models import (
        BrowseDirtyProject,
        CompanyIdentity,
        CompanyProjectMembership,
    )

    need_ids = seed(saved_db, count=2, histories=1)
    with saved_db.begin() as session:
        needs = [session.get(PowerNeed, need_id) for need_id in need_ids]
        projects = [session.get(Project, need.project_id) for need in needs]
        evidence = session.scalar(
            select(Evidence)
            .join(NeedObservation, NeedObservation.observation_id == Evidence.observation_id)
            .where(NeedObservation.need_id == need_ids[0])
        )
        identity = CompanyIdentity(rrc_operator_number="123456")
        session.add(identity)
        session.flush()
        identity_id = identity.id
        first_project_id, second_project_id = projects[0].id, projects[1].id
        evidence_id = evidence.id
        source_id = evidence.observation.source_id
        content_hash = evidence.content_hash
    assert rebuild(saved_db)["status"] == "published"

    with saved_db() as session:
        prior_input = session.get(BrowseState, 1).input_revision
        prior_full = session.get(BrowseState, 1).full_revision
    with saved_db.begin() as session:
        membership = CompanyProjectMembership(
            company_identity_id=identity_id,
            project_id=first_project_id,
            role="asset_operator",
            organization_name="Synthetic RRC Operator",
            source_id=source_id,
            source_evidence_id=evidence_id,
            source_version_hash=content_hash,
            decision_basis="typed_rrc_operator_number_v1",
            operator_number="123456",
        )
        session.add(membership)
        session.flush()
        membership_id = membership.id
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.input_revision == prior_input + 1
        assert state.full_revision == prior_full
        assert set(session.scalars(select(BrowseDirtyProject.project_id))) == {first_project_id}
    with saved_db.begin() as session:
        assert (
            refresh_project_changes(session, max_projects=None, max_needs=None)["status"]
            == "published"
        )
    with saved_db() as session:
        generation = current_generation(session)
        assert generation.input_revision == session.get(BrowseState, 1).input_revision

    with saved_db() as session:
        prior_input = session.get(BrowseState, 1).input_revision
        prior_full = session.get(BrowseState, 1).full_revision
    with saved_db.begin() as session:
        session.get(CompanyProjectMembership, membership_id).project_id = second_project_id
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.input_revision == prior_input + 1
        assert state.full_revision == prior_full
        assert set(session.scalars(select(BrowseDirtyProject.project_id))) == {
            first_project_id,
            second_project_id,
        }
    with saved_db.begin() as session:
        assert (
            refresh_project_changes(session, max_projects=None, max_needs=None)["status"]
            == "published"
        )
    with saved_db() as session:
        generation = current_generation(session)
        assert generation.input_revision == session.get(BrowseState, 1).input_revision


def test_malformed_company_membership_dependency_falls_back_to_full(saved_db):
    seed(saved_db, count=1)
    with saved_db.begin() as session:
        state = session.get(BrowseState, 1)
        prior_input = state.input_revision
        session.execute(
            text("SELECT invalidate_browse_company_membership_rows(CAST(:affected AS jsonb))"),
            {"affected": '[{"project_id":"not-a-uuid"}]'},
        )
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.input_revision == prior_input + 1
        assert state.full_revision == state.input_revision


def test_company_membership_truncate_keeps_full_invalidation(saved_db):
    seed(saved_db, count=1)
    with saved_db() as session:
        prior_input = session.get(BrowseState, 1).input_revision
    with saved_db.begin() as session:
        session.execute(
            text("TRUNCATE company_project_membership_corrections, company_project_memberships")
        )
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.input_revision == prior_input + 1
        assert state.full_revision == state.input_revision


def test_person_identifier_changes_scope_through_historical_project_claims(saved_db):
    from gridlens.persistence.models import (
        BrowseDirtyProject,
        BuyingChainClaim,
        BuyingChainEvidence,
        BuyingChainIdentityLink,
        IdentityIdentifier,
        PersonIdentity,
    )

    seed(saved_db, count=2)
    with saved_db.begin() as session:
        people = [PersonIdentity(), PersonIdentity()]
        projects = list(session.scalars(select(Project).order_by(Project.name)))
        evidence_rows = []
        for index, (person, project) in enumerate(zip(people, projects, strict=True)):
            evidence = BuyingChainEvidence(
                project_id=project.id,
                url=f"https://example.test/person-identity-{index}",
                title="Synthetic buyer relationship",
                excerpt="Synthetic only.",
                content_hash=str(index + 3) * 64,
                extraction_location="Synthetic fixture",
                observed_at=datetime.now(UTC),
                last_seen_at=datetime.now(UTC),
                project_match_reason="Synthetic test data.",
            )
            session.add_all([person, evidence])
            session.flush()
            claim = BuyingChainClaim(
                project_id=project.id,
                entity_key=f"synthetic-person-identity-{index}",
                fingerprint=str(index + 5) * 64,
                policy_version="synthetic-test-v1",
                organization="Synthetic buyer",
                person_name=f"Synthetic Person {index}",
                title="Decision maker",
                category="owner_developer",
                organization_relationship="DIRECT",
                person_organization_relationship="DIRECT",
                person_project_relationship="DIRECT",
                evidence_strength="High",
                reason="Synthetic test fixture.",
                citations=[],
                public_contacts=[],
                observed_at=datetime.now(UTC),
            )
            session.add(claim)
            session.flush()
            session.add(
                BuyingChainIdentityLink(
                    claim_id=claim.id,
                    entity_type="person",
                    person_identity_id=person.id,
                    company_identity_id=None,
                    reason="Synthetic identity link",
                    basis="strong_identifier",
                    source_evidence_id=evidence.id,
                    source_version_hash=evidence.content_hash,
                    state="superseded",
                )
            )
            evidence_rows.append(evidence)
        identifier = IdentityIdentifier(
            entity_type="person",
            company_identity_id=None,
            person_identity_id=people[0].id,
            identifier_type="test_person_identifier",
            normalized_value="synthetic-person-123456",
            source_evidence_id=evidence_rows[0].id,
            source_version_hash=evidence_rows[0].content_hash,
            reason="Synthetic test fixture.",
        )
        session.add(identifier)
        session.flush()
        person_ids = [person.id for person in people]
        project_ids = {project.id for project in projects}
        identifier_id = identifier.id
    assert rebuild(saved_db)["status"] == "published"
    with saved_db() as session:
        before = session.get(BrowseState, 1)
        prior_input, prior_full = before.input_revision, before.full_revision
    with saved_db.begin() as session:
        session.get(IdentityIdentifier, identifier_id).person_identity_id = person_ids[1]
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.input_revision == prior_input + 1
        assert state.full_revision == prior_full
        assert set(session.scalars(select(BrowseDirtyProject.project_id))) == project_ids
    with saved_db.begin() as session:
        session.delete(session.get(IdentityIdentifier, identifier_id))
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.input_revision == prior_input + 2
        assert state.full_revision == prior_full
        assert set(session.scalars(select(BrowseDirtyProject.project_id))) == project_ids


def test_malformed_identity_dependency_falls_back_to_full_invalidation(saved_db):
    seed(saved_db, count=1)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db() as session:
        before = session.get(BrowseState, 1).input_revision
    with saved_db.begin() as session:
        session.execute(
            text("""
                SELECT invalidate_browse_identity_entities(
                    jsonb_build_array(jsonb_build_object(
                        'entity_type', 'company',
                        'company_identity_id', 'malformed',
                        'person_identity_id', NULL
                    )),
                    'identity_identifiers'
                )
            """)
        )
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.input_revision == before + 1
        assert state.full_revision == state.input_revision
        with pytest.raises(HTTPException):
            current_generation(session)


def test_identity_identifier_truncate_keeps_full_invalidation(saved_db):
    seed(saved_db, count=1)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db() as session:
        before = session.get(BrowseState, 1).input_revision
    with saved_db.begin() as session:
        session.execute(text("TRUNCATE TABLE identity_identifiers"))
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.input_revision == before + 1
        assert state.full_revision == state.input_revision
        with pytest.raises(HTTPException):
            current_generation(session)


def test_long_history_can_publish_compact_browse_but_detail_stays_bounded(saved_db, monkeypatch):
    ids = seed(saved_db, count=1, histories=501)
    assert rebuild(saved_db)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    with saved_db() as session:
        saved = page(session, filters())["items"]
    assert len(saved) == 1
    assert saved[0]["evidence_count"] == 501
    assert saved[0]["evidence"] == []
    with pytest.raises(HTTPException) as exc:
        api.opportunity_need_detail(ids[0])
    assert exc.value.status_code == 413


@pytest.mark.parametrize(
    "selection",
    [
        {"tier": "Signal"},
        {"tier": "Lead"},
        {"geography": "California"},
        {"geography": "UNKNOWN"},
        {"industry": "UNKNOWN"},
        {"industry": "construction"},
        {"activity": "construction"},
        {"activity": "UNKNOWN"},
        {"timing": "UNKNOWN"},
        {"timing": "KNOWN"},
        {"mw_status": "UNKNOWN"},
        {"mw_min": "0.3"},
        {"mw_min": "1e1000000"},
        {"mw_max": "1e1000000"},
        {"mw_min": "1e-1000000"},
        {"mw_max": "1e-1000000"},
        {"priority_segment": "8"},
        {"tier": "Signal", "decision": "REVIEW", "search": "full history"},
    ],
)
def test_saved_filter_and_rank_parity(saved_db, selection):
    seed(saved_db)
    expected_response = Response()
    expected = api.opportunities(
        **selection, response=expected_response, sort="rank", limit=50, offset=0, cohort=None
    )
    rebuild(saved_db)
    with saved_db() as session:
        actual = page(session, filters(**selection), ranked=True)
    assert [str(row["id"]) for row in actual["items"]] == [str(row["id"]) for row in expected]
    assert actual["total_count"] == int(expected_response.headers["x-total-count"])
    assert actual["group_total_count"] == int(expected_response.headers["x-group-total-count"])


def test_group_membership_is_recomputed_after_activity_filter(saved_db):
    ids = seed(saved_db, count=1)
    with saved_db.begin() as session:
        original = session.get(PowerNeed, ids[0])
        sibling = PowerNeed(
            project_id=original.project_id,
            activity_key="operations",
            tier="Signal",
            rationale="Fixture",
            supply="Unknown",
        )
        session.add(sibling)
    rebuild(saved_db)
    for selection in (
        {},
        {"activity": "construction"},
        {"activity": "operations"},
        {"search": "full history 2"},
    ):
        expected = api.opportunities(**selection, limit=50, offset=0, cohort=None)
        with saved_db() as session:
            actual = page(session, filters(**selection))["items"]
        assert [
            (str(row["id"]), row["group_id"], row["group_total_filtered"]) for row in actual
        ] == [(str(row["id"]), row["group_id"], row["group_total_filtered"]) for row in expected]


def test_exact_fact_boundary_and_policy_expiry_fail_closed(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse
    from gridlens.persistence.models import BrowseGeneration, CallFactDecision, CallFactVersion

    ids = seed(saved_db, count=1)
    boundary = datetime.now(UTC) + timedelta(minutes=5)
    with saved_db.begin() as session:
        need = session.get(PowerNeed, ids[0])
        session.add(
            CallFactVersion(
                need_id=need.id,
                project_id=need.project_id,
                client_id=uuid4(),
                activity_key=need.activity_key,
                facility_scope="Synthetic",
                fact_type="demand",
                value={"mw": "20"},
                reporter_name="Synthetic operator",
                confirmation_channel="call",
                confirmed_at=datetime.now(UTC),
                effective_from=boundary,
                content_hash="a" * 64,
                recorded_by="Synthetic actor",
            )
        )
        session.flush()
        fact = session.scalar(select(CallFactVersion).where(CallFactVersion.need_id == need.id))
        session.add(
            CallFactDecision(
                need_id=need.id,
                fact_version_id=fact.id,
                version=1,
                client_id=uuid4(),
                decision="accepted",
                expected_version=0,
                reason="Synthetic accepted future demand",
                content_hash="b" * 64,
                actor="Synthetic",
            )
        )
    rebuild(saved_db)
    with saved_db() as session:
        generation = current_generation(session)
        assert generation.valid_until == saved_browse.clock_deadline(session, generation.built_at)
        assert generation.valid_until <= boundary
        with pytest.raises(HTTPException):
            current_generation(session, now=boundary)
        assert (
            session.scalar(select(BrowseGeneration)).policy_version == saved_browse.POLICY_VERSION
        )
    monkeypatch.setattr(saved_browse, "POLICY_VERSION", "changed-policy")
    with saved_db() as session, pytest.raises(HTTPException):
        current_generation(session)


def test_failed_build_preserves_current_generation_and_rolls_back_rows(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse
    from gridlens.persistence.models import BrowseGeneration

    seed(saved_db, count=1)
    first = rebuild(saved_db)

    def fail(*args):
        raise RuntimeError("Synthetic build interruption")

    monkeypatch.setattr(saved_browse, "_search_texts", fail)
    with pytest.raises(RuntimeError, match="Synthetic build interruption"):
        rebuild(saved_db)
    with saved_db() as session:
        assert str(current_generation(session).id) == first["generation_id"]
        assert len(session.scalars(select(BrowseGeneration)).all()) == 1


def test_competing_builder_is_excluded_without_input_or_pointer_changes(saved_db):
    from sqlalchemy import func

    from gridlens.intelligence.saved_browse import BUILD_LOCK

    with saved_db() as owner:
        assert owner.scalar(select(func.pg_try_advisory_lock(BUILD_LOCK)))
        try:
            assert rebuild(saved_db) == {"status": "busy"}
        finally:
            owner.execute(select(func.pg_advisory_unlock(BUILD_LOCK)))


def test_retention_and_safe_generation_rollback(saved_db):
    from uuid import UUID

    from gridlens.intelligence.saved_browse import restore_generation
    from gridlens.persistence.models import BrowseGeneration

    seed(saved_db, count=1)
    generations = [rebuild(saved_db)["generation_id"] for _ in range(4)]
    with saved_db() as session:
        assert len(session.scalars(select(BrowseGeneration)).all()) == 3
    assert not restore_generation(saved_db, UUID(generations[0]))
    assert restore_generation(saved_db, UUID(generations[1]))
    with saved_db.begin() as session:
        session.execute(text("UPDATE power_needs SET rationale='Changed fixture'"))
    assert not restore_generation(saved_db, UUID(generations[2]))


def test_clock_boundary_crossed_during_build_cannot_publish(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse

    seed(saved_db, count=1)
    monkeypatch.setattr(
        saved_browse, "clock_deadline", lambda session, now: now + timedelta(microseconds=1)
    )
    assert rebuild(saved_db)["status"] == "superseded"
    with saved_db() as session, pytest.raises(HTTPException):
        current_generation(session)


def test_map_group_detail_and_export_accept_saved_tokens(saved_db, monkeypatch):
    seed(saved_db, count=3)
    canonical = api.opportunity_map_window(tier="Signal")
    rebuild(saved_db)
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    saved = api.opportunity_map_window(tier="Signal")
    assert [str(row["id"]) for row in saved["items"]] == [
        str(row["id"]) for row in canonical["items"]
    ]
    assert "summaries" not in saved
    assert saved["items"][0]["evidence"] == []
    item = saved["items"][0]
    group = api.opportunity_group_page(
        item["group_id"], saved["cohort_token"], tier="Signal", limit=50, offset=0
    )
    assert group["items"][0]["id"] == item["id"]
    empty_page = api.opportunity_group_page(
        item["group_id"], saved["cohort_token"], tier="Signal", limit=50, offset=999
    )
    assert empty_page["items"] == []
    assert empty_page["total"] == group["total"]
    from uuid import UUID

    detail = api.opportunity_need_detail(
        UUID(str(item["id"])), tier="Signal", cohort_token=saved["cohort_token"]
    )
    assert len(detail["evidence"]) == 3
    exported = api.export_opportunities_csv(
        tier="Signal", cohort_token=saved["cohort_token"], limit=500
    )
    assert exported.headers["x-total-count"] == "3"

    async def read_export():
        return "".join([chunk.decode() async for chunk in exported.body_iterator])

    exported_csv = asyncio.run(read_export())
    export_rows = list(csv.DictReader(StringIO(exported_csv)))
    first_export = next(row for row in export_rows if row["need_id"] == str(item["id"]))
    assert int(first_export["rank_score"]) == detail["rank_score"]
    assert json.loads(first_export["rank_reasons"]) == detail["rank_reasons"]
    assert first_export["rank_version"] == detail["rank_version"]
    with saved_db.begin() as session:
        session.execute(text("UPDATE projects SET name='Changed fixture'"))
    with pytest.raises(HTTPException) as exc:
        api.opportunity_map_window(tier="Signal")
    assert exc.value.status_code == 503


def test_unscoped_detail_keeps_canonical_priority_metadata(saved_db, monkeypatch):
    ids = seed(saved_db, count=1)
    expected = api.opportunity_need_detail(ids[0])
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    actual = api.opportunity_need_detail(ids[0])
    for key in ("priority_segment", "priority_label", "workflow_status", "tier", "rank_score"):
        assert actual[key] == expected[key]


@pytest.mark.parametrize(
    "selection",
    [
        {"mw_min": "1e1000000"},
        {"mw_max": "1e1000000"},
        {"mw_min": "1e-1000000"},
        {"mw_max": "1e-1000000"},
    ],
)
def test_extreme_bounds_match_decimal_comparisons_for_known_and_zero_ranges(saved_db, selection):
    from decimal import Decimal

    from gridlens.persistence.models import BrowseRow

    seed(saved_db, count=3)
    rebuild(saved_db)
    canonical = []
    # Test the SQL filter against canonical interval arithmetic independently of
    # qualification. Zero lower bounds can occur in visible uncertain ranges.
    with saved_db.begin() as session:
        rows = session.scalars(select(BrowseRow).order_by(BrowseRow.need_id)).all()
        for row, interval in zip(rows, ("0 to 2 MW", "1 to 3 MW", None), strict=True):
            parsed = api.exact_mw_interval(interval)
            row.mw_low = parsed[0] if parsed else None
            row.mw_high = parsed[1] if parsed else None
            canonical.append({"id": str(row.need_id), "required_mw": interval})
        assert rows[0].mw_low == Decimal("0")
    selected_filters = filters(**selection)
    expected = api._filter_opportunity_summaries(canonical, selected_filters)
    with saved_db() as session:
        actual = page(session, selected_filters)["items"]
    assert {row["id"] for row in actual} == {row["id"] for row in expected}


@pytest.mark.parametrize("selection", [{}, {"search": "full history"}])
def test_offset_beyond_database_integer_range_is_a_valid_empty_page(saved_db, selection):
    seed(saved_db, count=1)
    rebuild(saved_db)
    with saved_db() as session:
        result = page(session, filters(**selection), offset=10**100)
    assert result["items"] == []
    assert result["total_count"] == 1


def test_incremental_refresh_is_atomic_and_rebuilds_only_dirty_project(saved_db, monkeypatch):
    from gridlens.intelligence.saved_browse import refresh_project_changes

    ids = seed(saved_db)
    rebuild(saved_db)
    with saved_db() as reader:
        original = current_generation(reader).id
    calls = []
    canonical = api.opportunity_projection

    def track(session, **kwargs):
        calls.append(kwargs.get("selected_need_ids"))
        return canonical(session, **kwargs)

    monkeypatch.setattr(api, "opportunity_projection", track)
    with saved_db.begin() as writer:
        need = writer.get(PowerNeed, ids[0])
        need.active = False
        writer.flush()
        result = refresh_project_changes(writer)
        assert result["mode"] == "projects"
        assert result["needs"] == 1
        with saved_db() as reader:
            assert current_generation(reader).id == original
            assert len(page(reader, filters())["items"]) == len(ids)
    assert calls and all(value == {ids[0]} for value in calls)
    with saved_db() as reader:
        assert current_generation(reader).id != original
        assert str(ids[0]) not in {str(item["id"]) for item in page(reader, filters())["items"]}
    monkeypatch.setattr(settings, "saved_browse_enabled", False)
    baseline = api.opportunities(limit=50, offset=0, cohort=None)
    with saved_db() as reader:
        actual = page(reader, filters())["items"]
    assert [str(item["id"]) for item in actual] == [str(item["id"]) for item in baseline]


def test_incremental_customer_projection_reassignment_matches_full_rebuild(saved_db, monkeypatch):
    from types import SimpleNamespace

    from gridlens.intelligence import customer_accounts
    from gridlens.intelligence.saved_browse import refresh_project_changes

    need_ids = seed(saved_db, count=3)
    old_identity_id, new_identity_id = uuid4(), uuid4()
    with saved_db.begin() as session:
        session.add_all([CompanyIdentity(id=old_identity_id), CompanyIdentity(id=new_identity_id)])
    with saved_db.begin() as session:
        project_ids = dict(
            session.execute(
                select(PowerNeed.id, PowerNeed.project_id).where(PowerNeed.id.in_(need_ids))
            ).all()
        )
    project_id = project_ids[need_ids[0]]
    untouched_project_id = project_ids[need_ids[1]]
    latest_support = datetime.now(UTC) - timedelta(days=1)
    claims_by_project = {
        project_id: (
            old_identity_id,
            SimpleNamespace(
                organization="Shared owner",
                category="owner_developer",
                citations=[{"evidence_id": "old-dirty-support"}],
                observed_at=latest_support - timedelta(days=1),
            ),
        ),
        untouched_project_id: (
            old_identity_id,
            SimpleNamespace(
                organization="Shared owner",
                category="owner_developer",
                citations=[{"evidence_id": "untouched-support"}],
                observed_at=latest_support,
            ),
        ),
    }

    def current_claims(session, identity_ids=None, *, project_ids=None, include_conflicts=False):
        return [
            (identity_id, current_project_id, claim)
            for current_project_id, (identity_id, claim) in claims_by_project.items()
            if (project_ids is None or current_project_id in project_ids)
            and (identity_ids is None or identity_id in identity_ids)
        ]

    monkeypatch.setattr(customer_accounts, "_current_customer_claims", current_claims)
    monkeypatch.setattr(customer_accounts, "_current_conflicted_memberships", lambda *_args: [])
    monkeypatch.setattr(customer_accounts, "_current_role_claims", lambda *_args, **_kwargs: [])
    rebuild(saved_db)
    with saved_db() as session:
        previous_generation = current_generation(session)
        untouched = session.scalar(
            select(BrowseCustomerMembership).where(
                BrowseCustomerMembership.generation_id == previous_generation.id,
                BrowseCustomerMembership.company_identity_id == old_identity_id,
                BrowseCustomerMembership.project_id == untouched_project_id,
            )
        )
        assert untouched.supporting_evidence_count == 2
    claims_by_project[project_id] = (
        new_identity_id,
        SimpleNamespace(
            organization="New owner",
            category="owner_developer",
            citations=[{"evidence_id": "reassigned-support"}],
            observed_at=latest_support + timedelta(days=1),
        ),
    )

    with saved_db.begin() as session:
        session.get(PowerNeed, need_ids[0]).rationale = "Updated synthetic evidence"
        session.flush()
        result = refresh_project_changes(session)
        assert result["status"] == "published"
        assert result["projects"] == 1

    with saved_db() as session:
        incremental = current_generation(session)
        memberships = session.scalars(
            select(BrowseCustomerMembership).where(
                BrowseCustomerMembership.generation_id == incremental.id
            )
        ).all()
        dirty_memberships = [row for row in memberships if row.project_id == project_id]
        assert [(row.company_identity_id, row.organization_name) for row in dirty_memberships] == [
            (new_identity_id, "New owner")
        ]
        untouched = next(row for row in memberships if row.project_id == untouched_project_id)
        assert untouched.company_identity_id == old_identity_id
        assert untouched.supporting_evidence_count == 1
        assert untouched.last_evidence_update == latest_support
        assert (
            session.scalar(
                select(func.count())
                .select_from(BrowseUnresolvedCustomer)
                .where(
                    BrowseUnresolvedCustomer.generation_id == incremental.id,
                    BrowseUnresolvedCustomer.project_id == project_id,
                )
            )
            == 0
        )

    rebuild(saved_db)
    with saved_db() as session:
        rebuilt = current_generation(session)
        incremental_memberships = session.execute(
            select(
                BrowseCustomerMembership.company_identity_id,
                BrowseCustomerMembership.project_id,
                BrowseCustomerMembership.organization_name,
                BrowseCustomerMembership.role,
                BrowseCustomerMembership.supporting_evidence_count,
                BrowseCustomerMembership.last_evidence_update,
            )
            .where(BrowseCustomerMembership.generation_id == incremental.id)
            .order_by(
                BrowseCustomerMembership.project_id,
                BrowseCustomerMembership.company_identity_id,
            )
        ).all()
        rebuilt_memberships = session.execute(
            select(
                BrowseCustomerMembership.company_identity_id,
                BrowseCustomerMembership.project_id,
                BrowseCustomerMembership.organization_name,
                BrowseCustomerMembership.role,
                BrowseCustomerMembership.supporting_evidence_count,
                BrowseCustomerMembership.last_evidence_update,
            )
            .where(BrowseCustomerMembership.generation_id == rebuilt.id)
            .order_by(
                BrowseCustomerMembership.project_id,
                BrowseCustomerMembership.company_identity_id,
            )
        ).all()
        incremental_unresolved = session.execute(
            select(
                BrowseUnresolvedCustomer.project_id,
                BrowseUnresolvedCustomer.organization_name,
                BrowseUnresolvedCustomer.role,
                BrowseUnresolvedCustomer.reason,
            )
            .where(BrowseUnresolvedCustomer.generation_id == incremental.id)
            .order_by(BrowseUnresolvedCustomer.project_id)
        ).all()
        rebuilt_unresolved = session.execute(
            select(
                BrowseUnresolvedCustomer.project_id,
                BrowseUnresolvedCustomer.organization_name,
                BrowseUnresolvedCustomer.role,
                BrowseUnresolvedCustomer.reason,
            )
            .where(BrowseUnresolvedCustomer.generation_id == rebuilt.id)
            .order_by(BrowseUnresolvedCustomer.project_id)
        ).all()
        assert incremental_memberships == rebuilt_memberships
        assert incremental_unresolved == rebuilt_unresolved


def test_incremental_rollback_unknown_write_and_expiry_fail_closed(saved_db):
    from gridlens.intelligence.saved_browse import refresh_project_changes
    from gridlens.persistence.models import BrowseGeneration

    ids = seed(saved_db)
    rebuild(saved_db)
    with saved_db() as reader:
        original = current_generation(reader).id
    with saved_db() as writer:
        writer.get(PowerNeed, ids[0]).active = False
        assert refresh_project_changes(writer)["status"] == "published"
        writer.rollback()
    with saved_db() as reader:
        assert current_generation(reader).id == original
    with saved_db.begin() as writer:
        writer.execute(text("UPDATE sources SET publisher = 'Changed source policy'"))
        assert refresh_project_changes(writer) is None
    with saved_db() as reader, pytest.raises(HTTPException):
        current_generation(reader)
    rebuild(saved_db)
    with saved_db.begin() as writer:
        generation = current_generation(writer)
        generation.valid_until = datetime.now(UTC) - timedelta(seconds=1)
    with saved_db.begin() as writer:
        writer.get(PowerNeed, ids[0]).active = False
        assert refresh_project_changes(writer) is None
    with saved_db() as reader, pytest.raises(HTTPException):
        current_generation(reader)
    with saved_db() as reader:
        assert reader.scalar(select(BrowseGeneration.id).limit(1)) is not None


def test_multiple_refreshes_in_one_transaction_keep_latest_revision(saved_db):
    from gridlens.intelligence.saved_browse import refresh_project_changes

    ids = seed(saved_db)
    rebuild(saved_db)
    with saved_db.begin() as writer:
        writer.get(PowerNeed, ids[0]).active = False
        assert refresh_project_changes(writer)["status"] == "published"
        writer.get(PowerNeed, ids[1]).active = False
        assert refresh_project_changes(writer)["status"] == "published"
    with saved_db() as reader:
        assert len(page(reader, filters())["items"]) == len(ids) - 2


def test_failed_derived_refresh_retains_canonical_change_as_pending(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse
    from gridlens.intelligence.worker_browse import install_worker_publication

    ids = seed(saved_db)
    rebuild(saved_db)
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    worker_factory = sessionmaker(saved_db.kw["bind"], expire_on_commit=False)
    install_worker_publication(worker_factory)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic derived failure")

    monkeypatch.setattr(saved_browse, "_write_rows", fail)
    with worker_factory.begin() as writer:
        writer.get(PowerNeed, ids[0]).active = False
        # The autonomous publication hook must let the canonical worker write
        # commit while leaving the derived generation pending on failure.
    with saved_db() as reader:
        assert reader.get(PowerNeed, ids[0]).active is False
        with pytest.raises(HTTPException):
            current_generation(reader)
    monkeypatch.undo()
    assert rebuild(saved_db)["status"] == "published"


def test_incremental_expiring_during_construction_never_serves_current(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse
    from gridlens.persistence.models import BrowseGeneration

    ids = seed(saved_db)
    rebuild(saved_db)
    canonical = saved_browse._write_rows

    def cross_boundary(session, generation_id, summaries):
        result = canonical(session, generation_id, summaries)
        after_deadline = session.get(BrowseGeneration, generation_id).valid_until + timedelta(
            seconds=1
        )

        class AdvancedClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return after_deadline

        monkeypatch.setattr(saved_browse, "datetime", AdvancedClock)
        return result

    monkeypatch.setattr(saved_browse, "_write_rows", cross_boundary)
    with saved_db.begin() as writer:
        writer.get(PowerNeed, ids[0]).active = False
        assert saved_browse.refresh_project_changes(writer) is None
    with saved_db() as reader, pytest.raises(HTTPException):
        current_generation(reader)


def test_full_build_rebases_repeated_scoped_writes_before_publication(saved_db):
    ids = seed(saved_db)

    def repeated_writes():
        for index in range(8):
            with saved_db.begin() as writer:
                writer.get(PowerNeed, ids[index % len(ids)]).active = False

    result = rebuild(saved_db, before_publish=repeated_writes)
    assert result["status"] == "published"
    assert result["row_count"] == 0
    with saved_db() as reader:
        assert (
            current_generation(reader).input_revision == reader.get(BrowseState, 1).input_revision
        )
        assert not page(reader, filters())["items"]


def test_full_build_rebases_ingestion_evidence_tail_without_stale_qualification(saved_db):
    ids = seed(saved_db, histories=1)

    def ingestion_tail():
        # Ingestion persists a new source version before evaluating it. The old
        # interpretation must stop admitting this need at the very same commit.
        with saved_db.begin() as writer:
            observation = writer.scalar(
                select(Observation)
                .join(NeedObservation, NeedObservation.observation_id == Observation.id)
                .where(NeedObservation.need_id == ids[0])
            )
            observation.content_hash = "f" * 64

    result = rebuild(saved_db, before_publish=ingestion_tail)
    assert result["status"] == "published"
    with saved_db() as reader:
        assert {item["id"] for item in page(reader, filters())["items"]} == set(map(str, ids[1:]))
        current_generation(reader)


def test_source_health_checkpoint_does_not_discard_current_browse(saved_db):
    seed(saved_db)
    rebuild(saved_db)
    with saved_db() as reader:
        generation_id = current_generation(reader).id
    with saved_db.begin() as writer:
        source = writer.get(Source, "synthetic-permits")
        source.health = {"status": "Running", "last_attempt": datetime.now(UTC).isoformat()}
    with saved_db() as reader:
        assert current_generation(reader).id == generation_id
    # Unknown/source-admission changes must continue to invalidate the snapshot.
    with saved_db.begin() as writer:
        writer.get(Source, "synthetic-permits").family = "changed-source-policy"
    with saved_db() as reader, pytest.raises(HTTPException):
        current_generation(reader)


def test_ordinary_maintainer_publishes_first_generation_for_opportunities(saved_db, monkeypatch):
    from fastapi.testclient import TestClient

    from gridlens.intelligence.saved_browse import maintain_once
    from gridlens.security import token_for

    seed(saved_db, count=2, histories=0)
    monkeypatch.setattr(settings, "saved_browse_enabled", False)
    monkeypatch.setattr(settings, "typesafe_api_key", None)
    token = token_for(int(datetime.now(UTC).timestamp()) + 300)
    with TestClient(api.app, base_url="https://testserver") as client:
        client.cookies.set("gridlens_session", token)
        assert client.get("/api/opportunities").status_code == 200

        monkeypatch.setattr(settings, "saved_browse_enabled", True)
        pending = client.get("/api/opportunities")
        assert pending.status_code == 503
        assert pending.headers["x-qualification-state"] == "pending"

        assert maintain_once(saved_db)["status"] == "published"
        assert client.get("/api/opportunities").status_code == 200


def test_worker_startup_publishes_flushed_ingestion_before_each_commit(saved_db, monkeypatch):
    import gridlens.jobs.worker as worker

    ids = seed(saved_db, histories=1)
    rebuild(saved_db)
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    monkeypatch.setattr(worker, "SessionLocal", saved_db)
    monkeypatch.setattr(worker, "load_registry", lambda: [])

    def run_ingestion(_stop, _definitions):
        for index, need_id in enumerate(ids):
            with saved_db.begin() as writer:
                observation = writer.scalar(
                    select(Observation)
                    .join(NeedObservation, NeedObservation.observation_id == Observation.id)
                    .where(NeedObservation.need_id == need_id)
                )
                observation.content_hash = "f" * 64
                writer.flush()  # The callback must not depend on ORM dirty collections.
                with saved_db() as before_commit:
                    assert len(page(before_commit, filters())["items"]) == len(ids) - index
            with saved_db() as after_commit:
                assert {item["id"] for item in page(after_commit, filters())["items"]} == set(
                    map(str, ids[index + 1 :])
                )

    monkeypatch.setattr(worker, "_run_worker_lanes", run_ingestion)
    worker.main()


def test_worker_refresh_uses_latest_database_values_after_prior_session_reads(
    saved_db, monkeypatch
):
    from gridlens.intelligence.worker_browse import install_worker_publication

    ids = seed(saved_db, histories=1)
    rebuild(saved_db)
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    worker_factory = sessionmaker(saved_db.kw["bind"], expire_on_commit=False)
    install_worker_publication(worker_factory)
    with worker_factory() as worker:
        stale = worker.scalar(
            select(Observation)
            .join(NeedObservation, NeedObservation.observation_id == Observation.id)
            .where(NeedObservation.need_id == ids[0])
        )
        worker.commit()
        with saved_db.begin() as concurrent:
            concurrent.get(Observation, stale.id).content_hash = "f" * 64
        # A later canonical write must refresh the concurrently changed object
        # too; a heartbeat alone deliberately cannot repair another transaction.
        worker.get(PowerNeed, ids[1]).rationale = "Retained operator annotation"
        worker.commit()
    with saved_db() as reader:
        assert {item["id"] for item in page(reader, filters())["items"]} == set(map(str, ids[1:]))


def test_operator_refresh_does_not_publish_cached_project_after_concurrent_identity_change(
    saved_db,
):
    from gridlens.intelligence.saved_browse import refresh_project_changes

    ids = seed(saved_db, histories=1)
    rebuild(saved_db)
    with saved_db() as operator:
        need = operator.get(PowerNeed, ids[0])
        cached_project = operator.get(Project, need.project_id)
        with saved_db.begin() as concurrent:
            concurrent.get(Project, cached_project.id).identity_key = "corrected-physical-identity"
        need.rationale = "Operator annotation after loading the prior project"
        assert refresh_project_changes(operator)["status"] == "published"
        operator.commit()
    with saved_db() as reader:
        assert {item["id"] for item in page(reader, filters())["items"]} == set(map(str, ids[1:]))


def test_worker_refresh_failure_preserves_evidence_and_restart_recovers(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse
    from gridlens.intelligence.worker_browse import install_worker_publication

    ids = seed(saved_db, histories=1)
    rebuild(saved_db)
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    worker_factory = sessionmaker(saved_db.kw["bind"], expire_on_commit=False)
    install_worker_publication(worker_factory)
    original = saved_browse._write_rows

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic derived failure")

    monkeypatch.setattr(saved_browse, "_write_rows", fail)
    with worker_factory.begin() as writer:
        observation = writer.scalar(
            select(Observation)
            .join(NeedObservation, NeedObservation.observation_id == Observation.id)
            .where(NeedObservation.need_id == ids[0])
        )
        observation_id = observation.id
        observation.content_hash = "f" * 64
    with saved_db() as reader:
        assert reader.get(Observation, observation_id).content_hash == "f" * 64
        with pytest.raises(HTTPException):
            current_generation(reader)
    monkeypatch.setattr(saved_browse, "_write_rows", original)
    # New pool/factory/process state must recover solely from persisted journal.
    saved_db.kw["bind"].dispose()
    restarted = sessionmaker(saved_db.kw["bind"], expire_on_commit=False)
    assert saved_browse.maintain_once(restarted)["status"] == "published"
    with restarted() as reader:
        assert {item["id"] for item in page(reader, filters())["items"]} == set(map(str, ids[1:]))


def test_continuous_worker_ingestion_keeps_saved_reads_current_and_exact(saved_db, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from gridlens.intelligence import saved_browse, worker_browse
    from gridlens.intelligence.worker_browse import install_worker_publication

    ids = seed(saved_db, histories=1)
    # Keep both publication and reader clocks on one ordinary instant, well
    # away from the next browse-policy boundary, so this concurrency scenario
    # cannot depend on sub-millisecond wall-clock sampling luck.
    fixed_now = datetime(2026, 10, 23, 16, 0, tzinfo=UTC)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr(saved_browse, "datetime", FixedDatetime)
    monkeypatch.setattr(worker_browse, "datetime", FixedDatetime)
    initial = rebuild(saved_db)
    assert initial["status"] == "published", initial
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    writer_factory = sessionmaker(saved_db.kw["bind"], expire_on_commit=False)
    install_worker_publication(writer_factory)
    started, finished = Event(), Event()
    writer_outcomes = []

    def ingest():
        try:
            for index in range(12):
                with writer_factory.begin() as writer:
                    observation = writer.scalar(
                        select(Observation)
                        .join(NeedObservation, NeedObservation.observation_id == Observation.id)
                        .where(NeedObservation.need_id == ids[0])
                    )
                    observation.content_hash = ("f" * 64) if index % 2 == 0 else ("0" * 64)
                    writer.flush()
                    started.set()
                writer_outcomes.append(writer.info.get("worker_browse_outcome"))
        finally:
            finished.set()

    reads = 0
    read_failure = None
    writer_failure = None
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(ingest)
        try:
            assert started.wait(10)
            while not finished.is_set() or reads < 12:
                with saved_db() as reader:
                    reader.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                    try:
                        actual = page(
                            reader, filters(tier="Signal", search="", decision="ALL"), ranked=True
                        )
                    except HTTPException as exc:
                        from gridlens.intelligence.saved_browse import POLICY_VERSION
                        from gridlens.persistence.models import BrowseGeneration

                        state = reader.get(BrowseState, 1)
                        generations = list(
                            reader.execute(
                                select(
                                    BrowseGeneration.id,
                                    BrowseGeneration.input_revision,
                                    BrowseGeneration.policy_version,
                                    BrowseGeneration.valid_from,
                                    BrowseGeneration.valid_until,
                                ).where(
                                    BrowseGeneration.id.in_(
                                        [state.generation_id, state.prepared_generation_id]
                                    )
                                )
                            )
                        )
                        pytest.fail(
                            "Saved-browse read was pending during ingestion: "
                            f"fixed_clock={fixed_now.isoformat()}, "
                            f"expected_policy={POLICY_VERSION!r}, "
                            f"status={exc.status_code}, input_revision={state.input_revision}, "
                            f"full_revision={state.full_revision}, "
                            f"generation_id={state.generation_id}, "
                            f"prepared_generation_id={state.prepared_generation_id}, "
                            f"candidates={generations!r}, writer_outcomes={writer_outcomes!r}"
                        )
                    canonical = api.opportunity_projection(reader, tier="Signal")
                    assert {item["id"] for item in actual["items"]} == {
                        str(item["id"]) for item in canonical
                    }
                    assert actual["qualification_state"] == "current"
                reads += 1
        except BaseException as exc:
            read_failure = exc
        finally:
            try:
                future.result(timeout=30)
            except BaseException as exc:
                writer_failure = exc
    if writer_failure is not None:
        pytest.fail(
            "Worker ingestion failed before all publication outcomes were collected: "
            f"{writer_failure!r}"
        )
    if read_failure is not None:
        raise read_failure
    assert len(writer_outcomes) == 12
    assert all(outcome and outcome["status"] == "published" for outcome in writer_outcomes), (
        writer_outcomes
    )
    with saved_db() as reader:
        assert len(page(reader, filters())["items"]) == 4


def test_worker_publication_pending_commit_recovers_after_engine_restart(saved_db, monkeypatch):
    from time import monotonic

    from gridlens.intelligence.saved_browse import maintain_once
    from gridlens.intelligence.worker_browse import install_worker_publication
    from gridlens.persistence.models import BrowseGeneration

    ids = seed(saved_db, count=1, histories=1)
    initial = rebuild(saved_db)
    assert initial["status"] == "published", initial
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    worker_factory = sessionmaker(saved_db.kw["bind"], expire_on_commit=False)
    install_worker_publication(worker_factory)

    with saved_db() as reader:
        before_state = reader.get(BrowseState, 1)
        before_revision = before_state.input_revision
        need = reader.get(PowerNeed, ids[0])
        project_id = need.project_id
        before_name = reader.get(Project, project_id).name

    with worker_factory.begin() as writer:
        # Deterministically exhaust the worker's bounded refresh budget. The
        # canonical project mutation and its invalidation still commit.
        writer.info["browse_publication_deadline"] = monotonic() - 1
        writer.get(Project, project_id).name = f"{before_name} retained"
    outcome = writer.info.get("worker_browse_outcome")
    assert outcome == {"status": "pending", "reason": "TimeoutError", "sqlstate": None}

    with saved_db() as reader:
        state = reader.get(BrowseState, 1)
        assert state.input_revision > before_revision
        assert reader.get(Project, project_id).name == f"{before_name} retained"
        with pytest.raises(HTTPException) as pending:
            page(reader, filters())
        assert pending.value.status_code == 503
        assert pending.value.headers["X-Qualification-State"] == "pending"

    with saved_db.kw["bind"].connect() as connection:
        schema = connection.scalar(text("SELECT current_schema()"))
    saved_db.kw["bind"].dispose()
    restarted_engine = create_engine(
        settings.test_database_url,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    restarted = sessionmaker(restarted_engine, expire_on_commit=False)
    try:
        assert maintain_once(restarted)["status"] == "published"
        with restarted() as reader:
            actual = page(reader, filters())
            canonical = api.opportunity_projection(reader)
            assert {item["id"] for item in actual["items"]} == {
                str(item["id"]) for item in canonical
            }
            assert actual["qualification_state"] == "current"
            current_state = reader.get(BrowseState, 1)
            generation = reader.get(BrowseGeneration, current_state.generation_id)
            assert generation.input_revision == current_state.input_revision
            assert reader.get(Project, project_id).name == f"{before_name} retained"
    finally:
        restarted_engine.dispose()


def test_worker_publishes_bulk_segment_but_operator_request_stays_small(saved_db, monkeypatch):
    from gridlens.intelligence.saved_browse import refresh_project_changes
    from gridlens.intelligence.worker_browse import install_worker_publication

    seed(saved_db, count=200, histories=1)
    rebuild(saved_db)
    with saved_db() as operator:
        operator.execute(text("UPDATE observations SET content_hash = repeat('f', 64)"))
        assert refresh_project_changes(operator) is None
        operator.rollback()
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    worker_factory = sessionmaker(saved_db.kw["bind"], expire_on_commit=False)
    install_worker_publication(worker_factory)
    with worker_factory.begin() as writer:
        writer.execute(text("SET LOCAL lock_timeout = '500ms'"))
        writer.execute(text("SET LOCAL statement_timeout = '2500ms'"))
        writer.execute(text("UPDATE projects SET name = name || ' refreshed'"))
    with saved_db() as reader:
        assert page(reader, filters())["total_count"] == 200
    with worker_factory.begin() as writer:
        writer.execute(text("UPDATE observations SET content_hash = repeat('f', 64)"))
    with saved_db() as reader:
        assert page(reader, filters())["total_count"] == 0


def test_worker_budget_exhaustion_retains_changes_and_offline_recovers(saved_db, monkeypatch):
    from time import monotonic

    from gridlens.intelligence.saved_browse import maintain_once
    from gridlens.intelligence.worker_browse import install_worker_publication

    seed(saved_db, count=150, histories=1)
    rebuild(saved_db)
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    worker_factory = sessionmaker(saved_db.kw["bind"], expire_on_commit=False)
    install_worker_publication(worker_factory)
    with worker_factory.begin() as writer:
        writer.info["browse_publication_deadline"] = monotonic() - 1
        writer.execute(text("UPDATE projects SET name = name || ' retained'"))
    with saved_db() as reader:
        assert all(p.name.endswith(" retained") for p in reader.scalars(select(Project)))
        with pytest.raises(HTTPException) as pending:
            page(reader, filters())
        assert pending.value.status_code == 503
    assert maintain_once(saved_db)["status"] == "published"
    with saved_db() as reader:
        assert page(reader, filters())["total_count"] == 150


def test_structured_ingestion_bulk_commit_keeps_authenticated_maps_current(saved_db, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic

    import httpx
    from fastapi.testclient import TestClient

    from gridlens.ingestion import registry, service
    from gridlens.intelligence.worker_browse import install_worker_publication
    from gridlens.persistence.models import Job, SourceCollectionProgress
    from gridlens.security import token_for

    seed(saved_db, count=200, histories=1)
    definition = deepcopy(
        next(s for s in registry.load_registry() if s["id"] == "chicago-building-permits")
    )
    definition["id"] = "synthetic-permits"
    monkeypatch.setattr(registry, "load_registry", lambda: [definition])
    with saved_db.begin() as session:
        source = session.get(Source, definition["id"])
        source.endpoint = definition["endpoint"]
        source.enabled = source.registry_enabled = True
        job = Job(
            source_id=source.id,
            status="running",
            lease_owner="synthetic",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id, lease_expiry = job.id, job.lease_until
        records = [
            {
                "document_number": obs.external_id,
                "title": obs.title,
                "abstract": "Synthetic corrected residential permit; no commercial scope.",
                "publication_date": "2026-10-15",
                "html_url": obs.url,
                "extraction_location": "synthetic row",
                "permit": {},
            }
            for obs in session.scalars(select(Observation).order_by(Observation.external_id))
        ]
    started = Event()

    def retrieve(*args, **kwargs):
        started.set()
        return {
            "records": records,
            "cursor": {"synthetic_page": 1},
            "partial": False,
            "window_complete": False,
            "expected_count": 200,
            "observed_count": 200,
        }

    monkeypatch.setattr(service, "retrieve_collection_segment", retrieve)
    assert rebuild(saved_db)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    monkeypatch.setattr(settings, "jev_enabled", False)
    factory = sessionmaker(saved_db.kw["bind"], expire_on_commit=False)
    install_worker_publication(factory)

    def ingest():
        deadline = monotonic() + 180
        with (
            factory() as session,
            httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: pytest.fail("Unexpected external request")
                )
            ) as client,
        ):
            session.info["browse_publication_deadline"] = deadline
            return service.process_job(
                session,
                job_id,
                "synthetic",
                1,
                definition,
                client,
                deadline=deadline,
                lease_expiry=lease_expiry,
            )

    with (
        TestClient(api.app, base_url="https://testserver") as client,
        ThreadPoolExecutor(1) as pool,
    ):
        client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
        future = pool.submit(ingest)
        if not started.wait(10):
            future.result(timeout=5)
            pytest.fail("Structured acquisition never reached its synthetic retrieval")
        reads = 0
        while not future.done() or reads < 5:
            response = client.get("/api/opportunities/map-window?tier=Signal&search=&decision=ALL")
            assert response.status_code == 200, response.text
            reads += 1
        counts = future.result(timeout=60)
    assert counts["retrieved_records"] == counts["changed"] == 200
    assert counts["collection_status"] == "PARTIAL"
    assert counts["collection_error_class"] is None
    with saved_db() as reader:
        assert reader.get(Job, job_id).checkpoint == records[-1]["document_number"]
        progress = reader.scalar(
            select(SourceCollectionProgress).where(
                SourceCollectionProgress.cursor == {"synthetic_page": 1}
            )
        )
        assert progress.status == "incomplete"
        assert progress.completed_through is None
        canonical = api.opportunity_projection(reader)
        saved = page(reader, filters(), limit=200, ranked=True)
        assert {row["id"]: row["rank_score"] for row in saved["items"]} == {
            str(row["id"]): row["rank_score"] for row in canonical
        }
        evidence_count = reader.scalar(select(func.count()).select_from(Evidence))
    replay = ingest()
    assert replay["changed"] == replay["new"] == 0
    with saved_db() as reader:
        assert reader.scalar(select(func.count()).select_from(Evidence)) == evidence_count
        assert (
            current_generation(reader).input_revision == reader.get(BrowseState, 1).input_revision
        )


def test_worker_heartbeat_does_not_repair_another_transaction_backlog(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse
    from gridlens.intelligence.worker_browse import install_worker_publication

    seed(saved_db, histories=1)
    rebuild(saved_db)
    with saved_db.begin() as writer:
        writer.execute(text("UPDATE projects SET name = name || ' changed'"))
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    factory = sessionmaker(saved_db.kw["bind"], expire_on_commit=False)
    install_worker_publication(factory)
    monkeypatch.setattr(
        saved_browse,
        "refresh_project_changes",
        lambda *a, **k: pytest.fail("Unrelated heartbeat attempted canonical reconstruction"),
    )
    with factory.begin() as heartbeat:
        heartbeat.execute(text('UPDATE sources SET health = \'{"status":"Updated"}\'::jsonb'))
    with factory.begin() as heartbeat:
        with heartbeat.begin_nested() as rolled_back:
            heartbeat.execute(text("UPDATE projects SET name = name || ' rolled-back'"))
            rolled_back.rollback()
        heartbeat.execute(text("SELECT 1"))
    with saved_db() as reader:
        with pytest.raises(HTTPException):
            page(reader, filters())


def test_shared_observation_presence_and_identity_changes_refresh_every_owner(saved_db):
    from gridlens.intelligence.saved_browse import refresh_project_changes
    from gridlens.persistence.models import BrowseDirtyProject, ChangeEvent

    ids = seed(saved_db, histories=1)
    with saved_db.begin() as session:
        observations = list(session.scalars(select(Observation).order_by(Observation.external_id)))
        owner_ids = [session.get(PowerNeed, need_id).project_id for need_id in ids]
        session.add(NeedObservation(need_id=ids[1], observation_id=observations[0].id))
        direct = session.get(Project, owner_ids[2])
        direct.external_id = observations[0].external_id
    rebuild(saved_db)
    with saved_db.begin() as writer:
        observation = writer.get(Observation, observations[0].id)
        writer.add(
            ChangeEvent(
                observation_id=observation.id,
                project_id=owner_ids[0],
                content_hash=observation.content_hash,
                kind="absent_from_source",
            )
        )
        writer.flush()
        assert set(writer.scalars(select(BrowseDirtyProject.project_id))) >= {
            writer.get(PowerNeed, ids[0]).project_id,
            writer.get(PowerNeed, ids[1]).project_id,
            owner_ids[2],
        }
        assert refresh_project_changes(writer)["status"] == "published"
    # Moving the direct identity must also refresh the OLD direct owner.
    rebuild(saved_db)
    with saved_db.begin() as writer:
        writer.get(Observation, observations[0].id).external_id = "different-source-record"
        writer.flush()
        assert owner_ids[2] in set(writer.scalars(select(BrowseDirtyProject.project_id)))
        assert refresh_project_changes(writer)["status"] == "published"
    with saved_db() as reader:
        actual = page(reader, filters())["items"]
        canonical = api.opportunity_projection(reader)
        assert {item["id"] for item in actual} == {str(item["id"]) for item in canonical}


def test_retained_only_buying_chain_correction_refreshes_canonical_rank(saved_db):
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.buying_chain import enrich_buying_chain
    from gridlens.intelligence.saved_browse import refresh_project_changes
    from gridlens.persistence.models import BuyingChainEvidence

    ids = seed(saved_db, count=1, histories=1)
    now = datetime.now(UTC)
    with saved_db.begin() as session:
        project = session.get(Project, session.get(PowerNeed, ids[0]).project_id)
        project.name, project.location = "Orion Data Center", "Austin, TX"
        session.flush()
        quote = "Acme is the general contractor for Orion Data Center in Austin, TX."
        enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda url: PublicDocument(
                url,
                "Orion Data Center, Austin, TX",
                quote,
                now.date(),
                now,
            ),
            now=now,
        )
        retained = Evidence(
            id=uuid4(),
            observation_id=uuid4(),
            content_hash="a" * 64,
            title="Orion Data Center, Austin, TX",
            abstract=quote,
            url="https://example.test/independent-contractor",
            observed_at=now,
            published_at=now.date(),
            extraction_location="Synthetic contractor notice",
        )
        session.add(
            Observation(
                id=retained.observation_id,
                source_id="synthetic-permits",
                external_id="independent-contractor",
                title=retained.title,
                abstract=quote,
                url=retained.url,
                content_hash=retained.content_hash,
            )
        )
        session.flush()
        session.add(retained)
        session.add(
            Interpretation(
                observation_id=retained.observation_id,
                content_hash=retained.content_hash,
                evaluator_version="fixture",
                status="accepted",
                assessment={
                    "semantic_hash": retained.content_hash,
                    "evidence_hash": retained.content_hash,
                    "project_identity_key": project.identity_key,
                    "power_activity": "construction",
                    "decision": "accepted",
                    "subject": project.name,
                    "location": project.location,
                },
            )
        )
        session.flush()
        for citation in session.scalars(select(BuyingChainEvidence)):
            citation.retained_evidence_id = retained.id
        observation_id = retained.observation_id
    rebuild(saved_db)
    with saved_db() as reader:
        prior_rank = page(reader, filters())["items"][0]["rank_score"]
    with saved_db.begin() as writer:
        writer.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation_id)
        ).status = "withdrawn"
        assert refresh_project_changes(writer)["status"] == "published"
    with saved_db() as reader:
        saved = page(reader, filters())["items"][0]
        canonical = api.opportunity_projection(reader)[0]
        assert canonical["rank_score"] < prior_rank
        for key in (
            "tier",
            "rank_score",
            "rank_reasons",
            "title_company",
            "signal_display_decision",
        ):
            assert saved[key] == canonical[key]


def test_lifecycle_only_evidence_and_reassignment_invalidate_old_and_new_owners(saved_db):
    from gridlens.intelligence.saved_browse import refresh_project_changes
    from gridlens.persistence.models import BrowseDirtyProject, LifecycleEvent

    ids = seed(saved_db, count=3, histories=1)
    with saved_db.begin() as session:
        owners = [session.get(PowerNeed, need_id).project_id for need_id in ids]
        evidence = session.scalar(
            select(Evidence)
            .join(NeedObservation, NeedObservation.observation_id == Evidence.observation_id)
            .where(NeedObservation.need_id == ids[0])
        )
        event_row = LifecycleEvent(
            project_id=owners[1],
            observation_id=evidence.observation_id,
            evidence_id=evidence.id,
            event_type="synthetic_event",
            state="synthetic_state",
        )
        session.add(event_row)
        session.flush()
        event_id, evidence_id = event_row.id, evidence.id
    rebuild(saved_db)
    with saved_db.begin() as writer:
        writer.get(Evidence, evidence_id).abstract = "Corrected source excerpt"
        writer.flush()
        assert set(writer.scalars(select(BrowseDirtyProject.project_id))) == set(owners[:2])
        assert refresh_project_changes(writer)["status"] == "published"
    rebuild(saved_db)
    with saved_db.begin() as writer:
        writer.get(LifecycleEvent, event_id).project_id = owners[2]
        writer.flush()
        assert set(writer.scalars(select(BrowseDirtyProject.project_id))) == set(owners[1:])
        assert refresh_project_changes(writer)["status"] == "published"


def test_full_build_rebase_keeps_concurrent_already_published_operator_edit(saved_db):
    from gridlens.intelligence.saved_browse import refresh_project_changes

    ids = seed(saved_db)
    rebuild(saved_db)

    def atomic_operator_write():
        with saved_db.begin() as writer:
            writer.get(PowerNeed, ids[0]).active = False
            assert refresh_project_changes(writer)["status"] == "published"

    assert rebuild(saved_db, before_publish=atomic_operator_write)["status"] == "published"
    with saved_db() as reader:
        assert str(ids[0]) not in {str(item["id"]) for item in page(reader, filters())["items"]}
        current_generation(reader)


def test_long_repeatable_read_cohort_survives_pruning_without_blocking_writers(saved_db):
    from gridlens.intelligence.saved_browse import refresh_project_changes
    from gridlens.persistence.models import BrowseGeneration

    ids = seed(saved_db)
    rebuild(saved_db)
    with saved_db() as reader:
        api._begin_consistent_read(reader)
        original = current_generation(reader).id
        for need_id in ids:
            with saved_db.begin() as writer:
                writer.get(PowerNeed, need_id).active = False
                assert refresh_project_changes(writer)["status"] == "published"
        assert current_generation(reader).id == original
        assert len(page(reader, filters())["items"]) == len(ids)
        with saved_db() as fresh:
            assert not page(fresh, filters())["items"]
            assert fresh.get(BrowseGeneration, original) is None


def test_expiry_without_preparation_has_explicit_pending_window(saved_db):
    seed(saved_db, count=1)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db() as session:
        deadline = current_generation(session).valid_until
        with pytest.raises(HTTPException) as failure:
            current_generation(session, now=deadline)
        assert failure.value.status_code == 503
        assert failure.value.headers["X-Qualification-State"] == "pending"


def test_prepared_clock_snapshot_is_not_early_and_matches_future_canonical(saved_db, monkeypatch):
    from gridlens.domain.evaluation_clock import evaluate_at
    from gridlens.intelligence.saved_browse import prepare_next, restore_generation
    from gridlens.persistence.models import BrowseGeneration

    seed(saved_db)
    rebuild(saved_db)
    with saved_db() as session:
        old = current_generation(session)
        boundary = old.valid_until
        old_id = old.id
    assert prepare_next(saved_db, lead_seconds=90000)["status"] == "prepared"
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        prepared_id = state.prepared_generation_id
        prepared = session.get(BrowseGeneration, prepared_id)
        assert prepared.valid_from == boundary
        assert prepared.built_at < boundary
        assert current_generation(session, now=boundary - timedelta(microseconds=1)).id == old_id
        assert current_generation(session, now=boundary).id == prepared_id
        with pytest.raises(HTTPException):
            current_generation(session, now=prepared.valid_until)
    assert not restore_generation(saved_db, prepared_id)
    monkeypatch.setattr(settings, "saved_browse_enabled", False)
    with evaluate_at(boundary):
        expected = api.opportunities(limit=50, offset=0, cohort=None, sort="rank")
    # Simulate only the reader's real clock at B; canonical future evaluation has
    # already completed and is no longer active in this thread.
    from gridlens.intelligence import saved_browse

    class AtBoundary(datetime):
        @classmethod
        def now(cls, tz=None):
            return boundary

    monkeypatch.setattr(saved_browse, "datetime", AtBoundary)
    with saved_db() as session:
        actual = page(session, filters(), ranked=True)["items"]
    for left, right in zip(actual, expected, strict=True):
        for field in ("id", "tier", "required_mw", "rank_score", "rank_reasons", "group_id"):
            assert str(left[field]) == str(right[field]), field


def test_dirty_revision_maintenance_prepares_near_boundary_and_preserves_parity(
    saved_db, monkeypatch
):
    from gridlens.domain.evaluation_clock import evaluate_at
    from gridlens.intelligence import saved_browse
    from gridlens.persistence.models import BrowseGeneration

    ids = seed(saved_db)
    expected_ids = {str(need_id) for need_id in ids[1:]}
    rebuild(saved_db)
    with saved_db() as session:
        old = current_generation(session)
        boundary = old.valid_until
        old_id = old.id
    with saved_db.begin() as writer:
        writer.get(PowerNeed, ids[0]).active = False
    with saved_db() as session:
        with pytest.raises(HTTPException) as pending:
            current_generation(session)
        assert pending.value.status_code == 503
        assert pending.value.headers["X-Qualification-State"] == "pending"

    now = boundary - timedelta(seconds=30)

    class NearBoundary(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(saved_browse, "datetime", NearBoundary)
    assert saved_browse.maintain_once(saved_db)["status"] == "prepared"
    with saved_db() as fresh_session:
        refreshed = current_generation(fresh_session, now=now)
        refreshed_id = refreshed.id
        assert refreshed_id != old_id
        assert refreshed.valid_from == now
        assert refreshed.valid_until == boundary
        state = fresh_session.get(BrowseState, 1)
        prepared_id = state.prepared_generation_id
        prepared = fresh_session.get(BrowseGeneration, prepared_id)
        assert prepared_id != refreshed_id
        assert prepared.valid_from == boundary
        assert prepared.built_at < boundary
    assert saved_browse.maintain_once(saved_db)["status"] == "ready"

    monkeypatch.setattr(settings, "saved_browse_enabled", False)
    with evaluate_at(now):
        expected_now = api.opportunities(limit=50, offset=0, cohort=None, sort="rank")
    with evaluate_at(boundary):
        expected_boundary = api.opportunities(limit=50, offset=0, cohort=None, sort="rank")
    monkeypatch.setattr(settings, "saved_browse_enabled", True)

    def assert_parity(at, expected):
        class ReaderClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return at

        monkeypatch.setattr(saved_browse, "datetime", ReaderClock)
        with saved_db() as session:
            if at == boundary:
                assert current_generation(session, now=at).id == prepared_id
            actual = page(session, filters(), limit=50, ranked=True)["items"]
        assert {str(item["id"]) for item in expected} == expected_ids
        assert {str(item["id"]) for item in actual} == expected_ids
        for left, right in zip(actual, expected, strict=True):
            for field in ("id", "tier", "required_mw", "rank_score", "rank_reasons", "group_id"):
                assert str(left[field]) == str(right[field]), field

    assert_parity(now, expected_now)
    assert_parity(boundary, expected_boundary)


def test_preparation_write_race_discard_and_rollback_safety(saved_db):
    from gridlens.intelligence.saved_browse import prepare_next

    ids = seed(saved_db)
    rebuild(saved_db)

    def mutate():
        with saved_db.begin() as writer:
            writer.get(PowerNeed, ids[0]).active = False

    assert (
        prepare_next(saved_db, lead_seconds=90000, before_publish=mutate)["status"] == "superseded"
    )
    with saved_db() as session:
        assert session.get(BrowseState, 1).prepared_generation_id is None
        with pytest.raises(HTTPException):
            current_generation(session)
    rebuild(saved_db)
    assert prepare_next(saved_db, lead_seconds=90000)["status"] == "prepared"
    with saved_db() as writer:
        writer.execute(text("UPDATE sources SET publisher='Changed source policy'"))
        writer.rollback()
    with saved_db() as session:
        assert session.get(BrowseState, 1).prepared_generation_id is not None
    with saved_db.begin() as writer:
        writer.execute(text("UPDATE sources SET publisher='Changed source policy'"))
    with saved_db() as session:
        assert session.get(BrowseState, 1).prepared_generation_id is None
        with pytest.raises(HTTPException):
            current_generation(session)


def test_boundary_write_promotes_ready_base_before_invalidation(saved_db):
    from gridlens.intelligence.saved_browse import prepare_next, refresh_project_changes
    from gridlens.persistence.models import BrowseGeneration

    ids = seed(saved_db)
    rebuild(saved_db)
    prepare_next(saved_db, lead_seconds=90000)
    # Simulate wall time reaching the candidate interval in persisted metadata;
    # the PostgreSQL trigger uses real database time, not a Python test clock.
    with saved_db.begin() as session:
        state = session.get(BrowseState, 1)
        old = session.get(BrowseGeneration, state.generation_id)
        ready = session.get(BrowseGeneration, state.prepared_generation_id)
        old.valid_until = datetime.now(UTC) - timedelta(seconds=1)
        ready.valid_from = datetime.now(UTC) - timedelta(seconds=1)
    with saved_db.begin() as writer:
        writer.get(PowerNeed, ids[0]).active = False
        result = refresh_project_changes(writer)
        assert result["mode"] == "projects"
    with saved_db() as reader:
        assert str(ids[0]) not in {str(row["id"]) for row in page(reader, filters())["items"]}
        assert reader.get(BrowseState, 1).prepared_generation_id is None


def test_preparation_failure_and_policy_mismatch_fail_closed(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse

    seed(saved_db)
    rebuild(saved_db)
    with saved_db() as session:
        old = current_generation(session).id
        boundary = current_generation(session).valid_until
    original = saved_browse._write_rows

    def fail(*args):
        raise RuntimeError("synthetic preparation failure")

    monkeypatch.setattr(saved_browse, "_write_rows", fail)
    with pytest.raises(RuntimeError):
        saved_browse.prepare_next(saved_db, lead_seconds=90000)
    with saved_db() as session:
        assert current_generation(session).id == old
        assert session.get(BrowseState, 1).prepared_generation_id is None
        with pytest.raises(HTTPException):
            current_generation(session, now=boundary)
    monkeypatch.setattr(saved_browse, "_write_rows", original)
    saved_browse.prepare_next(saved_db, lead_seconds=90000)
    monkeypatch.setattr(saved_browse, "POLICY_VERSION", "different-runtime")
    with saved_db() as session, pytest.raises(HTTPException):
        current_generation(session, now=boundary)


def test_prepared_pointer_survives_pruning_and_new_pool_restart(saved_db):
    from gridlens.intelligence.saved_browse import prepare_next
    from gridlens.persistence.models import BrowseGeneration

    seed(saved_db)
    rebuild(saved_db)
    prepare_next(saved_db, lead_seconds=90000)
    with saved_db() as session:
        prepared_id = session.get(BrowseState, 1).prepared_generation_id
        boundary = session.get(BrowseGeneration, prepared_id).valid_from
    for _ in range(4):
        assert rebuild(saved_db)["status"] == "published"
    saved_db.kw["bind"].dispose()
    with saved_db() as restarted:
        assert current_generation(restarted, now=boundary).id == prepared_id
        assert restarted.get(BrowseGeneration, prepared_id) is not None


def test_future_fact_start_and_end_use_same_prepared_instant(saved_db, monkeypatch):
    from gridlens.domain.evaluation_clock import evaluate_at
    from gridlens.ingestion.service import load_current_need_operator_inputs
    from gridlens.intelligence import saved_browse
    from gridlens.intelligence.saved_browse import prepare_next
    from gridlens.persistence.models import CallFactDecision, CallFactVersion

    fixed = datetime(2026, 10, 18, 12, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(saved_browse, "datetime", Clock)
    ids = seed(saved_db, count=1)
    start = fixed + timedelta(minutes=10)
    end = start + timedelta(minutes=10)
    with saved_db.begin() as session:
        need = session.get(PowerNeed, ids[0])
        fact = CallFactVersion(
            need_id=need.id,
            project_id=need.project_id,
            client_id=uuid4(),
            activity_key=need.activity_key,
            facility_scope="Dallas, TX",
            fact_type="demand",
            value={"mw": "20"},
            reporter_name="Synthetic",
            confirmation_channel="call",
            confirmed_at=datetime.now(UTC),
            effective_from=start,
            effective_until=end,
            content_hash="e" * 64,
            recorded_by="Synthetic",
        )
        session.add(fact)
        session.flush()
        session.add(
            CallFactDecision(
                need_id=need.id,
                fact_version_id=fact.id,
                version=1,
                client_id=uuid4(),
                decision="accepted",
                expected_version=0,
                reason="Synthetic",
                content_hash="d" * 64,
                actor="Synthetic",
            )
        )
    rebuild(saved_db)
    prepare_next(saved_db, lead_seconds=90000)
    with saved_db() as session:
        with evaluate_at(fixed):
            before, _ = load_current_need_operator_inputs(session, ids)
            assert not before
        with evaluate_at(start):
            after, _ = load_current_need_operator_inputs(session, ids)
            assert len(after[ids[0]]) == 1
        with evaluate_at(end):
            expired, _ = load_current_need_operator_inputs(session, ids)
            assert not expired
        candidate = current_generation(session, now=start)
        assert candidate.valid_from == start
        assert candidate.valid_until == end


def test_prepared_boundary_adds_and_expires_real_qualified_lead(saved_db, monkeypatch):
    """Retained official clauses + accepted exact-need facts change qualification."""
    from gridlens.intelligence import saved_browse
    from gridlens.persistence.models import CallFactDecision, CallFactVersion

    ids = seed(saved_db, count=1, histories=1)
    boundary = datetime(2027, 1, 1, 0, tzinfo=UTC)
    instant = boundary - timedelta(minutes=10)
    expiry = datetime(2027, 3, 4, 0, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr(saved_browse, "datetime", Clock)
    with saved_db.begin() as session:
        need = session.get(PowerNeed, ids[0])
        project = session.get(Project, need.project_id)
        observation = session.scalar(select(Observation))
        evidence = session.scalar(select(Evidence))
        interpretation = session.scalar(select(Interpretation))
        observation.abstract = evidence.abstract = (
            "description: Dallas, TX construction requires 20 to 25 MW. "
            "Power supply for Dallas, TX construction is insufficient.\n"
            "address: Dallas, TX"
        )
        observation.published_at = evidence.published_at = instant.date()
        interpretation.assessment = {
            "decision": "accepted",
            "semantic_hash": observation.content_hash,
            "evidence_hash": evidence.content_hash,
            "project_identity_key": project.identity_key,
            "power_activity": "construction",
            "tier": "Prospect",
            "demand_mw": "20 to 25 MW",
            "demand_quote": "Dallas, TX construction requires 20 to 25 MW.",
            "supply_quote": "Power supply for Dallas, TX construction is insufficient.",
            "reason": "Current retained exact-site permit support.",
            "subject": project.name,
            "location": project.location,
        }
        values = [
            ("timing", {"start_date": "2027-01-01", "end_date": "2027-02-01", "duration_days": 31}),
            ("suitable_supply", {"mw": "5", "quality": "suitable"}),
            ("buyer", {"organization": "Synthetic Owner", "role": "project owner"}),
        ]
        for index, (kind, value) in enumerate(values):
            fact = CallFactVersion(
                need_id=need.id,
                project_id=project.id,
                client_id=uuid4(),
                activity_key=need.activity_key,
                facility_scope=project.location,
                fact_type=kind,
                value=value,
                reporter_name="Synthetic",
                confirmation_channel="customer_call",
                confirmed_at=instant,
                effective_from=boundary,
                effective_until=expiry,
                content_hash=str(index) * 64,
                recorded_by="Synthetic",
            )
            session.add(fact)
            session.flush()
            session.add(
                CallFactDecision(
                    need_id=need.id,
                    fact_version_id=fact.id,
                    version=index + 1,
                    client_id=uuid4(),
                    decision="accepted",
                    expected_version=index,
                    reason="Synthetic exact-need accepted fact",
                    content_hash=str(index + 3) * 64,
                    actor="Synthetic",
                )
            )
    rebuild(saved_db)
    with saved_db() as session:
        assert page(session, filters())["items"][0]["tier"] == "Prospect"
    assert saved_browse.prepare_next(saved_db, lead_seconds=90000)["status"] == "prepared"
    instant = boundary
    with saved_db() as session:
        lead = page(session, filters())["items"][0]
        assert lead["tier"] == "Lead"
        assert lead["required_mw"] == "20 to 25 MW"
    # Move through the later calendar intervals using normal rebuilds, then
    # prepare the exact accepted-fact expiry. Expired facts cannot carry a Lead.
    instant = expiry - timedelta(minutes=10)
    rebuild(saved_db)
    with saved_db() as session:
        assert page(session, filters())["items"][0]["tier"] == "Lead"
    assert saved_browse.prepare_next(saved_db, lead_seconds=90000)["status"] == "prepared"
    instant = expiry
    with saved_db() as session:
        assert page(session, filters())["items"][0]["tier"] == "Prospect"


def test_maintenance_promotes_persisted_preparation_without_rebuild(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse

    seed(saved_db)
    rebuild(saved_db)
    saved_browse.prepare_next(saved_db, lead_seconds=90000)
    with saved_db() as session:
        boundary = current_generation(session).valid_until
        prepared_id = session.get(BrowseState, 1).prepared_generation_id

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return boundary

    monkeypatch.setattr(saved_browse, "datetime", Clock)

    def unexpected_build(*args):
        raise AssertionError("promotion must not reconstruct canonical rows")

    monkeypatch.setattr(saved_browse, "_write_rows", unexpected_build)
    assert saved_browse.maintain_once(saved_db)["status"] == "current"
    with saved_db() as restarted:
        state = restarted.get(BrowseState, 1)
        assert state.generation_id == prepared_id
        assert state.prepared_generation_id is None
        assert current_generation(restarted).id == prepared_id


def test_default_rollover_lead_prepares_early_without_exposing_future_rows(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse
    from gridlens.persistence.models import BrowseGeneration

    seed(saved_db, count=1)
    assert rebuild(saved_db)["status"] == "published"
    now = datetime.now(UTC)
    with saved_db.begin() as session:
        original = current_generation(session)
        original_id = original.id
        original.valid_until = now + timedelta(minutes=10)
        boundary = original.valid_until

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(saved_browse, "datetime", Clock)
    result = saved_browse.prepare_next(saved_db)
    assert result["status"] == "prepared"
    prepared_id = UUID(result["generation_id"])
    with saved_db() as session:
        prepared = session.get(BrowseGeneration, prepared_id)
        assert prepared.valid_from == boundary
        assert current_generation(session, now=now).id == original_id
        assert current_generation(session, now=boundary).id == prepared_id


def test_preparing_subsequent_interval_preserves_now_effective_preparation(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse

    seed(saved_db)
    rebuild(saved_db)
    saved_browse.prepare_next(saved_db, lead_seconds=90000)
    with saved_db() as session:
        boundary = current_generation(session).valid_until
        prepared_id = session.get(BrowseState, 1).prepared_generation_id

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return boundary

    monkeypatch.setattr(saved_browse, "datetime", Clock)
    assert saved_browse.prepare_next(saved_db, lead_seconds=90000)["status"] == "prepared"
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.generation_id == prepared_id
        assert state.prepared_generation_id != prepared_id
        assert current_generation(session).id == prepared_id


def test_incremental_refresh_never_blesses_future_base_if_clocks_disagree(saved_db):
    from gridlens.intelligence.saved_browse import prepare_next, refresh_project_changes

    ids = seed(saved_db)
    rebuild(saved_db)
    prepare_next(saved_db, lead_seconds=90000)
    # Simulate DB-clock-ahead promotion while application time is still before B.
    with saved_db.begin() as session:
        state = session.get(BrowseState, 1)
        state.generation_id = state.prepared_generation_id
        state.prepared_generation_id = None
    with saved_db.begin() as writer:
        writer.get(PowerNeed, ids[0]).active = False
        assert refresh_project_changes(writer) is None
    with saved_db() as reader, pytest.raises(HTTPException):
        current_generation(reader)


def test_saved_commercial_page_avoids_population_projection(saved_db, monkeypatch):
    """Saved selection must keep the canonical cards without replaying all summaries."""
    factory = saved_db
    ids = seed(factory, count=6, histories=3)
    with factory.begin() as session:
        for index, need_id in enumerate(ids):
            project = session.get(Project, session.get(PowerNeed, need_id).project_id)
            project.location = f"{index} Synthetic Road, Dallas, TX"
    with factory() as session:
        expected = api._commercial_triage_payload(session, 2, 2)
    assert rebuild(factory)["status"] == "published"
    original = api.opportunity_projection

    def targeted_only(session, *, summary_only=False, **kwargs):
        assert not summary_only, "pursuits replayed population canonical summaries"
        assert kwargs.get("selected_need_ids") is not None
        return original(session, **kwargs)

    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    monkeypatch.setattr(api, "opportunity_projection", targeted_only)
    actual = api.commercial_triage(limit=2, offset=2)
    expected.pop("evaluated_at")
    actual.pop("evaluated_at")
    assert actual == expected


def test_commercial_selection_matches_canonical_complete_group_priority(saved_db):
    """Tuple minima, Austin cross-project work, UUID ties and all page offsets."""
    from gridlens.domain.commercial_triage import (
        _priority,
        grouped_need_groups,
        work_group_identity,
    )
    from gridlens.intelligence.saved_browse import commercial_selection
    from gridlens.persistence.models import BrowseRow

    factory = saved_db
    seed(factory, count=8, histories=1)
    assert rebuild(factory)["status"] == "published"
    with factory.begin() as session:
        generation = current_generation(session)
        rows = list(
            session.scalars(select(BrowseRow).where(BrowseRow.generation_id == generation.id))
        )
        items = []
        for index, row in enumerate(rows):
            item = {
                "id": row.need_id,
                "project_id": row.project_id,
                "name": "Synthetic data center" if index % 2 else "Synthetic oil well",
                "location": "100 Synthetic Road, Dallas, TX"
                if index < 3
                else f"{index} Austin, TX",
                "activity": "construction",
                "asset_type": "data_center" if index % 2 else None,
                "_priority_features": {
                    "latest_date": "2026-10-31"
                    if index == 2
                    else ("2026-10-10" if index >= 5 else f"2026-10-{index + 1:02}"),
                    "evidence_construction": True,
                },
                "evidence": [
                    {
                        "source_id": "austin-building-permits",
                        "document_number": "2026-123456 BP" if index % 2 else "2026-123456 EP",
                        "assessment_current": True,
                    }
                ],
            }
            if index == 2:
                item["evidence"].insert(0, {"source_id": "stale", "assessment_current": False})
            priority = _priority(item)
            row.commercial_group = work_group_identity(item)
            row.commercial_segment, row.commercial_geography, row.commercial_date = priority[:3]
            items.append(item)
        # A non-Signal must not enter commercial groups even if it ranks first.
        rows[4].tier = "Lead"
        items = [item for item in items if item["id"] != rows[4].need_id]
    expected = grouped_need_groups(items)
    assert any(len(members) == 3 for _identity, members in expected)
    for limit, offset in ((1, 0), (2, 1), (50, 0), (2, len(expected)), (2, 10_000), (2, 10**100)):
        with factory() as session:
            groups, projects, total = commercial_selection(session, limit, offset)
        assert groups == expected[offset : offset + limit]
        assert total == len(expected)
        assert set(projects) == {UUID(need) for _, group in groups for need in group}


def test_commercial_saved_selection_pending_and_write_callers_remain_canonical(
    saved_db, monkeypatch
):
    factory = saved_db
    ids = seed(factory, count=2, histories=1)
    assert rebuild(factory)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    with factory.begin() as session:
        session.get(Project, session.get(PowerNeed, ids[0]).project_id).name = "Corrected synthetic"
    with factory() as session, pytest.raises(HTTPException) as caught:
        api._commercial_triage_payload(session, 50, saved_selection=True)
    assert caught.value.status_code == 503
    with factory() as session:
        cards = api._commercial_triage_cards(session, 50)
    assert any(card["name"] == "Corrected synthetic" for card in cards)


def test_saved_commercial_group_budget_keeps_all_members(saved_db, monkeypatch):
    factory = saved_db
    ids = seed(factory, count=52, histories=1)
    from gridlens.domain.commercial_triage import grouped_need_groups

    with factory.begin() as session:
        session.execute(
            text("UPDATE projects SET location = '100 Synthetic Test Road, Dallas, TX'")
        )
        session.get(
            Project, session.get(PowerNeed, ids[-1]).project_id
        ).location = "Other synthetic site"
    with factory() as session:
        groups = grouped_need_groups(
            api.opportunity_projection(session, tier="Signal", summary_only=True)
        )
    large_offset = next(i for i, (_key, group) in enumerate(groups) if len(group) == 51)
    small_offset = 1 - large_offset
    with factory() as session, pytest.raises(HTTPException) as canonical:
        api._commercial_triage_page(session, 1, large_offset)
    assert canonical.value.status_code == 413
    assert canonical.value.detail["group_member_count"] == 51
    assert rebuild(factory)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    with factory() as session, pytest.raises(HTTPException) as saved:
        api._commercial_triage_page(session, 1, large_offset, saved_selection=True)
    assert saved.value.detail == canonical.value.detail
    with factory() as session:
        canonical_cards = api._commercial_triage_page(session, 1, small_offset)
        saved_cards = api._commercial_triage_page(session, 1, small_offset, saved_selection=True)
    assert saved_cards == canonical_cards


def test_commercial_scalar_selection_refreshes_transactionally(saved_db):
    from gridlens.domain.commercial_triage import grouped_need_groups
    from gridlens.intelligence.saved_browse import commercial_selection, refresh_project_changes

    factory = saved_db
    ids = seed(factory, count=4, histories=1)
    assert rebuild(factory)["status"] == "published"
    with factory.begin() as session:
        session.get(PowerNeed, ids[0]).active = False
        assert refresh_project_changes(session)["status"] == "published"
        expected = grouped_need_groups(
            api.opportunity_projection(session, tier="Signal", summary_only=True)
        )
        actual, _projects, total = commercial_selection(session, 50, 0)
        assert actual == expected
        assert total == len(expected)
    # Restart/read from a new session; no prepared data or Python cache is required.
    with factory() as session:
        actual, _projects, total = commercial_selection(session, 50, 0)
    assert actual == expected
    assert total == len(expected)


def test_commercial_prepared_generation_retains_exact_group_selection(saved_db, monkeypatch):
    from gridlens.domain.commercial_triage import grouped_need_groups
    from gridlens.domain.evaluation_clock import evaluate_at
    from gridlens.intelligence import saved_browse as browse

    factory = saved_db
    seed(factory, count=4, histories=2)
    assert rebuild(factory)["status"] == "published"
    with factory() as session:
        boundary = current_generation(session).valid_until
    assert rebuild(factory, _prepare_at=boundary)["status"] == "prepared"

    class AtBoundary(datetime):
        @classmethod
        def now(cls, tz=None):
            return boundary

    monkeypatch.setattr(browse, "datetime", AtBoundary)
    with factory() as session, evaluate_at(boundary):
        expected = grouped_need_groups(
            api.opportunity_projection(session, tier="Signal", summary_only=True)
        )
        groups, _projects, total = browse.commercial_selection(session, 50, 0)
    assert groups == expected
    assert total == len(expected)


def test_receipt_and_note_save_readback_does_not_invalidate(saved_db, monkeypatch):
    from gridlens.intelligence.commercial_evaluation import save_evaluations
    from gridlens.persistence.models import Pursuit, PursuitCallNote

    factory = saved_db
    seed(factory, count=2, histories=1)
    assert rebuild(factory)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    with factory.begin() as session:
        before = current_generation(session).id
        cards = api._commercial_triage_cards(session, 50)
        save_evaluations(session, cards)
        session.flush()
        assert current_generation(session).id == before
        receipt = session.scalar(select(Pursuit))
        session.add(
            PursuitCallNote(
                pursuit_id=receipt.id,
                client_id=uuid4(),
                note="Synthetic saved note",
                outcome="Contacted",
                next_action="Synthetic follow-up",
            )
        )
        session.flush()
        assert current_generation(session).id == before
        payload = api._commercial_triage_payload(session, 50, saved_selection=True)
        assert any(
            note["note"] == "Synthetic saved note"
            for card in payload["items"]
            for note in card["notes"]
        )
    with factory() as session:
        assert current_generation(session).id == before
        assert session.scalar(select(PursuitCallNote.note)) == "Synthetic saved note"


def test_commercial_card_reuses_canonical_detail_buying_chain(saved_db, monkeypatch):
    factory = saved_db
    seed(factory, count=2, histories=1)
    assert rebuild(factory)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    with factory() as session:
        expected = api._commercial_triage_payload(session, 50, saved_selection=True)
    calls = []
    original = api.buying_chain_views

    def counted(session, project_ids, **kwargs):
        calls.append(project_ids)
        return original(session, project_ids, **kwargs)

    monkeypatch.setattr(api, "buying_chain_views", counted)
    with factory() as session:
        actual = api._commercial_triage_payload(session, 50, saved_selection=True)
    expected.pop("evaluated_at")
    actual.pop("evaluated_at")
    assert actual == expected
    assert len(calls) == 1


def _saved_receipt_fixture(factory):
    from gridlens.intelligence.commercial_evaluation import save_evaluations
    from gridlens.persistence.models import Pursuit

    seed(factory, count=2, histories=1)
    assert rebuild(factory)["status"] == "published"
    with factory.begin() as session:
        cards = api._commercial_triage_cards(session, 50)
        save_evaluations(session, cards)
        session.flush()
        return session.scalar(select(Pursuit.id)), cards


@pytest.mark.parametrize("mutation", ["unknown_root", "scope", "identity", "research", "malformed"])
def test_unknown_receipt_changes_remain_scoped_or_full_pending(saved_db, mutation):
    from gridlens.persistence.models import Pursuit

    receipt_id, _cards = _saved_receipt_fixture(saved_db)
    with saved_db() as session:
        prior_revision = session.get(BrowseState, 1).input_revision
        prior_full = session.get(BrowseState, 1).full_revision
    with saved_db.begin() as session:
        row = session.get(Pursuit, receipt_id)
        if mutation == "unknown_root":
            row.snapshot = {**row.snapshot, "research_state": {"phase": "changed"}}
        elif mutation == "scope":
            row.project_id = session.scalar(select(Project.id).where(Project.id != row.project_id))
        elif mutation == "identity":
            row.identity_key = "unrecognized-workspace"
        elif mutation == "research":
            row.research_status = "completed"
        else:
            row.snapshot = {"commercial_triage": None}
    with saved_db() as session, pytest.raises(HTTPException):
        current_generation(session)
    with saved_db() as session:
        state = session.get(BrowseState, 1)
        assert state.input_revision == prior_revision + 1
        assert state.full_revision == (state.input_revision if mutation == "scope" else prior_full)


@pytest.mark.parametrize("prepared", [False, True])
def test_concurrent_receipt_note_saves_during_generation_publication(
    saved_db, prepared, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from copy import deepcopy

    from gridlens.intelligence.commercial_evaluation import save_evaluations
    from gridlens.persistence.models import Pursuit, PursuitCallNote

    receipt_id, cards = _saved_receipt_fixture(saved_db)
    with saved_db() as session:
        prior = current_generation(session)
        prior_revision, boundary = prior.input_revision, prior.valid_until

    def save(index):
        with saved_db.begin() as writer:
            save_evaluations(writer, deepcopy(cards))
            receipt = writer.get(Pursuit, receipt_id)
            receipt.snapshot = {
                **receipt.snapshot,
                "commercial_triage": {
                    **receipt.snapshot["commercial_triage"],
                    "saved_at": datetime.now(UTC).isoformat(),
                },
            }
            writer.add(
                PursuitCallNote(
                    pursuit_id=receipt_id,
                    client_id=uuid4(),
                    note=f"Concurrent synthetic {index}",
                    outcome="Contacted",
                    next_action="Synthetic follow-up",
                )
            )
            writer.flush()
            assert current_generation(writer).input_revision == prior_revision

    def race():
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(save, range(4)))

    result = rebuild(saved_db, _prepare_at=boundary if prepared else None, before_publish=race)
    assert result["status"] == ("prepared" if prepared else "published")
    with saved_db() as reader:
        assert current_generation(reader).input_revision == prior_revision
        assert len(list(reader.scalars(select(PursuitCallNote)))) == 4
        assert len(reader.get(Pursuit, receipt_id).snapshot["commercial_triage"]["versions"]) == 1
        state = reader.get(BrowseState, 1)
        if prepared:
            assert state.prepared_generation_id is not None
            ready_id = state.prepared_generation_id
    if prepared:
        save(4)
        with saved_db() as reader:
            assert reader.get(BrowseState, 1).prepared_generation_id == ready_id
        from gridlens.intelligence import saved_browse as browse

        class AtBoundary(datetime):
            @classmethod
            def now(cls, tz=None):
                return boundary

        monkeypatch.setattr(browse, "datetime", AtBoundary)
        with saved_db() as reader:
            assert current_generation(reader).id == ready_id


def test_receipt_rollback_and_failed_preparation_leave_current_state(saved_db):
    from gridlens.persistence.models import Pursuit, PursuitCallNote

    receipt_id, _cards = _saved_receipt_fixture(saved_db)
    with saved_db() as session:
        prior = current_generation(session)
        before_id, boundary = prior.id, prior.valid_until
    with pytest.raises(RuntimeError), saved_db.begin() as session:
        session.add(
            PursuitCallNote(
                pursuit_id=receipt_id,
                client_id=uuid4(),
                note="Rolled back",
                outcome="Contacted",
                next_action="Synthetic",
            )
        )
        session.flush()
        raise RuntimeError("Synthetic rollback")

    def save_then_fail():
        with saved_db.begin() as session:
            row = session.get(Pursuit, receipt_id)
            row.snapshot = {
                **row.snapshot,
                "commercial_triage": {
                    **row.snapshot["commercial_triage"],
                    "saved_at": datetime.now(UTC).isoformat(),
                },
            }
        raise RuntimeError("Synthetic publication failure")

    with pytest.raises(RuntimeError):
        rebuild(saved_db, _prepare_at=boundary, before_publish=save_then_fail)
    with saved_db() as session:
        assert current_generation(session).id == before_id
        assert list(session.scalars(select(PursuitCallNote))) == []
        assert session.get(BrowseState, 1).prepared_generation_id is None
        assert session.get(Pursuit, receipt_id).snapshot["commercial_triage"]["saved_at"]


def test_receipt_exemption_never_hides_canonical_change_or_expiry(saved_db, monkeypatch):
    from gridlens.intelligence import saved_browse as browse
    from gridlens.persistence.models import Pursuit

    receipt_id, _cards = _saved_receipt_fixture(saved_db)
    with saved_db() as session:
        boundary = current_generation(session).valid_until

    def canonical_change():
        with saved_db.begin() as session:
            row = session.get(Pursuit, receipt_id)
            row.snapshot = {**row.snapshot, "commercial_triage": {"saved_at": "Synthetic"}}
            session.execute(text("UPDATE sources SET publisher = 'Canonical correction'"))

    assert (
        rebuild(saved_db, _prepare_at=boundary, before_publish=canonical_change)["status"]
        == "superseded"
    )
    with saved_db() as session, pytest.raises(HTTPException):
        current_generation(session)
    assert rebuild(saved_db)["status"] == "published"

    class Expired(datetime):
        @classmethod
        def now(cls, tz=None):
            return boundary

    monkeypatch.setattr(browse, "datetime", Expired)
    with saved_db.begin() as session:
        row = session.get(Pursuit, receipt_id)
        row.project_ids = []
    with saved_db() as session, pytest.raises(HTTPException):
        current_generation(session)


def test_note_bulk_update_delete_and_truncate_contract(saved_db, monkeypatch):
    from gridlens.persistence.models import PursuitCallNote

    receipt_id, _cards = _saved_receipt_fixture(saved_db)
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    with saved_db.begin() as session:
        session.add(
            PursuitCallNote(
                pursuit_id=receipt_id,
                client_id=uuid4(),
                note="Synthetic",
                outcome="Contacted",
                next_action="Synthetic",
            )
        )
    with saved_db.begin() as session:
        session.execute(text("UPDATE pursuit_call_notes SET note = 'Corrected synthetic'"))
    with saved_db() as session:
        payload = api._commercial_triage_payload(session, 50, saved_selection=True)
        assert any(
            note["note"] == "Corrected synthetic"
            for card in payload["items"]
            for note in card["notes"]
        )
    with saved_db.begin() as session:
        session.execute(text("DELETE FROM pursuit_call_notes"))
    with saved_db() as session:
        assert current_generation(session)
        payload = api._commercial_triage_payload(session, 50, saved_selection=True)
        assert not any(card["notes"] for card in payload["items"])
    with saved_db.begin() as session:
        session.execute(text("TRUNCATE pursuit_call_notes"))
    with saved_db() as session, pytest.raises(HTTPException):
        current_generation(session)


@pytest.mark.parametrize("kind", ["unknown_root", "research_fields", "unknown_identity"])
def test_unrecognized_pursuit_insert_stays_pending_until_scoped_publication(saved_db, kind):
    from gridlens.persistence.models import Pursuit

    ids = seed(saved_db, count=1, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db.begin() as session:
        need = session.get(PowerNeed, ids[0])
        row = Pursuit(
            identity_key="commercial-need:" + str(need.id), project_id=need.project_id, snapshot={}
        )
        if kind == "unknown_root":
            row.snapshot = {"research_state": {}}
        elif kind == "research_fields":
            row.research_status = "completed"
        else:
            row.identity_key = "unrecognized-insert"
        session.add(row)
    with saved_db() as session, pytest.raises(HTTPException):
        current_generation(session)


def test_mixed_receipt_bulk_update_fails_closed_once(saved_db):
    from gridlens.persistence.models import BrowseDirtyProject, Pursuit

    receipt_id, _cards = _saved_receipt_fixture(saved_db)
    with saved_db() as session:
        assert len(list(session.scalars(select(Pursuit)))) == 2
        revision = current_generation(session).input_revision
        full_revision = session.get(BrowseState, 1).full_revision
        owner = session.get(Pursuit, receipt_id).project_id
    with saved_db.begin() as session:
        session.execute(
            text(
                "UPDATE pursuits SET snapshot = CASE WHEN id = :id "
                "THEN snapshot || jsonb_build_object('unknown_root', true) "
                "ELSE jsonb_set(snapshot, '{commercial_triage,saved_at}', "
                "'\"Synthetic receipt update\"'::jsonb) END"
            ),
            {"id": receipt_id},
        )
    with saved_db() as session, pytest.raises(HTTPException):
        current_generation(session)
    with saved_db() as session:
        assert session.get(BrowseState, 1).input_revision == revision + 1
        assert session.get(BrowseState, 1).full_revision == full_revision
        assert set(
            session.scalars(
                select(BrowseDirtyProject.project_id).where(BrowseDirtyProject.revision > revision)
            )
        ) == {owner}


@pytest.mark.parametrize("document", [False, True])
def test_legacy_research_scopes_old_and_new_primary_and_member_owners(saved_db, document):
    from gridlens.persistence.models import BrowseDirtyProject, Pursuit, PursuitDocument

    ids = seed(saved_db, count=4, histories=1)
    with saved_db.begin() as session:
        owners = [session.get(PowerNeed, need_id).project_id for need_id in ids]
        old = Pursuit(
            identity_key="legacy-old",
            project_id=owners[0],
            project_ids=[str(owners[1])],
            snapshot={},
        )
        new = Pursuit(
            identity_key="legacy-new",
            project_id=owners[2],
            project_ids=[str(owners[3])],
            snapshot={},
        )
        session.add_all([old, new])
        session.flush()
        doc = PursuitDocument(
            pursuit_id=old.id,
            url="https://example.test/synthetic",
            content_hash="a" * 64,
            source={},
        )
        session.add(doc)
        session.flush()
        old_id, new_id, document_id = old.id, new.id, doc.id
    assert rebuild(saved_db)["status"] == "published"
    with saved_db() as reader:
        revision = current_generation(reader).input_revision
        full_revision = reader.get(BrowseState, 1).full_revision
    with saved_db.begin() as writer:
        if document:
            writer.execute(
                text("UPDATE pursuit_documents SET pursuit_id = :new WHERE id = :id"),
                {"new": new_id, "id": document_id},
            )
        else:
            writer.execute(
                text(
                    "UPDATE pursuits SET project_id = :owner, "
                    "project_ids = CAST(:members AS jsonb) WHERE id = :id"
                ),
                {"owner": owners[2], "members": '["' + str(owners[3]) + '"]', "id": old_id},
            )
    with saved_db() as reader:
        state = reader.get(BrowseState, 1)
        assert state.input_revision == revision + 1
        assert state.full_revision == full_revision
        assert set(
            reader.scalars(
                select(BrowseDirtyProject.project_id).where(BrowseDirtyProject.revision > revision)
            )
        ) == set(owners)
        with pytest.raises(HTTPException):
            current_generation(reader)
    from gridlens.intelligence.saved_browse import refresh_project_changes

    with saved_db.begin() as writer:
        assert refresh_project_changes(writer)["status"] == "published"
    with saved_db() as reader:
        assert {item["id"] for item in page(reader, filters())["items"]} == set(map(str, ids))


@pytest.mark.parametrize(
    "bad_members",
    [None, {}, [None], [42], ["invalid-uuid"], ["00000000-0000-0000-0000-000000000001"] * 1001],
)
def test_malformed_legacy_owner_members_fall_back_to_full(saved_db, bad_members):
    from gridlens.persistence.models import Pursuit

    ids = seed(saved_db, count=1, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db.begin() as writer:
        writer.add(
            Pursuit(
                identity_key="synthetic-malformed-owner",
                project_id=writer.get(PowerNeed, ids[0]).project_id,
                project_ids=bad_members,
                snapshot={},
            )
        )
    with saved_db() as reader:
        state = reader.get(BrowseState, 1)
        assert state.full_revision == state.input_revision
        with pytest.raises(HTTPException):
            current_generation(reader)


@pytest.mark.parametrize(
    "identity",
    ["commercial-need:not-a-uuid", "commercial-need:00000000-0000-0000-0000-000000000001"],
)
def test_unresolvable_commercial_need_owner_falls_back_to_full(saved_db, identity):
    from gridlens.persistence.models import Pursuit

    ids = seed(saved_db, count=1, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db.begin() as writer:
        writer.add(
            Pursuit(
                identity_key=identity,
                project_id=writer.get(PowerNeed, ids[0]).project_id,
                project_ids=[],
                snapshot={},
            )
        )
    with saved_db() as reader:
        state = reader.get(BrowseState, 1)
        assert state.full_revision == state.input_revision
        with pytest.raises(HTTPException):
            current_generation(reader)


@pytest.mark.parametrize("unsafe", [False, True])
def test_receipt_rollback_preserves_ready_generation(saved_db, unsafe):
    from gridlens.persistence.models import Pursuit, PursuitCallNote

    receipt_id, _cards = _saved_receipt_fixture(saved_db)
    with saved_db() as session:
        boundary = current_generation(session).valid_until
    assert rebuild(saved_db, _prepare_at=boundary)["status"] == "prepared"
    with saved_db() as session:
        ready = session.get(BrowseState, 1).prepared_generation_id
        revision = current_generation(session).input_revision
    with pytest.raises(RuntimeError), saved_db.begin() as session:
        row = session.get(Pursuit, receipt_id)
        row.snapshot = (
            {**row.snapshot, "unknown_root": True}
            if unsafe
            else {**row.snapshot, "commercial_triage": {"saved_at": "Synthetic rollback"}}
        )
        session.add(
            PursuitCallNote(
                pursuit_id=receipt_id,
                client_id=uuid4(),
                note="Rollback",
                outcome="Contacted",
                next_action="Synthetic",
            )
        )
        session.flush()
        raise RuntimeError("Synthetic rollback")
    with saved_db() as session:
        assert current_generation(session).input_revision == revision
        assert session.get(BrowseState, 1).prepared_generation_id == ready
        assert list(session.scalars(select(PursuitCallNote))) == []


def test_receipt_bucket_cannot_promote_current_qualification(saved_db, monkeypatch):
    from gridlens.persistence.models import Pursuit

    receipt_id, _cards = _saved_receipt_fixture(saved_db)
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    with saved_db.begin() as session:
        row = session.get(Pursuit, receipt_id)
        # This is stored presentation/history, never accepted evidence or call facts.
        row.snapshot = {**row.snapshot, "commercial_triage": {"saved_card": {"tier": "Lead"}}}
    with saved_db() as session:
        payload = api._commercial_triage_payload(session, 50, saved_selection=True)
    assert all(card["tier"] == "Signal" for card in payload["items"])


def test_positive_chain_collector_equals_fresh_canonical_fallback(saved_db, monkeypatch):
    """Synthetic canonical nonempty chain preserves organization and full payload."""
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.buying_chain import buying_chain_view, enrich_buying_chain

    ids = seed(saved_db, count=1, histories=1)
    now = datetime.now(UTC)
    with saved_db.begin() as s:
        project = s.get(Project, s.get(PowerNeed, ids[0]).project_id)
        project.name = "Orion Data Center"
        project.location = "Austin, TX"
        s.flush()
        view = enrich_buying_chain(
            s,
            project.id,
            fetcher=lambda url: PublicDocument(
                url,
                "Orion Data Center, Austin, TX",
                "Acme is the general contractor for Orion Data Center in Austin, TX.",
                now.date(),
                now,
            ),
            now=now,
        )
        assert any(c["organization"] == "Acme" for c in view["candidates"])
        pid = project.id
    assert rebuild(saved_db)["status"] == "published"
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    original = api.opportunity_projection

    def suppress_output(s, **kwargs):
        kwargs.pop("buying_chain_results", None)
        return original(s, **kwargs)

    monkeypatch.setattr(api, "opportunity_projection", suppress_output)
    with saved_db() as s:
        expected = api._commercial_triage_payload(s, 50, saved_selection=True)
        assert any(c["organization"] == "Acme" for c in buying_chain_view(s, pid)["candidates"])
    monkeypatch.setattr(api, "opportunity_projection", original)
    with saved_db() as s:
        actual = api._commercial_triage_payload(s, 50, saved_selection=True)
    expected.pop("evaluated_at")
    actual.pop("evaluated_at")
    assert actual == expected
    assert any(c["organization"] == "Acme" for c in actual["items"])


def test_industrial_asset_group_survives_workspace_and_both_export_paths(saved_db, monkeypatch):
    from fastapi.testclient import TestClient

    from gridlens.domain.lifecycle import AssetType
    from gridlens.persistence.models import PowerNeed, Project
    from gridlens.security import token_for

    need_ids = seed(saved_db, count=6, histories=1)
    asset_types = [
        AssetType.GAS_PROCESSING_PLANT,
        AssetType.COMPRESSOR_STATION,
        AssetType.UPSTREAM_WELL,
        AssetType.CRYOGENIC_PLANT,
        AssetType.DATA_CENTER,
        AssetType.UNKNOWN,
    ]
    with saved_db.begin() as session:
        for need_id, asset_type in zip(need_ids, asset_types, strict=True):
            need = session.get(PowerNeed, need_id)
            session.get(Project, need.project_id).asset_type = asset_type.value
    assert rebuild(saved_db)["status"] == "published"
    expected_ids = {str(need_id) for need_id in need_ids[:4]}
    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))

    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    workspace = client.get("/api/opportunities/workspace?industry_group=industrial")
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()["total"] == 4
    assert {item["id"] for item in workspace.json()["items"]} == expected_ids
    saved_export = client.get("/api/opportunities/export.csv?tier=Signal&industry_group=industrial")
    assert saved_export.status_code == 200, saved_export.text
    saved_ids = {row["need_id"] for row in csv.DictReader(StringIO(saved_export.text))}
    assert saved_ids == expected_ids

    monkeypatch.setattr(settings, "saved_browse_enabled", False)
    legacy_export = client.get(
        "/api/opportunities/export.csv?tier=Signal&industry_group=industrial"
    )
    assert legacy_export.status_code == 200, legacy_export.text
    legacy_ids = {row["need_id"] for row in csv.DictReader(StringIO(legacy_export.text))}
    assert legacy_ids == expected_ids
    exact_export = client.get(
        "/api/opportunities/export.csv?tier=Signal&industry=gas_processing_plant"
    )
    assert exact_export.status_code == 200, exact_export.text
    assert {row["need_id"] for row in csv.DictReader(StringIO(exact_export.text))} == {
        str(need_ids[0])
    }
    assert client.get("/api/opportunities?industry_group=industrial").status_code == 422
    assert client.get("/api/opportunities/map-window?industry_group=industrial").status_code == 422
