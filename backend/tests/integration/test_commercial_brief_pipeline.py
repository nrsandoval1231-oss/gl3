"""Persisted research claims flow into the public project result brief."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import event, func, select
from test_pursuit_evidence import research_db as _isolated_research_db
from test_pursuit_evidence import seed

from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.intelligence.contact_suppressions import global_method_suppression_key
from gridlens.intelligence.project_results import page as project_result_page
from gridlens.intelligence.project_state import current_research_state
from gridlens.intelligence.research_evidence import retain_research_document
from gridlens.intelligence.saved_browse import rebuild
from gridlens.persistence.browse_invalidation import install
from gridlens.persistence.models import BuyingChainClaim, PowerNeed, Project
from gridlens.persistence.suppression_models import ContactSuppression

pytest_plugins = ["test_research_transitions", "test_retained_document_import"]


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


def test_source_only_brief_scrubs_tokens_without_claim_history(research_db):
    factory, source, job_id = research_db
    with factory.kw["bind"].begin() as connection:
        install(connection)
    need_id = seed(factory, source, job_id)
    url = "https://www.federalregister.gov/documents/orion-source-only/"
    email = "private@example.invalid"
    phone = "512-555-0134"
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
                f"Orion Data Center construction update {email} {phone}",
                "Orion Data Center at 811 Clayton Ln, Austin, TX construction is underway.\n"
                "Orion Data Center construction requires 12 MW.",
                date.today(),
                datetime.now(UTC),
                "public project update",
            ),
        )
        assert accepted["disposition"] == "ACCEPTED", accepted.get("reason") or accepted
        evidence_id = accepted["evidence_id"]
        assert session.scalar(
            select(func.count(BuyingChainClaim.id)).where(
                BuyingChainClaim.project_id == project.id
            )
        ) == 0
        session.add(
            ContactSuppression(
                scope="method",
                subject_key=global_method_suppression_key("email", email),
                expected_version=0,
                version=1,
                action="suppress",
                reason="source-only brief token regression",
                actor="test",
                idempotency_key="source-only-brief-email",
            )
        )

    assert rebuild(factory)["status"] == "published"
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = statement.lstrip().lower()
        if normalized.startswith(("select", "with")):
            statements.append(normalized)

    event.listen(factory.kw["bind"], "before_cursor_execute", capture)
    try:
        with factory() as session:
            response = project_result_page(session, need_id=UUID(str(need_id)), limit=1)
    finally:
        event.remove(factory.kw["bind"], "before_cursor_execute", capture)

    assert response["total"] == 1
    brief = response["items"][0]["commercial_brief"]
    brief_text = repr(brief)
    assert any(source_ref["evidence_id"] == evidence_id for source_ref in brief["sources"])
    assert url in brief_text
    assert email not in brief_text
    assert phone not in brief_text
    assert "[redacted]" in brief_text
    assert not any("select buying_chain_claims.id" in statement for statement in statements)
    assert not any("from contact_suppressions" in statement for statement in statements)


def test_native_split_semantic_and_evidence_hash_still_resolves_source(
    retained_db, monkeypatch
):
    import hashlib

    from test_retained_document_import import (
        SOURCES,
        _process_synthetic_tx_source,
        _synthetic_tx_record,
    )

    from gridlens.intelligence.project_results import page as project_result_page
    from gridlens.intelligence.saved_browse import rebuild
    from gridlens.persistence.models import Evidence, Interpretation, NeedObservation, Observation

    factory, _definitions, _synthetic_text = retained_db
    source_id = "test-retained-tx-a"
    record = _synthetic_tx_record(source_id)
    _process_synthetic_tx_source(factory, source_id, record)
    revised_body = f"%PDF-synthetic-{source_id}|reviewed-v2".encode()
    revised_hash = hashlib.sha256(revised_body).hexdigest()
    monkeypatch.setitem(SOURCES, source_id, {**SOURCES[source_id], "sha256": revised_hash})
    revised = {**record, "source_hash": revised_hash}
    revised["retained_document"] = {
        **record["retained_document"],
        "sha256": revised_hash,
    }
    _process_synthetic_tx_source(factory, source_id, revised)

    with factory.kw["bind"].begin() as connection:
        install(connection)
    with factory() as session:
        observation = session.scalar(select(Observation).where(Observation.source_id == source_id))
        assert observation is not None
        interpretation = session.scalar(
            select(Interpretation).where(Interpretation.observation_id == observation.id)
        )
        current_evidence = session.scalar(
            select(Evidence).where(
                Evidence.observation_id == observation.id,
                Evidence.content_hash == revised_hash,
            )
        )
        need_id = session.scalar(
            select(NeedObservation.need_id).where(
                NeedObservation.observation_id == observation.id
            )
        )
        assert interpretation is not None and current_evidence is not None and need_id
        assert interpretation.status == "accepted"
        assert observation.content_hash == interpretation.assessment["semantic_hash"]
        assert current_evidence.content_hash == interpretation.assessment["evidence_hash"]
        assert observation.content_hash != current_evidence.content_hash

    assert rebuild(factory)["status"] == "published"
    with factory() as session:
        response = project_result_page(session, need_id=UUID(str(need_id)), limit=1)
    assert response["total"] == 1
    brief = response["items"][0]["commercial_brief"]
    assert any(
        source_ref["evidence_id"] == str(current_evidence.id)
        and source_ref["url"] == revised["html_url"]
        for source_ref in brief["sources"]
    )


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
