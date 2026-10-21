from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from importlib import import_module

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.intelligence.buying_chain import buying_chain_view, enrich_buying_chain
from gridlens.intelligence.change_detection import (
    material_state,
    record_material_diff,
    seed_material_state,
)
from gridlens.intelligence.lifecycle_service import refresh_lifecycle_projection
from gridlens.intelligence.project_state import _conflict, current_research_state, project_state
from gridlens.intelligence.research_recommendation import recommend_from_context
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainRun,
    ChangeEvent,
    Evidence,
    Interpretation,
    LifecycleEvent,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    ProjectLifecycle,
    ProjectMaterialState,
    Source,
)
from gridlens.security import token_for
from gridlens.settings import settings

NOW = datetime(2026, 10, 2, tzinfo=UTC)


@pytest.fixture
def db():
    target, application = make_url(settings.test_database_url), make_url(settings.database_url)
    assert target.database.endswith("_test") and target != application
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            Source(
                id="state-test",
                publisher="Synthetic",
                endpoint="https://example.test/source",
                family="news",
                geography="US",
                industries=[],
                retrieval_method="test",
                health={},
            )
        )
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def seed(
    session,
    *,
    lifecycle_abstract: str = "Orion Data Center construction has started in Austin, TX",
):
    observation = Observation(
        source_id="state-test",
        external_id="orion",
        title="Orion Data Center",
        url="https://example.test/source",
        abstract=lifecycle_abstract,
        published_at=date(2026, 9, 20),
        content_hash="accepted-v1",
    )
    session.add(observation)
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        title="Orion Data Center",
        abstract=observation.abstract,
        url=observation.url,
        content_hash="accepted-evidence-v1",
        published_at=observation.published_at,
        observed_at=NOW,
    )
    project = Project(
        source_id="state-test",
        external_id="orion",
        name="Orion Data Center",
        location="Austin, TX",
        identity_key="state-test-orion",
        identity_facts={},
    )
    session.add_all(
        [
            evidence,
            Interpretation(
                observation_id=observation.id,
                content_hash="accepted-v1",
                status="accepted",
                assessment={
                    "decision": "accepted",
                    "semantic_hash": observation.content_hash,
                    "evidence_hash": evidence.content_hash,
                    "project_identity_key": "state-test-orion",
                    "admission_status": "supplemental",
                },
            ),
            project,
        ]
    )
    session.flush()
    return project, observation, evidence


def linked_official_need_evidence(
    session,
    project,
    need,
    *,
    key: str,
    identity_key: str | None = None,
    activity: str | None = None,
    tier: str = "Prospect",
    demand_mw: str = "42 MW",
    start_window: str = "2026 Q4",
    duration: str = "6 months",
    official: bool = True,
):
    source_id = f"need-{key}"
    session.add(
        Source(
            id=source_id,
            publisher="Fixture permit office",
            endpoint=f"https://permits.example/{key}",
            family="construction-permits" if official else "news",
            geography="US",
            industries=[],
            retrieval_method="socrata-permits" if official else "publisher-rss",
            health={},
        )
    )
    session.flush()
    semantic_hash = f"need-hash-{key}"
    evidence_hash = f"need-evidence-{key}"
    observation = Observation(
        source_id=source_id,
        external_id=key,
        title="Orion Data Center construction permit",
        abstract="Orion Data Center construction in Austin, TX.",
        url=f"https://permits.example/{key}",
        published_at=date(2026, 9, 20),
        content_hash=semantic_hash,
    )
    session.add(observation)
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        title=observation.title,
        abstract=observation.abstract,
        url=observation.url,
        content_hash=evidence_hash,
        published_at=observation.published_at,
        observed_at=NOW,
    )
    assessment = {
        "decision": "accepted",
        "semantic_hash": observation.content_hash,
        "evidence_hash": evidence.content_hash,
        "project_identity_key": identity_key or project.identity_key,
        "power_activity": activity or need.activity_key,
        "tier": tier,
        "demand_mw": demand_mw,
        "start_window": start_window,
        "duration": duration,
        "subject": project.name,
        "location": project.location,
    }
    session.add_all(
        [
            evidence,
            Interpretation(
                observation_id=observation.id,
                content_hash=observation.content_hash,
                status="accepted",
                assessment=assessment,
            ),
            NeedObservation(need_id=need.id, observation_id=observation.id),
        ]
    )
    session.flush()
    return (
        evidence,
        observation,
        session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        ),
    )


def test_state_keeps_unproven_fields_unknown_and_rejected_revision_is_not_current(db):
    with db.begin() as session:
        project, observation, evidence = seed(session)
        state = project_state(session, project.id)
        assert state["state"]["identity"]["status"] == "UNKNOWN"
        assert state["state"]["utility_service"]["status"] == "UNKNOWN"
        session.add(
            LifecycleEvent(
                project_id=project.id,
                observation_id=observation.id,
                evidence_id=evidence.id,
                event_type="construction",
                state="construction",
                occurred_on=date(2026, 9, 20),
            )
        )
        session.add(ProjectLifecycle(project_id=project.id, current_state="construction"))
        assert project_state(session, project.id)["state"]["lifecycle"]["status"] == "SUPPORTED"
        interpretation = session.scalar(select(Interpretation))
        interpretation.status = "rejected"
        interpretation.assessment = {
            "decision": "rejected",
            "evidence_hash": evidence.content_hash,
        }
        assert project_state(session, project.id)["state"]["lifecycle"]["status"] == "UNKNOWN"


def test_original_retained_permit_claims_are_version_bound_and_activity_scoped(db):
    from gridlens.domain.project_research import VERSION as RESEARCH_VERSION

    with db.begin() as session:
        project, _, _ = seed(session)
        rows = (
            (
                "fort-worth-development-permits",
                "facility-expansion",
                "Project: Edged Energy Outpost Building 2\n"
                "Work description: 488,628 SF 196MW data center\n"
                "Owner of record: not stated",
                "Work description: 488,628 SF 196MW data center",
            ),
            (
                "boston-building-permits",
                "temporary-power",
                "Permit number: ETS1870328\nDescription: Electrical\n"
                "Comments: Provide temporary electrical work required to support Boss steel "
                "Office trailer 100A 208v 1Ph $5000",
                "Comments: Provide temporary electrical work required to support Boss steel "
                "Office trailer 100A 208v 1Ph $5000",
            ),
        )
        needs = []
        for index, (source_id, activity, abstract, quote) in enumerate(rows):
            session.add(
                Source(
                    id=source_id,
                    publisher="Official permit office",
                    endpoint=f"https://permits.example/{source_id}",
                    family="construction-permits",
                    geography="US",
                    industries=[],
                    retrieval_method="socrata-permits",
                    health={},
                )
            )
            session.flush()
            need = PowerNeed(
                project_id=project.id,
                activity_key=activity,
                tier="Signal",
                rationale="retained permit fixture",
                active=True,
            )
            session.add(need)
            session.flush()
            observation_hash = evidence_hash = f"permit-current-{index}"
            observation = Observation(
                source_id=source_id,
                external_id=f"permit-{index}",
                title="Official permit",
                abstract=abstract,
                url=f"https://permits.example/{source_id}/{index}",
                published_at=date(2026, 10, 1),
                content_hash=observation_hash,
            )
            session.add(observation)
            session.flush()
            evidence = Evidence(
                observation_id=observation.id,
                title=observation.title,
                abstract=abstract,
                url=observation.url,
                content_hash=evidence_hash,
                published_at=observation.published_at,
                event_date=date(2026, 10, 1),
                observed_at=NOW,
            )
            session.add_all(
                [
                    evidence,
                    Interpretation(
                        observation_id=observation.id,
                        evaluator_version=RESEARCH_VERSION,
                        content_hash=observation_hash,
                        status="accepted",
                        assessment={"evidence_hash": evidence_hash},
                    ),
                    NeedObservation(need_id=need.id, observation_id=observation.id),
                ]
            )
            needs.append((need, evidence, quote))
        session.flush()
        state = current_research_state(session, project.id)
        facility, electrical = needs
        facility_claim = state[str(facility[0].id)]["facility_scale_mw"]
        voltage_claim = state[str(electrical[0].id)]["voltage"]
        assert facility_claim["status"] == "SUPPORTED"
        assert facility_claim["value"] == "196"
        assert facility_claim["claims"][0]["quote"] == facility[2]
        assert voltage_claim["status"] == "SUPPORTED"
        assert voltage_claim["value"] == "208 V, 1 phase"
        assert voltage_claim["claims"][0]["quote"] == electrical[2]
        assert state[str(facility[0].id)]["activity_load_mw"]["status"] == "UNKNOWN"
        assert state[str(electrical[0].id)]["activity_load_mw"]["status"] == "UNKNOWN"


def test_need_state_excludes_reassigned_and_supplemental_evidence(db):
    with db.begin() as session:
        project, observation, evidence = seed(session)
        other = Project(
            source_id="state-test",
            external_id="other",
            name="Other Data Center",
            location="Dallas, TX",
            identity_key="state-test-other",
            identity_facts={},
        )
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            required_mw="12 MW",
            supply="Reported constraint",
            active=True,
        )
        session.add_all([other, need])
        session.flush()
        session.add(NeedObservation(need_id=need.id, observation_id=observation.id))
        interpretation = session.scalar(select(Interpretation))
        interpretation.assessment = {
            "decision": "accepted",
            "semantic_hash": observation.content_hash,
            "evidence_hash": evidence.content_hash,
            "project_identity_key": other.identity_key,
            "power_activity": "construction",
            "tier": "Prospect",
            "demand_mw": "12 MW",
            "admission_status": "supplemental",
        }
        assert project_state(session, project.id)["state"]["power_need"] == {
            "value": None,
            "status": "UNKNOWN",
        }


def test_project_identity_site_do_not_borrow_another_need_after_rejection(db):
    with db.begin() as session:
        project, _, _ = seed(session)
        original_need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="original",
            active=True,
        )
        other_need = PowerNeed(
            project_id=project.id,
            activity_key="facility-expansion",
            tier="Prospect",
            rationale="other",
            active=True,
        )
        session.add_all([original_need, other_need])
        session.flush()
        original, _, original_interpretation = linked_official_need_evidence(
            session, project, original_need, key="original-identity"
        )
        other, _, other_interpretation = linked_official_need_evidence(
            session, project, other_need, key="different-identity"
        )
        other_interpretation.assessment = {
            **other_interpretation.assessment,
            "subject": "Another Campus",
            "location": "Dallas, TX",
        }
        original_interpretation.status = "rejected"
        original_interpretation.assessment = {
            "decision": "rejected",
            "evidence_hash": original.content_hash,
        }
        state = project_state(session, project.id)
        assert state["state"]["identity"]["status"] == "UNKNOWN"
        assert state["state"]["site"]["status"] == "UNKNOWN"
        assert str(other.id) in {row["id"] for row in state["evidence"]}
        assert str(original.id) not in {row["id"] for row in state["evidence"]}


def test_project_identity_site_expose_competing_current_claims(db):
    with db.begin() as session:
        project, _, _ = seed(session)
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            active=True,
        )
        session.add(need)
        session.flush()
        original, _, _ = linked_official_need_evidence(
            session, project, need, key="competing-original"
        )
        other, _, interpretation = linked_official_need_evidence(
            session, project, need, key="competing-other"
        )
        interpretation.assessment = {
            **interpretation.assessment,
            "subject": "Another Campus",
            "location": "Dallas, TX",
        }
        state = project_state(session, project.id)["state"]
        for field in ("identity", "site"):
            assert state[field]["status"] == "CONFLICT"
            assert {claim["evidence"]["id"] for claim in state[field]["claims"]} == {
                str(original.id),
                str(other.id),
            }


def test_project_identity_site_use_only_field_claims_and_current_binding(db):
    with db.begin() as session:
        project, _, _ = seed(session)
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            active=True,
        )
        session.add(need)
        session.flush()
        named, _, _ = linked_official_need_evidence(session, project, need, key="named-site")
        blank, _, blank_interpretation = linked_official_need_evidence(
            session, project, need, key="blank-identity"
        )
        blank_interpretation.assessment = {
            **blank_interpretation.assessment,
            "subject": "",
            "location": "",
        }
        wrong, _, wrong_interpretation = linked_official_need_evidence(
            session, project, need, key="wrong-binding"
        )
        wrong_interpretation.assessment = {
            **wrong_interpretation.assessment,
            "project_identity_key": "another-project",
        }
        nonadmitted, _, _ = linked_official_need_evidence(
            session, project, need, key="nonadmitted-identity", official=False
        )
        state = project_state(session, project.id)["state"]
        for field in ("identity", "site"):
            assert state[field]["status"] == "SUPPORTED"
            assert [row["id"] for row in state[field]["evidence"]] == [str(named.id)]
        assert {row["id"] for row in project_state(session, project.id)["evidence"]} == {
            str(named.id),
            str(blank.id),
        }
        assert {str(wrong.id), str(nonadmitted.id)}.isdisjoint(
            {row["id"] for row in project_state(session, project.id)["evidence"]}
        )


def test_project_identity_site_accept_existing_normalization_only(db):
    with db.begin() as session:
        project, _, _ = seed(session)
        project.location = "100 Main Street, Austin, TX"
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            active=True,
        )
        session.add(need)
        session.flush()
        evidence, _, interpretation = linked_official_need_evidence(
            session, project, need, key="normalized-identity-site"
        )
        interpretation.assessment = {
            **interpretation.assessment,
            "subject": "  ORION data-center  ",
            "location": "100 Main Street Austin TX",
        }
        state = project_state(session, project.id)["state"]
        for field in ("identity", "site"):
            assert state[field]["status"] == "SUPPORTED"
            assert [row["id"] for row in state[field]["evidence"]] == [str(evidence.id)]


def test_project_site_same_street_different_city_cannot_attest_stored_site(db):
    with db.begin() as session:
        project, _, _ = seed(session)
        project.location = "100 Main Street Austin TX"
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            active=True,
        )
        session.add(need)
        session.flush()
        _, _, interpretation = linked_official_need_evidence(
            session, project, need, key="wrong-city-site"
        )
        interpretation.assessment = {
            **interpretation.assessment,
            "location": "100 Main Street Dallas TX",
        }
        assert project_state(session, project.id)["state"]["site"] == {
            "value": None,
            "status": "UNKNOWN",
        }


def test_project_site_same_street_different_cities_are_conflicting_claims(db):
    with db.begin() as session:
        project, _, _ = seed(session)
        project.location = "100 Main Street Austin TX"
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            active=True,
        )
        session.add(need)
        session.flush()
        austin, _, _ = linked_official_need_evidence(
            session, project, need, key="austin-same-street"
        )
        dallas, _, interpretation = linked_official_need_evidence(
            session, project, need, key="dallas-same-street"
        )
        interpretation.assessment = {
            **interpretation.assessment,
            "location": "100 Main Street Dallas TX",
        }
        site = project_state(session, project.id)["state"]["site"]
        assert site["status"] == "CONFLICT"
        assert {claim["evidence"]["id"] for claim in site["claims"]} == {
            str(austin.id),
            str(dallas.id),
        }


@pytest.mark.parametrize("two_claims", [False, True])
def test_project_site_equivalent_full_address_spellings_retain_support(db, two_claims):
    with db.begin() as session:
        project, _, _ = seed(session)
        project.location = "100 Main Street, Austin, Texas"
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            active=True,
        )
        session.add(need)
        session.flush()
        evidence_ids = []
        if two_claims:
            full, _, _ = linked_official_need_evidence(
                session, project, need, key="full-address-spelling"
            )
            evidence_ids.append(str(full.id))
        short, _, interpretation = linked_official_need_evidence(
            session, project, need, key="short-address-spelling"
        )
        interpretation.assessment = {
            **interpretation.assessment,
            "location": "100 Main St, Austin, TX",
        }
        evidence_ids.append(str(short.id))
        site = project_state(session, project.id)["state"]["site"]
        assert site["status"] == "SUPPORTED"
        assert site["value"] == "100 Main Street, Austin, Texas"
        assert {row["id"] for row in site["evidence"]} == set(evidence_ids)


@pytest.mark.parametrize(
    "wrong_site",
    [
        "100 Main St, Dallas, TX",
        "100 Main St, Austin, Oklahoma",
        "100 Main St Unit 2, Austin, TX",
        "101 Main St, Austin, TX",
        "100 Main St, Court, TX",
    ],
)
def test_project_site_address_key_keeps_city_state_unit_and_number(db, wrong_site):
    with db.begin() as session:
        project, _, _ = seed(session)
        project.location = "100 Main Street, Austin, Texas"
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            active=True,
        )
        session.add(need)
        session.flush()
        _, _, interpretation = linked_official_need_evidence(
            session, project, need, key="wrong-address-component"
        )
        interpretation.assessment = {**interpretation.assessment, "location": wrong_site}
        assert project_state(session, project.id)["state"]["site"]["status"] == "UNKNOWN"


@pytest.mark.parametrize(
    "wrong_site",
    [
        "100 Main St, Dallas, TX",
        "100 Main St, Austin, Oklahoma",
        "100 Main St Unit 2, Austin, TX",
        "101 Main St, Austin, TX",
    ],
)
def test_project_site_different_full_address_claims_remain_conflict(db, wrong_site):
    with db.begin() as session:
        project, _, _ = seed(session)
        project.location = "100 Main Street, Austin, Texas"
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            active=True,
        )
        session.add(need)
        session.flush()
        valid, _, _ = linked_official_need_evidence(
            session, project, need, key="valid-full-address"
        )
        wrong, _, interpretation = linked_official_need_evidence(
            session, project, need, key="different-full-address"
        )
        interpretation.assessment = {**interpretation.assessment, "location": wrong_site}
        site = project_state(session, project.id)["state"]["site"]
        assert site["status"] == "CONFLICT"
        assert {claim["evidence"]["id"] for claim in site["claims"]} == {
            str(valid.id),
            str(wrong.id),
        }


def test_project_site_street_name_suffix_word_is_not_rewritten_as_city(db):
    with db.begin() as session:
        project, _, _ = seed(session)
        project.location = "100 Main Street Court TX"
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            active=True,
        )
        session.add(need)
        session.flush()
        _, _, interpretation = linked_official_need_evidence(
            session, project, need, key="city-suffix-word"
        )
        interpretation.assessment = {**interpretation.assessment, "location": "100 Main St Ct TX"}
        assert project_state(session, project.id)["state"]["site"]["status"] == "UNKNOWN"


@pytest.mark.parametrize(
    ("stored", "claimed"),
    [
        ("100 Main Street, Austin, Texas 78701", "100 Main St, Austin, TX 78701"),
        ("100 Main Street, Austin, Texas 78701-1234", "100 Main St, Austin, TX 78701-1234"),
        ("100 Main Street, Austin, Texas 78701-1234", "100 Main St, Austin, TX 78701 1234"),
        ("100 Main Street, Austin, Texas 787011234", "100 Main St, Austin, TX 787011234"),
        ("100 Main Street, Austin, Texas 787011234", "100 Main St, Austin, TX 78701-1234"),
        ("100 Main Street, Austin, Texas 78701-1234", "100 Main St, Austin, TX 787011234"),
    ],
)
@pytest.mark.parametrize("two_claims", [False, True])
def test_project_site_zip_state_variants_preserve_current_support(db, stored, claimed, two_claims):
    with db.begin() as session:
        project, _, _ = seed(session)
        project.location = stored
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            active=True,
        )
        session.add(need)
        session.flush()
        evidence_ids = []
        if two_claims:
            original, _, _ = linked_official_need_evidence(
                session, project, need, key="zip-original"
            )
            evidence_ids.append(str(original.id))
        variant, _, interpretation = linked_official_need_evidence(
            session, project, need, key="zip-variant"
        )
        interpretation.assessment = {**interpretation.assessment, "location": claimed}
        evidence_ids.append(str(variant.id))
        site = project_state(session, project.id)["state"]["site"]
        assert site["status"] == "SUPPORTED"
        assert site["value"] == stored
        assert {row["id"] for row in site["evidence"]} == set(evidence_ids)


@pytest.mark.parametrize(
    "wrong_site",
    [
        "100 Main St, Austin, TX 78702",
        "100 Main St, Austin, TX 78701-1235",
        "100 Main St, Austin, TX 78701",
        "100 Main St, Austin, TX",
        "100 Main St, Dallas, TX 78701-1234",
        "100 Main St, Austin, OK 78701-1234",
        "100 Main St Unit 2, Austin, TX 78701-1234",
    ],
)
@pytest.mark.parametrize("two_claims", [False, True])
def test_project_site_zip_key_retains_zip_city_state_and_unit(db, wrong_site, two_claims):
    with db.begin() as session:
        project, _, _ = seed(session)
        project.location = "100 Main Street, Austin, Texas 78701-1234"
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            active=True,
        )
        session.add(need)
        session.flush()
        original_id = None
        if two_claims:
            original, _, _ = linked_official_need_evidence(
                session, project, need, key="zip-control-original"
            )
            original_id = str(original.id)
        wrong, _, interpretation = linked_official_need_evidence(
            session, project, need, key="zip-control-wrong"
        )
        interpretation.assessment = {**interpretation.assessment, "location": wrong_site}
        site = project_state(session, project.id)["state"]["site"]
        if two_claims:
            assert site["status"] == "CONFLICT"
            assert {claim["evidence"]["id"] for claim in site["claims"]} == {
                original_id,
                str(wrong.id),
            }
        else:
            assert site == {"value": None, "status": "UNKNOWN"}


@pytest.mark.parametrize(
    "wrong_site",
    [
        "100 Main St, Austin, TX 787011235",
        "100 Main St, Austin, TX 787021234",
        "100 Main St, Dallas, TX 787011234",
        "100 Main St, Austin, OK 787011234",
        "100 Main St Unit 2, Austin, TX 787011234",
        "101 Main St, Austin, TX 787011234",
    ],
)
@pytest.mark.parametrize("two_claims", [False, True])
def test_project_site_compact_zip_retains_all_place_and_postal_digits(db, wrong_site, two_claims):
    with db.begin() as session:
        project, _, _ = seed(session)
        project.location = "100 Main Street, Austin, Texas 787011234"
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            active=True,
        )
        session.add(need)
        session.flush()
        original_id = None
        if two_claims:
            original, _, _ = linked_official_need_evidence(
                session, project, need, key="compact-zip-original"
            )
            original_id = str(original.id)
        wrong, _, interpretation = linked_official_need_evidence(
            session, project, need, key="compact-zip-wrong"
        )
        interpretation.assessment = {**interpretation.assessment, "location": wrong_site}
        site = project_state(session, project.id)["state"]["site"]
        if two_claims:
            assert site["status"] == "CONFLICT"
            assert {claim["evidence"]["id"] for claim in site["claims"]} == {
                original_id,
                str(wrong.id),
            }
        else:
            assert site == {"value": None, "status": "UNKNOWN"}


@pytest.mark.parametrize("variation", ["identity", "activity", "admission"])
def test_need_state_excludes_each_ineligible_dimension_without_losing_valid_support(db, variation):
    with db.begin() as session:
        project, _, _ = seed(session)
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            required_mw="42 MW",
            start_window="2026 Q4",
            duration="6 months",
            supply="Reported constraint",
            active=True,
        )
        session.add(need)
        session.flush()
        valid, _, _ = linked_official_need_evidence(
            session, project, need, key=f"valid-{variation}"
        )
        kwargs = {
            "identity_key": "another-project" if variation == "identity" else None,
            "activity": "commissioning" if variation == "activity" else None,
            "official": variation != "admission",
            "tier": "Signal",
            "demand_mw": "58 MW",
            "start_window": "2027 Q1",
            "duration": "12 months",
        }
        excluded, _, _ = linked_official_need_evidence(
            session, project, need, key=f"excluded-{variation}", **kwargs
        )
        fields = project_state(session, project.id)["state"]["power_need"]["value"][0]
        for field in ("activity", "tier", "mw", "timing", "duration", "supply"):
            assert fields[field]["status"] == "SUPPORTED"
            assert [row["id"] for row in fields[field]["evidence"]] == [str(valid.id)]
        assert str(excluded.id) not in {
            row["id"] for row in project_state(session, project.id)["evidence"]
        }


def test_need_state_uses_exact_field_evidence_and_preserves_refresh_fallback(db):
    with db.begin() as session:
        project, _, _ = seed(session)
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            required_mw="42 MW",
            start_window="2026 Q4",
            duration="6 months",
            supply="Reported constraint",
            active=True,
        )
        session.add(need)
        session.flush()
        matching, observation, interpretation = linked_official_need_evidence(
            session, project, need, key="matching"
        )
        other, _, _ = linked_official_need_evidence(
            session,
            project,
            need,
            key="other-fields",
            tier="Signal",
            demand_mw="58 MW",
            start_window="2027 Q1",
            duration="12 months",
        )
        observation.content_hash = "failed-refresh-current-hash"
        interpretation.status = "failed"
        state = project_state(session, project.id)
        fields = state["state"]["power_need"]["value"][0]
        assert {row["id"] for row in fields["activity"]["evidence"]} == {
            str(matching.id),
            str(other.id),
        }
        for field, values in (
            ("tier", {"Prospect", "Signal"}),
            ("mw", {"42 MW", "58 MW"}),
            ("timing", {"2026 Q4", "2027 Q1"}),
            ("duration", {"6 months", "12 months"}),
        ):
            assert fields[field]["status"] == "CONFLICT"
            assert {claim["value"] for claim in fields[field]["claims"]} == values
            assert {claim["evidence"]["id"] for claim in fields[field]["claims"]} == {
                str(matching.id),
                str(other.id),
            }
        assert [row["id"] for row in fields["supply"]["evidence"]] == [str(matching.id)]
        assert {row["id"] for row in state["evidence"]} == {str(matching.id), str(other.id)}
        assert len(state["evidence"]) == 2

        interpretation.status = "pending"
        pending = project_state(session, project.id)["state"]["power_need"]["value"][0]
        assert pending["mw"]["status"] == "CONFLICT"

        need.required_mw = "99 MW"
        need.start_window = "2030 Q1"
        need.duration = "24 months"
        unsupported = project_state(session, project.id)["state"]["power_need"]["value"][0]
        for field in ("mw", "timing", "duration"):
            assert unsupported[field]["status"] == "CONFLICT"


def test_need_state_single_nonmatching_claim_cannot_support_mutable_projection(db):
    with db.begin() as session:
        project, _, _ = seed(session)
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            required_mw="99 MW",
            start_window="2030 Q1",
            duration="24 months",
            supply="Reported constraint",
            active=True,
        )
        session.add(need)
        session.flush()
        linked_official_need_evidence(session, project, need, key="lone-old")
        fields = project_state(session, project.id)["state"]["power_need"]["value"][0]
        for field in ("mw", "timing", "duration"):
            assert fields[field] == {"value": None, "status": "UNKNOWN"}
        assert fields["tier"]["status"] == "SUPPORTED"


def test_equivalent_numeric_claims_share_support_without_false_conflict(db):
    with db.begin() as session:
        project, _, _ = seed(session)
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            active=True,
        )
        session.add(need)
        session.flush()
        first, _, _ = linked_official_need_evidence(session, project, need, key="numeric-first")
        second, _, _ = linked_official_need_evidence(session, project, need, key="numeric-second")
        projected = _conflict([(42, first), (42.0, second)])
        assert projected["status"] == "SUPPORTED"
        assert projected["value"] == 42.0
        assert {row["id"] for row in projected["evidence"]} == {str(first.id), str(second.id)}


def test_equivalent_mw_spellings_are_supported_without_material_churn(db):
    with db.begin() as session:
        project, _, unrelated = seed(session)
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            required_mw="12MW",
            supply="Reported constraint",
            active=True,
        )
        session.add(need)
        session.flush()
        first, _, _ = linked_official_need_evidence(
            session, project, need, key="mw-first", demand_mw="12MW"
        )
        need.required_mw = "12 megawatts"
        sole_mw = project_state(session, project.id)["state"]["power_need"]["value"][0]["mw"]
        assert sole_mw["status"] == "SUPPORTED"
        assert [row["id"] for row in sole_mw["evidence"]] == [str(first.id)]
        need.required_mw = "12MW"
        baseline = seed_material_state(session, project)
        second, _, _ = linked_official_need_evidence(
            session, project, need, key="mw-spelling", demand_mw="12 megawatts"
        )
        mw = project_state(session, project.id)["state"]["power_need"]["value"][0]["mw"]
        assert mw["status"] == "SUPPORTED"
        assert {row["id"] for row in mw["evidence"]} == {str(first.id), str(second.id)}
        assert record_material_diff(session, project, second, baseline) == []
        need.required_mw = "12mw"
        assert record_material_diff(session, project, second, baseline) == []
        assert baseline.state == material_state(session, project.id)

        third, _, _ = linked_official_need_evidence(
            session, project, need, key="mw-real-change", demand_mw="13 MW"
        )
        mw = project_state(session, project.id)["state"]["power_need"]["value"][0]["mw"]
        assert mw["status"] == "CONFLICT"
        assert {claim["value"] for claim in mw["claims"]} == {"12MW", "12 megawatts", "13 MW"}
        changed = record_material_diff(session, project, third, baseline)
        assert len(changed) == 1 and changed[0].evidence_id == third.id
        assert changed[0].new_state["value"][0]["conflicts"]["mw"] == ["12 MW", "13 MW"]
        assert record_material_diff(session, project, unrelated, baseline) == []


def test_mw_range_and_qualifier_do_not_collapse_to_exact_claim(db):
    with db.begin() as session:
        project, _, _ = seed(session)
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            required_mw="up to 12 MW",
            supply="Reported constraint",
            active=True,
        )
        session.add(need)
        session.flush()
        linked_official_need_evidence(
            session, project, need, key="mw-upper-bound", demand_mw="up to 12 MW"
        )
        linked_official_need_evidence(session, project, need, key="mw-exact", demand_mw="12 MW")
        fields = project_state(session, project.id)["state"]["power_need"]["value"][0]
        assert fields["mw"]["status"] == "CONFLICT"
        assert material_state(session, project.id)["power_need"][0]["conflicts"]["mw"] == [
            "12 MW",
            "up to 12 MW",
        ]


@pytest.mark.parametrize("selected_changes", [False, True])
def test_need_conflict_is_material_with_causal_evidence_and_quiet_replay(db, selected_changes):
    with db.begin() as session:
        project, _, unrelated = seed(session)
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            required_mw="42 MW",
            start_window="2026 Q4",
            duration="6 months",
            supply="Reported constraint",
            active=True,
        )
        session.add(need)
        session.flush()
        linked_official_need_evidence(session, project, need, key=f"baseline-{selected_changes}")
        baseline = seed_material_state(session, project)
        second, _, interpretation = linked_official_need_evidence(
            session,
            project,
            need,
            key=f"conflict-{selected_changes}",
            tier="Signal",
            demand_mw="58 MW",
            start_window="2027 Q1",
            duration="12 months",
        )
        if selected_changes:
            need.required_mw = "58 MW"
            need.tier = "Signal"
            need.start_window = "2027 Q1"
            need.duration = "12 months"
        current_fields = project_state(session, project.id)["state"]["power_need"]["value"][0]
        assert all(
            current_fields[field]["status"] == "CONFLICT"
            for field in ("tier", "mw", "timing", "duration")
        )
        changes = record_material_diff(session, project, second, baseline)
        assert len(changes) == 1 and changes[0].field_name == "power_need"
        assert changes[0].evidence_id == second.id
        after = changes[0].new_state["value"][0]
        assert after["conflicts"] == {
            "tier": ["Prospect", "Signal"],
            "mw": ["42 MW", "58 MW"],
            "timing": ["2026 Q4", "2027 Q1"],
            "duration": ["12 months", "6 months"],
        }
        assert record_material_diff(session, project, second, baseline) == []
        assert record_material_diff(session, project, unrelated, baseline) == []

        interpretation.status = "rejected"
        interpretation.assessment = {"decision": "rejected", "evidence_hash": second.content_hash}
        resolved = record_material_diff(session, project, second, baseline)
        assert len(resolved) == 1 and resolved[0].field_name == "power_need"
        assert resolved[0].evidence_id == second.id
        assert "conflicts" not in resolved[0].new_state["value"][0]
        assert record_material_diff(session, project, unrelated, baseline) == []

        interpretation.status = "accepted"
        interpretation.assessment = {
            "decision": "accepted",
            "evidence_hash": second.content_hash,
            "project_identity_key": project.identity_key,
            "power_activity": need.activity_key,
            "tier": "Signal",
            "demand_mw": "58 MW",
            "start_window": "2027 Q1",
            "duration": "12 months",
            "subject": project.name,
            "location": project.location,
        }
        renewed = record_material_diff(session, project, second, baseline)
        assert len(renewed) == 1 and renewed[0].field_name == "power_need"
        assert renewed[0].evidence_id == second.id
        assert renewed[0].new_state == changes[0].new_state


def test_preaction_snapshot_normalizes_old_conflict_without_unrelated_same_need_event(db):
    with db.begin() as session:
        project, _, unrelated = seed(session)
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            rationale="fixture",
            required_mw="42 MW",
            supply="Reported constraint",
            active=True,
        )
        session.add(need)
        session.flush()
        linked_official_need_evidence(session, project, need, key="backfill-first")
        baseline = seed_material_state(session, project)
        linked_official_need_evidence(
            session, project, need, key="backfill-second", demand_mw="58 MW"
        )
        assert (
            project_state(session, project.id)["state"]["power_need"]["value"][0]["mw"]["status"]
            == "CONFLICT"
        )
        # Simulate an old persisted snapshot created before conflict metadata
        # existed, then begin a later unrelated same-need citation action.
        assert "conflicts" not in baseline.state["power_need"][0]
        baseline = seed_material_state(session, project)
        assert baseline.state["power_need"][0]["conflicts"]["mw"] == ["42 MW", "58 MW"]
        agreeing, _, _ = linked_official_need_evidence(
            session, project, need, key="backfill-agreeing"
        )
        assert record_material_diff(session, project, agreeing, baseline) == []
        assert record_material_diff(session, project, unrelated, baseline) == []
        assert baseline.state == material_state(session, project.id)
        assert session.scalar(select(ChangeEvent).where(ChangeEvent.material.is_(True))) is None


def test_project_change_history_openapi_has_typed_array_response():
    api = import_module("gridlens.api.app")
    response = api.app.openapi()["paths"]["/api/projects/{project_id}/changes"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    assert response["type"] == "array"
    item_ref = response["items"]["$ref"]
    item = api.app.openapi()["components"]["schemas"][item_ref.rsplit("/", 1)[-1]]
    assert set(item["required"]) == {
        "kind",
        "field",
        "prior",
        "new",
        "evidence_id",
        "buying_chain_evidence_id",
        "sources",
        "source_date",
        "detected_at",
    }


def test_rejected_interpretation_with_supported_withdrawal_remains_current(db):
    with db.begin() as session:
        project, observation, evidence = seed(session)
        session.add(
            LifecycleEvent(
                project_id=project.id,
                observation_id=observation.id,
                evidence_id=evidence.id,
                event_type="planning_application_withdrawn",
                state="planning_application_withdrawn",
            )
        )
        session.add(
            ProjectLifecycle(project_id=project.id, current_state="planning_application_withdrawn")
        )
        interpretation = session.scalar(select(Interpretation))
        assert interpretation is not None
        interpretation.status = "rejected"
        interpretation.assessment = {
            "decision": "rejected",
            "semantic_hash": observation.content_hash,
            "evidence_hash": evidence.content_hash,
            "withdrawal_supported": True,
            "project_identity_key": project.identity_key,
        }
        refresh_lifecycle_projection(session, project)
        projection = session.get(ProjectLifecycle, project.id)
        assert projection is not None
        assert projection.current_state == "planning_application_withdrawn"
        assert (
            project_state(session, project.id)["state"]["lifecycle"]["value"]["state"]
            == "planning_application_withdrawn"
        )
        assert material_state(session, project.id)["phase"] == "planning_application_withdrawn"


def test_failed_refresh_keeps_previous_accepted_lifecycle_evidence(db):
    with db.begin() as session:
        project, observation, evidence = seed(session)
        project.asset_type = "data_center"
        session.add(
            LifecycleEvent(
                project_id=project.id,
                observation_id=observation.id,
                evidence_id=evidence.id,
                event_type="construction",
                state="construction",
            )
        )
        session.add(ProjectLifecycle(project_id=project.id, current_state="construction"))
        interpretation = session.scalar(select(Interpretation))
        assert interpretation is not None
        interpretation.status = "failed"
        refresh_lifecycle_projection(session, project)
        assert session.get(ProjectLifecycle, project.id).current_state == "construction"
        assert project_state(session, project.id)["state"]["lifecycle"]["status"] == "SUPPORTED"
        assert material_state(session, project.id)["phase"] == "construction"


def test_actual_prior_new_transitions_revert_and_authenticated_reads(db, monkeypatch):
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", db)
    unresolved = ["buyer remains UNKNOWN"]
    monkeypatch.setattr(
        "gridlens.intelligence.project_state.buying_chain_view",
        lambda *_args: {"candidates": [], "unresolved": unresolved},
    )
    with db.begin() as session:
        project, observation, evidence = seed(session)
        baseline = seed_material_state(session, project)
        session.add(ProjectLifecycle(project_id=project.id, current_state="permitted"))
        session.flush()
        record_material_diff(session, project, evidence, baseline)
        lifecycle = session.get(ProjectLifecycle, project.id)
        lifecycle.current_state = "construction"
        record_material_diff(session, project, evidence, baseline)
        lifecycle.current_state = "permitted"
        record_material_diff(session, project, evidence, baseline)
        lifecycle.current_state = "construction"
        record_material_diff(session, project, evidence, baseline)
        phase_events = session.scalars(
            select(ChangeEvent).where(ChangeEvent.field_name == "phase").order_by(ChangeEvent.id)
        ).all()
        assert [(event.prior_state, event.new_state) for event in phase_events] == [
            ({"value": None}, {"value": "permitted"}),
            ({"value": "permitted"}, {"value": "construction"}),
            ({"value": "construction"}, {"value": "permitted"}),
            ({"value": "permitted"}, {"value": "construction"}),
        ]
    client = TestClient(api.app)
    path = f"/api/projects/{project.id}/state"
    assert client.get(path).status_code == 401
    client.cookies.set(
        "gridlens_session", token_for(int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()))
    )
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()["unresolved"] == unresolved
    changes = client.get(f"/api/projects/{project.id}/changes")
    assert changes.status_code == 200 and len(changes.json()) == 4


def test_accepted_utility_revision_replaces_current_date_but_keeps_history(db):
    with db.begin() as session:
        project, observation, evidence = seed(
            session,
            lifecycle_abstract=("Orion Data Center utility service was energized in Austin, TX"),
        )
        session.add(ProjectLifecycle(project_id=project.id, current_state="utility_energization"))
        session.add(
            LifecycleEvent(
                project_id=project.id,
                observation_id=observation.id,
                evidence_id=evidence.id,
                event_type="utility_service",
                state="utility_energization",
                occurred_on=date(2027, 1, 1),
            )
        )
        session.flush()
        baseline = seed_material_state(session, project)
        replacement = Evidence(
            observation_id=observation.id,
            title="Orion revision",
            abstract="Orion Data Center utility service was energized in Austin, TX",
            url=observation.url,
            content_hash="accepted-evidence-v2",
            published_at=date(2026, 9, 21),
            observed_at=NOW + timedelta(minutes=1),
        )
        session.add(replacement)
        observation.content_hash = "accepted-semantic-v2"
        interpretation = session.scalar(select(Interpretation))
        interpretation.content_hash = observation.content_hash
        interpretation.assessment = {
            "decision": "accepted",
            "semantic_hash": observation.content_hash,
            "evidence_hash": replacement.content_hash,
            "project_identity_key": project.identity_key,
        }
        session.add(
            LifecycleEvent(
                project_id=project.id,
                observation_id=observation.id,
                evidence_id=replacement.id,
                event_type="utility_service",
                state="utility_energization",
                occurred_on=date(2027, 7, 1),
            )
        )
        session.flush()
        record_material_diff(session, project, replacement, baseline)
        current = project_state(session, project.id)
        assert current["state"]["utility_service"]["value"] == date(2027, 7, 1)
        assert len(current["lifecycle_events"]) == 2
        utility_event = session.scalar(
            select(ChangeEvent).where(ChangeEvent.field_name == "utility_timing")
        )
        assert utility_event.prior_state == {"value": ["2027-01-01"]}
        assert utility_event.new_state == {"value": ["2027-07-01"]}


@pytest.mark.parametrize(
    ("removed_assessment_key", "nested_field"),
    [
        ("demand_mw", "mw"),
        ("start_window", "timing"),
        ("duration", "duration"),
        ("tier", "supply"),
    ],
)
def test_research_recommendation_sees_nested_missing_current_need_fact(
    db, removed_assessment_key, nested_field
):
    judgment = {"material_change": "YES", "relevant": "YES", "power_relevance": "HIGH"}
    with db.begin() as session:
        project, observation, lifecycle_evidence = seed(
            session,
            lifecycle_abstract=("Orion Data Center utility service was energized in Austin, TX"),
        )
        session.add(ProjectLifecycle(project_id=project.id, current_state="utility_energization"))
        session.add(
            LifecycleEvent(
                project_id=project.id,
                observation_id=observation.id,
                evidence_id=lifecycle_evidence.id,
                event_type="utility_service",
                state="utility_energization",
                occurred_on=date(2027, 1, 1),
            )
        )
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            required_mw="42 MW",
            start_window="2026 Q4",
            duration="6 months",
            supply="Reported constraint",
            rationale="fixture",
            active=True,
        )
        session.add(need)
        session.flush()
        _, _, interpretation = linked_official_need_evidence(
            session, project, need, key=f"advisory-{nested_field}"
        )
        complete_assessment = dict(interpretation.assessment)
        interpretation.assessment = {
            key: value
            for key, value in complete_assessment.items()
            if key != removed_assessment_key
        }
        state = project_state(session, project.id)
        statuses = {
            field: state["state"][field]["status"]
            for field in ("power_need", "utility_service", "lifecycle", "activity")
        }
        assert all(status == "SUPPORTED" for status in statuses.values()), statuses
        assert state["state"]["power_need"]["value"][0][nested_field]["status"] == "UNKNOWN"
        assert recommend_from_context(judgment, state) is True

        interpretation.assessment = complete_assessment
        complete = project_state(session, project.id)
        assert all(
            item["status"] == "SUPPORTED"
            for item in complete["state"]["power_need"]["value"][0].values()
        )
        assert recommend_from_context(judgment, complete) is False


def test_research_recommendation_sees_nested_current_need_conflict(db):
    judgment = {"material_change": "YES", "relevant": "YES", "power_relevance": "HIGH"}
    with db.begin() as session:
        project, observation, lifecycle_evidence = seed(
            session,
            lifecycle_abstract=("Orion Data Center utility service was energized in Austin, TX"),
        )
        session.add(ProjectLifecycle(project_id=project.id, current_state="utility_energization"))
        session.add(
            LifecycleEvent(
                project_id=project.id,
                observation_id=observation.id,
                evidence_id=lifecycle_evidence.id,
                event_type="utility_service",
                state="utility_energization",
                occurred_on=date(2027, 1, 1),
            )
        )
        need = PowerNeed(
            project_id=project.id,
            activity_key="construction",
            tier="Prospect",
            required_mw="42 MW",
            start_window="2026 Q4",
            duration="6 months",
            supply="Reported constraint",
            rationale="fixture",
            active=True,
        )
        session.add(need)
        session.flush()
        linked_official_need_evidence(session, project, need, key="advisory-conflict-a")
        linked_official_need_evidence(
            session, project, need, key="advisory-conflict-b", demand_mw="43 MW"
        )
        state = project_state(session, project.id)
        assert state["state"]["power_need"]["status"] == "SUPPORTED"
        assert state["state"]["power_need"]["value"][0]["mw"]["status"] == "CONFLICT"
        assert recommend_from_context(judgment, state) is True


def test_accepted_buying_chain_contractor_change_is_material_and_replay_is_quiet(db, monkeypatch):
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", db)
    with db.begin() as session:
        project, _, _ = seed(session)

        def contractor(role: str, observed: datetime) -> PublicDocument:
            return PublicDocument(
                "https://external.example/acme",
                "Orion Data Center",
                f"Acme is the {role} for Orion Data Center in Austin, TX.",
                date(2026, 9, 20),
                observed,
            )

        enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda _: contractor("general contractor", NOW),
            now=NOW,
        )
        prior_events = session.scalars(select(ChangeEvent)).all()
        assert {event.field_name for event in prior_events} >= {"contractor", "buyer"}
        prior_ids = {event.id for event in prior_events}

        electrical = contractor("electrical contractor", NOW + timedelta(minutes=1))
        enrich_buying_chain(
            session, project.id, fetcher=lambda _: electrical, now=NOW + timedelta(minutes=1)
        )
        changed_events = session.scalars(
            select(ChangeEvent)
            .where(ChangeEvent.field_name.in_(("contractor", "buyer")))
            .order_by(ChangeEvent.id)
        ).all()
        new_events = [event for event in changed_events if event.id not in prior_ids]
        assert {event.field_name for event in new_events} >= {"contractor", "buyer"}
        for event in new_events:
            support = session.get(BuyingChainEvidence, event.buying_chain_evidence_id)
            assert event.evidence_id is None
            assert support is not None and support.url == electrical.url
            assert "electrical contractor" in support.excerpt

        event_count = len(changed_events)
        enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda _: contractor("electrical contractor", NOW + timedelta(minutes=1)),
            now=NOW + timedelta(minutes=1),
        )
        assert (
            len(
                session.scalars(
                    select(ChangeEvent).where(ChangeEvent.field_name.in_(("contractor", "buyer")))
                ).all()
            )
            == event_count
        )
        expected_support = {
            event.field_name: str(event.buying_chain_evidence_id) for event in new_events
        }

    client = TestClient(api.app)
    client.cookies.set(
        "gridlens_session", token_for(int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()))
    )
    response = client.get(f"/api/projects/{project.id}/changes")
    assert response.status_code == 200
    api_rows = response.json()
    for field, support_id in expected_support.items():
        latest = next(row for row in api_rows if row["field"] == field)
        assert latest["evidence_id"] is None
        assert latest["buying_chain_evidence_id"] == support_id


def test_buying_chain_multidocument_delta_retains_all_causal_sources(db, monkeypatch):
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", db)
    urls = (
        "https://external.example/acme",
        "https://external.example/buildco",
        "https://external.example/wireco",
    )
    unrelated_url = "https://external.example/unrelated"
    texts = {
        urls[0]: "Acme is the general contractor for Orion Data Center in Austin, TX.",
        urls[1]: "BuildCo is the electrical contractor for Orion Data Center in Austin, TX.",
        urls[2]: "Orion Data Center construction in Austin, TX.",
    }

    def fetch(url: str) -> PublicDocument:
        return PublicDocument(
            url,
            "Orion Data Center",
            texts.get(url, "Orion Data Center construction in Austin, TX."),
            date(2026, 9, 20),
            NOW,
        )

    with db.begin() as session:
        project, _, _ = seed(session)
        enrich_buying_chain(
            session, project.id, source_urls=[*urls[:2], unrelated_url], fetcher=fetch, now=NOW
        )
        additions = session.scalars(
            select(ChangeEvent).where(ChangeEvent.field_name == "contractor")
        ).all()
        assert len(additions) == 1
        added_sources = session.scalars(
            select(BuyingChainEvidence).where(
                BuyingChainEvidence.project_id == project.id,
                BuyingChainEvidence.url.in_(urls[:2]),
            )
        ).all()
        assert {str(row.id) for row in added_sources} == set(
            additions[0].new_state["buying_chain_evidence_ids"]
        )
        assert len(added_sources) == 2
        assert additions[0].evidence_id is None

        # In one pass Acme withdraws, WireCo is independently added, and
        # unchanged BuildCo must not be mislabeled as a cause.
        texts[urls[0]] = "Orion Data Center construction in Austin, TX."
        texts[urls[2]] = "WireCo is the general contractor for Orion Data Center in Austin, TX."
        enrich_buying_chain(
            session,
            project.id,
            source_urls=[urls[2]],
            fetcher=fetch,
            now=NOW + timedelta(minutes=1),
        )
        mixed_events = session.scalars(
            select(ChangeEvent).where(ChangeEvent.field_name == "contractor")
        ).all()
        assert len(mixed_events) == 2
        mixed = next(event for event in mixed_events if event.id != additions[0].id)
        mixed_sources = session.scalars(
            select(BuyingChainEvidence).where(
                BuyingChainEvidence.project_id == project.id,
                BuyingChainEvidence.url.in_((urls[0], urls[2])),
                BuyingChainEvidence.id.not_in([row.id for row in added_sources]),
            )
        ).all()
        assert {str(row.id) for row in mixed_sources} == set(
            mixed.new_state["buying_chain_evidence_ids"]
        )
        assert len(mixed_sources) == 2
        assert mixed.evidence_id is None

        # Two further checked withdrawals must cite both fresh versions.
        texts[urls[1]] = "Orion Data Center construction in Austin, TX."
        texts[urls[2]] = "Orion Data Center construction in Austin, TX."
        enrich_buying_chain(session, project.id, fetcher=fetch, now=NOW + timedelta(minutes=2))
        removals = session.scalars(
            select(ChangeEvent).where(ChangeEvent.field_name == "contractor")
        ).all()
        assert len(removals) == 3
        removal = next(event for event in removals if event.id not in {additions[0].id, mixed.id})
        replacement_sources = session.scalars(
            select(BuyingChainEvidence).where(
                BuyingChainEvidence.project_id == project.id,
                BuyingChainEvidence.url.in_((urls[1], urls[2])),
                BuyingChainEvidence.id.not_in([row.id for row in [*added_sources, *mixed_sources]]),
            )
        ).all()
        assert {str(row.id) for row in replacement_sources} == set(
            removal.new_state["buying_chain_evidence_ids"]
        )
        assert len(replacement_sources) == 2
        assert removal.evidence_id is None
        count = len(removals)
        enrich_buying_chain(session, project.id, fetcher=fetch, now=NOW + timedelta(minutes=2))
        assert (
            len(
                session.scalars(
                    select(ChangeEvent).where(ChangeEvent.field_name == "contractor")
                ).all()
            )
            == count
        )

        # A -> B -> A may reuse old immutable versions but must emit a new
        # revision only for the actual restored documents.
        texts[urls[0]] = "Acme is the general contractor for Orion Data Center in Austin, TX."
        texts[urls[1]] = "BuildCo is the electrical contractor for Orion Data Center in Austin, TX."
        enrich_buying_chain(session, project.id, fetcher=fetch, now=NOW + timedelta(minutes=3))
        restored = session.scalars(
            select(ChangeEvent).where(ChangeEvent.field_name == "contractor")
        ).all()
        assert len(restored) == count + 1
        restored_event = next(
            event for event in restored if event.id not in {additions[0].id, mixed.id, removal.id}
        )
        assert set(restored_event.new_state["buying_chain_evidence_ids"]) == {
            str(row.id) for row in added_sources
        }
        buyer_events = session.scalars(
            select(ChangeEvent).where(ChangeEvent.field_name == "buyer")
        ).all()
        assert len(buyer_events) == 4
        assert {
            frozenset(event.new_state["buying_chain_evidence_ids"]) for event in buyer_events
        } == {frozenset(event.new_state["buying_chain_evidence_ids"]) for event in restored}
        assert all(event.evidence_id is None for event in buyer_events)

    client = TestClient(api.app)
    client.cookies.set(
        "gridlens_session", token_for(int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()))
    )
    history = client.get(f"/api/projects/{project.id}/changes")
    assert history.status_code == 200
    latest = next(
        row for row in history.json() if row["field"] == "contractor" and row["new"]["value"] == []
    )
    assert {row["url"] for row in latest["sources"]} == set(urls[1:])
    assert {row["id"] for row in latest["sources"]} == {str(row.id) for row in replacement_sources}
    assert unrelated_url not in {row["url"] for row in latest["sources"]}
    mixed_history = next(
        row
        for row in history.json()
        if row["field"] == "contractor"
        and set(row["new"].get("buying_chain_evidence_ids", []))
        == {str(source.id) for source in mixed_sources}
    )
    assert {row["url"] for row in mixed_history["sources"]} == {urls[0], urls[2]}
    morning = client.get("/api/changes")
    assert morning.status_code == 200
    assert any(
        {source["url"] for source in row["sources"]} == {urls[0], urls[2]}
        for row in morning.json()
        if row["kind"] == "contractor_changed"
    )

    # Events written before the additive list retain their singular citation.
    with db.begin() as session:
        legacy = session.get(ChangeEvent, additions[0].id)
        assert legacy is not None
        legacy.new_state = {"value": legacy.new_state["value"]}
    legacy_history = client.get(f"/api/projects/{project.id}/changes")
    assert legacy_history.status_code == 200
    legacy_row = next(
        row
        for row in legacy_history.json()
        if row["field"] == "contractor"
        and row["buying_chain_evidence_id"] == str(additions[0].buying_chain_evidence_id)
        and "buying_chain_evidence_ids" not in row["new"]
        and row["new"]["value"] == additions[0].new_state["value"]
    )
    assert [row["id"] for row in legacy_row["sources"]] == [
        str(additions[0].buying_chain_evidence_id)
    ]


def test_rechecked_aged_role_citation_is_not_causal_to_fresh_restoration(db):
    org_url = "https://external.example/orion-org"
    old_role_url = "https://acme.example/old-team"
    fresh_role_url = "https://acme.example/current-team"
    later = NOW + timedelta(days=370)
    pages = {
        org_url: (
            "Acme is the general contractor for Orion Data Center in Austin, TX.",
            NOW.date(),
        ),
        old_role_url: ("Alice Smith is Project Director at Acme.", NOW.date()),
        fresh_role_url: ("Alice Smith is Project Director at Acme.", later.date()),
    }

    def fetch(url: str) -> PublicDocument:
        text, published = pages.get(
            url, ("Orion Data Center construction in Austin, TX.", NOW.date())
        )
        return PublicDocument(url, "Orion Data Center", text, published, later)

    with db.begin() as session:
        project, _, _ = seed(session)
        enrich_buying_chain(
            session,
            project.id,
            source_urls=[org_url, old_role_url],
            fetcher=fetch,
            now=NOW,
        )
        previous_ids = {event.id for event in session.scalars(select(ChangeEvent)).all()}
        old_role = session.scalar(
            select(BuyingChainEvidence).where(BuyingChainEvidence.url == old_role_url)
        )
        assert old_role is not None
        current = enrich_buying_chain(
            session,
            project.id,
            source_urls=[fresh_role_url],
            fetcher=fetch,
            now=later,
        )
        person = next(row for row in current["candidates"] if row["person_name"])
        assert person["stale"] is False
        assert old_role.id in {citation["id"] for citation in person["evidence"]}
        fresh_role = session.scalar(
            select(BuyingChainEvidence).where(BuyingChainEvidence.url == fresh_role_url)
        )
        assert fresh_role is not None
        new_buyer_events = [
            event
            for event in session.scalars(
                select(ChangeEvent).where(ChangeEvent.field_name == "buyer")
            ).all()
            if event.id not in previous_ids
        ]
        assert len(new_buyer_events) == 1
        assert new_buyer_events[0].new_state["buying_chain_evidence_ids"] == [str(fresh_role.id)]


def test_partial_run_keeps_historical_id_without_silencing_a_b_a_change(db):
    url = "https://external.example/acme"
    failure_url = "https://external.example/unavailable"
    role = "general contractor"

    def fetch(request_url: str) -> PublicDocument:
        if request_url == failure_url:
            raise RuntimeError("fixture retrieval unavailable")
        return PublicDocument(
            url,
            "Orion Data Center",
            f"Acme is the {role} for Orion Data Center in Austin, TX.",
            date(2026, 9, 20),
            NOW,
        )

    with db.begin() as session:
        project, _, _ = seed(session)
        enrich_buying_chain(session, project.id, fetcher=fetch, now=NOW)
        original = session.scalar(
            select(BuyingChainEvidence).where(
                BuyingChainEvidence.project_id == project.id,
                BuyingChainEvidence.url == url,
            )
        )
        assert original is not None
        role = "electrical contractor"
        enrich_buying_chain(
            session,
            project.id,
            source_urls=[failure_url],
            fetcher=fetch,
            now=NOW + timedelta(minutes=1),
        )
        latest_run = session.scalar(
            select(BuyingChainRun)
            .where(BuyingChainRun.project_id == project.id)
            .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
        )
        assert latest_run is not None
        assert str(original.id) in latest_run.evidence_ids
        assert len(latest_run.evidence_ids) >= 2
        before = session.scalars(
            select(ChangeEvent).where(ChangeEvent.field_name == "contractor")
        ).all()
        assert len(before) == 2

        role = "general contractor"
        enrich_buying_chain(session, project.id, fetcher=fetch, now=NOW + timedelta(minutes=2))
        after = session.scalars(
            select(ChangeEvent).where(ChangeEvent.field_name == "contractor")
        ).all()
        assert len(after) == 3
        restored = next(event for event in after if event.id not in {row.id for row in before})
        assert restored.new_state["buying_chain_evidence_ids"] == [str(original.id)]


def test_buying_chain_role_expiry_updates_state_without_unrelated_event(db, monkeypatch):
    change_detection = import_module("gridlens.intelligence.change_detection")

    class ControlledDateTime(datetime):
        current: datetime = NOW

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(change_detection, "datetime", ControlledDateTime)
    with db.begin() as session:
        project, _, permit_evidence = seed(session)
        role_text = (
            "Acme is the general contractor for Orion Data Center in Austin, TX.\n"
            "Alice Smith is Project Director at Acme for Orion Data Center."
        )
        role_document = PublicDocument(
            "https://external.example/acme-team",
            "Orion Data Center",
            role_text,
            date(2025, 10, 2),
            NOW,
        )
        enrich_buying_chain(session, project.id, fetcher=lambda _: role_document, now=NOW)
        persisted = session.get(ProjectMaterialState, project.id)
        assert persisted is not None
        assert any(row.get("person_name") == "Alice Smith" for row in persisted.state["buyer"])
        fresh_state = deepcopy(persisted.state)
        fresh_revision = persisted.revision
        events_before = session.scalars(
            select(ChangeEvent).where(ChangeEvent.field_name.in_(("contractor", "buyer")))
        ).all()
        assert {event.field_name for event in events_before} >= {"contractor", "buyer"}

        later = NOW + timedelta(days=1)
        ControlledDateTime.current = later
        # An unrelated accepted permit may arrive after the role expires. Its
        # observation is not the retained source for this external relationship.
        record_material_diff(session, project, permit_evidence, persisted)
        assert len(
            session.scalars(
                select(ChangeEvent).where(ChangeEvent.field_name.in_(("contractor", "buyer")))
            ).all()
        ) == len(events_before)
        assert not any(row.get("person_name") == "Alice Smith" for row in persisted.state["buyer"])

        # Restore the persisted fresh predecessor to separately exercise enrichment's
        # explicit provenance context at the same freshness boundary.
        persisted.state = fresh_state
        persisted.revision = fresh_revision
        session.flush()
        unchanged_source = PublicDocument(
            role_document.url,
            role_document.title,
            role_document.text,
            role_document.published_at,
            later,
        )
        result = enrich_buying_chain(
            session, project.id, fetcher=lambda _: unchanged_source, now=later
        )
        expired_person = next(
            row for row in result["candidates"] if row.get("person_name") == "Alice Smith"
        )
        assert expired_person["stale"] is True
        assert expired_person["person_project_relationship"] == "UNKNOWN"
        persisted = session.get(ProjectMaterialState, project.id)
        assert persisted is not None
        assert not any(row.get("person_name") == "Alice Smith" for row in persisted.state["buyer"])

        events_after = session.scalars(
            select(ChangeEvent).where(ChangeEvent.field_name.in_(("contractor", "buyer")))
        ).all()
        assert len(events_after) == len(events_before)
        replay = enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda _: unchanged_source,
            now=later + timedelta(minutes=1),
        )
        assert any(
            row.get("person_name") == "Alice Smith" and row["stale"] for row in replay["candidates"]
        )
        assert len(
            session.scalars(
                select(ChangeEvent).where(ChangeEvent.field_name.in_(("contractor", "buyer")))
            ).all()
        ) == len(events_before)


def test_accepted_retained_source_withdrawal_keeps_evidence_backed_chain_events(db):
    with db.begin() as session:
        project, observation, evidence = seed(session)
        quote = "Acme is the general contractor for Orion Data Center in Austin, TX."
        chain_source = BuyingChainEvidence(
            project_id=project.id,
            retained_evidence_id=evidence.id,
            url=evidence.url,
            title=evidence.title,
            excerpt=quote,
            content_hash=evidence.content_hash,
            extraction_location="fixture",
            published_at=evidence.published_at,
            observed_at=evidence.observed_at,
            last_seen_at=evidence.observed_at,
            project_match_reason="Exact selected project fixture.",
        )
        session.add(chain_source)
        session.flush()
        claim = BuyingChainClaim(
            project_id=project.id,
            entity_key="acme",
            fingerprint="retained-source-claim",
            policy_version="test",
            organization="Acme",
            person_name=None,
            title=None,
            category="general_contractor",
            organization_relationship="DIRECT",
            person_organization_relationship="UNKNOWN",
            person_project_relationship="UNKNOWN",
            evidence_strength="High",
            reason="Accepted retained permit citation.",
            citations=[
                {
                    "evidence_id": str(chain_source.id),
                    "url": chain_source.url,
                    "quote": quote,
                    "supports": "organization_category",
                }
            ],
            public_contacts=[],
            observed_at=evidence.observed_at,
        )
        session.add(claim)
        session.flush()
        session.add(
            BuyingChainRun(
                project_id=project.id,
                input_hash="retained-source-run",
                evidence_ids=[str(chain_source.id)],
                claim_ids=[str(claim.id)],
                policy_version="test",
                status="complete",
                documents_checked=1,
                candidates_added=1,
                unresolved=[],
            )
        )
        session.flush()
        baseline = seed_material_state(session, project)
        assert baseline.state["contractor"]

        replacement = Evidence(
            observation_id=observation.id,
            title="Orion Data Center revised permit",
            abstract="Orion Data Center construction in Austin, TX",
            url=evidence.url,
            content_hash="accepted-v2",
            published_at=evidence.published_at,
            observed_at=NOW + timedelta(minutes=1),
        )
        session.add(replacement)
        interpretation = session.scalar(select(Interpretation))
        assert interpretation is not None
        interpretation.content_hash = replacement.content_hash
        interpretation.assessment = {
            "decision": "accepted",
            "evidence_hash": replacement.content_hash,
        }
        session.flush()

        changes = record_material_diff(session, project, replacement, baseline)
        assert {event.field_name for event in changes} >= {"contractor", "buyer"}
        assert all(event.evidence_id == replacement.id for event in changes)
        assert all(event.buying_chain_evidence_id is None for event in changes)


@pytest.mark.parametrize(
    ("binding", "admission", "supported"),
    [
        ("missing", "supplemental", False),
        ("other", "supplemental", False),
        ("current", "unmatched", False),
        ("current", "supplemental", True),
    ],
)
def test_retained_chain_citation_requires_current_project_and_admission(
    db, binding, admission, supported
):
    """A retained claim remains historical when its source is not current support."""
    with db.begin() as session:
        project, observation, evidence = seed(session)
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        assert interpretation is not None
        assessment = dict(interpretation.assessment)
        if binding == "missing":
            assessment.pop("project_identity_key")
        elif binding == "other":
            assessment["project_identity_key"] = "another-project"
        assessment["admission_status"] = admission
        interpretation.assessment = assessment
        quote = "Acme is the general contractor for Orion Data Center in Austin, TX."
        source = BuyingChainEvidence(
            project_id=project.id,
            retained_evidence_id=evidence.id,
            url=evidence.url,
            title=evidence.title,
            excerpt=quote,
            content_hash=evidence.content_hash,
            extraction_location="fixture",
            published_at=evidence.published_at,
            observed_at=evidence.observed_at,
            last_seen_at=evidence.observed_at,
            project_match_reason="Explicit supplemental match.",
        )
        session.add(source)
        session.flush()
        claim = BuyingChainClaim(
            project_id=project.id,
            entity_key="acme",
            fingerprint="binding-admission-claim",
            policy_version="test",
            organization="Acme",
            person_name=None,
            title=None,
            category="general_contractor",
            organization_relationship="DIRECT",
            person_organization_relationship="UNKNOWN",
            person_project_relationship="UNKNOWN",
            evidence_strength="High",
            reason="Retained supplemental source.",
            citations=[
                {
                    "evidence_id": str(source.id),
                    "url": source.url,
                    "quote": quote,
                    "supports": "organization_category",
                }
            ],
            public_contacts=[],
            observed_at=evidence.observed_at,
        )
        session.add(claim)
        session.flush()
        session.add(
            BuyingChainRun(
                project_id=project.id,
                input_hash="binding-admission-run",
                evidence_ids=[str(source.id)],
                claim_ids=[str(claim.id)],
                policy_version="test",
                status="complete",
                documents_checked=1,
                candidates_added=1,
                unresolved=[],
            )
        )
        session.flush()
        assert bool(buying_chain_view(session, project.id)["candidates"]) is supported
        historical = buying_chain_view(session, project.id, history=True)["candidates"]
        assert [row["id"] for row in historical] == [claim.id]


def test_multidocument_run_keeps_claim_with_still_current_citation(db):
    with db.begin() as session:
        project, observation_a, evidence_a = seed(session)
        observation_b = Observation(
            source_id="state-test",
            external_id="orion-b",
            title="Orion contractor update",
            abstract="BuildCo is the contractor.",
            url="https://example.test/b",
            published_at=date(2026, 9, 21),
            content_hash="accepted-b",
        )
        session.add(observation_b)
        session.flush()
        evidence_b = Evidence(
            observation_id=observation_b.id,
            title=observation_b.title,
            abstract=observation_b.abstract,
            url=observation_b.url,
            content_hash="accepted-b",
            published_at=observation_b.published_at,
            observed_at=NOW + timedelta(minutes=1),
        )
        session.add_all(
            [
                evidence_b,
                Interpretation(
                    observation_id=observation_b.id,
                    content_hash="accepted-b",
                    status="accepted",
                    assessment={
                        "decision": "accepted",
                        "evidence_hash": "accepted-b",
                        "project_identity_key": project.identity_key,
                        "admission_status": "supplemental",
                    },
                ),
            ]
        )
        session.flush()

        def chain_source(evidence, quote):
            row = BuyingChainEvidence(
                project_id=project.id,
                retained_evidence_id=evidence.id,
                url=evidence.url,
                title=evidence.title,
                excerpt=quote,
                content_hash=evidence.content_hash,
                extraction_location="fixture",
                published_at=evidence.published_at,
                observed_at=evidence.observed_at,
                last_seen_at=evidence.observed_at,
                project_match_reason="fixture",
            )
            session.add(row)
            session.flush()
            return row

        source_a = chain_source(evidence_a, "Acme is the general contractor.")
        source_b = chain_source(evidence_b, "BuildCo is the electrical contractor.")

        def claim(source, organization, fingerprint):
            row = BuyingChainClaim(
                project_id=project.id,
                entity_key=organization.casefold(),
                fingerprint=fingerprint,
                policy_version="test",
                organization=organization,
                person_name=None,
                title=None,
                category="general_contractor",
                organization_relationship="DIRECT",
                person_organization_relationship="UNKNOWN",
                person_project_relationship="UNKNOWN",
                evidence_strength="High",
                reason="fixture",
                citations=[
                    {
                        "evidence_id": str(source.id),
                        "url": source.url,
                        "quote": source.excerpt,
                        "supports": "organization_category",
                    }
                ],
                public_contacts=[],
                observed_at=source.observed_at,
            )
            session.add(row)
            session.flush()
            return row

        claim_b = claim(source_b, "BuildCo", "run-b")
        session.add(
            BuyingChainRun(
                project_id=project.id,
                input_hash="multi-doc",
                evidence_ids=[str(source_a.id), str(source_b.id)],
                claim_ids=[str(claim_b.id)],
                policy_version="test",
                status="complete",
                documents_checked=2,
                candidates_added=1,
                unresolved=[],
            )
        )
        session.flush()
        baseline = seed_material_state(session, project)
        assert {
            row["organization"] for row in buying_chain_view(session, project.id)["candidates"]
        } == {"BuildCo"}

        interpretation_a = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation_a.id)
        )
        interpretation_a.status = "rejected"
        interpretation_a.assessment = {
            "decision": "rejected",
            "evidence_hash": evidence_a.content_hash,
        }
        session.flush()
        current = buying_chain_view(session, project.id)
        assert current["status"] == "complete"
        assert "Buying chain has not been researched for this project." not in current["unresolved"]
        assert [row["organization"] for row in current["candidates"]] == ["BuildCo"]
        changes = record_material_diff(session, project, evidence_a, baseline)
        assert not any(change.field_name == "contractor" for change in changes)
        assert material_state(session, project.id)["contractor"]


def test_partial_contractor_removal_uses_checked_replacement_document(db):
    with db.begin() as session:
        project, _, _ = seed(session)
        url = "https://external.example/team"

        def document(text: str, observed: datetime) -> PublicDocument:
            return PublicDocument(url, "Orion Data Center", text, date(2026, 9, 20), observed)

        enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda _: document(
                "Acme is the general contractor for Orion Data Center in Austin, TX. "
                "BuildCo is the electrical contractor for Orion Data Center in Austin, TX.",
                NOW,
            ),
            now=NOW,
        )
        before = session.scalars(
            select(ChangeEvent).where(ChangeEvent.field_name == "contractor")
        ).all()
        assert before
        enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda _: document(
                "BuildCo is the electrical contractor for Orion Data Center in Austin, TX.",
                NOW + timedelta(minutes=1),
            ),
            now=NOW + timedelta(minutes=1),
        )
        events = session.scalars(
            select(ChangeEvent)
            .where(ChangeEvent.field_name == "contractor")
            .order_by(ChangeEvent.id)
        ).all()
        assert len(events) == len(before) + 1
        support = session.get(BuyingChainEvidence, events[-1].buying_chain_evidence_id)
        assert support is not None and support.url == url
        assert "Acme" not in support.excerpt and "BuildCo" in support.excerpt


def test_morning_changes_are_unique_and_use_immutable_evidence(db, monkeypatch):
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(api, "SessionLocal", db)
    with db.begin() as session:
        project, observation, evidence = seed(session)
        first = PowerNeed(
            project_id=project.id, activity_key="construction", tier="Signal", rationale="test"
        )
        second = PowerNeed(
            project_id=project.id, activity_key="temporary-power", tier="Signal", rationale="test"
        )
        session.add_all([first, second])
        session.flush()
        session.add_all(
            [
                NeedObservation(need_id=first.id, observation_id=observation.id),
                NeedObservation(need_id=second.id, observation_id=observation.id),
                ChangeEvent(
                    observation_id=observation.id,
                    content_hash=evidence.content_hash,
                    kind="power_need_changed",
                    project_id=project.id,
                    evidence_id=evidence.id,
                    field_name="power_need",
                    prior_state={"value": []},
                    new_state={"value": ["construction"]},
                    material=True,
                    replay_key="morning-event",
                ),
            ]
        )
        enrich_buying_chain(
            session,
            project.id,
            fetcher=lambda _: PublicDocument(
                "https://external.example/acme",
                "Orion Data Center",
                "Acme is the general contractor for Orion Data Center in Austin, TX.",
                date(2026, 9, 20),
                NOW,
            ),
            now=NOW,
        )
        # Mutable Observation fields later change; the event's Evidence citation cannot.
        observation.title = "Rewritten source title"
        observation.url = "https://example.test/revised"
    client = TestClient(api.app)
    client.cookies.set(
        "gridlens_session", token_for(int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()))
    )
    response = client.get("/api/changes")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 3
    assert {item["kind"] for item in payload} == {
        "power_need_changed",
        "contractor_changed",
        "buyer_changed",
    }
    assert next(item for item in payload if item["kind"] == "contractor_changed")["url"] == (
        "https://external.example/acme"
    )
    assert next(item for item in payload if item["kind"] == "power_need_changed") == {
        "kind": "power_need_changed",
        "title": "Orion Data Center",
        "url": "https://example.test/source",
        "published_at": "2026-09-20",
        "sources": [
            {
                "id": str(evidence.id),
                "title": "Orion Data Center",
                "url": "https://example.test/source",
                "published_at": "2026-09-20",
            }
        ],
    }
