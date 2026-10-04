"""Synthetic exact-source fixtures exercising canonical research transitions."""

from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.adapters.socrata_permits import render_record
from gridlens.ingestion.registry import load_registry
from gridlens.ingestion.service import process_records
from gridlens.intelligence.buying_chain import enrich_buying_chain
from gridlens.intelligence.commercial_evaluation import evaluate_target
from gridlens.intelligence.pursuit_questions import schedule_questions
from gridlens.jobs.queue import lease_one
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    Job,
    PowerNeed,
    Pursuit,
    PursuitResearchQuestion,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def canonical_runtime(monkeypatch):
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    schema = "transition_test_" + uuid4().hex
    admin = create_engine(settings.test_database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        settings.test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    source = next(s for s in load_registry() if s["id"] == "austin-building-permits")
    worker = import_module("gridlens.intelligence.autonomous_research")
    api = import_module("gridlens.api.app")
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(settings, "firecrawl_api_key", None)
    monkeypatch.setattr(settings, "autonomous_research_daily_questions", 100)
    with factory.begin() as session:
        session.add(Source(**{k: v for k, v in source.items() if k in Source.__table__.columns}))
        session.flush()
        job = Job(
            source_id=source["id"],
            status="running",
            lease_owner="seed-test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        seed_job = job.id
    try:
        yield factory, source, worker, seed_job
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def record(source, description, **extra):
    return render_record(
        source,
        {
            "permit_number": "TRANSITION-TEST-1",
            "issue_date": datetime.now(UTC).date().isoformat(),
            "description": description,
            "permit_type_desc": "Electrical Permit",
            "permit_class_mapped": "Commercial",
            "status_current": "Active",
            "original_address1": "811 Clayton Ln",
            "original_city": "Austin",
            "original_state": "TX",
            "project_id": "123",
            "link": {"url": "https://abc.austintexas.gov/permit/123"},
            **extra,
        },
    )


@pytest.mark.parametrize(
    ("initial", "updated", "extra", "before", "after"),
    [
        (
            "Construct new data center.",
            "Construct new data center.",
            {
                "contractor_company_name": "Synthetic Electric",
                "contractor_full_name": "Pat Example",
                "contractor_phone": "5125550100",
            },
            "RESEARCH",
            "ACTION NOW",
        ),
        (
            "Construct new data center.",
            "Construct new data center.",
            {"status_current": "Completed"},
            "RESEARCH",
            "REJECT",
        ),
        (
            "Construct new data center.",
            "Construct new warehouse.",
            {},
            "RESEARCH",
            "WATCH",
        ),
        (
            "Construct new warehouse.",
            "Construct new data center.",
            {},
            "WATCH",
            "RESEARCH",
        ),
        (
            "Construct new data center.",
            "Construct new data center.",
            {},
            "RESEARCH",
            "RESEARCH",
        ),
    ],
)
def test_worker_reevaluates_real_canonical_source_updates(
    canonical_runtime, monkeypatch, initial, updated, extra, before, after
):
    factory, source, worker, seed_job = canonical_runtime
    with factory.begin() as session:
        process_records(
            session,
            seed_job,
            "seed-test",
            1,
            source,
            [record(source, initial)],
            commit=False,
            allow_model=False,
        )
        need = session.scalar(select(PowerNeed))
        assert need is not None
        need_id = need.id
        enrich_buying_chain(session, need.project_id, retained_only=True)
    with factory.begin() as session:
        card = evaluate_target(session, need_id)
        assert card is not None
        assert card["disposition"] == before, card
        old_evidence = {e.id: e.abstract for e in session.scalars(select(Evidence))}
        questions = schedule_questions(session, [card])
        assert questions
        question_id = questions[0].id
        job = session.scalar(select(Job).where(Job.target_id == question_id))
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        leased = lease_one(session, "transition-test", lease_seconds=600, job_ids=[job.id])
        assert leased
        job, fence = leased
        job_id = job.id
    calls = []

    def acquire(source_id, external_id, *, before_request, **_kwargs):
        calls.append((source_id, external_id))
        before_request("https://abc.austintexas.gov/permit/123")
        return source, record(source, updated, **extra)

    monkeypatch.setattr(worker, "acquire_registered_record", acquire)
    worker.process_question_job(job_id, "transition-test", fence)
    with factory() as session:
        question = session.get(PursuitResearchQuestion, question_id)
        assert calls == [(source["id"], "TRANSITION-TEST-1")]
        assert question.receipt["before"] == before
        assert question.receipt["after"] == after, question.receipt
        assert question.receipt["reevaluation_status"] == "COMPLETED"
        assert question.receipt["resulting_evidence_ids"]
        assert session.get(PowerNeed, need_id).tier == "Signal"
        assert question.receipt["tier"] == "Signal"
        assert {
            e.id: e.abstract for e in session.scalars(select(Evidence)) if e.id in old_evidence
        } == old_evidence
        pursuit = session.get(Pursuit, question.pursuit_id)
        versions = pursuit.snapshot["commercial_triage"]["versions"]
        assert [v["disposition"] for v in versions] == (
            [before, after] if before != after else [before]
        )


def test_grouped_primary_switch_does_not_redirect_exact_target_receipt(
    canonical_runtime, monkeypatch
):
    from gridlens.intelligence.commercial_evaluation import save_evaluations

    factory, source, _, seed_job = canonical_runtime
    api = import_module("gridlens.api.app")
    with factory.begin() as session:
        process_records(
            session,
            seed_job,
            "seed-test",
            1,
            source,
            [record(source, "Construct new data center.")],
            commit=False,
            allow_model=False,
        )
        need = session.scalar(select(PowerNeed))
        assert need is not None
        target_id = need.id
        enrich_buying_chain(session, need.project_id, retained_only=True)
    with factory.begin() as session:
        initial = evaluate_target(session, target_id)
        assert initial is not None
        save_evaluations(session, [initial])
    different_primary_id = uuid4()
    switched_group = {
        **initial,
        "id": str(different_primary_id),
        "related_need_ids": [str(different_primary_id), str(target_id)],
        "input_hash": "group-primary-switched",
    }
    monkeypatch.setattr(api, "_commercial_triage_cards", lambda *_args: [switched_group])
    with factory.begin() as session:
        actual = evaluate_target(session, target_id)
        assert actual is not None
        assert actual["id"] == str(target_id)
        assert actual["related_need_ids"] == [str(target_id)]
        assert actual["input_hash"] != switched_group["input_hash"]
        save_evaluations(session, [actual])
        save_evaluations(session, [evaluate_target(session, target_id)])
    with factory() as session:
        pursuits = session.scalars(select(Pursuit)).all()
        assert len(pursuits) == 1
        assert pursuits[0].identity_key == f"commercial-need:{target_id}"
        versions = pursuits[0].snapshot["commercial_triage"]["versions"]
        assert len(versions) == 2
        assert all(v["saved_card"]["id"] == str(target_id) for v in versions)


@pytest.mark.parametrize(
    ("initial_tier", "target_tier", "nonzero_supply"),
    [("Signal", "Prospect", False), ("Prospect", "Lead", False), ("Prospect", "Lead", True)],
)
def test_research_promotes_only_complete_official_qualification_gates(
    canonical_runtime, monkeypatch, initial_tier, target_tier, nonzero_supply
):
    from gridlens.persistence.models import Interpretation

    factory, source, worker, seed_job = canonical_runtime
    site = "811 Clayton Ln"
    base = "Construct new data center. "
    prospect = (
        f"{site} construction requires 1 to 2 MW. "
        f"Power supply for {site} construction is unavailable. "
    )
    lead = (
        f"{site} construction starts between 2026-11-01 and 2026-11-05. "
        f"{site} construction lasts 30 to 60 days. "
        f"No suitable power supply is available for {site} construction "
        "throughout this start window and duration. "
        f"The electrical contractor is responsible for power procurement for {site} construction."
    )
    first = base if initial_tier == "Signal" else base + prospect
    updated = base + prospect + (lead if target_tier == "Lead" else "")
    if nonzero_supply:
        updated = updated.replace("is unavailable", "is insufficient").replace(
            f"No suitable power supply is available for {site} construction "
            "throughout this start window and duration.",
            f"Total suitable power supply available for {site} construction is 0.2 to 0.4 MW "
            "throughout this start window and duration.",
        )
    with factory.begin() as session:
        process_records(
            session,
            seed_job,
            "seed-test",
            1,
            source,
            [record(source, first)],
            commit=False,
            allow_model=False,
        )
        need = session.scalar(select(PowerNeed))
        assert need is not None
        assert need.tier == initial_tier
        need_id = need.id
        enrich_buying_chain(session, need.project_id, retained_only=True)
    with factory.begin() as session:
        card = evaluate_target(session, need_id)
        assert card is not None
        questions = schedule_questions(session, [card])
        assert questions, card
        question_id = questions[0].id
        job = session.scalar(select(Job).where(Job.target_id == question_id))
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        leased = lease_one(session, "promotion-test", lease_seconds=600, job_ids=[job.id])
        assert leased
        job, fence = leased
        job_id = job.id
        original = {e.id: e.abstract for e in session.scalars(select(Evidence))}

    def acquire(_source_id, _external_id, *, before_request, **_kwargs):
        before_request("https://abc.austintexas.gov/permit/123")
        return source, record(source, updated)

    monkeypatch.setattr(worker, "acquire_registered_record", acquire)
    worker.process_question_job(job_id, "promotion-test", fence)
    with factory() as session:
        need = session.get(PowerNeed, need_id)
        question = session.get(PursuitResearchQuestion, question_id)
        assert need.tier == target_tier, str(question.receipt)
        assert need.required_mw == "1 to 2 MW"
        assert need.supply == "Reported constraint"
        assert question.receipt["tier"] == target_tier
        assert question.receipt["resulting_evidence_ids"]
        assert {
            e.id: e.abstract for e in session.scalars(select(Evidence)) if e.id in original
        } == original
        assessment = session.scalar(select(Interpretation)).assessment
        assert assessment["tier"] == target_tier
        assert assessment["demand_quote"] in updated
        assert assessment["supply_quote"] in updated
        if target_tier == "Lead":
            assert need.start_window == "2026-11-01 to 2026-11-05"
            assert need.duration == "30 to 60 days"
            assert assessment["qualified_remaining_gap"]["remaining_mw_min"] == (
                "0.6" if nonzero_supply else "1"
            )
            assert assessment["qualified_remaining_gap"]["remaining_mw_max"] == (
                "1.8" if nonzero_supply else "2"
            )
        else:
            assert need.start_window is None and need.duration is None


@pytest.mark.parametrize(
    "correction", ["remove_duration", "remove_supply", "closed", "sufficient_conflict"]
)
def test_official_correction_demotes_lead_and_clears_obsolete_fields(canonical_runtime, correction):
    from gridlens.persistence.models import Interpretation

    factory, source, _, seed_job = canonical_runtime
    base = "Construct new data center. "
    demand = "811 Clayton Ln construction requires 1 MW. "
    supply = "Power supply for 811 Clayton Ln construction is unavailable. "
    start = "811 Clayton Ln construction starts between 2026-11-01 and 2026-11-05. "
    duration = "811 Clayton Ln construction lasts 30 to 60 days. "
    gap = (
        "No suitable power supply is available for 811 Clayton Ln construction "
        "throughout this start window and duration. "
    )
    buyer = (
        "The electrical contractor is responsible for power procurement "
        "for 811 Clayton Ln construction."
    )
    complete = base + demand + supply + start + duration + gap + buyer
    with factory.begin() as session:
        process_records(
            session,
            seed_job,
            "seed-test",
            1,
            source,
            [record(source, complete)],
            commit=False,
            allow_model=False,
        )
        need = session.scalar(select(PowerNeed))
        assert need.tier == "Lead"
        need_id = need.id
        evidence_ids = {e.id for e in session.scalars(select(Evidence))}
    corrected = (
        complete.replace(duration, "")
        if correction == "remove_duration"
        else (complete.replace(supply, "") if correction == "remove_supply" else complete)
    )
    if correction == "sufficient_conflict":
        corrected = complete.replace("is unavailable", "is insufficient").replace(
            gap,
            "Total suitable power supply available for 811 Clayton Ln construction is 1 MW "
            "throughout this start window and duration. ",
        )
    extra = {"status_current": "Completed"} if correction == "closed" else {}
    with factory.begin() as session:
        process_records(
            session,
            seed_job,
            "seed-test",
            1,
            source,
            [record(source, corrected, **extra)],
            commit=False,
            allow_model=False,
        )
        need = session.get(PowerNeed, need_id)
        assert need.tier == ("Prospect" if correction == "remove_duration" else "Signal")
        assert need.start_window is None and need.duration is None
        if correction != "remove_duration":
            assert need.required_mw is None and need.supply == "Unknown"
        if correction == "sufficient_conflict":
            assert "conflict" in need.rationale.lower()
            latest = session.scalar(select(Interpretation)).assessment
            assert latest["qualification_conflict"] is True
        if correction == "closed":
            assert not need.active
        assert evidence_ids.issubset({e.id for e in session.scalars(select(Evidence))})
        history = session.scalar(select(Interpretation)).assessment["previous_decisions"]
        assert any(old.get("tier") == "Lead" for old in history)


def test_effective_qualification_ages_out_lead_without_mutating_retained_history(
    canonical_runtime, monkeypatch
):
    from gridlens.ingestion.service import effective_need_qualification
    from gridlens.persistence.models import Interpretation, Project

    factory, source, _, seed_job = canonical_runtime
    description = (
        "Construct new data center. 811 Clayton Ln construction requires 1 MW. "
        "Power supply for 811 Clayton Ln construction is unavailable. "
        "811 Clayton Ln construction starts between 2026-11-01 and 2026-11-05. "
        "811 Clayton Ln construction lasts 30 to 60 days. "
        "No suitable power supply is available for 811 Clayton Ln construction "
        "throughout this start window and duration. "
        "The electrical contractor is responsible for power procurement "
        "for 811 Clayton Ln construction."
    )
    with factory.begin() as session:
        process_records(
            session,
            seed_job,
            "seed-test",
            1,
            source,
            [record(source, description)],
            commit=False,
            allow_model=False,
        )
        need = session.scalar(select(PowerNeed))
        assert need.tier == "Lead"
        need_id = need.id
    qualification = import_module("gridlens.domain.power_qualification")

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2030, 1, 1, tzinfo=UTC)

    monkeypatch.setattr(qualification, "datetime", Later)
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        effective = effective_need_qualification(session, need, project)
        assert effective["tier"] == "Prospect"
        assert effective["required_mw"] == "1 MW"
        assert effective["qualified_remaining_gap"] is None
        assert effective["start_window"] is None and effective["duration"] is None
        assert need.tier == "Lead"  # Read projection does not rewrite historical state.
        assert need.start_window == "2026-11-01 to 2026-11-05"
        assert session.scalar(select(Interpretation)).assessment["tier"] == "Lead"
        assert not session.dirty
        api = import_module("gridlens.api.app")
        assert api.opportunity_projection(session, tier="Lead") == []
        projected = api.opportunity_projection(session, tier="Prospect")
        assert len(projected) == 1 and projected[0]["id"] == need_id
        assert projected[0]["start_window"] is None and projected[0]["duration"] is None
        assert session.get(PowerNeed, need_id).tier == "Lead"


def test_resolved_public_phase_worker_creates_one_bounded_followup(canonical_runtime, monkeypatch):
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.research_evidence import retain_research_document
    from gridlens.persistence.models import Project

    factory, source, worker, seed_job = canonical_runtime
    today = datetime.now(UTC).date()
    url = "https://www.datacenterdynamics.com/en/news/synthetic-clayton-update/"
    initial_description = "Construct new data center."
    with factory.begin() as session:
        process_records(
            session,
            seed_job,
            "seed-test",
            1,
            source,
            [record(source, initial_description)],
            commit=False,
            allow_model=False,
        )
        need = session.scalar(select(PowerNeed))
        need_id = need.id
        project = session.get(Project, need.project_id)
        project_name = project.name
        initial_document = PublicDocument(
            url,
            project_name + " project update",
            project_name + " at 811 Clayton Ln, Austin, TX construction requires 400 kW.",
            today,
            datetime.now(UTC),
        )
        receipt = retain_research_document(session, project, need, initial_document)
        assert receipt["disposition"] == "ACCEPTED", str(receipt)
        enrich_buying_chain(session, project.id, retained_only=True)
    with factory.begin() as session:
        card = evaluate_target(session, need_id)
        rows = schedule_questions(session, [card])
        parent = next(row for row in rows if row.category == "phase")
        question_id = parent.id
        job = session.scalar(select(Job).where(Job.target_id == question_id))
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        leased = lease_one(session, "followup-test", lease_seconds=600, job_ids=[job.id])
        assert leased
        job, fence = leased
        job_id = job.id

    def acquire(_source_id, _external_id, *, before_request, **_kwargs):
        before_request("https://abc.austintexas.gov/permit/123")
        return source, record(source, initial_description)

    def retrieve(requested_url, **_kwargs):
        assert requested_url == url
        return PublicDocument(
            url,
            project_name + " project update",
            project_name + " at 811 Clayton Ln, Austin, TX construction requires 400 kW. "
            "811 Clayton Ln, Austin, TX construction is underway.",
            today,
            datetime.now(UTC),
        )

    monkeypatch.setattr(worker, "acquire_registered_record", acquire)
    monkeypatch.setattr(worker, "retrieve", retrieve)
    worker.process_question_job(job_id, "followup-test", fence)
    with factory.begin() as session:
        parent = session.get(PursuitResearchQuestion, question_id)
        assert parent.status == "RESOLVED", str(parent.receipt)
        assert parent.receipt["after"] == "RESEARCH"
        children = session.scalars(
            select(PursuitResearchQuestion).where(PursuitResearchQuestion.parent_id == question_id)
        ).all()
        assert len(children) == 1
        child = children[0]
        assert child.category == "buyer"
        active = session.scalars(
            select(PursuitResearchQuestion).where(
                PursuitResearchQuestion.status.in_(["QUEUED", "SEARCHING", "REVIEWING_EVIDENCE"])
            )
        ).all()
        assert len(active) <= 2
        card = evaluate_target(session, need_id)
        assert schedule_questions(session, [card], parent_id=question_id, force=True) == []
        assert schedule_questions(session, [card], parent_id=child.id, force=True) == []
        assert session.get(PowerNeed, need_id).tier == "Signal"


@pytest.mark.parametrize(("mw", "below_floor"), [("0.299", True), ("0.3", False), ("0.301", False)])
def test_qualified_official_load_respects_exact_commercial_floor(
    canonical_runtime, mw, below_floor
):
    factory, source, _, seed_job = canonical_runtime
    description = (
        f"Construct new data center. 811 Clayton Ln construction requires {mw} MW. "
        "Power supply for 811 Clayton Ln construction is unavailable."
    )
    with factory.begin() as session:
        process_records(
            session,
            seed_job,
            "seed-test",
            1,
            source,
            [record(source, description)],
            commit=False,
            allow_model=False,
        )
        need = session.scalar(select(PowerNeed))
        assert need.tier == "Prospect"
        need_id = need.id
        enrich_buying_chain(session, need.project_id, retained_only=True)
    with factory() as session:
        card = evaluate_target(session, need_id)
        assert card["required_mw"] == mw + " MW"
        assert (card["disposition"] == "REJECT") is below_floor, card
        assert session.get(PowerNeed, need_id).tier == "Prospect"


@pytest.mark.parametrize(
    ("finding", "tier", "disposition"),
    [
        ("811 Clayton Ln, Austin, TX construction power is adequate.", "Signal", "REJECT"),
        ("811 Clayton Ln, Austin, TX project is completed.", "Signal", "REJECT"),
        ("811 Clayton Ln, Austin, TX commissioning power is adequate.", "Lead", "RESEARCH"),
    ],
)
def test_worker_public_adverse_report_vetoes_only_supported_exact_activity(
    canonical_runtime, monkeypatch, finding, tier, disposition
):
    from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
    from gridlens.intelligence.research_evidence import retain_research_document
    from gridlens.persistence.models import Project

    factory, source, worker, seed_job = canonical_runtime
    today = datetime.now(UTC).date()
    url = "https://www.datacenterdynamics.com/en/news/synthetic-adverse-update/"
    description = (
        "Construct new data center. 811 Clayton Ln construction requires 1 MW. "
        "Power supply for 811 Clayton Ln construction is unavailable. "
        "811 Clayton Ln construction starts between 2026-11-01 and 2026-11-05. "
        "811 Clayton Ln construction lasts 30 to 60 days. "
        "No suitable power supply is available for 811 Clayton Ln construction "
        "throughout this start window and duration. "
        "The electrical contractor is responsible for power procurement "
        "for 811 Clayton Ln construction."
    )
    with factory.begin() as session:
        process_records(
            session,
            seed_job,
            "seed-test",
            1,
            source,
            [record(source, description)],
            commit=False,
            allow_model=False,
        )
        need = session.scalar(select(PowerNeed))
        assert need.tier == "Lead"
        need_id = need.id
        project = session.get(Project, need.project_id)
        identity = project.name + " at 811 Clayton Ln, Austin, TX construction requires 1 MW. "
        result = retain_research_document(
            session,
            project,
            need,
            PublicDocument(url, project.name + " update", identity, today, datetime.now(UTC)),
        )
        assert result["disposition"] == "ACCEPTED", result
        enrich_buying_chain(session, project.id, retained_only=True)
        project_name = project.name
    with factory.begin() as session:
        card = evaluate_target(session, need_id)
        rows = schedule_questions(session, [card])
        assert rows, card
        question_id = rows[0].id
        job = session.scalar(select(Job).where(Job.target_id == question_id))
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        leased = lease_one(session, "veto-test", lease_seconds=600, job_ids=[job.id])
        assert leased
        job, fence = leased
        job_id = job.id

    def acquire(_source_id, _external_id, *, before_request, **_kwargs):
        before_request("https://abc.austintexas.gov/permit/123")
        return source, record(source, description)

    monkeypatch.setattr(worker, "acquire_registered_record", acquire)
    monkeypatch.setattr(
        worker,
        "retrieve",
        lambda *_a, **_kw: PublicDocument(
            url, project_name + " update", identity + finding, today, datetime.now(UTC)
        ),
    )
    worker.process_question_job(job_id, "veto-test", fence)
    with factory() as session:
        need = session.get(PowerNeed, need_id)
        question = session.get(PursuitResearchQuestion, question_id)
        assert need.tier == tier, str(question.receipt)
        assert question.receipt["tier"] == tier
        assert question.receipt["after"] == disposition
        assert question.category == "power_need"
        assert question.status == "UNRESOLVED"  # Accepted other facts do not answer this question.
        assert any(c["disposition"] == "ACCEPTED" for c in question.receipt["source_checks"])
        if tier == "Signal":
            assert need.required_mw is None and need.start_window is None and need.duration is None
        else:
            assert need.required_mw == "1 MW" and need.start_window is not None


@pytest.mark.parametrize(
    ("corroborating_mw", "expected", "changed_supply"),
    [("1", "Lead", False), ("2", "Signal", False), ("1", "Signal", True)],
)
def test_corroborating_missing_lead_fields_are_not_conflicting_but_different_load_is(
    canonical_runtime, corroborating_mw, expected, changed_supply
):
    from gridlens.ingestion.service import effective_need_qualification
    from gridlens.persistence.models import Project

    factory, source, _, seed_job = canonical_runtime
    lead = (
        "Construct new data center. 811 Clayton Ln construction requires 1 MW. "
        "Power supply for 811 Clayton Ln construction is unavailable. "
        "811 Clayton Ln construction starts between 2026-11-01 and 2026-11-05. "
        "811 Clayton Ln construction lasts 30 to 60 days. "
        "No suitable power supply is available for 811 Clayton Ln construction "
        "throughout this start window and duration. "
        "The electrical contractor is responsible for power procurement "
        "for 811 Clayton Ln construction."
    )
    corroborating = (
        f"Construct new data center. 811 Clayton Ln construction requires {corroborating_mw} MW. "
        "Power supply for 811 Clayton Ln construction is unavailable."
    )
    if changed_supply:
        corroborating = lead.replace("is unavailable", "is insufficient").replace(
            "No suitable power supply is available for 811 Clayton Ln construction "
            "throughout this start window and duration.",
            "Total suitable power supply available for 811 Clayton Ln construction is 0.2 MW "
            "throughout this start window and duration.",
        )
    with factory.begin() as session:
        process_records(
            session,
            seed_job,
            "seed-test",
            1,
            source,
            [
                record(source, lead),
                record(source, corroborating, permit_number="TRANSITION-TEST-2"),
            ],
            commit=False,
            allow_model=False,
        )
        needs = list(session.scalars(select(PowerNeed)))
        assert len(needs) == 1
        need = needs[0]
        project = session.get(Project, need.project_id)
        effective = effective_need_qualification(session, need, project)
        assert effective["tier"] == expected
        if expected == "Lead":
            assert effective["qualified_remaining_gap"]["remaining_mw_min"] == "1"
        else:
            assert effective["qualified_remaining_gap"] is None
            assert effective["required_mw"] is None


def test_batch_evaluation_reuses_projection_for_multiple_targets_outside_shortlist(
    canonical_runtime, monkeypatch
):
    from gridlens.intelligence.commercial_evaluation import evaluate_targets

    factory, source, _, seed_job = canonical_runtime
    api = import_module("gridlens.api.app")
    with factory.begin() as session:
        process_records(
            session,
            seed_job,
            "seed-test",
            1,
            source,
            [
                record(source, "Construct new data center."),
                record(
                    source,
                    "Construct new data center. 900 Test Ln construction requires 0.2 MW. "
                    "Power supply for 900 Test Ln construction is unavailable.",
                    permit_number="BATCH-TARGET-2",
                    project_id="999",
                    original_address1="900 Test Ln",
                    link={"url": "https://abc.austintexas.gov/permit/999"},
                ),
            ],
            commit=False,
            allow_model=False,
        )
        needs = list(session.scalars(select(PowerNeed)))
        assert len(needs) == 2
        for need in needs:
            enrich_buying_chain(session, need.project_id, retained_only=True)
        ids = [need.id for need in needs]
    original = api.opportunity_projection
    calls = []

    def counted(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(api, "opportunity_projection", counted)
    with factory.begin() as session:
        actual = evaluate_targets(session, ids, cohort=[])
        assert set(actual) == {str(identity) for identity in ids}
        assert all(key == card["id"] for key, card in actual.items())
        assert {card["disposition"] for card in actual.values()} == {"RESEARCH", "REJECT"}
        assert len(calls) == 1
        assert calls[0]["include_below_floor"] is True


@pytest.mark.parametrize(
    ("supply", "expected"),
    [("0.8", "below_floor"), ("0.7", "at_or_above_floor"), ("0.6 to 0.8", "unknown")],
)
def test_effective_lead_remaining_gap_controls_visibility_without_changing_gross_load(
    canonical_runtime, supply, expected
):
    factory, source, _, seed_job = canonical_runtime
    description = (
        "Construct new data center. 811 Clayton Ln construction requires 1 MW. "
        "Power supply for 811 Clayton Ln construction is insufficient. "
        "811 Clayton Ln construction starts between 2026-11-01 and 2026-11-05. "
        "811 Clayton Ln construction lasts 30 to 60 days. "
        f"Total suitable power supply available for 811 Clayton Ln construction is {supply} MW "
        "throughout this start window and duration. "
        "The electrical contractor is responsible for power procurement "
        "for 811 Clayton Ln construction."
    )
    with factory.begin() as session:
        process_records(
            session,
            seed_job,
            "seed-test",
            1,
            source,
            [record(source, description)],
            commit=False,
            allow_model=False,
        )
        need = session.scalar(select(PowerNeed))
        assert need.tier == "Lead"
        api = import_module("gridlens.api.app")
        items = api.opportunity_projection(session, include_below_floor=True)
        assert len(items) == 1
        assert items[0]["commercial_size_status"] == expected
        assert items[0]["required_mw"] == need.required_mw == "1 MW"
        visible = api.opportunity_projection(session)
        assert len(visible) == (0 if expected == "below_floor" else 1)
