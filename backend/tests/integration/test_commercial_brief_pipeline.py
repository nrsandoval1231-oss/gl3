"""Persisted research claims flow into the public project result brief."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from test_pursuit_evidence import research_db as _isolated_research_db
from test_pursuit_evidence import seed

from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.intelligence.project_results import page as project_result_page
from gridlens.intelligence.project_state import current_research_state
from gridlens.intelligence.research_evidence import retain_research_document
from gridlens.intelligence.saved_browse import rebuild
from gridlens.persistence.browse_invalidation import install
from gridlens.persistence.models import PowerNeed, Project

pytest_plugins = ["test_research_transitions"]


@pytest.fixture
def research_db():
    yield from _isolated_research_db.__wrapped__()


def test_retained_research_claim_reaches_project_result_commercial_brief(research_db):
    factory, source, job_id = research_db
    with factory.kw["bind"].begin() as connection:
        install(connection)
    need_id = seed(factory, source, job_id)
    url = "https://www.federalregister.gov/documents/orion/"
    quote = "Orion Data Center construction requires 12 MW."
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        accepted = retain_research_document(
            session,
            project,
            need,
            PublicDocument(
                url,
                "Orion Data Center construction status",
                "Orion Data Center at 811 Clayton Ln, Austin, TX construction is underway.\n"
                + quote,
                date.today(),
                datetime.now(UTC),
                "public project update",
            ),
        )
        assert accepted["disposition"] == "ACCEPTED", accepted.get("reason") or accepted
        state = current_research_state(session, project.id, need.id)[str(need.id)]
        activity = need.activity_key
        assert state["activity_load_mw"]["status"] == "SUPPORTED"
        assert state["activity_load_mw"]["value"] == "12"
        assert need.required_mw is None
        assert need.tier == "Signal"

    assert rebuild(factory)["status"] == "published"
    with factory() as session:
        response = project_result_page(session, need_id=UUID(str(need_id)), limit=1)

    assert response["total"] == 1
    brief = response["items"][0]["commercial_brief"]
    assert brief["power_need"]["status"] == "supported"
    assert brief["power_need"]["value"] == "12"
    assert brief["power_need"]["unit"] == "MW"
    assert brief["power_need"]["scope"] == activity
    assert brief["power_need"]["amount_class"] == "documented"
    assert any(
        "temporary rental equipment need remains unconfirmed" in value
        for value in brief["limitations"]
    )
    assert any(source_ref["url"] == url for source_ref in brief["sources"])
    with factory() as session:
        need = session.get(PowerNeed, need_id)
        assert need.required_mw is None


def test_retained_campus_capacity_does_not_become_activity_power_need(research_db):
    factory, source, job_id = research_db
    with factory.kw["bind"].begin() as connection:
        install(connection)
    need_id = seed(factory, source, job_id)
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        project.name = "Orion Data Center"
        accepted = retain_research_document(
            session,
            project,
            need,
            PublicDocument(
                "https://www.federalregister.gov/documents/orion-campus/",
                "Orion Data Center construction status",
                "Orion Data Center at 811 Clayton Ln, Austin, TX construction is underway.\n"
                "Orion Data Center campus capacity requires 400 MW.",
                date.today(),
                datetime.now(UTC),
                "public project update",
            ),
        )
        assert accepted["disposition"] == "ACCEPTED", accepted.get("reason") or accepted
        state = current_research_state(session, project.id, need.id)[str(need.id)]
        assert state["activity_load_mw"]["status"] == "UNKNOWN"
        assert need.required_mw is None

    assert rebuild(factory)["status"] == "published"
    with factory() as session:
        response = project_result_page(session, need_id=UUID(str(need_id)), limit=1)
    assert response["total"] == 1
    power_need = response["items"][0]["commercial_brief"]["power_need"]
    assert power_need["status"] == "unknown"
    assert power_need["value"] is None


def test_failed_research_refresh_retains_last_good_commercial_brief(canonical_runtime, monkeypatch):
    from test_pursuit_evidence import seed as seed_research

    from gridlens.intelligence.commercial_evaluation import evaluate_target
    from gridlens.intelligence.pursuit_questions import schedule_questions
    from gridlens.jobs.queue import lease_one
    from gridlens.persistence.models import Job, PursuitResearchQuestion

    factory, source, worker, seed_job = canonical_runtime
    with factory.kw["bind"].begin() as connection:
        install(connection)
    with factory.begin() as session:
        session.get(Job, seed_job).lease_owner = "research-test"
    need_id = seed_research(factory, source, seed_job)
    with factory.begin() as session:
        need = session.get(PowerNeed, need_id)
        project = session.get(Project, need.project_id)
        need_id = need.id
        project.name = "Orion Data Center"
        url = "https://www.federalregister.gov/documents/orion/"
        accepted = retain_research_document(
            session,
            project,
            need,
            PublicDocument(
                url,
                "Orion Data Center construction status",
                "Orion Data Center at 811 Clayton Ln, Austin, TX construction is underway.\n"
                "Orion Data Center construction requires 12 MW.",
                date.today(),
                datetime.now(UTC),
                "public project update",
            ),
        )
        assert accepted["disposition"] == "ACCEPTED", accepted.get("reason") or accepted
        last_good_evidence_id = accepted["evidence_id"]

    assert rebuild(factory)["status"] == "published"
    with factory() as session:
        before = project_result_page(session, need_id=UUID(str(need_id)), limit=1)
    assert before["total"] == 1
    before_brief = before["items"][0]["commercial_brief"]
    assert before_brief["power_need"]["value"] == "12"
    assert last_good_evidence_id in {
        source_ref["evidence_id"] for source_ref in before_brief["sources"]
    }

    with factory.begin() as session:
        card = evaluate_target(session, need_id)
        questions = schedule_questions(session, [card])
        assert questions, card
        question = questions[0]
        question_id = question.id
        job = session.scalar(select(Job).where(Job.target_id == question_id))
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        leased = lease_one(
            session,
            "commercial-brief-refresh-failure",
            lease_seconds=600,
            job_ids=[job.id],
        )
        assert leased
        job, fence = leased
        job_id = job.id

    def failed_refresh(*_args, **_kwargs):
        raise OSError("synthetic source refresh failure")

    monkeypatch.setattr(worker, "acquire_registered_record", failed_refresh)
    worker.process_question_job(job_id, "commercial-brief-refresh-failure", fence)

    with factory() as session:
        question = session.get(PursuitResearchQuestion, question_id)
        assert question.status == "FAILED", question.receipt
        assert any(
            check.get("disposition") == "FAILED"
            for check in question.receipt["source_checks"]
        )
        need = session.get(PowerNeed, need_id)
        assert need.required_mw is None
        assert need.tier == "Signal"

    assert rebuild(factory)["status"] == "published"

    with factory() as session:
        after = project_result_page(session, need_id=UUID(str(need_id)), limit=1)
    assert after["total"] == 1
    after_brief = after["items"][0]["commercial_brief"]
    assert after_brief["power_need"] == before_brief["power_need"]
    assert after_brief["why_now"] == before_brief["why_now"]
    assert after_brief["sources"] == before_brief["sources"]
    assert last_good_evidence_id in {
        source_ref["evidence_id"] for source_ref in after_brief["sources"]
    }
    assert "synthetic source refresh failure" not in repr(after_brief)
