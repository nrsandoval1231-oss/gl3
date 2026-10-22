"""API regression for current canonical schedule scope serialization."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from gridlens.domain.call_facts import validate_fact

pytest_plugins = ["test_call_fact_workflow_integration"]


def test_schedule_refs_require_current_project_activity_and_facility_binding(runtime, monkeypatch):
    from gridlens.settings import settings

    monkeypatch.setattr(settings, "saved_browse_enabled", False)
    client, factory, need_id, project_id, pursuit_id = runtime
    headers = {"origin": "http://testserver"}
    now = datetime.now(UTC)
    source_hash = "a" * 64
    source_abstract = (
        "description: Test City construction requires 20 to 25 MW. "
        "Power supply for Test City construction is insufficient.\naddress: Test City"
    )
    from gridlens.persistence.models import (
        Evidence,
        Interpretation,
        NeedObservation,
        Observation,
        PowerNeed,
        Project,
    )

    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, project_id)
        assert need is not None and project is not None
        observation = Observation(
            source_id="a6-test-source",
            external_id="synthetic-permit-pr105",
            title="Synthetic current construction permit",
            abstract=source_abstract,
            published_at=now.date(),
            url="https://example.test/synthetic-permit-pr105",
            content_hash=source_hash,
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=source_hash,
            title=observation.title,
            abstract=source_abstract,
            url=observation.url,
            published_at=observation.published_at,
            observed_at=now,
        )
        interpretation = Interpretation(
            observation_id=observation.id,
            content_hash=source_hash,
            status="accepted",
            assessment={
                "decision": "accepted",
                "semantic_hash": source_hash,
                "evidence_hash": source_hash,
                "project_identity_key": project.identity_key,
                "power_activity": "construction",
                "tier": "Prospect",
                "demand_mw": "20 to 25 MW",
                "demand_quote": "Test City construction requires 20 to 25 MW.",
                "supply_quote": "Power supply for Test City construction is insufficient.",
                "reason": "Current retained exact-site permit support.",
                "subject": project.name,
                "location": project.location,
            },
        )
        session.add_all(
            [
                evidence,
                interpretation,
                NeedObservation(need_id=need.id, observation_id=observation.id),
            ]
        )

    def accept_fact(fact_type, value, version):
        body = {
            "client_id": str(uuid4()),
            "project_id": str(project_id),
            "pursuit_id": str(pursuit_id),
            "expected_version": version,
            "predecessor_id": None,
            "activity_key": "construction",
            "facility_scope": "Test City",
            "fact_type": fact_type,
            "value": value,
            "reporter_name": "Synthetic Account Manager",
            "reporter_organization": "Synthetic Owner LLC",
            "reporter_role": "Project owner",
            "confirmation_channel": "customer_call",
            "source_reference": "synthetic-qualification-call",
            "source_date": now.date().isoformat(),
            "confirmed_at": now.isoformat(),
            "effective_from": "2026-01-01T00:00:00+00:00",
            "effective_until": "2027-03-04T00:00:00+00:00",
        }
        draft = client.post(f"/api/needs/{need_id}/facts", json=body, headers=headers)
        assert draft.status_code == 200, draft.text
        decision = client.post(
            f"/api/needs/{need_id}/facts/{draft.json()['id']}/decision",
            json={
                "client_id": str(uuid4()),
                "expected_version": version + 1,
                "decision": "accepted",
                "reason": f"Synthetic accepted {fact_type}",
            },
            headers=headers,
        )
        assert decision.status_code == 200, decision.text
        return decision.json()

    assert (
        accept_fact(
            "timing", {"start_date": "2027-01-01", "end_date": "2027-02-01", "duration_days": 31}, 0
        )["tier"]
        == "Prospect"
    )
    assert (
        accept_fact("suitable_supply", {"mw": "5", "quality": "suitable"}, 2)["tier"] == "Prospect"
    )
    assert (
        accept_fact("buyer", {"organization": "Synthetic Owner LLC", "role": "project owner"}, 4)[
            "tier"
        ]
        == "Lead"
    )

    value = validate_fact(
        "power_schedule",
        {
            "basis": "Operator-reported schedule",
            "source_quote": "Owner confirmed a commissioning interval.",
            "phases": [
                {
                    "phase_id": "commissioning",
                    "start_date": "2027-01-01",
                    "end_date": "2027-02-01",
                    "mw_min": "10",
                    "mw_max": "10",
                    "basis": "Attributed owner call",
                    "supply_coverage": "confirmed_complete",
                    "coverage_reason": "Owner confirmed full coverage",
                }
            ],
            "supplies": [],
            "zero_supply_basis": "Owner explicitly confirmed no available supply",
        },
    )
    body = {
        "client_id": str(uuid4()),
        "project_id": str(project_id),
        "pursuit_id": str(pursuit_id),
        "expected_version": 6,
        "predecessor_id": None,
        "activity_key": "construction",
        "facility_scope": "Test City",
        "fact_type": "power_schedule",
        "value": value,
        "reporter_name": "Synthetic Account Manager",
        "reporter_organization": "Synthetic Owner LLC",
        "reporter_role": "Project owner",
        "confirmation_channel": "customer_call",
        "source_reference": "synthetic-test-call",
        "source_date": now.date().isoformat(),
        "confirmed_at": now.isoformat(),
        "effective_from": now.isoformat(),
        "effective_until": (now + timedelta(days=90)).isoformat(),
    }
    draft = client.post(f"/api/needs/{need_id}/facts", json=body, headers=headers)
    assert draft.status_code == 200, draft.text
    schedule_fact_id = UUID(draft.json()["id"])
    accepted = client.post(
        f"/api/needs/{need_id}/facts/{schedule_fact_id}/decision",
        json={
            "client_id": str(uuid4()),
            "expected_version": 7,
            "decision": "accepted",
            "reason": "Synthetic operator review",
        },
        headers=headers,
    )
    assert accepted.status_code == 200, accepted.text

    matching = client.get(f"/api/opportunity-intelligence?need_ids={need_id}")
    assert matching.status_code == 200, matching.text
    matching_schedule = matching.json()[0]["power_schedule"]
    assert matching_schedule["status"] == "SUPPORTED_SCENARIO"
    assert matching_schedule["segments"]
    from gridlens.api import app as api

    with factory() as session:
        raw = api.opportunity_projection(
            session, selected_need_ids={UUID(str(need_id))}, include_operator_fact_refs=True
        )[0]
    reference = next(
        fact for fact in raw["operator_fact_refs"] if fact["fact_type"] == "power_schedule"
    )
    assert reference["need_id"] == str(need_id)
    assert reference["project_id"] == str(project_id)
    assert reference["activity_key"] == "construction"
    assert reference["facility_scope"] == "Test City"

    with factory.begin() as session:
        from gridlens.persistence.models import Project

        session.get(Project, project_id).location = "Changed Test City"
    stale = client.get(f"/api/opportunity-intelligence?need_ids={need_id}")
    assert stale.status_code == 200, stale.text
    assert stale.json()[0]["power_schedule"] is None
    with factory() as session:
        stale_raw = api.opportunity_projection(
            session, selected_need_ids={UUID(str(need_id))}, include_operator_fact_refs=True
        )[0]
    assert not any(
        fact["fact_type"] == "power_schedule" for fact in stale_raw.get("operator_fact_refs", [])
    )
    from gridlens.persistence.models import CallFactVersion

    with factory() as session:
        retained = session.get(CallFactVersion, schedule_fact_id)
        assert retained is not None
        assert retained.project_id == project_id
        assert retained.activity_key == "construction"
        assert retained.facility_scope == "Test City"
