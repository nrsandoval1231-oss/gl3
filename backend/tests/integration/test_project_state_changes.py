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
from gridlens.intelligence.project_state import _conflict, project_state
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


def seed(session):
    observation = Observation(
        source_id="state-test",
        external_id="orion",
        title="Orion Data Center",
        url="https://example.test/source",
        abstract="Orion Data Center construction in Austin, TX",
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
        content_hash="accepted-v1",
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
                    "evidence_hash": "accepted-v1",
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
    content_hash = f"need-hash-{key}"
    observation = Observation(
        source_id=source_id,
        external_id=key,
        title="Orion Data Center construction permit",
        abstract="Orion Data Center construction in Austin, TX.",
        url=f"https://permits.example/{key}",
        published_at=date(2026, 9, 20),
        content_hash=content_hash,
    )
    session.add(observation)
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        title=observation.title,
        abstract=observation.abstract,
        url=observation.url,
        content_hash=content_hash,
        published_at=observation.published_at,
        observed_at=NOW,
    )
    assessment = {
        "decision": "accepted",
        "evidence_hash": content_hash,
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
                content_hash=content_hash,
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
        interpretation.assessment = {"decision": "rejected", "evidence_hash": "accepted-v1"}
        assert project_state(session, project.id)["state"]["lifecycle"]["status"] == "UNKNOWN"


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
        assert project_state(session, project.id)["state"]["power_need"]["value"][0]["mw"][
            "status"
        ] == "CONFLICT"
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
    response = api.app.openapi()["paths"]["/api/projects/{project_id}/changes"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert response["type"] == "array"
    item_ref = response["items"]["$ref"]
    item = api.app.openapi()["components"]["schemas"][item_ref.rsplit("/", 1)[-1]]
    assert set(item["required"]) == {
        "kind", "field", "prior", "new", "evidence_id", "buying_chain_evidence_id",
        "source_date", "detected_at",
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
        project, observation, evidence = seed(session)
        session.add(ProjectLifecycle(project_id=project.id, current_state="permitted"))
        session.add(
            LifecycleEvent(
                project_id=project.id,
                observation_id=observation.id,
                evidence_id=evidence.id,
                event_type="utility_energization",
                state="permitted",
                occurred_on=date(2027, 1, 1),
            )
        )
        session.flush()
        baseline = seed_material_state(session, project)
        replacement = Evidence(
            observation_id=observation.id,
            title="Orion revision",
            abstract="Revised utility date",
            url=observation.url,
            content_hash="accepted-v2",
            published_at=date(2026, 9, 21),
            observed_at=NOW + timedelta(minutes=1),
        )
        session.add(replacement)
        interpretation = session.scalar(select(Interpretation))
        interpretation.content_hash = "accepted-v2"
        interpretation.assessment = {
            "decision": "accepted",
            "evidence_hash": "accepted-v2",
            "project_identity_key": project.identity_key,
        }
        session.add(
            LifecycleEvent(
                project_id=project.id,
                observation_id=observation.id,
                evidence_id=replacement.id,
                event_type="utility_energization",
                state="permitted",
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
            citations=[{
                "evidence_id": str(source.id),
                "url": source.url,
                "quote": quote,
                "supports": "organization_category",
            }],
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
    }
