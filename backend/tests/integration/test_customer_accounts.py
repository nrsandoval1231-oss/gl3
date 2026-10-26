from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.customer_accounts import (
    account_browse_page,
    account_projects,
    account_queue,
    backfill_rrc_operator_memberships,
    record_rrc_operator_membership,
)
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BrowseGeneration,
    BrowseRow,
    BrowseState,
    CompanyIdentity,
    CompanyProjectMembership,
    CompanyProjectMembershipCorrection,
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def customer_db():
    if not settings.test_database_url:
        pytest.skip("TEST_DATABASE_URL required for PostgreSQL account tests")
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test") and target != application
    schema = "customer_test_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    yield factory
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


def _project_evidence(session, source_id: str, number: str, slug: str):
    project = Project(
        identity_key=f"{slug}-{uuid4()}",
        name=f"Diamondback site {slug}",
        location=f"{slug} Synthetic Road, Dallas, TX",
        source_id=source_id,
        external_id=f"permit-{slug}",
    )
    observation = Observation(
        source_id=source_id,
        external_id=f"permit-{slug}",
        title=f"RRC permit {slug}",
        abstract=f"Operator number: {number}\nOperator: DIAMONDBACK E&P LLC",
        published_at=None,
        url=f"https://rrc.example/{slug}",
        content_hash=f"observation-{slug}",
    )
    session.add_all([project, observation])
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        content_hash=f"evidence-{slug}",
        title=observation.title,
        abstract=observation.abstract,
        url=observation.url,
        observed_at=datetime.now(UTC),
        extraction_location="RRC row",
    )
    interpretation = Interpretation(
        observation_id=observation.id,
        content_hash=observation.content_hash,
        status="accepted",
        assessment={
            "decision": "accepted",
            "evidence_hash": evidence.content_hash,
        },
    )
    session.add_all([evidence, interpretation])
    session.flush()
    record = {
        "abstract": observation.abstract,
        "permit": {
            "source_type": source_id,
            "operator_number": number,
            "operator": "DIAMONDBACK E&P LLC",
        },
    }
    return project, observation, evidence, record


def test_rrc_operator_memberships_group_sites_and_preserve_separate_projects(customer_db):
    source_id = "texas-rrc-flare-vent-exceptions"
    with customer_db.begin() as session:
        session.add(
            Source(
                id=source_id,
                publisher="Texas Railroad Commission",
                endpoint="https://rrc.example",
                family="oil-and-gas-permits",
                geography="Texas",
                industries=["oil-and-gas"],
                retrieval_method="rrc-flare-exceptions",
            )
        )
        session.flush()
        sites = [
            _project_evidence(session, source_id, "217012", "site-a"),
            _project_evidence(session, source_id, "217012", "site-b"),
            _project_evidence(session, source_id, "999999", "same-name-other-operator"),
        ]
        for project, observation, evidence, record in sites:
            record_rrc_operator_membership(
                session,
                project=project,
                observation=observation,
                evidence=evidence,
                source_id=source_id,
                record=record,
            )
        # Replaying the same source version is idempotent.
        record_rrc_operator_membership(
            session,
            project=sites[0][0],
            observation=sites[0][1],
            evidence=sites[0][2],
            source_id=source_id,
            record=sites[0][3],
        )
        session.flush()
        memberships = session.scalars(select(CompanyProjectMembership)).all()
        assert len(memberships) == 3
        assert len({row.company_identity_id for row in memberships}) == 2
        assert session.scalar(
            select(CompanyIdentity).where(CompanyIdentity.rrc_operator_number == "217012")
        )


def test_rrc_membership_requires_current_accepted_evidence(customer_db):
    source_id = "texas-rrc-flare-vent-exceptions"
    with customer_db.begin() as session:
        session.add(
            Source(
                id=source_id,
                publisher="Texas Railroad Commission",
                endpoint="https://rrc.example",
                family="oil-and-gas-permits",
                geography="Texas",
                industries=["oil-and-gas"],
                retrieval_method="rrc-flare-exceptions",
            )
        )
        session.flush()
        project, observation, evidence, record = _project_evidence(
            session, source_id, "217012", "site-stale"
        )
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        interpretation.status = "pending"
        record_rrc_operator_membership(
            session,
            project=project,
            observation=observation,
            evidence=evidence,
            source_id=source_id,
            record=record,
        )
        assert session.scalar(select(CompanyProjectMembership.id)) is None


def test_retained_rrc_backfill_requires_active_need_observation_binding(customer_db):
    source_id = "texas-rrc-flare-vent-exceptions"
    with customer_db.begin() as session:
        session.add(
            Source(
                id=source_id,
                publisher="Texas Railroad Commission",
                endpoint="https://rrc.example",
                family="oil-and-gas-permits",
                geography="Texas",
                industries=["oil-and-gas"],
                retrieval_method="rrc-flare-exceptions",
            )
        )
        session.flush()
        project, observation, _evidence, _record = _project_evidence(
            session, source_id, "217012", "backfill-site"
        )
        need = PowerNeed(
            project_id=project.id,
            activity_key="drilling",
            tier="Lead",
            rationale="Current retained need",
        )
        session.add(need)
        session.flush()
        session.add(NeedObservation(need_id=need.id, observation_id=observation.id))
        session.flush()
        result = backfill_rrc_operator_memberships(session)
        assert result["eligible_evidence_rows_examined"] == 1
        assert result["current_operator_memberships"] == 1
        assert session.scalar(select(CompanyProjectMembership.project_id)) == project.id


def test_account_workspace_groups_filtered_saved_rows_in_sql(customer_db):
    from gridlens.intelligence.saved_browse import POLICY_VERSION

    now = datetime.now(UTC)
    generation_id = uuid4()
    with customer_db.begin() as session:
        source_id = "texas-rrc-flare-vent-exceptions"
        session.add(
            Source(
                id=source_id,
                publisher="Texas Railroad Commission",
                endpoint="https://rrc.example",
                family="oil-and-gas-permits",
                geography="Texas",
                industries=["oil-and-gas"],
                retrieval_method="rrc-flare-exceptions",
            )
        )
        session.flush()
        project, observation, evidence, record = _project_evidence(
            session, source_id, "217012", "workspace-site"
        )
        record_rrc_operator_membership(
            session,
            project=project,
            observation=observation,
            evidence=evidence,
            source_id=source_id,
            record=record,
        )
        identity_id = session.scalar(
            select(CompanyIdentity.id).where(CompanyIdentity.rrc_operator_number == "217012")
        )
        session.add(
            BrowseGeneration(
                id=generation_id,
                input_revision=0,
                policy_version=POLICY_VERSION,
                built_at=now,
                valid_from=now,
                valid_until=now.replace(year=now.year + 1),
                row_count=1,
                digest="generation-digest",
                counts={},
            )
        )
        session.flush()
        need_id = uuid4()
        session.add_all(
            [
                BrowseState(id=1, input_revision=0, generation_id=generation_id),
                BrowseCustomerMembership(
                    generation_id=generation_id,
                    company_identity_id=identity_id,
                    project_id=project.id,
                    organization_name="DIAMONDBACK E&P LLC",
                    role="asset_operator",
                    supporting_evidence_count=3,
                    last_evidence_update=now,
                ),
                BrowseRow(
                    generation_id=generation_id,
                    need_id=need_id,
                    project_id=project.id,
                    tier="Lead",
                    location="Texas",
                    industry="Oil and gas",
                    activity="drilling",
                    has_timing=False,
                    mw_low=None,
                    mw_high=None,
                    priority_segment=1,
                    workflow_status="UNKNOWN",
                    signal_decision="UNKNOWN",
                    project_group="group",
                    single_group="single",
                    rank_score=100,
                    updated_at=now,
                    search_text="diamondback texas drilling",
                    display_title=project.name,
                    commercial_group=None,
                    commercial_segment=None,
                    commercial_geography=None,
                    commercial_date=None,
                    summary={},
                    compact={
                        "id": str(need_id),
                        "project_id": str(project.id),
                        "name": project.name,
                        "location": "Texas",
                        "tier": "Lead",
                        "asset_type": "oil_and_gas",
                        "activity": "drilling",
                        "rationale": "Source-backed permit",
                        "required_mw": None,
                        "start_window": None,
                        "duration": None,
                        "supply": "Unknown",
                        "next_action": "Review evidence",
                        "conflict_state": "clear",
                        "evidence": [{"abstract": "PRIVATE SOURCE DOCUMENT"}],
                        "commercial_preview": {
                            "disposition": "RESEARCH",
                            "reason": "Review permit",
                            "next_question": "What is the project need?",
                            "next_action": "Review source",
                        },
                    },
                ),
            ]
        )
        filters = {
            "search": "",
            "tier": None,
            "disposition": None,
            "geography": None,
            "industry": None,
            "industry_group": None,
            "activity": None,
            "timing": None,
            "mw_status": None,
            "mw_min": None,
            "mw_max": None,
            "sort": "priority",
        }
        result = account_browse_page(session, filters, limit=25, offset=0, token=None)
        assert result["total"] == 1
        assert result["count_unit"] == "company accounts"
        assert result["items"][0]["project_count"] == 1
        assert result["items"][0]["matching_need_count"] == 1
        assert result["items"][0]["supporting_evidence_count"] == 3
        assert result["items"][0]["account_aliases"] == ["DIAMONDBACK E&P LLC"]
        assert result["items"][0]["evidence"] == []
        assert result["items"][0]["evidence_count"] == 1
        saved_row = session.scalar(
            select(BrowseRow).where(
                BrowseRow.generation_id == generation_id, BrowseRow.need_id == need_id
            )
        )
        for disposition in ("ACTION NOW", "RESEARCH", "WATCH", "REJECT"):
            saved_row.compact = {
                **saved_row.compact,
                "commercial_preview": {
                    **saved_row.compact["commercial_preview"],
                    "disposition": disposition,
                },
            }
            session.flush()
            selected = account_browse_page(
                session,
                {**filters, "disposition": disposition},
                limit=25,
                offset=0,
                token=None,
            )
            assert selected["total"] == 1
            assert selected["items"][0]["commercial_disposition"] == disposition
            assert selected["items"][0]["matching_need_count"] == 1
            assert selected["counts"] == {
                "action_now": int(disposition == "ACTION NOW"),
                "research": int(disposition == "RESEARCH"),
                "watch": int(disposition == "WATCH"),
                "reject": int(disposition == "REJECT"),
            }
            other = next(
                item
                for item in ("ACTION NOW", "RESEARCH", "WATCH", "REJECT")
                if item != disposition
            )
            empty = account_browse_page(
                session,
                {**filters, "disposition": other},
                limit=25,
                offset=0,
                token=None,
            )
            assert empty["items"] == []
            assert empty["total"] == 0
        accounts = account_queue(session, search=None, limit=25, offset=0)
        assert accounts["total"] == 1
        assert accounts["items"][0]["highest_priority_need"]["id"] == str(need_id)
        assert accounts["items"][0]["highest_priority_need"]["industry"] == "oil_and_gas"
        assert accounts["items"][0]["supporting_evidence_count"] == 3
        assert accounts["items"][0]["aliases"] == ["DIAMONDBACK E&P LLC"]
        projects = account_projects(session, identity_id, limit=25, offset=0)
        assert projects["account"]["company_identity_id"] == identity_id
        assert projects["account"]["highest_priority_need"]["industry"] == "oil_and_gas"
        assert projects["account"]["project_count"] == 1
        assert projects["account"]["need_count"] == 1
        assert projects["account"]["supporting_evidence_count"] == 3
        assert projects["account"]["last_evidence_update"] == now
        assert projects["account"]["aliases"] == ["DIAMONDBACK E&P LLC"]


def test_historical_membership_retraction_survives_automatic_source_refresh(customer_db):
    source_id = "texas-rrc-flare-vent-exceptions"
    with customer_db.begin() as session:
        session.add(
            Source(
                id=source_id,
                publisher="Texas Railroad Commission",
                endpoint="https://rrc.example",
                family="oil-and-gas-permits",
                geography="Texas",
                industries=["oil-and-gas"],
                retrieval_method="rrc-flare-exceptions",
            )
        )
        session.flush()
        project, observation, evidence, record = _project_evidence(
            session, source_id, "217012", "retract-me"
        )
        record_rrc_operator_membership(
            session,
            project=project,
            observation=observation,
            evidence=evidence,
            source_id=source_id,
            record=record,
        )
        membership = session.scalar(select(CompanyProjectMembership))
        # Retained historical correction fixture: the public mutation and its
        # manual-only writer are retired, but automatic evidence refresh must
        # continue to honor pre-existing attributed decisions.
        membership.state = "retracted"
        membership.version = 1
        event = CompanyProjectMembershipCorrection(
            membership_id=membership.id,
            expected_version=0,
            idempotency_key="historical-retract-217012-1",
            action="retracted",
            reason="Historical operator attribution dispute",
            actor="historical_authenticated_operator",
        )
        session.add(event)
        session.flush()
        event_id = event.id
        # A same-operator refresh with a new source hash cannot resurrect the
        # corrected association.
        refreshed_evidence = Evidence(
            observation_id=observation.id,
            content_hash="new-content-hash-after-retraction",
            title=evidence.title,
            abstract=evidence.abstract,
            url=evidence.url,
            observed_at=datetime.now(UTC),
            extraction_location="RRC refreshed row",
        )
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        interpretation.assessment = {
            **interpretation.assessment,
            "evidence_hash": refreshed_evidence.content_hash,
        }
        session.add(refreshed_evidence)
        session.flush()
        refreshed_record = {"abstract": refreshed_evidence.abstract}
        record_rrc_operator_membership(
            session,
            project=project,
            observation=observation,
            evidence=refreshed_evidence,
            source_id=source_id,
            record=refreshed_record,
        )
        assert (
            session.scalar(
                select(CompanyProjectMembership.id).where(
                    CompanyProjectMembership.project_id == project.id,
                    CompanyProjectMembership.state == "current",
                )
            )
            is None
        )
        retained = session.scalars(select(CompanyProjectMembershipCorrection)).all()
        assert len(retained) == 1
        assert retained[0].id == event_id
        assert retained[0].reason == "Historical operator attribution dispute"
        assert retained[0].expected_version == 0
        assert membership.version == 1
