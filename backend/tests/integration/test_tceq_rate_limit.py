from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.registry import load_registry
from gridlens.persistence.database import Base
from gridlens.persistence.models import Evidence, Job, Observation, Source
from gridlens.settings import settings


def _pdf_response(status: int = 200, retry_after: str | None = None) -> httpx.Response:
    headers = {"content-type": "application/pdf"}
    if retry_after is not None:
        headers["retry-after"] = retry_after
    return httpx.Response(status, headers=headers, content=b"%PDF-1.7 test")


def _install_public_ip(monkeypatch):
    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _host: "8.8.8.8")


def _nsr_rows():
    return [
        {
            "project": str(index),
            "applicant": "Example Power LLC",
            "facility": f"EXAMPLE DATA CENTER {index}",
            "permits": [f"18{index:04d}"],
            "received": date(2026, 10, 20 - index),
            "application_stage": "Initial Application",
            "notice_url": f"https://www.tceq.texas.gov/notice#{index}",
            "application_url": f"https://www.tceq.texas.gov/assets/public/permitting/air/reports/applications/{index}-ac.pdf",
            "notice_href": f"/notice#{index}",
            "application_href": (
                f"/assets/public/permitting/air/reports/applications/{index}-ac.pdf"
            ),
        }
        for index in (1, 2, 3)
    ]


def test_nsr_rate_limit_keeps_valid_prefix_and_defers_later_documents(monkeypatch):
    import gridlens.ingestion.adapters.tceq_nsr_pending as adapter

    _install_public_ip(monkeypatch)
    rows = _nsr_rows()
    monkeypatch.setattr(adapter, "parse_listing", lambda *_args, **_kwargs: rows)
    monkeypatch.setattr(
        adapter,
        "parse_summary",
        lambda *_args: {
            "city": "Austin",
            "county": "Travis",
            "latitude": 30.2672,
            "longitude": -97.7431,
            "purpose": "New power generation for a data center campus.",
            "text": "Verified Texas data center power generation project.",
        },
    )
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == httpx.URL(adapter.LISTING_URL).path:
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"rows")
        return _pdf_response(200) if len(requested) == 2 else _pdf_response(429, "120")

    request_started_at = datetime.now(UTC)
    records = adapter.retrieve(
        {"id": adapter.SOURCE_ID, "endpoint": adapter.LISTING_URL, "query": {"max_summaries": 3}},
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert len(requested) == 3  # listing, first success, second throttled; no third PDF request
    assert records[0]["permit"]["summary_fetched"] is True
    assert records[1]["presence_only"] is True
    diagnostics = records[1]["_acquisition_diagnostics"]
    assert diagnostics["retry_after_seconds"] == 120
    assert diagnostics["http_status"] == 429
    retry_at = datetime.fromisoformat(diagnostics["retry_after_at"])
    assert request_started_at + timedelta(seconds=120) <= retry_at
    assert retry_at <= datetime.now(UTC) + timedelta(seconds=120)
    assert records[2]["presence_only"] is True
    assert records[2]["rejected_record"]["error_code"] == "document_deferred"


def test_temporary_batch_rate_limit_stops_later_notice_requests(monkeypatch):
    import gridlens.ingestion.adapters.tceq_temporary_batch as adapter

    _install_public_ip(monkeypatch)
    rows = [
        {
            "project": str(index),
            "applicant": "Example Ready Mix",
            "facility": f"DATA CENTER TEMPORARY CONCRETE BATCH PLANT {index}",
            "registration": f"173154L00{index}",
        }
        for index in (1, 2, 3)
    ]
    monkeypatch.setattr(adapter, "parse_listing", lambda *_args: rows)
    monkeypatch.setattr(
        adapter,
        "parse_notice",
        lambda *_args: {
            "city": "Austin",
            "county": "Travis",
            "latitude": 30.2672,
            "longitude": -97.7431,
            "submitted": "2026-10-01",
            "issued": "2026-10-02",
            "text": "Temporary batch plant notice.",
        },
    )
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == httpx.URL(adapter.LISTING_URL).path:
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"rows")
        return _pdf_response(200) if len(requested) == 2 else _pdf_response(429, "120")

    records = adapter.retrieve(
        {"id": adapter.SOURCE_ID, "endpoint": adapter.LISTING_URL, "query": {"max_notices": 3}},
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert len(requested) == 3
    assert records[0]["permit"]["registration"] == "173154L001"
    assert records[1]["_acquisition_diagnostics"]["retry_after_seconds"] == 120
    assert records[2]["rejected_record"]["error_code"] == "document_deferred"


def test_retry_after_over_bound_preserves_scheduled_deadline(monkeypatch):
    import gridlens.ingestion.adapters.tceq_nsr_pending as adapter

    _install_public_ip(monkeypatch)
    monkeypatch.setattr(adapter, "parse_listing", lambda *_args, **_kwargs: _nsr_rows())
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path == httpx.URL(adapter.LISTING_URL).path:
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"rows")
        return _pdf_response(429, "604801")

    records = adapter.retrieve(
        {"id": adapter.SOURCE_ID, "endpoint": adapter.LISTING_URL, "query": {"max_summaries": 3}},
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert calls == 2
    assert records[0]["_acquisition_diagnostics"]["retry_after_exceeds_bound"] == 1
    assert datetime.fromisoformat(
        records[0]["_acquisition_diagnostics"]["retry_after_at"]
    ) >= datetime.now(UTC) + timedelta(days=7)


@pytest.fixture
def regional_db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    definition = next(item for item in load_registry() if item["id"] == "texas-tceq-nsr-pending")
    with factory.begin() as session:
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
                health={
                    "last_success": "2026-10-21T12:00:00+00:00",
                    "last_success_counts": {"new_records": 9, "changed_records": 2},
                },
            )
        )
        session.flush()
        job = Job(
            source_id=definition["id"],
            status="queued",
            available_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    yield factory, definition, job_id
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.mark.parametrize(
    ("retry_after", "expected_state"),
    [
        ("120", "scheduled"),
        ("604801", "scheduled"),
        ("9" * 128, "retry_after_unrepresentable"),
        (None, "scheduled"),
    ],
)
def test_worker_preserves_partial_source_cooldown_and_prefix(
    regional_db, monkeypatch, retry_after, expected_state
):
    import gridlens.ingestion.adapters.tceq_nsr_pending as adapter
    import gridlens.ingestion.registry as registry
    import gridlens.ingestion.service as service
    import gridlens.jobs.worker as worker
    from gridlens.jobs.queue import enqueue, lease_one

    _install_public_ip(monkeypatch)
    request_started_at = datetime.now(UTC)
    rows = _nsr_rows()
    monkeypatch.setattr(adapter, "parse_listing", lambda *_args, **_kwargs: rows)
    monkeypatch.setattr(
        adapter,
        "parse_summary",
        lambda *_args: {
            "city": "Austin",
            "county": "Travis",
            "latitude": 30.2672,
            "longitude": -97.7431,
            "purpose": "New power generation for a data center campus.",
            "text": "Verified Texas data center power generation project.",
        },
    )
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path == httpx.URL(adapter.LISTING_URL).path:
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"rows")
        return _pdf_response(200) if calls == 2 else _pdf_response(429, retry_after)

    with httpx.Client(transport=httpx.MockTransport(handler)) as mock_client:
        acquired = adapter.retrieve(
            {
                "id": adapter.SOURCE_ID,
                "endpoint": adapter.LISTING_URL,
                "query": {"max_summaries": 3},
            },
            mock_client,
        )
    request_finished_at = datetime.now(UTC)
    assert len(acquired) == 3 and calls == 3
    monkeypatch.setattr(service, "retrieve_source", lambda *_args, **_kwargs: acquired)
    monkeypatch.setattr(worker, "load_registry", lambda: [regional_db[1]])
    monkeypatch.setattr(registry, "load_registry", lambda: [regional_db[1]])
    monkeypatch.setattr(worker, "SessionLocal", regional_db[0])
    monkeypatch.setattr(worker, "WORKER_ID", "rate-limit-test-worker")

    class Admission:
        def __enter__(self):
            return True

        def __exit__(self, *_args):
            return False

    class NoopRenewer:
        def __init__(self, *_args):
            pass

        def start(self):
            return self

        def stop(self):
            return None

    monkeypatch.setattr(worker, "try_public_acquisition_admission", lambda *_args: Admission())
    monkeypatch.setattr(worker, "FencedLeaseRenewer", NoopRenewer)
    worked = worker.run_one({regional_db[1]["id"]: regional_db[1]}, job_ids=[regional_db[2]])
    assert worked, f"worker did not lease job {regional_db[2]} with Retry-After={retry_after}"

    with regional_db[0]() as session:
        source = session.get(Source, regional_db[1]["id"])
        finished_job = session.get(Job, regional_db[2])
        assert finished_job.status == "succeeded"
        assert source.health["retry_state"] == expected_state
        assert source.health["last_success"] == "2026-10-21T12:00:00+00:00"
        assert source.health["last_success_counts"] == {"new_records": 9, "changed_records": 2}
        assert source.health["attempt_new"] == 1
        assert source.health["attempt_processed"] == 1
        assert source.health["attempt_fetched"] == 3
        assert source.health["attempt_rejected"] == 2
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        if retry_after in {"120", "604801"}:
            retry_at = datetime.fromisoformat(source.health["retry_at"])
            delay = timedelta(seconds=int(retry_after))
            # Preserve the exact request-time deadline across later worker latency.
            assert request_started_at + delay <= retry_at <= request_finished_at + delay
        elif expected_state == "retry_after_unrepresentable":
            assert source.health["retry_at"] is None
        else:
            retry_at = datetime.fromisoformat(source.health["retry_at"])
            assert datetime.now(UTC) < retry_at < datetime.now(UTC) + timedelta(hours=1)

        queued_id = enqueue(session, source.id)
        queued = session.get(Job, queued_id)
        if expected_state == "retry_after_unrepresentable":
            assert queued.available_at.year == 9999
            assert lease_one(session, "test-worker", job_ids=[queued_id]) is None
        else:
            assert queued.available_at >= retry_at
            assert lease_one(session, "test-worker", job_ids=[queued_id]) is None
            # Advance the persisted boundary explicitly; the source and queued job become leasable.
            source.health = {
                **source.health,
                "retry_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            }
            queued.available_at = datetime.now(UTC) - timedelta(seconds=1)
            assert lease_one(session, "test-worker", job_ids=[queued_id]) is not None

    with regional_db[0].begin() as session:
        job = session.get(Job, regional_db[2])
        job.status = "running"
        job.lease_owner = "test"
        job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
    with regional_db[0]() as session:
        replay = service.process_records(
            session,
            regional_db[2],
            "test",
            job.fence,
            regional_db[1],
            acquired[:1],
            allow_model=False,
        )
        assert replay["new"] == 0 and replay["unchanged"] == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
    with regional_db[0].begin() as session:
        job = session.get(Job, regional_db[2])
        job.status = "succeeded"
