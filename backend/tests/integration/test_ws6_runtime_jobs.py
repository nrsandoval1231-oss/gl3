"""WS6 runtime on a disposable Postgres: extraction jobs, health findings, timestamps.

Disposable test database only. HTTP is a MockTransport; the model passes are fakes; no network.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from test_tceq_application_documents_ingestion import (  # noqa: F401  (fixtures and helpers)
    BASE,
    ELECTRIC,
    WORKER,
    nsr_record,
    portfolio,
    setup_source,
    stage_db,
)

import gridlens.ingestion.adapters.tceq_application_documents as docs
import gridlens.jobs.document_extraction as djob
from gridlens.ingestion.adapters.tceq_application_documents import ApplicationLink
from gridlens.ingestion.parsers.permit_docs.proposals import ProposerOutcome
from gridlens.ingestion.service import _enrich_with_application_documents, process_records
from gridlens.intelligence.first_signal import first_signal_sample, lead_time_days
from gridlens.intelligence.spend_caps import recent_capped_out_jobs
from gridlens.jobs import document_alerts as da
from gridlens.persistence import database
from gridlens.persistence.database import Base
from gridlens.persistence.models import Evidence, Job, Observation, Project, Source
from gridlens.settings import settings

REAL_CLIENT = httpx.Client


class Publisher:
    """A mock TCEQ: serves one portfolio, counts requests, can be told to misbehave."""

    def __init__(self, body: bytes, etag: str = '"v1"') -> None:
        self.body, self.etag = body, etag
        self.requests: list[str] = []
        self.status = 200
        self.content_type = "application/pdf"

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.method)
        headers = {
            "content-type": self.content_type,
            "etag": self.etag,
            "last-modified": "Mon, 02 Nov 2026 10:00:00 GMT",
            "content-length": str(len(self.body)),
        }
        if self.status != 200:
            return httpx.Response(self.status, headers={"retry-after": "120"})
        content = b"" if request.method == "HEAD" else self.body
        return httpx.Response(200, headers=headers, content=content)

    def client(self) -> httpx.Client:
        return REAL_CLIENT(transport=httpx.MockTransport(self.handler), follow_redirects=False)


@pytest.fixture
def world(stage_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _h: "8.8.8.8")
    monkeypatch.setattr(docs, "Pacer", lambda *a, **k: (lambda: None))
    monkeypatch.setattr(
        docs, "config_from_source", lambda _s: docs.StageConfig(1, 5, 120.0, isolate=False)
    )
    monkeypatch.setattr(settings, "document_extraction_jobs_enabled", True)
    monkeypatch.setattr(djob, "SessionLocal", stage_db)
    monkeypatch.setattr(database, "SessionLocal", stage_db)
    definition, ingestion_job = setup_source(stage_db)
    return SimpleNamespace(
        factory=stage_db,
        definition=definition,
        ingestion_job=ingestion_job,
        monkeypatch=monkeypatch,
    )


def use_publisher(world, publisher: Publisher) -> None:
    world.publisher = publisher
    world.monkeypatch.setattr(
        docs.httpx,
        "Client",
        lambda **_kw: REAL_CLIENT(
            transport=httpx.MockTransport(publisher.handler), follow_redirects=False
        ),
    )


def discover(world, publisher: Publisher, records=None):
    records = records if records is not None else [nsr_record()]
    config_definition = {
        **world.definition,
        "query": {**world.definition["query"], "application_documents": {}},
    }
    with world.factory() as session:
        report = _enrich_with_application_documents(
            session,
            world.ingestion_job,
            WORKER,
            1,
            config_definition,
            records,
            publisher.client(),
            deadline=None,
        )
        session.commit()
    return report, records


def lease(world, job_id) -> None:
    with world.factory.begin() as session:
        job = session.get(Job, job_id)
        job.status, job.lease_owner, job.fence, job.attempts = "running", WORKER, 1, 1
        job.lease_until = datetime.now(UTC) + timedelta(minutes=10)


def extraction_jobs(world) -> list[Job]:
    with world.factory() as session:
        return list(session.scalars(select(Job).where(Job.kind == djob.KIND)))


def link() -> ApplicationLink:
    record = nsr_record()
    return docs.discover([record])[0]


# ------------------------------------------------------------------ discovery and idempotency


def test_discovery_queues_one_job_per_version_and_fetches_nothing(world):
    publisher = Publisher(portfolio([ELECTRIC]))
    report, records = discover(world, publisher)
    assert report.counts["enqueued"] == 1 and "downloads" in report.counts
    assert publisher.requests == ["HEAD"]  # discovery never downloads
    assert "application_document" not in records[0]
    jobs = extraction_jobs(world)
    assert len(jobs) == 1 and jobs[0].status == "queued" and jobs[0].kind == "document_extraction"
    body = json.loads(jobs[0].checkpoint)
    assert body["project"] == "900001" and body["url"] == BASE + "900001-tc.pdf"

    again, _ = discover(world, publisher)
    assert again.counts.get("enqueued", 0) == 0 and again.counts["already_queued"] == 1
    assert len(extraction_jobs(world)) == 1

    publisher.etag = '"v2"'  # a changed document is a new version and a new job
    discover(world, publisher)
    assert len(extraction_jobs(world)) == 2
    with world.factory() as session:
        runs = session.get(Source, world.definition["id"]).health["document_stage"]["runs"]
    assert runs[-1]["mode"] == "discovery" and runs[0]["enqueued"] == 1


def test_enqueue_is_idempotent_and_failed_versions_rest(world):
    validators = {"etag": '"v1"', "content_length": 5}
    with world.factory.begin() as session:
        first, how = djob.enqueue_document_extraction(
            session, world.definition["id"], link=link(), validators=validators
        )
        again, how2 = djob.enqueue_document_extraction(
            session, world.definition["id"], link=link(), validators=validators
        )
    assert first == again and (how, how2) == ("created", "existing")
    with world.factory.begin() as session:
        session.get(Job, first).status = "failed"
    with world.factory.begin() as session:
        _, how = djob.enqueue_document_extraction(
            session, world.definition["id"], link=link(), validators=validators
        )
    assert how == "existing"  # a recent failure rests
    with world.factory.begin() as session:
        session.get(Job, first).created_at = datetime.now(UTC) - timedelta(days=3)
    with world.factory.begin() as session:
        new_id, how = djob.enqueue_document_extraction(
            session, world.definition["id"], link=link(), validators=validators
        )
    assert how == "created" and new_id != first
    assert len(extraction_jobs(world)) == 2


def test_enqueue_refuses_a_disabled_source(world):
    with world.factory.begin() as session:
        session.get(Source, world.definition["id"]).enabled = False
    with pytest.raises(ValueError), world.factory.begin() as session:
        djob.enqueue_document_extraction(
            session, world.definition["id"], link=link(), validators=None
        )


# ------------------------------------------------------------------ the extraction job


def run_job(world, publisher: Publisher):
    use_publisher(world, publisher)
    report, _ = discover(world, publisher)
    (job,) = [j for j in extraction_jobs(world) if j.status == "queued"]
    lease(world, job.id)
    djob.process_document_extraction_job(job.id, WORKER, 1, deadline=None)
    return job.id


def test_job_extracts_stores_state_and_the_next_listing_folds_it(world):
    publisher = Publisher(portfolio([ELECTRIC]))
    job_id = run_job(world, publisher)
    with world.factory() as session:
        job = session.get(Job, job_id)
        assert job.status == "succeeded" and job.lease_owner is None
        body = json.loads(job.checkpoint)
        assert body["permit_document_stage_enabled"] is True
        assert body["outcome"] == "extracted" and body["content_sha256"]
        extraction = body["state"]["document"]["extraction"]
        assert extraction["verified_rows"] == 1 and extraction["schedule_text"]
        # Ships off: the pipeline ran with no proposer and no OCR, and records neither.
        assert "proposer" not in extraction and "ocr" not in extraction
        assert session.scalar(select(func.count()).select_from(Evidence)) == 0
        runs = session.get(Source, world.definition["id"]).health["document_stage"]["runs"]
        assert runs[-1]["mode"] == "document_extraction" and runs[-1]["docs"] == 1

    # The next listing run folds the finished state into evidence: no new download, no new job.
    before = len(publisher.requests)
    report, records = discover(world, publisher)
    assert report.counts["unchanged"] == 1 and len(extraction_jobs(world)) == 1
    assert publisher.requests[before:] == ["HEAD"]
    assert "Equipment ID" in records[0]["abstract"]
    with world.factory() as session:
        counts = process_records(
            session, world.ingestion_job, WORKER, 1, world.definition, records, allow_model=False
        )
        assert counts["permit_accepted"] == 1
        evidence = session.scalar(select(Evidence))
        assert evidence is not None and "Equipment ID" in (evidence.abstract or "")

    # Same version again: the finished job makes it a no-op.
    with world.factory.begin() as session:
        _, how = djob.enqueue_document_extraction(
            session,
            world.definition["id"],
            link=link(),
            validators=docs._validators(
                httpx.Headers(
                    {
                        "etag": '"v1"',
                        "last-modified": "Mon, 02 Nov 2026 10:00:00 GMT",
                        "content-length": str(len(publisher.body)),
                    }
                )
            ),
        )
    assert how == "existing"


def test_leased_document_job_without_captured_stage_permission_does_not_fetch(world):
    publisher = Publisher(portfolio([ELECTRIC]))
    use_publisher(world, publisher)
    discover(world, publisher)
    (job,) = extraction_jobs(world)
    with world.factory.begin() as session:
        queued = session.get(Job, job.id)
        body = json.loads(queued.checkpoint)
        body.pop("permit_document_stage_enabled")
        queued.checkpoint = json.dumps(body)
    lease(world, job.id)
    before = len(publisher.requests)
    djob.process_document_extraction_job(job.id, WORKER, 1, deadline=None)
    assert len(publisher.requests) == before
    with world.factory() as session:
        body = json.loads(session.get(Job, job.id).checkpoint)
    assert body["outcome"] == "undecided_disabled"


def test_current_stage_opt_out_vetoes_a_previously_authorized_leased_job(world):
    publisher = Publisher(portfolio([ELECTRIC]))
    use_publisher(world, publisher)
    discover(world, publisher)
    (job,) = extraction_jobs(world)
    world.monkeypatch.setattr(docs, "config_from_source", lambda _source: None)
    lease(world, job.id)
    before = len(publisher.requests)
    djob.process_document_extraction_job(job.id, WORKER, 1, deadline=None)
    assert len(publisher.requests) == before
    with world.factory() as session:
        body = json.loads(session.get(Job, job.id).checkpoint)
    assert body["outcome"] == "undecided_disabled"


class FakeProposer:
    def __init__(self) -> None:
        self.calls = 0

    def propose(self, pages, *, document_hash):
        self.calls += 1
        return ProposerOutcome("disabled", "FAKE")


def test_proposer_and_ocr_are_passed_from_the_leased_job_context(world):
    seen: dict = {}
    proposer = FakeProposer()

    def fake_proposer(source_id, job_id, worker_id, fence):
        seen["proposer_ctx"] = (source_id, worker_id, fence)
        return proposer

    def fake_ocr(path, url, source_id, job_id, worker_id, fence):
        seen["ocr"] = (url, source_id, worker_id, fence)
        return None  # OCR off for this document

    world.monkeypatch.setattr(djob, "_proposer", fake_proposer)
    world.monkeypatch.setattr(djob, "_ocr", fake_ocr)
    job_id = run_job(world, Publisher(portfolio([ELECTRIC])))
    assert seen["proposer_ctx"] == (world.definition["id"], WORKER, 1)
    assert seen["ocr"] == (BASE + "900001-tc.pdf", world.definition["id"], WORKER, 1)
    with world.factory() as session:
        body = json.loads(session.get(Job, job_id).checkpoint)
    # The proposer was handed to the pipeline (the rules found everything: not needed).
    assert body["state"]["document"]["extraction"]["proposer"]["status"] == "not_needed"
    assert proposer.calls == 0
    assert "capped_out" not in body


def test_real_hook_factories_return_none_while_the_settings_are_off(world):
    assert djob._proposer("s", None, WORKER, 1) is None
    assert djob._ocr("/x.pdf", BASE + "1-tc.pdf", "s", None, WORKER, 1) is None


def test_not_before_defers_the_job_without_a_request_or_a_spent_attempt(world):
    publisher = Publisher(portfolio([ELECTRIC]))
    use_publisher(world, publisher)
    discover(world, publisher)
    from gridlens.ingestion.tceq_document_stage import save_not_before

    until = datetime.now(UTC) + timedelta(hours=2)
    with world.factory.begin() as session:
        save_not_before(session, world.definition["id"], until)
    (job,) = extraction_jobs(world)
    lease(world, job.id)
    before = len(publisher.requests)
    djob.process_document_extraction_job(job.id, WORKER, 1, deadline=None)
    assert len(publisher.requests) == before
    with world.factory() as session:
        again = session.get(Job, job.id)
        assert again.status == "queued" and again.attempts == 0
        assert abs((again.available_at - until).total_seconds()) < 1
        assert json.loads(again.checkpoint)["outcome"] == "deferred_retry_after"


def test_a_publisher_rate_limit_requeues_at_the_retry_after_time(world):
    publisher = Publisher(portfolio([ELECTRIC]))
    use_publisher(world, publisher)
    discover(world, publisher)
    publisher.status = 429
    (job,) = extraction_jobs(world)
    lease(world, job.id)
    djob.process_document_extraction_job(job.id, WORKER, 1, deadline=None)
    with world.factory() as session:
        again = session.get(Job, job.id)
        assert again.status == "queued" and again.attempts == 0
        assert again.available_at > datetime.now(UTC) + timedelta(seconds=60)
        assert json.loads(again.checkpoint)["outcome"] == "rate_limited"
        assert (
            "application_documents_not_before" in session.get(Source, world.definition["id"]).health
        )


def test_a_retryable_failure_raises_for_the_workers_backoff(world):
    publisher = Publisher(portfolio([ELECTRIC]))
    use_publisher(world, publisher)
    discover(world, publisher)
    publisher.status = 500
    (job,) = extraction_jobs(world)
    lease(world, job.id)
    with pytest.raises(djob.DocumentExtractionRetry):
        djob.process_document_extraction_job(job.id, WORKER, 1, deadline=None)
    with world.factory() as session:
        assert session.get(Job, job.id).status == "running"  # the worker requeues it


def test_a_js_shell_is_a_visible_failed_state_not_a_retry(world):
    publisher = Publisher(b"<html><script>x()</script></html>")

    def shell(request):
        headers = {"content-type": "text/html", "content-length": "10"}
        return httpx.Response(200, headers=headers, content=b"")

    use_publisher(world, publisher)
    discover(world, Publisher(portfolio([ELECTRIC])))
    world.monkeypatch.setattr(
        docs.httpx,
        "Client",
        lambda **_kw: REAL_CLIENT(transport=httpx.MockTransport(shell), follow_redirects=False),
    )
    (job,) = extraction_jobs(world)
    lease(world, job.id)
    djob.process_document_extraction_job(job.id, WORKER, 1, deadline=None)
    with world.factory() as session:
        body = json.loads(session.get(Job, job.id).checkpoint)
        assert body["state"]["last_attempt"]["code"] == "js_shell"
        runs = session.get(Source, world.definition["id"]).health["document_stage"]["runs"]
        assert runs[-1]["failures"] == {"js_shell": 1}


def test_capped_out_extraction_jobs_are_counted_by_the_alert(world):
    body = json.dumps(
        {"capped_out": True, "cap_state": "CAPPED_OUT", "cap_pass": "ocr"},
        sort_keys=True,
        separators=(",", ":"),
    )
    with world.factory.begin() as session:
        session.add(
            Job(
                source_id=world.definition["id"],
                kind=djob.KIND,
                status="succeeded",
                checkpoint=body,
            )
        )
    with world.factory() as session:
        assert recent_capped_out_jobs(session)["jobs"] == 1


# ------------------------------------------------------------------ health findings from the DB


def test_document_report_reads_source_health_and_first_seen(world):
    now = datetime.now(UTC)
    run = {
        "at": now.isoformat(),
        "docs": 0,
        "in_scope": 6,
        "failures": {"js_shell": 3},
        "notices": {},
    }
    with world.factory.begin() as session:
        source = session.get(Source, world.definition["id"])
        source.health = {**source.health, "document_stage": {"runs": [run]}}
        session.add(
            Observation(
                source_id=source.id,
                external_id="TCEQ-1",
                title="t",
                url="https://example.test/1",
                content_hash="a" * 64,
                first_seen_at=now - timedelta(days=40),
            )
        )
    found = da.document_report(now)
    assert sorted(f.code for f in found) == [da.WRONG_CONTENT_TYPE, da.ZERO_NEW_RECORDS]
    assert all(f.source_id == world.definition["id"] for f in found)


# ------------------------------------------------------------------ timestamps and first signal


def test_tceq_timestamps_are_complete_and_first_seen_survives_a_changed_document(world):
    definition = world.definition
    publisher = Publisher(portfolio([ELECTRIC]))

    def ingest(pub: Publisher):
        use_publisher(world, pub)
        world.monkeypatch.setattr(settings, "document_extraction_jobs_enabled", False)
        report, records = discover(world, pub)
        with world.factory() as session:
            process_records(
                session, world.ingestion_job, WORKER, 1, definition, records, allow_model=False
            )
        return report

    ingest(publisher)
    with world.factory() as session:
        observation = session.scalar(select(Observation))
        first_seen = observation.first_seen_at
        evidence = session.scalar(select(Evidence))
        assert first_seen.tzinfo is not None and evidence.observed_at.tzinfo is not None
        assert evidence.published_at is None  # the publisher states none: never inferred
        assert evidence.event_date is not None
        assert evidence.provenance["application_document"]["dates"]["published_at_basis"]
    ingest(Publisher(portfolio([ELECTRIC + ["Standby unit: none."]]), etag='"v2"'))
    with world.factory() as session:
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(Observation.first_seen_at)) == first_seen
        stamps = session.execute(select(Evidence.observed_at, Evidence.event_date)).all()
        assert all(o is not None and e is not None for o, e in stamps)


def test_first_seen_cannot_be_rewritten(world):
    with world.factory.begin() as session:
        session.add(
            Observation(
                source_id=world.definition["id"],
                external_id="TCEQ-9",
                title="t",
                url="https://example.test/9",
                content_hash="b" * 64,
            )
        )
    with pytest.raises(ValueError, match="immutable"), world.factory.begin() as session:
        session.scalar(select(Observation)).first_seen_at = datetime(2020, 1, 1, tzinfo=UTC)
    with world.factory.begin() as session:  # other columns still update
        session.scalar(select(Observation)).title = "changed"


def test_first_signal_sample_lists_each_project_with_its_first_sighting(world):
    seen = datetime(2026, 10, 1, 8, tzinfo=UTC)
    with world.factory.begin() as session:
        observation = Observation(
            source_id=world.definition["id"],
            external_id="TCEQ-7",
            title="t",
            url="https://example.test/7",
            content_hash="c" * 64,
            first_seen_at=seen,
        )
        session.add(observation)
        session.flush()
        session.add(
            Evidence(
                observation_id=observation.id,
                content_hash="c" * 64,
                title="t",
                url="https://example.test/7",
                observed_at=seen + timedelta(minutes=5),
                event_date=datetime(2026, 9, 25).date(),
            )
        )
        session.add(
            Project(
                identity_key="tceq:7",
                name="Seven",
                source_id=world.definition["id"],
                external_id="TCEQ-7",
            )
        )
    with world.factory() as session:
        rows = first_signal_sample(session, source_ids=[world.definition["id"]])
        assert len(rows) == 1 and rows[0]["first_seen_at"] == seen
        assert rows[0]["first_evidence_observed_at"] == seen + timedelta(minutes=5)
        assert rows[0]["first_event_date"].isoformat() == "2026-09-25"
        assert first_signal_sample(session, since=seen + timedelta(days=1)) == []
    assert lead_time_days(seen, seen + timedelta(days=30)) == 30.0


def test_federal_register_timestamps_are_complete_and_first_seen_is_kept(world):
    from gridlens.ingestion.registry import load_registry
    from gridlens.ingestion.service import process_job

    definition = next(s for s in load_registry() if s["id"] == "federal-register-eis")
    with world.factory.begin() as session:
        session.add(
            Source(
                id=definition["id"],
                publisher=definition["publisher"],
                endpoint=definition["endpoint"],
                family=definition["family"],
                geography=definition["geography"],
                industries=definition["industries"],
                retrieval_method=definition["retrieval_method"],
                cadence_hours=definition["cadence_hours"],
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner="t",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    def run(abstract: str) -> None:
        row = {
            "document_number": "TEST-0001",
            "title": "Silver Ridge Mine: Synthetic Test Notice",
            "abstract": abstract,
            "publication_date": "2026-09-14",
            "html_url": "https://www.federalregister.gov/documents/2026/09/14/TEST-0001/x",
        }
        payload = {"total_pages": 1, "count": 1, "results": [row]}
        client = REAL_CLIENT(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
        )
        with world.factory() as session:
            process_job(session, job_id, "t", 1, definition, client)

    run("The proposed Mine Plan of Operations would develop the mine.")
    with world.factory() as session:
        first_seen = session.scalar(select(Observation.first_seen_at))
        assert session.scalar(select(Observation.published_at)) == datetime(2026, 9, 14).date()
        evidence = session.scalar(select(Evidence))
        assert evidence.published_at == datetime(2026, 9, 14).date()
        assert evidence.observed_at.tzinfo is not None and first_seen.tzinfo is not None
    run("The proposed Mine Plan of Operations would develop the mine and a new haul road.")
    with world.factory() as session:
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(Observation.first_seen_at)) == first_seen


# ------------------------------------------------------------------ review fixes


def finish_age(world, job_id, *, hours=0.0, days=0.0):
    """Pretend a finished job ended (and was created) this long ago."""
    ago = datetime.now(UTC) - timedelta(hours=hours, days=days)
    with world.factory.begin() as session:
        job = session.get(Job, job_id)
        body = json.loads(job.checkpoint)
        body["finished_at"] = ago.isoformat()
        job.checkpoint = json.dumps(body, sort_keys=True, separators=(",", ":"))
        job.created_at = ago


def current_validators(publisher):
    return docs._validators(
        httpx.Headers(
            {
                "etag": publisher.etag,
                "last-modified": "Mon, 02 Nov 2026 10:00:00 GMT",
                "content-length": str(len(publisher.body)),
            }
        )
    )


def enqueue_again(world, publisher):
    with world.factory.begin() as session:
        return djob.enqueue_document_extraction(
            session,
            world.definition["id"],
            link=link(),
            validators=current_validators(publisher),
        )


def test_a_fourth_attempt_that_is_backed_off_decides_nothing_and_is_requeued_later(world):
    publisher = Publisher(portfolio([ELECTRIC]))
    use_publisher(world, publisher)
    discover(world, publisher)
    (job,) = extraction_jobs(world)
    with world.factory.begin() as session:  # three counted environment failures on these bytes
        source = session.get(Source, world.definition["id"])
        source.health = {
            **source.health,
            "application_documents_attempts": {
                "900001": {
                    "code": "text_layer_memory_limit",
                    "attempts": 3,
                    "at": datetime.now(UTC).isoformat(),
                    "sha256": None,
                    "validators": current_validators(publisher),
                }
            },
        }
    lease(world, job.id)
    djob.process_document_extraction_job(job.id, WORKER, 1, deadline=None)
    with world.factory() as session:
        assert session.get(Job, job.id).status == "succeeded"
        body = json.loads(session.get(Job, job.id).checkpoint)
    assert body["outcome"] == "undecided_backed_off" and body["decided"] is False
    assert "state" not in body and body["rest_hours"] == 168
    assert enqueue_again(world, publisher)[1] == "existing"  # still resting
    finish_age(world, job.id, days=8)
    new_id, how = enqueue_again(world, publisher)
    assert how == "created" and new_id != job.id  # the version is tried again after the rest


def test_a_job_with_no_time_left_defers_and_is_requeued_after_its_rest(world):
    from time import monotonic

    publisher = Publisher(portfolio([ELECTRIC]))
    use_publisher(world, publisher)
    discover(world, publisher)
    (job,) = extraction_jobs(world)
    lease(world, job.id)
    before = len(publisher.requests)
    djob.process_document_extraction_job(job.id, WORKER, 1, deadline=monotonic() + 5)
    assert len(publisher.requests) == before  # no time even for a HEAD: nothing requested
    with world.factory() as session:
        body = json.loads(session.get(Job, job.id).checkpoint)
    assert body["outcome"].startswith("undecided_") and body["decided"] is False
    assert enqueue_again(world, publisher)[1] == "existing"
    finish_age(world, job.id, hours=30)
    assert enqueue_again(world, publisher)[1] == "created"


def test_pending_states_older_than_the_lookback_are_requeued_not_lost(world):
    publisher = Publisher(portfolio([ELECTRIC]))
    job_id = run_job(world, publisher)
    assert enqueue_again(world, publisher)[1] == "existing"
    with world.factory() as session:
        assert set(djob.load_pending_states(session, world.definition["id"])) == {"900001"}
    finish_age(world, job_id, days=djob.PENDING_DAYS + 1)
    with world.factory() as session:
        assert djob.load_pending_states(session, world.definition["id"]) == {}
    assert enqueue_again(world, publisher)[1] == "created"  # the unfolded state is produced again


def test_pending_states_are_one_newest_row_per_project(world):
    base = {"project": "900001", "outcome": "extracted", "decided": True}
    with world.factory.begin() as session:
        for index, sha in enumerate(("a", "b", "c")):
            session.add(
                Job(
                    source_id=world.definition["id"],
                    kind=djob.KIND,
                    status="succeeded",
                    created_at=datetime.now(UTC) - timedelta(hours=3 - index),
                    checkpoint=json.dumps({**base, "state": {"document": {"sha256": sha}}}),
                )
            )
    with world.factory() as session:
        got = djob.load_pending_states(session, world.definition["id"])
    assert list(got) == ["900001"] and got["900001"][0]["document"]["sha256"] == "c"


def test_budget_counts_created_jobs_only(world):
    report = docs.StageReport()
    first = link()
    other = replace(first, project="900002", url=BASE + "900002-tc.pdf")
    third = replace(first, project="900003", url=BASE + "900003-tc.pdf")
    with world.factory() as session:
        callback = djob.discovery_callback(session, world.definition["id"], report, limit=1)
        callback(first, {"etag": "a"})
        callback(first, {"etag": "a"})  # already queued: spends nothing
        callback(other, {"etag": "b"})  # the budget (1) is spent: deferred, not queued
        callback(third, {"etag": "c"})
    assert report.counts == {"enqueued": 1, "already_queued": 1, "deferred_enqueue_budget": 2}
    assert len(extraction_jobs(world)) == 1


def test_refresh_requests_are_coalesced_per_source(world):
    with world.factory.begin() as session:
        session.get(Job, world.ingestion_job).status = "succeeded"
    ids = []
    for etag in ("a", "b"):
        with world.factory.begin() as session:
            ids.append(
                djob.enqueue_document_extraction(
                    session, world.definition["id"], link=link(), validators={"etag": etag}
                )[0]
            )

    def queued_ingestion():
        with world.factory() as session:
            return session.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.kind == "ingestion", Job.status == "queued")
            )

    djob._request_refresh(world.definition["id"], ids[0])
    assert queued_ingestion() == 0  # a sibling job will ask when it finishes
    with world.factory.begin() as session:
        session.get(Job, ids[1]).status = "succeeded"
    djob._request_refresh(world.definition["id"], ids[0])
    assert queued_ingestion() == 1


def test_run_history_is_capped_per_mode(world):
    from gridlens.ingestion.document_health import record_run

    with world.factory.begin() as session:
        for index in range(5):
            record_run(session, world.definition["id"], {"mode": "discovery", "n": index})
        for index in range(45):
            record_run(session, world.definition["id"], {"mode": "document_extraction", "n": index})
    with world.factory() as session:
        runs = session.get(Source, world.definition["id"]).health["document_stage"]["runs"]
    assert sum(r["mode"] == "discovery" for r in runs) == 5  # not pushed out by job runs
    jobs = [r for r in runs if r["mode"] == "document_extraction"]
    assert len(jobs) == 30 and jobs[-1]["n"] == 44


def test_job_summaries_omit_the_listing_size():
    from gridlens.ingestion.document_health import build_run_summary

    at = datetime(2026, 11, 4, tzinfo=UTC)
    assert "in_scope" not in build_run_summary("document_extraction", {"in_scope": 1}, [], at=at)
    assert build_run_summary("discovery", {"in_scope": 7}, [], at=at)["in_scope"] == 7


def test_a_capped_out_pass_is_visible_on_a_real_job(world):
    from gridlens.ingestion.parsers.permit_docs.proposals import OcrOutcome

    class CappedOcr:
        def ocr_pages(self, pages, *, document_hash):
            return OcrOutcome(
                "capped_out",
                "CAP",
                {},
                "",
                {"cap_scope": "provider", "cap_period": "daily", "cap_reason": "daily_usd"},
            )

    world.monkeypatch.setattr(djob, "_ocr", lambda *a, **k: CappedOcr())
    # Page 2 has no text layer: the OCR pass is asked for it and is capped out.
    job_id = run_job(world, Publisher(portfolio([ELECTRIC, ["."]])))
    with world.factory() as session:
        body = json.loads(session.get(Job, job_id).checkpoint)
        assert body["capped_out"] is True and body["cap_pass"] == "ocr"
        assert body["cap_scope"] == "provider" and body["cap_period"] == "daily"
        assert recent_capped_out_jobs(session)["jobs"] == 1


def test_run_one_runs_the_new_kind_through_admission_and_the_generic_retry(world):
    import gridlens.jobs.worker as worker

    world.monkeypatch.setattr(worker, "SessionLocal", world.factory)
    publisher = Publisher(portfolio([ELECTRIC]))
    use_publisher(world, publisher)
    discover(world, publisher)
    (job,) = extraction_jobs(world)
    publisher.status = 500  # a retryable publisher failure
    assert worker.run_one({}, job_ids=[job.id]) is True
    with world.factory() as session:
        again = session.get(Job, job.id)
        assert again.status == "queued" and again.attempts == 1
        assert again.error == "DocumentExtractionRetry"
        assert again.available_at > datetime.now(UTC) + timedelta(seconds=5)
        assert again.lease_owner is None
        again.available_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    publisher.status = 200
    assert worker.run_one({}, job_ids=[job.id]) is True
    with world.factory() as session:
        done = session.get(Job, job.id)
        assert done.status == "succeeded" and done.attempts == 2
        assert json.loads(done.checkpoint)["outcome"] == "extracted"


def test_job_mode_and_inline_mode_produce_the_same_evidence_hashes(stage_db, monkeypatch):  # noqa: F811
    """Same publisher sequence, flag on versus off: identical source_hash at every step."""
    shell = Publisher(b"<html><script>x()</script></html>")
    shell.content_type = "text/html"
    steps = [
        Publisher(portfolio([ELECTRIC]), '"v1"'),
        Publisher(portfolio([ELECTRIC]), '"v2"'),  # same bytes, refreshed validators
        shell,  # the accepted schedule survives a script shell
    ]

    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _h: "8.8.8.8")
    monkeypatch.setattr(docs, "Pacer", lambda *a, **k: (lambda: None))
    monkeypatch.setattr(
        docs, "config_from_source", lambda _s: docs.StageConfig(1, 5, 120.0, isolate=False)
    )

    def sequence(factory, job_mode: bool):
        monkeypatch.setattr(settings, "document_extraction_jobs_enabled", job_mode)
        monkeypatch.setattr(djob, "SessionLocal", factory)
        monkeypatch.setattr(database, "SessionLocal", factory)
        definition, ingestion = setup_source(factory)
        world = SimpleNamespace(
            factory=factory,
            definition=definition,
            ingestion_job=ingestion,
            monkeypatch=monkeypatch,
        )
        seen, docs_per_run = [], []
        for publisher in steps:
            use_publisher(world, publisher)
            if job_mode:
                discover(world, publisher)
                for queued in [j for j in extraction_jobs(world) if j.status == "queued"]:
                    lease(world, queued.id)
                    djob.process_document_extraction_job(queued.id, WORKER, 1, deadline=None)
            _, records = discover(world, publisher)
            with factory() as session:
                process_records(
                    session, ingestion, WORKER, 1, definition, records, allow_model=False
                )
            seen.append((records[0]["source_hash"], records[0]["abstract"]))
            with factory() as session:
                runs = session.get(Source, definition["id"]).health["document_stage"]["runs"]
            docs_per_run.append(
                sum(r["docs"] for r in runs if r["mode"] in {"inline", "discovery"})
            )
        return seen, docs_per_run

    schema_b = "ws6_equiv_" + uuid4().hex
    target = make_url(settings.test_database_url)
    admin = create_engine(target)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_b}"'))
    engine_b = create_engine(target, connect_args={"options": f"-csearch_path={schema_b}"})
    Base.metadata.create_all(engine_b)
    try:
        inline, inline_docs = sequence(stage_db, False)
        jobbed, job_docs = sequence(sessionmaker(engine_b, expire_on_commit=False), True)
    finally:
        engine_b.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema_b}" CASCADE'))
        admin.dispose()
    assert len({h for h, _ in inline}) == 3  # each step really is a distinct evidence version
    assert jobbed == inline
    # Copies of an accepted state (unchanged bytes, failed attempt) are not new documents.
    assert inline_docs == [1, 1, 1] and job_docs == [0, 0, 0]
