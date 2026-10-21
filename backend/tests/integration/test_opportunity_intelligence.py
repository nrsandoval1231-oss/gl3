"""Disposable database checks; synthetic fixtures are not retained-corpus acceptance."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

pytest_plugins = ["test_saved_browse"]


def authenticated(api):
    from gridlens.security import token_for

    client = TestClient(api.app, base_url="https://testserver")
    client.cookies.set("gridlens_session", token_for(int(datetime.now(UTC).timestamp()) + 300))
    return client


def test_aggregate_is_authenticated_bounded_read_only_and_preserves_qualification(saved_db):
    from test_saved_browse import seed

    from gridlens.api import app as api
    from gridlens.persistence.models import Job, PursuitResearchQuestion

    ids = seed(saved_db, count=3, histories=1)
    anon = TestClient(api.app, base_url="https://testserver")
    assert (
        anon.get("/api/opportunity-intelligence", params={"need_ids": str(ids[0])}).status_code
        == 401
    )
    client = authenticated(api)
    with saved_db() as session:
        before = session.scalar(select(func.count()).select_from(Job))
    result = client.get("/api/opportunity-intelligence", params=[("need_ids", str(i)) for i in ids])
    assert result.status_code == 200, result.text
    cards = result.json()
    assert {c["need_id"] for c in cards} == {str(i) for i in ids}
    assert all(c["qualification"] == "Signal" and c["power_gap"] is None for c in cards)
    assert all(c["research_gaps"] for c in cards)
    detail = client.get(f"/api/opportunities/needs/{ids[0]}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["intelligence_card"]["need_id"] == str(ids[0])
    assert (
        client.get(
            "/api/opportunity-intelligence", params=[("need_ids", str(uuid4())) for _ in range(21)]
        ).status_code
        == 422
    )
    with saved_db() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == before
        assert session.scalar(select(func.count()).select_from(PursuitResearchQuestion)) == 0


def test_old_retained_boston_voltage_remains_dated_and_hash_bound_on_authenticated_card_read(
    saved_db,
):
    from test_saved_browse import seed

    from gridlens.api import app as api
    from gridlens.domain.opportunity_intelligence import IntelligenceCard
    from gridlens.persistence.models import (
        Evidence,
        Interpretation,
        Job,
        NeedObservation,
        Observation,
        PowerNeed,
        Project,
        PursuitResearchQuestion,
        Source,
    )

    need_id = seed(saved_db, count=1, histories=1)[0]
    old_event_date = date.today() - timedelta(days=120)
    old_text = (
        "Permit number: ETS1870328\n"
        "Description: Electrical\n"
        "Comments: Provide temporary electrical work required to support Boss steel "
        "Office trailer 100A 208v 1Ph $5000\n"
        "Address: 5308 Dorchester Ave, Boston, MA"
    )
    with saved_db.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Boston office trailer electrical work"
        project.location = "5308 Dorchester Ave, Boston, MA"
        need.activity_key = "temporary-power"
        for existing in session.scalars(
            select(Interpretation)
            .join(Observation, Observation.id == Interpretation.observation_id)
            .join(NeedObservation, NeedObservation.observation_id == Observation.id)
            .where(NeedObservation.need_id == need.id)
        ):
            existing.assessment = {
                **existing.assessment,
                "power_activity": need.activity_key,
            }
        source = Source(
            id="boston-building-permits",
            publisher="City of Boston",
            endpoint="https://data.boston.gov/api/3/action/datastore_search",
            family="construction-permits",
            geography="Boston, Massachusetts",
            industries=["commercial-construction"],
            retrieval_method="boston-ckan-permits",
            health={},
        )
        session.add(source)
        session.flush()
        observation = Observation(
            source_id=source.id,
            external_id="ETS1870328",
            title="Boston building permit ETS1870328",
            abstract=old_text,
            url="https://data.boston.gov/resource/permit/ETS1870328",
            published_at=old_event_date,
            content_hash="boston-voltage-v1",
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            title=observation.title,
            abstract=old_text,
            url=observation.url,
            content_hash=observation.content_hash,
            published_at=old_event_date,
            event_date=old_event_date,
            observed_at=datetime.now(UTC),
            extraction_location="retained permit row",
        )
        session.add_all(
            [
                evidence,
                Interpretation(
                    observation_id=observation.id,
                    content_hash=observation.content_hash,
                    evaluator_version="retained-permit-v1",
                    status="accepted",
                    assessment={
                        "decision": "accepted",
                        "evidence_hash": observation.content_hash,
                        "project_identity_key": project.identity_key,
                        "power_activity": need.activity_key,
                    },
                ),
                NeedObservation(need_id=need.id, observation_id=observation.id),
            ]
        )
        session.flush()
        observation_id, evidence_id, interpretation_id = (
            observation.id,
            evidence.id,
            session.scalar(
                select(Interpretation.id).where(Interpretation.observation_id == observation.id)
            ),
        )
        qualification_before = (need.tier, need.required_mw)

    client = authenticated(api)
    with saved_db() as session:
        jobs_before = session.scalar(select(func.count()).select_from(Job))
        questions_before = session.scalar(select(func.count()).select_from(PursuitResearchQuestion))
    first_response = client.get("/api/opportunity-intelligence", params={"need_ids": str(need_id)})
    assert first_response.status_code == 200, first_response.text
    first = IntelligenceCard.model_validate(first_response.json()[0])
    first_fields = {item.key: item for item in first.fields}
    voltage = first_fields["voltage"]
    assert voltage.value == "208 V, 1 phase"
    assert voltage.status == "Verified"
    assert voltage.sources[0].source_date == old_event_date.isoformat()
    assert first_fields["required_mw"].value is None
    assert first.power_gap is None
    old_fingerprint = first.input_fingerprint

    with saved_db.begin() as session:
        observation = session.get(Observation, observation_id)
        evidence = session.get(Evidence, evidence_id)
        interpretation = session.get(Interpretation, interpretation_id)
        assert observation and evidence and interpretation
        replacement_text = "Permit number: ETS1870328\nDescription: Electrical repair work."
        replacement_hash = "boston-voltage-v2"
        observation.abstract = replacement_text
        observation.content_hash = replacement_hash
        evidence.abstract = replacement_text
        evidence.content_hash = replacement_hash
        # The retained accepted interpretation still names the prior version;
        # its stale quote cannot restore the removed descriptor.
        assert interpretation.content_hash == "boston-voltage-v1"

    second_response = client.get("/api/opportunity-intelligence", params={"need_ids": str(need_id)})
    assert second_response.status_code == 200, second_response.text
    second = IntelligenceCard.model_validate(second_response.json()[0])
    second_fields = {item.key: item for item in second.fields}
    assert second_fields["voltage"].value is None
    assert second_fields["required_mw"].value is None
    assert second.power_gap is None
    assert second.input_fingerprint != old_fingerprint
    with saved_db() as session:
        final_need = session.get(PowerNeed, need_id)
        assert (final_need.tier, final_need.required_mw) == qualification_before
        assert session.scalar(select(func.count()).select_from(Job)) == jobs_before
        assert (
            session.scalar(select(func.count()).select_from(PursuitResearchQuestion))
            == questions_before
        )


def test_explicit_refresh_evaluates_exact_target_not_shortlist(saved_db, monkeypatch):
    from test_saved_browse import seed

    from gridlens.api import app as api
    from gridlens.intelligence import pursuit_questions
    from gridlens.settings import settings

    ids = seed(saved_db, count=2, histories=1)
    monkeypatch.setattr(settings, "autonomous_research_enabled", True)

    def fail_shortlist(*args, **kwargs):
        raise AssertionError("Exact target must not use the top-50 shortlist")

    monkeypatch.setattr(api, "_commercial_triage_cards", fail_shortlist)
    received = []

    def schedule(session, cards, **kwargs):
        received.extend(cards)
        assert kwargs["enrich"] is True
        return []

    monkeypatch.setattr(pursuit_questions, "schedule_questions", schedule)
    response = authenticated(api).post(
        f"/api/commercial/triage/{ids[1]}/autonomous-research",
        json={"force": False, "complete_intelligence": True},
        headers={"Origin": "https://testserver"},
    )
    assert response.status_code == 200, response.text
    assert received[0]["id"] == str(ids[1])


def test_optional_projection_does_not_churn_or_erase_saved_snapshot(saved_db):
    from copy import deepcopy

    from test_saved_browse import seed

    from gridlens.intelligence.commercial_evaluation import evaluate_target, save_evaluations
    from gridlens.persistence.models import Pursuit

    need_id = seed(saved_db, count=1, histories=1)[0]
    with saved_db.begin() as session:
        exact = evaluate_target(session, need_id)
        save_evaluations(session, [exact])
    with saved_db.begin() as session:
        row = session.scalar(select(Pursuit))
        before = deepcopy(row.snapshot)
        without_projection = {k: v for k, v in exact.items() if k != "intelligence_card"}
        save_evaluations(session, [without_projection])
        save_evaluations(session, [exact])
        assert row.snapshot == before
        assert row.snapshot["commercial_triage"]["saved_card"]["intelligence_card"][
            "need_id"
        ] == str(need_id)


def test_first_intelligence_projection_versions_legacy_receipt_once(saved_db):
    from copy import deepcopy

    from test_saved_browse import seed

    from gridlens.intelligence.commercial_evaluation import evaluate_target, save_evaluations
    from gridlens.persistence.models import Pursuit

    need_id = seed(saved_db, count=1, histories=1)[0]
    with saved_db.begin() as session:
        current = evaluate_target(session, need_id)
        legacy = deepcopy(current)
        legacy.pop("intelligence_card")
        save_evaluations(session, [legacy])
        row = session.scalar(select(Pursuit))
        prior_snapshot = deepcopy(row.snapshot["commercial_triage"])
        prior_version = deepcopy(prior_snapshot["versions"][-1])
        assert prior_version["saved_card"].get("intelligence_card") is None

        save_evaluations(session, [current])
        updated = row.snapshot["commercial_triage"]
        assert len(updated["versions"]) == len(prior_snapshot["versions"]) + 1
        assert updated["versions"][-2] == prior_version
        assert updated["saved_card"]["intelligence_card"] == current["intelligence_card"]

        save_evaluations(session, [current])
        assert (
            len(row.snapshot["commercial_triage"]["versions"])
            == len(prior_snapshot["versions"]) + 1
        )

        omitted = deepcopy(current)
        omitted.pop("intelligence_card")
        save_evaluations(session, [omitted])
        assert (
            row.snapshot["commercial_triage"]["saved_card"]["intelligence_card"]
            == current["intelligence_card"]
        )


def test_intelligence_fingerprint_versions_once_and_omission_preserves_prior_card(saved_db):
    from copy import deepcopy

    from test_saved_browse import seed

    from gridlens.intelligence.commercial_evaluation import evaluate_target, save_evaluations
    from gridlens.persistence.models import Pursuit

    need_id = seed(saved_db, count=1, histories=1)[0]
    with saved_db.begin() as session:
        first = evaluate_target(session, need_id)
        save_evaluations(session, [first])
    with saved_db.begin() as session:
        changed_intelligence = deepcopy(first)
        changed_intelligence["intelligence_card"]["input_fingerprint"] = "b" * 64
        save_evaluations(session, [changed_intelligence])
        row = session.scalar(select(Pursuit))
        assert len(row.snapshot["commercial_triage"]["versions"]) == 2
        saved_fingerprint = row.snapshot["commercial_triage"]["saved_card"]["intelligence_card"][
            "input_fingerprint"
        ]
        assert saved_fingerprint == "b" * 64

        save_evaluations(session, [changed_intelligence])
        assert len(row.snapshot["commercial_triage"]["versions"]) == 2

        omitted = {key: value for key, value in first.items() if key != "intelligence_card"}
        omitted["input_hash"] = "c" * 64
        save_evaluations(session, [omitted])
        assert len(row.snapshot["commercial_triage"]["versions"]) == 3
        assert (
            row.snapshot["commercial_triage"]["saved_card"]["intelligence_card"][
                "input_fingerprint"
            ]
            == saved_fingerprint
        )


def test_batch_enforces_complete_response_byte_bound_after_assembly(saved_db, monkeypatch):
    from test_saved_browse import seed

    from gridlens.api import app as api
    from gridlens.intelligence import opportunity_intelligence

    need_id = seed(saved_db, count=1, histories=1)[0]
    original = opportunity_intelligence.attach_cards

    def enlarged(session, items, chains):
        original(session, items, chains)
        items[0]["intelligence_card"]["next_action"] = "x" * 5_000_000

    monkeypatch.setattr(opportunity_intelligence, "attach_cards", enlarged)
    response = authenticated(api).get(
        "/api/opportunity-intelligence", params={"need_ids": str(need_id)}
    )
    assert response.status_code == 413


def test_batch_query_count_does_not_scale_per_field_or_need(saved_db):
    from time import perf_counter

    from sqlalchemy import event
    from test_saved_browse import seed

    from gridlens.api import app as api

    ids = seed(saved_db, count=10, histories=2)
    engine = saved_db.kw["bind"]
    queries = []

    def count(*args):
        queries.append(1)

    event.listen(engine, "before_cursor_execute", count)
    measurements = []
    try:
        for subset in (ids[:1], ids):
            queries.clear()
            start = perf_counter()
            cards = api.opportunity_intelligence_batch(subset)
            measurements.append((len(queries), round((perf_counter() - start) * 1000, 2)))
            assert len(cards) == len(subset)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    print(f"Synthetic PostgreSQL card batch (queries, ms), n=1/n=10: {measurements}")
    assert measurements[1][0] <= measurements[0][0] + 2


def test_research_status_accepts_post_acquisition_fingerprint_then_invalidates_drift(saved_db):
    from test_saved_browse import seed

    from gridlens.api import app as api
    from gridlens.domain.pursuit_research import fingerprint
    from gridlens.intelligence.commercial_evaluation import evaluate_target, save_evaluations
    from gridlens.persistence.models import Project, Pursuit, PursuitResearchQuestion

    need_id = seed(saved_db, count=1, histories=1)[0]
    with saved_db.begin() as session:
        commercial = evaluate_target(session, need_id)
        save_evaluations(session, [commercial])
        pursuit = session.scalar(select(Pursuit))
        project = session.get(Project, pursuit.project_id)
        question = PursuitResearchQuestion(
            pursuit_id=pursuit.id,
            project_id=project.id,
            need_id=need_id,
            category="load",
            question="Verify scoped load",
            status="UNRESOLVED",
            query_fingerprint="q" * 64,
            evidence_fingerprint="old" * 21,
            context={},
            budget={},
            receipt={
                "post_evidence_fingerprint": fingerprint(
                    [commercial["input_hash"], project.identity_key]
                )
            },
        )
        session.add(question)
        session.flush()
        question_id = question.id
    fields = api.opportunity_intelligence_batch([need_id])[0]["fields"]
    assert next(f for f in fields if f["key"] == "required_mw")["research_status"] == "UNRESOLVED"
    with saved_db.begin() as session:
        session.get(PursuitResearchQuestion, question_id).receipt = {
            "post_evidence_fingerprint": "stale"
        }
    fields = api.opportunity_intelligence_batch([need_id])[0]["fields"]
    assert next(f for f in fields if f["key"] == "required_mw")["research_status"] == "STALE_INPUT"
