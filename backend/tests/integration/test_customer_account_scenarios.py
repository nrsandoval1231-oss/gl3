"""Synthetic canonical-path acceptance cases for customer account projections."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.customer_accounts import (
    account_queue,
    record_rrc_operator_membership,
    retract_customer_membership,
    unresolved_projects,
)
from gridlens.intelligence.saved_browse import (
    current_generation,
    rebuild,
    refresh_project_changes,
)
from gridlens.persistence.browse_invalidation import install
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BrowseCustomerMembership,
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    BuyingChainRun,
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
def scenario_db():
    assert settings.test_database_url
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    schema = "customer_scenario_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install(connection)
    factory = sessionmaker(engine, expire_on_commit=False)
    yield factory
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


def _source(session, source_id):
    if session.get(Source, source_id) is None:
        session.add(
            Source(
                id=source_id,
                publisher="Synthetic RRC fixture",
                endpoint="https://example.test/rrc",
                family="construction-permits",
                geography="Texas",
                industries=["oil-and-gas"],
                retrieval_method=(
                    "rrc-drilling-permits"
                    if source_id == "texas-rrc-drilling-permits"
                    else "rrc-flare-exceptions"
                ),
                health={},
            )
        )
        session.flush()


def _project(
    session,
    slug,
    *,
    source_id="texas-rrc-drilling-permits",
    include_operator=True,
    operator_number="217012",
    operator_name=None,
):
    _source(session, source_id)
    project = Project(
        identity_key=f"synthetic-{slug}-{uuid4()}",
        name=f"Synthetic site {slug}",
        location="Texas",
        source_id=source_id,
        external_id=f"permit-{slug}",
    )
    session.add(project)
    session.flush()
    need = PowerNeed(
        project_id=project.id,
        activity_key="drilling",
        tier="Signal",
        rationale="Synthetic only; no real power demand is asserted.",
        supply="Unknown",
        active=True,
    )
    session.add(need)
    session.flush()
    abstract = (
        f"Project: {project.name}\nLocation: Texas\nOperator number: {operator_number}\n"
        f"Operator: {operator_name or f'Synthetic Operator {slug}'}"
    )
    observation = Observation(
        source_id=source_id,
        external_id=project.external_id,
        title=project.name,
        abstract=abstract,
        url=f"https://example.test/rrc/{slug}",
        content_hash=f"observation-{uuid4().hex}",
        published_at=date(2026, 10, 20),
    )
    session.add(observation)
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        content_hash=observation.content_hash,
        title=project.name,
        abstract=abstract,
        url=observation.url,
        observed_at=datetime.now(UTC),
        extraction_location="Synthetic fixture",
    )
    interpretation = Interpretation(
        observation_id=observation.id,
        content_hash=observation.content_hash,
        evaluator_version="synthetic-fixture-v1",
        status="accepted",
        assessment={
            "decision": "accepted",
            "evidence_hash": evidence.content_hash,
            "semantic_hash": observation.content_hash,
            "project_identity_key": project.identity_key,
            "subject": project.name,
            "power_activity": "drilling",
            "location": "Texas",
        },
    )
    session.add_all(
        [evidence, interpretation, NeedObservation(need_id=need.id, observation_id=observation.id)]
    )
    session.flush()
    identity = None
    if include_operator:
        identity = session.scalar(
            select(CompanyIdentity).where(CompanyIdentity.rrc_operator_number == operator_number)
        )
        if identity is None:
            identity = CompanyIdentity(rrc_operator_number=operator_number)
            session.add(identity)
            session.flush()
        record_rrc_operator_membership(
            session,
            project=project,
            observation=observation,
            evidence=evidence,
            source_id=source_id,
            record={"abstract": evidence.abstract},
        )
    session.flush()
    return project, need, observation, evidence, identity


def _owner_claim(session, project, identity, organization, slug, *, role="owner_developer"):
    now = datetime.now(UTC)
    quote = f"{organization} is named on synthetic project {slug}."
    source = BuyingChainEvidence(
        project_id=project.id,
        url=f"https://example.test/relationships/{slug}/{organization.replace(' ', '-')}",
        title="Synthetic relationship record",
        excerpt=quote,
        content_hash=uuid4().hex,
        extraction_location="Synthetic fixture",
        observed_at=now,
        last_seen_at=now,
        project_match_reason="Synthetic, isolated test data.",
    )
    session.add(source)
    session.flush()
    claim = BuyingChainClaim(
        project_id=project.id,
        entity_key=f"{slug}-{organization}",
        fingerprint=uuid4().hex,
        policy_version="synthetic-fixture-v1",
        organization=organization,
        person_name=None,
        title=None,
        category=role,
        organization_relationship="DIRECT",
        person_organization_relationship="UNKNOWN",
        person_project_relationship="DIRECT",
        evidence_strength="High",
        reason="Synthetic owner/participant statement.",
        citations=[
            {
                "evidence_id": str(source.id),
                "url": source.url,
                "quote": quote,
                "supports": "project_organization",
            }
        ],
        public_contacts=[],
        observed_at=now,
    )
    session.add(claim)
    session.flush()
    run = session.scalar(
        select(BuyingChainRun)
        .where(BuyingChainRun.project_id == project.id)
        .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
    )
    if run is None:
        run = BuyingChainRun(
            project_id=project.id,
            input_hash=uuid4().hex,
            evidence_ids=[str(source.id)],
            claim_ids=[str(claim.id)],
            policy_version="synthetic-fixture-v1",
            status="complete",
            documents_checked=1,
            candidates_added=1,
            unresolved=[],
        )
        session.add(run)
    else:
        run.claim_ids = [*run.claim_ids, str(claim.id)]
        run.evidence_ids = [*run.evidence_ids, str(source.id)]
    session.add(
        BuyingChainIdentityLink(
            claim_id=claim.id,
            entity_type="company",
            company_identity_id=identity.id,
            reason="Explicit synthetic test identity link.",
            basis="attributed_review",
            reviewed_by="scenario-test-operator",
            source_evidence_id=source.id,
            source_version_hash=source.content_hash,
            state="current",
        )
    )
    session.flush()
    return claim


def _rrc_version(session, project, operator_number, operator_name, version):
    abstract = (
        f"Project: {project.name}\nLocation: Texas\nOperator number: {operator_number}\n"
        f"Operator: {operator_name}"
    )
    observation = session.scalar(
        select(Observation).where(
            Observation.source_id == project.source_id,
            Observation.external_id == project.external_id,
        )
    )
    observation.abstract = abstract
    observation.url = f"https://example.test/rrc/{project.external_id}/{version}"
    observation.content_hash = f"{version}-{uuid4().hex}"
    observation.published_at = date(2026, 10, 20)
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        content_hash=observation.content_hash,
        title=project.name,
        abstract=abstract,
        url=observation.url,
        observed_at=datetime.now(UTC),
        extraction_location="Synthetic version fixture",
    )
    session.add(evidence)
    interpretation = session.scalar(
        select(Interpretation).where(Interpretation.observation_id == observation.id)
    )
    interpretation.content_hash = observation.content_hash
    interpretation.status = "accepted"
    interpretation.assessment = {
        "decision": "accepted",
        "evidence_hash": evidence.content_hash,
        "semantic_hash": observation.content_hash,
        "project_identity_key": project.identity_key,
        "power_activity": "drilling",
        "subject": project.name,
        "location": "Texas",
    }
    session.flush()
    record_rrc_operator_membership(
        session,
        project=project,
        observation=observation,
        evidence=evidence,
        source_id=project.source_id,
        record={"abstract": abstract},
    )
    return evidence


def test_synthetic_owner_contractor_and_unresolved_projects(scenario_db):
    with scenario_db.begin() as session:
        owner_project, _need, _obs, _ev, _operator = _project(
            session, "owner", include_operator=False
        )
        contractor_project, _need, _obs, _ev, _operator = _project(
            session, "contractor", include_operator=False
        )
        empty_project, _need, _obs, _ev, _operator = _project(
            session, "no-owner", include_operator=False
        )
        sabey = CompanyIdentity()
        jcl = CompanyIdentity()
        session.add_all([sabey, jcl])
        session.flush()
        _owner_claim(session, owner_project, sabey, "Sabey Data Centers", "owner")
        _owner_claim(session, owner_project, jcl, "JCL Electrical", "owner", role="contractor")
        _owner_claim(
            session, contractor_project, jcl, "JCL Electrical", "contractor", role="contractor"
        )
    result = rebuild(scenario_db)
    assert result["status"] == "published"
    with scenario_db() as session:
        queue = account_queue(session, search=None, limit=25, offset=0)
        names = {item["name"] for item in queue["items"]}
        assert "Sabey Data Centers" in names, result
        assert "JCL Electrical" not in names
        unresolved = unresolved_projects(session, search=None, limit=25, offset=0)
        unresolved_ids = {item["project_id"] for item in unresolved["items"]}
        assert contractor_project.id in unresolved_ids
        assert empty_project.id in unresolved_ids
        assert owner_project.id not in unresolved_ids
        assert not session.scalar(
            select(func.count())
            .select_from(BrowseCustomerMembership)
            .where(BrowseCustomerMembership.company_identity_id == jcl.id)
        )


def test_same_name_accounts_conflicts_shared_document_and_generation_refresh(scenario_db):
    with scenario_db.begin() as session:
        first_project, _n1, _o1, _first_evidence, first_identity = _project(
            session,
            "same-name-a",
            operator_number="900001",
            operator_name="Twin Energy LLC",
        )
        second_project, _n2, _o2, _second_evidence, second_identity = _project(
            session,
            "same-name-b",
            operator_number="900002",
            operator_name="Twin Energy LLC",
        )
        conflict_project, _n3, _o3, _e3, conflict_identity = _project(
            session,
            "conflicting",
            operator_number="900003",
            operator_name="Conflict Operator LLC",
        )
        shared_a, _n4, _o4, shared_document, shared_identity = _project(
            session,
            "shared-a",
            operator_number="900005",
            operator_name="Shared Document Operator LLC",
        )
        shared_b, _n5, _o5, _e5, shared_identity_b = _project(
            session,
            "shared-b",
            operator_number="900005",
            operator_name="Shared Document Operator LLC",
        )
        assert shared_identity.id == shared_identity_b.id
        # The same synthetic support document is referenced by two separate
        # project memberships and two separate eligible needs.
        shared_b.external_id = shared_a.external_id
        shared_membership_b = session.scalar(
            select(CompanyProjectMembership).where(
                CompanyProjectMembership.project_id == shared_b.id
            )
        )
        shared_membership_b.source_evidence_id = shared_document.id
        shared_membership_b.source_version_hash = shared_document.content_hash
        # A separate admitted RRC source currently names a second operator on
        # this same project. Conflicting customer candidates must fail closed.
        other_source_id = "texas-rrc-flare-vent-exceptions"
        _source(session, other_source_id)
        alternate_number = "900004"
        alternate_name = "Alternate Conflict Operator LLC"
        alternate_observation = Observation(
            source_id=other_source_id,
            external_id=conflict_project.external_id,
            title=conflict_project.name,
            abstract=(
                f"Project: {conflict_project.name}\nLocation: Texas\n"
                f"Operator number: {alternate_number}\nOperator: {alternate_name}"
            ),
            url="https://example.test/rrc/conflict-alternate",
            content_hash="conflict-alternate-observation",
            published_at=date(2026, 10, 20),
        )
        session.add(alternate_observation)
        session.flush()
        alternate_evidence = Evidence(
            observation_id=alternate_observation.id,
            content_hash=alternate_observation.content_hash,
            title=alternate_observation.title,
            abstract=alternate_observation.abstract,
            url=alternate_observation.url,
            observed_at=datetime.now(UTC),
            extraction_location="Synthetic fixture",
        )
        session.add(alternate_evidence)
        session.add(
            Interpretation(
                observation_id=alternate_observation.id,
                content_hash=alternate_observation.content_hash,
                status="accepted",
                assessment={
                    "decision": "accepted",
                    "evidence_hash": alternate_evidence.content_hash,
                },
            )
        )
        alternate_identity = CompanyIdentity(rrc_operator_number=alternate_number)
        session.add(alternate_identity)
        session.flush()
        session.add(
            CompanyProjectMembership(
                company_identity_id=alternate_identity.id,
                project_id=conflict_project.id,
                role="asset_operator",
                organization_name=alternate_name,
                source_id=other_source_id,
                source_evidence_id=alternate_evidence.id,
                source_version_hash=alternate_evidence.content_hash,
                decision_basis="synthetic_source_conflict_v1",
                operator_number=alternate_number,
            )
        )

    first_build = rebuild(scenario_db)
    assert first_build["status"] == "published"
    with scenario_db() as session:
        page = account_queue(session, search=None, limit=25, offset=0)
        twins = [item for item in page["items"] if item["name"] == "Twin Energy LLC"]
        assert {item["company_identity_id"] for item in twins} == {
            first_identity.id,
            second_identity.id,
        }
        assert all(item["supporting_evidence_count"] == 1 for item in twins)
        assert all(item["project_count"] == 1 and item["need_count"] == 1 for item in twins)
        shared_account = next(
            item for item in page["items"] if item["company_identity_id"] == shared_identity.id
        )
        assert shared_account["supporting_evidence_count"] == 1
        assert shared_account["project_count"] == 2 and shared_account["need_count"] == 2
        assert conflict_identity.id not in {item["company_identity_id"] for item in page["items"]}
        unresolved = unresolved_projects(session, search="conflict", limit=25, offset=0)
        assert any(item["project_id"] == conflict_project.id for item in unresolved["items"])

    # Retraction invalidates the generation before any account reader can serve
    # stale associations; the next full publication has a stable remaining ID.
    with scenario_db.begin() as session:
        second_membership = session.scalar(
            select(CompanyProjectMembership).where(
                CompanyProjectMembership.project_id == second_project.id,
                CompanyProjectMembership.state == "current",
            )
        )
        correction = retract_customer_membership(
            session,
            membership_id=second_membership.id,
            expected_version=0,
            idempotency_key="scenario-retract-twin-b",
            reason="Synthetic acceptance correction",
            actor="scenario-test-operator",
        )
        correction_id = correction.id
    with scenario_db() as session, pytest.raises(HTTPException) as stale_generation:
        current_generation(session)
    assert stale_generation.value.status_code == 503
    with scenario_db.begin() as session:
        # Customer membership/evidence affects the company-wide summary, so a
        # scoped incremental clone must defer to the full generation builder.
        assert refresh_project_changes(session, max_projects=None, max_needs=None) is None
    refreshed = rebuild(scenario_db)
    assert refreshed["status"] == "published"
    with scenario_db() as session:
        current = account_queue(session, search=None, limit=25, offset=0)
        remaining = [item for item in current["items"] if item["name"] == "Twin Energy LLC"]
        assert [item["company_identity_id"] for item in remaining] == [first_identity.id]
        assert session.get(CompanyProjectMembership, second_membership.id).state == "retracted"
        assert (
            session.scalar(
                select(CompanyProjectMembershipCorrection.id).where(
                    CompanyProjectMembershipCorrection.id == correction_id
                )
            )
            == correction_id
        )
    assert first_build["generation_id"] != refreshed["generation_id"]

    # An operator change after human retraction is visible for review, while an
    # A -> B -> A source replay cannot restore the retracted A relationship.
    with scenario_db.begin() as session:
        changed_project = session.get(Project, second_project.id)
        _rrc_version(session, changed_project, "900006", "Changed Operator LLC", "B")
        _rrc_version(session, changed_project, "900002", "Twin Energy LLC", "A-again")
        stable_identity = session.scalar(
            select(CompanyIdentity).where(CompanyIdentity.rrc_operator_number == "900002")
        )
        assert stable_identity.id == second_identity.id
        assert (
            session.scalar(
                select(func.count())
                .select_from(CompanyProjectMembership)
                .where(
                    CompanyProjectMembership.project_id == second_project.id,
                    CompanyProjectMembership.state == "current",
                )
            )
            == 0
        )
    with scenario_db() as session, pytest.raises(HTTPException) as stale_generation:
        current_generation(session)
    assert stale_generation.value.status_code == 503
    with scenario_db.begin() as session:
        assert refresh_project_changes(session, max_projects=None, max_needs=None) is None
    replay_build = rebuild(scenario_db)
    assert replay_build["status"] == "published"
    with scenario_db() as session:
        unresolved = unresolved_projects(session, search="same-name-b", limit=25, offset=0)
        assert any(item["project_id"] == second_project.id for item in unresolved["items"]), (
            unresolved
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(CompanyProjectMembershipCorrection)
                .where(CompanyProjectMembershipCorrection.id == correction_id)
            )
            == 1
        )


def test_need_detail_has_current_unambiguous_associated_account(scenario_db, monkeypatch):
    from gridlens.api import app as api

    with scenario_db.begin() as session:
        operator_project, operator_need, _obs, operator_evidence, operator_identity = _project(
            session, "detail-operator"
        )
        owner_project, owner_need, _obs, _owner_evidence, _none = _project(
            session, "detail-owner", include_operator=False
        )
        contractor_project, contractor_need, _obs, _contractor_evidence, _none = _project(
            session, "detail-contractor", include_operator=False
        )
        conflict_project, conflict_need, _obs, _conflict_evidence, _conflict_identity = _project(
            session, "detail-conflict"
        )
        retracted_project, retracted_need, _obs, _retracted_evidence, _retracted_identity = (
            _project(session, "detail-retracted", operator_number="800001")
        )
        owner_identity = CompanyIdentity()
        contractor_identity = CompanyIdentity()
        session.add_all([owner_identity, contractor_identity])
        session.flush()
        _owner_claim(session, owner_project, owner_identity, "Synthetic Owner LLC", "detail-owner")
        _owner_claim(
            session,
            contractor_project,
            contractor_identity,
            "Synthetic Contractor LLC",
            "detail-contractor",
            role="contractor",
        )
        retracted_membership = session.scalar(
            select(CompanyProjectMembership).where(
                CompanyProjectMembership.project_id == retracted_project.id,
                CompanyProjectMembership.state == "current",
            )
        )
        retract_customer_membership(
            session,
            membership_id=retracted_membership.id,
            expected_version=0,
            idempotency_key="detail-retract-operator",
            reason="Synthetic detail acceptance test",
            actor="scenario-test-operator",
        )
        other_source_id = "texas-rrc-flare-vent-exceptions"
        _source(session, other_source_id)
        number, name = "800002", "Conflicting Operator LLC"
        abstract = (
            f"Project: {conflict_project.name}\nLocation: Texas\n"
            f"Operator number: {number}\nOperator: {name}"
        )
        observation = Observation(
            source_id=other_source_id,
            external_id=conflict_project.external_id,
            title=conflict_project.name,
            abstract=abstract,
            url="https://example.test/rrc/detail-conflict-other",
            content_hash="detail-conflict-other-v1",
            published_at=date(2026, 10, 20),
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=observation.content_hash,
            title=observation.title,
            abstract=abstract,
            url=observation.url,
            observed_at=datetime.now(UTC),
            extraction_location="Synthetic detail fixture",
        )
        identity = CompanyIdentity(rrc_operator_number=number)
        session.add_all(
            [
                evidence,
                identity,
                Interpretation(
                    observation_id=observation.id,
                    content_hash=observation.content_hash,
                    status="accepted",
                    assessment={
                        "decision": "accepted",
                        "evidence_hash": evidence.content_hash,
                    },
                ),
            ]
        )
        session.flush()
        session.add(
            CompanyProjectMembership(
                company_identity_id=identity.id,
                project_id=conflict_project.id,
                role="asset_operator",
                organization_name=name,
                source_id=other_source_id,
                source_evidence_id=evidence.id,
                source_version_hash=evidence.content_hash,
                decision_basis="synthetic_conflict_v1",
                operator_number=number,
            )
        )

    assert rebuild(scenario_db)["status"] == "published"
    monkeypatch.setattr(api, "SessionLocal", scenario_db)
    monkeypatch.setattr(settings, "saved_browse_enabled", True)
    details = {
        need_id: api.opportunity_need_detail(need_id)
        for need_id in (
            operator_need.id,
            owner_need.id,
            contractor_need.id,
            conflict_need.id,
            retracted_need.id,
        )
    }
    operator = details[operator_need.id]["associated_account"]
    assert operator == {
        "company_identity_id": operator_identity.id,
        "name": "Synthetic Operator detail-operator",
        "role": "asset_operator",
        "basis": "typed_rrc_operator_number_v1",
        "support_status": "current",
        "evidence_refs": [
            {
                "namespace": "retained-evidence",
                "id": str(operator_evidence.id),
                "retained_evidence_id": str(operator_evidence.id),
            }
        ],
    }
    owner = details[owner_need.id]["associated_account"]
    assert owner["company_identity_id"] == owner_identity.id
    assert owner["role"] == "owner_developer"
    assert owner["basis"] == "attributed_review"
    assert owner["support_status"] == "current"
    assert owner["evidence_refs"][0]["namespace"] == "buying-chain-evidence"
    assert details[contractor_need.id]["associated_account"] is None
    assert details[conflict_need.id]["associated_account"] is None
    assert details[retracted_need.id]["associated_account"] is None


def test_rrc_new_permit_refresh_preserves_account_and_separate_sites(scenario_db):
    with scenario_db.begin() as session:
        first_project, _n1, _o1, _e1, first_identity = _project(
            session,
            "refresh-first-site",
            operator_number="700001",
            operator_name="Refresh Operator LLC",
        )
        second_project, _n2, _o2, _e2, second_identity = _project(
            session,
            "refresh-second-site",
            operator_number="700001",
            operator_name="Refresh Operator LLC",
        )
        assert first_identity.id == second_identity.id
        first_source_version = _rrc_version(
            session, first_project, "700001", "Refresh Operator LLC", "updated"
        )
        first_observation = session.get(Observation, first_source_version.observation_id)
        record_rrc_operator_membership(
            session,
            project=first_project,
            observation=first_observation,
            evidence=first_source_version,
            source_id=first_project.source_id,
            record={"abstract": first_source_version.abstract},
        )
    assert rebuild(scenario_db)["status"] == "published"
    with scenario_db() as session:
        history = session.scalars(
            select(CompanyProjectMembership).where(
                CompanyProjectMembership.project_id == first_project.id
            )
        ).all()
        assert sorted(row.state for row in history) == ["current", "superseded"]
        page = account_queue(session, search=None, limit=25, offset=0)
        account = next(
            item for item in page["items"] if item["company_identity_id"] == first_identity.id
        )
        assert account["project_count"] == 2
        assert account["need_count"] == 2
        assert account["supporting_evidence_count"] == 2
        assert account["aliases"] == ["Refresh Operator LLC"]
