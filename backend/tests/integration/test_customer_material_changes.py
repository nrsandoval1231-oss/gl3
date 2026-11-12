"""Typed material changes use real admitted source facts on an isolated test schema."""

from copy import deepcopy
from datetime import date
from hashlib import sha256

from sqlalchemy import func, select

from gridlens.intelligence.change_detection import (
    material_state,
    record_material_diff,
    seed_material_state,
)
from gridlens.persistence.models import (
    ChangeEvent,
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
)

pytest_plugins = ["test_equipment_intelligence"]

NAME = "Mock Permian Compression Station"


def seed(session, *, mw="120", quarter="Q2 2027"):
    from test_equipment_intelligence import seed as source_seed

    return source_seed(session, body=body(mw, quarter))


def body(mw="120", quarter="Q2 2027"):
    return (
        f"{NAME} has {mw} MW of campus development capacity. "
        f"{NAME} construction is scheduled to begin in {quarter}."
    )


def replace_source(session, rows, *, mw="140", quarter="Q3 2027", text=None):
    _, project, observation, _, interpretation, _ = rows
    content = text or body(mw, quarter)
    content_hash = sha256(content.encode()).hexdigest()
    observation.abstract = content
    observation.content_hash = content_hash
    evidence = Evidence(
        observation_id=observation.id,
        content_hash=content_hash,
        title=NAME,
        abstract=content,
        url=observation.url,
        published_at=date.today(),
    )
    session.add(evidence)
    session.flush()
    interpretation.content_hash = content_hash
    interpretation.assessment = {
        **interpretation.assessment,
        "semantic_hash": content_hash,
        "evidence_hash": content_hash,
        "project_identity_key": project.identity_key,
        "evidence": {"id": str(evidence.id), "url": evidence.url},
    }
    session.flush()
    return evidence


def another_article(session, rows, *, mw="120", quarter="Q2 2027", suffix="article"):
    need, project, _, _, _, source = rows
    content = body(mw, quarter)
    content_hash = sha256(content.encode()).hexdigest()
    observation = Observation(
        source_id=source.id,
        external_id=suffix,
        title=NAME,
        abstract=content,
        content_hash=content_hash,
        url=f"https://example.test/{suffix}",
        published_at=date.today(),
    )
    session.add(observation)
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        content_hash=content_hash,
        title=NAME,
        abstract=content,
        url=observation.url,
        published_at=date.today(),
    )
    session.add(evidence)
    session.flush()
    interpretation = Interpretation(
        observation_id=observation.id,
        content_hash=content_hash,
        status="accepted",
        assessment={
            "project_identity_key": project.identity_key,
            "semantic_hash": content_hash,
            "evidence_hash": content_hash,
            "decision": "accepted",
            "evidence": {"id": str(evidence.id), "url": evidence.url},
        },
    )
    session.add_all(
        [interpretation, NeedObservation(need_id=need.id, observation_id=observation.id)]
    )
    session.flush()
    return evidence, interpretation


def test_typed_capacity_and_quarter_revision_preserve_both_evidence_sides(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        _, project, _, prior_evidence, _, _ = rows
        baseline = seed_material_state(session, project)
        evidence = replace_source(session, rows)
        changes = record_material_diff(session, project, evidence, baseline)
        typed = {event.field_name: event for event in changes}
        assert set(typed) == {"capacity", "build_timing"}
        capacity = typed["capacity"]
        assert capacity.prior_state["value"]["claims"][0]["value_mw"] == "120"
        assert capacity.new_state["value"]["claims"][0]["value_mw"] == "140"
        timing = typed["build_timing"]
        assert timing.prior_state["value"]["claims"][0]["precision"] == "quarter"
        assert timing.new_state["value"]["claims"][0]["start"] == "2027-07-01"
        assert {r["evidence_id"] for r in capacity.prior_state["evidence_refs"]} == {
            str(prior_evidence.id)
        }
        assert {r["evidence_id"] for r in capacity.new_state["evidence_refs"]} == {str(evidence.id)}
        assert all(len(event.kind) <= 30 and event.evidence_id == evidence.id for event in changes)
        assert record_material_diff(session, project, evidence, baseline) == []
        assert (
            session.scalar(
                select(func.count()).select_from(ChangeEvent).where(ChangeEvent.material)
            )
            == 2
        )


def test_deadline_to_within_year_is_a_schedule_change_and_replay_is_quiet(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        project = rows[1]
        replace_source(session, rows, text=f"{NAME} is expected to be operational by 2027.")
        baseline = seed_material_state(session, project)
        evidence = replace_source(
            session, rows, text=f"{NAME} is expected to be operational in 2027."
        )
        changes = record_material_diff(session, project, evidence, baseline)
        assert [event.field_name for event in changes] == ["build_timing"]
        before = changes[0].prior_state["value"]["claims"][0]
        after = changes[0].new_state["value"]["claims"][0]
        assert before["qualifier"] == "deadline"
        assert after["qualifier"] == "within"
        assert record_material_diff(session, project, evidence, baseline) == []


def test_syndicated_article_and_metadata_refresh_do_not_alert(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        baseline = seed_material_state(session, rows[1])
        first = deepcopy(baseline.state["capacity"])
        evidence, _ = another_article(session, rows)
        assert record_material_diff(session, rows[1], evidence, baseline) == []
        assert baseline.state["capacity"] == first
        replacement = replace_source(session, rows, text=body() + " Unrelated wording changed.")
        assert record_material_diff(session, rows[1], replacement, baseline) == []


def test_preversion_state_is_normalized_quietly_in_seed(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        baseline = seed_material_state(session, rows[1])
        baseline.state = {
            key: value
            for key, value in baseline.state.items()
            if key not in {"capacity", "build_timing", "_customer_fact_evidence"}
        }
        session.flush()
        revision = baseline.revision
        normalized = seed_material_state(session, rows[1])
        assert normalized.state["capacity"]["claims"]
        assert normalized.revision == revision
        assert record_material_diff(session, rows[1], rows[3], normalized) == []


def test_preversion_direct_diff_does_not_generate_backfill_alerts(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        baseline = seed_material_state(session, rows[1])
        baseline.state = {
            key: value
            for key, value in baseline.state.items()
            if key not in {"capacity", "build_timing", "_customer_fact_evidence"}
        }
        session.flush()
        assert record_material_diff(session, rows[1], rows[3], baseline) == []
        assert baseline.state["build_timing"]["claims"]


def test_conflicting_capacity_then_withdrawal_is_material_not_a_silent_new_total(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        baseline = seed_material_state(session, rows[1])
        evidence, interpretation = another_article(session, rows, mw="160")
        changes = record_material_diff(session, rows[1], evidence, baseline)
        assert len(changes) == 1 and changes[0].field_name == "capacity"
        assert all(row["conflicted"] for row in changes[0].new_state["value"]["claims"])
        interpretation.status = "rejected"
        session.flush()
        changes = record_material_diff(session, rows[1], evidence, baseline)
        assert len(changes) == 1
        assert changes[0].new_state["value"]["claims"][0]["value_mw"] == "120"
        assert not changes[0].new_state["value"]["claims"][0]["conflicted"]


def test_unrelated_receipt_cannot_claim_or_swallow_a_capacity_revision(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        unrelated, unrelated_interpretation = another_article(session, rows, suffix="unrelated")
        unrelated_interpretation.status = "rejected"
        session.flush()
        baseline = seed_material_state(session, rows[1])
        relevant = replace_source(session, rows, mw="140", quarter="Q2 2027")
        assert record_material_diff(session, rows[1], unrelated, baseline) == []
        assert baseline.state["capacity"]["claims"][0]["value_mw"] == "120"
        changes = record_material_diff(session, rows[1], relevant, baseline)
        assert len(changes) == 1 and changes[0].field_name == "capacity"
        assert baseline.state == material_state(session, rows[1].id)


def test_equivalent_units_and_quarter_case_are_not_new_material_facts(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        baseline = seed_material_state(session, rows[1])
        evidence = replace_source(
            session,
            rows,
            text=(
                f"{NAME} has 0.12 GW of campus development capacity. "
                f"{NAME} construction is scheduled to begin in q2 2027."
            ),
        )
        assert record_material_diff(session, rows[1], evidence, baseline) == []
        assert baseline.state["capacity"]["claims"][0]["value_mw"] == "120"
        assert baseline.state["build_timing"]["claims"][0]["precision"] == "quarter"
