from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from db_reset import reset_test_database
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.registry import load_registry
from gridlens.ingestion.service import process_job, process_records
from gridlens.persistence.models import Evidence, Job, Observation, Source
from gridlens.settings import settings


@pytest.fixture
def acquisition_db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    engine = __import__("sqlalchemy").create_engine(settings.test_database_url)
    reset_test_database(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    definition = next(item for item in load_registry() if item["id"] == "federal-register-eis")
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
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner="test-acquisition",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    yield factory, definition, job_id
    engine.dispose()


def _row(external_id: str, abstract: str) -> dict:
    return {
        "document_number": external_id,
        "title": f"Silver Ridge Mine: Synthetic Test Notice {external_id}",
        "abstract": abstract,
        "publication_date": "2026-10-01",
        "html_url": f"https://www.federalregister.gov/documents/{external_id}",
    }


@pytest.mark.parametrize("method", ["json-api", "publisher-rss"])
@pytest.mark.parametrize("change", ["disabled", "endpoint"])
def test_source_update_succeeds_during_acquisition_and_stale_result_is_not_written(
    acquisition_db, monkeypatch, method, change
):
    factory, original_definition, job_id = acquisition_db
    import gridlens.ingestion.service as service

    definition = {**original_definition, "retrieval_method": method}
    with factory.begin() as session:
        source = session.get(Source, definition["id"])
        assert source
        source.retrieval_method = method

    previous = _row("LAST-GOOD", "Prior retained source evidence.")
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [previous])
    with factory() as session:
        process_job(session, job_id, "test-acquisition", 1, definition)

    entered = Event()
    release = Event()

    def blocked_retrieval(*_args):
        entered.set()
        assert release.wait(5), "test did not release blocked acquisition"
        return [_row("NEW-UNCOMMITTED", "Replacement source evidence.")]

    monkeypatch.setattr(service, "retrieve_source", blocked_retrieval)

    def acquire():
        with factory() as session:
            return process_job(session, job_id, "test-acquisition", 1, definition)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(acquire)
        try:
            assert entered.wait(3), "acquisition did not reach network retrieval"
            with factory.begin() as operator:
                operator.execute(text("SET LOCAL lock_timeout = '700ms'"))
                source = operator.get(Source, definition["id"])
                assert source
                if change == "disabled":
                    source.enabled = False
                else:
                    source.endpoint = "https://example.test/reconfigured-source"
        finally:
            release.set()
        with pytest.raises(SourceParseError, match="source"):
            future.result(timeout=6)

    with factory() as session:
        observation = session.scalar(select(Observation))
        assert observation and observation.external_id == "LAST-GOOD"
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1


@pytest.mark.parametrize("method", ["json-api", "publisher-rss"])
def test_stale_fence_after_acquisition_blocks_all_retrieved_records(
    acquisition_db, monkeypatch, method
):
    factory, original_definition, job_id = acquisition_db
    import gridlens.ingestion.service as service

    definition = {**original_definition, "retrieval_method": method}
    with factory.begin() as session:
        source = session.get(Source, definition["id"])
        assert source
        source.retrieval_method = method
    entered = Event()
    release = Event()

    def blocked_retrieval(*_args):
        entered.set()
        assert release.wait(5), "test did not release blocked acquisition"
        return [_row("STALE-LEASE-RECORD", "Must not be retained after fence loss.")]

    monkeypatch.setattr(service, "retrieve_source", blocked_retrieval)

    def acquire():
        with factory() as session:
            return process_job(session, job_id, "test-acquisition", 1, definition)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(acquire)
        try:
            assert entered.wait(3), "acquisition did not reach network retrieval"
            with factory.begin() as replacement:
                replacement.execute(text("SET LOCAL lock_timeout = '700ms'"))
                job = replacement.get(Job, job_id)
                assert job
                job.fence += 1
                job.lease_owner = "replacement-worker"
        finally:
            release.set()
        with pytest.raises(RuntimeError, match="fence lost"):
            future.result(timeout=6)

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 0
        assert session.scalar(select(func.count()).select_from(Evidence)) == 0


def test_deadline_expiry_after_retrieval_preserves_last_good_evidence_and_checkpoint(
    acquisition_db, monkeypatch
):
    factory, definition, job_id = acquisition_db
    import gridlens.ingestion.service as service

    last_good = _row("LAST-GOOD-DEADLINE", "Previously retained evidence remains current.")
    monkeypatch.setattr(service, "retrieve_source", lambda *_args, **_kwargs: [last_good])
    with factory() as session:
        process_job(session, job_id, "test-acquisition", 1, definition)
        session.commit()
    with factory.begin() as session:
        job = session.get(Job, job_id)
        assert job
        job.checkpoint = "last-good-checkpoint"

    replacement = _row("UNCOMMITTED-NEW-RECORD", "Must remain unretained after deadline.")
    calls = []

    def retrieved(*_args, **_kwargs):
        calls.append("retrieved")
        return [replacement]

    def deadline_check(_deadline):
        calls.append("deadline")
        if calls.count("deadline") == 2:
            raise TimeoutError("synthetic monotonic deadline expired")

    monkeypatch.setattr(service, "retrieve_source", retrieved)
    monkeypatch.setattr(service, "remaining_seconds", deadline_check)
    with factory() as session:
        with pytest.raises(TimeoutError, match="deadline expired"):
            process_job(
                session,
                job_id,
                "test-acquisition",
                1,
                definition,
                deadline=10.0,
                lease_expiry=datetime.now(UTC) + timedelta(minutes=10),
            )

    with factory() as session:
        observation = session.scalar(select(Observation))
        assert observation and observation.external_id == "LAST-GOOD-DEADLINE"
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.get(Job, job_id).checkpoint == "last-good-checkpoint"
    assert calls == ["deadline", "retrieved", "deadline"]


def test_source_update_succeeds_during_companion_retrieval_and_stale_pdf_is_discarded(
    acquisition_db, monkeypatch
):
    factory, definition, job_id = acquisition_db
    import gridlens.ingestion.service as service

    source_record = _row(
        "COMPANION-LOCK",
        "The proposed Mine Plan of Operations would develop the mine, with dewatering "
        "and ventilation shafts.",
    )
    source_record["pdf_url"] = (
        "https://www.govinfo.gov/content/pkg/FR-2099-01-01/pdf/2099-01001.pdf"
    )
    monkeypatch.setattr(service, "retrieve_source", lambda *_args: [source_record])
    entered = Event()
    release = Event()

    def blocked_companion(*_args):
        entered.set()
        assert release.wait(5), "test did not release blocked companion retrieval"
        return [
            {
                "content_hash": "f" * 64,
                "title": "GovInfo companion",
                "abstract": "Stale companion citation",
                "url": source_record["pdf_url"],
                "extraction_location": "GovInfo PDF page 1",
            }
        ]

    monkeypatch.setattr(service, "retrieve_companion", blocked_companion)

    def acquire():
        with factory() as session:
            return process_job(session, job_id, "test-acquisition", 1, definition)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(acquire)
        try:
            assert entered.wait(3), "companion retrieval did not begin"
            with factory.begin() as operator:
                operator.execute(text("SET LOCAL lock_timeout = '700ms'"))
                source = operator.get(Source, definition["id"])
                assert source
                source.endpoint = "https://example.test/reconfigured-source"
        finally:
            release.set()
        with pytest.raises(SourceParseError, match="endpoint"):
            future.result(timeout=6)

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        evidence = list(session.scalars(select(Evidence)))
        assert len(evidence) == 1
        assert evidence[0].content_hash != "f" * 64


def test_commit_false_skips_companion_network_without_committing_callers_transaction(
    acquisition_db, monkeypatch
):
    factory, definition, job_id = acquisition_db
    import gridlens.ingestion.service as service

    row = _row(
        "CALLER-TRANSACTION",
        "The proposed Mine Plan of Operations would develop the mine, with dewatering "
        "and ventilation shafts.",
    )
    row["pdf_url"] = "https://www.govinfo.gov/content/pkg/FR-2099-01-01/pdf/test.pdf"
    monkeypatch.setattr(
        service,
        "retrieve_companion",
        lambda *_args: pytest.fail("commit=False must not start companion network retrieval"),
    )
    session = factory()
    try:
        session.execute(text("SET LOCAL lock_timeout = '700ms'"))
        result = process_records(
            session,
            job_id,
            "test-acquisition",
            1,
            definition,
            [row],
            commit=False,
            allow_model=False,
        )
        assert result["pdf_skipped_transaction"] == 1
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        with factory() as observer:
            assert observer.scalar(select(func.count()).select_from(Observation)) == 0
    finally:
        session.rollback()
        session.close()

    with factory() as observer:
        assert observer.scalar(select(func.count()).select_from(Observation)) == 0


@pytest.mark.parametrize("caller_state", ["dirty", "nested"])
def test_source_acquisition_rejects_caller_owned_pending_transactions(
    acquisition_db, monkeypatch, caller_state
):
    factory, definition, job_id = acquisition_db
    import gridlens.ingestion.service as service

    monkeypatch.setattr(
        service,
        "retrieve_source",
        lambda *_args: pytest.fail("unsafe caller transaction must be rejected before network"),
    )
    with factory() as session:
        source = session.get(Source, definition["id"])
        assert source
        if caller_state == "dirty":
            source.publisher = "uncommitted caller edit"
            with pytest.raises(RuntimeError, match="clean, non-nested"):
                process_job(session, job_id, "test-acquisition", 1, definition)
        else:
            with session.begin_nested():
                with pytest.raises(RuntimeError, match="clean, non-nested"):
                    process_job(session, job_id, "test-acquisition", 1, definition)
        session.rollback()
    with factory() as observer:
        source = observer.get(Source, definition["id"])
        assert source and source.publisher == definition["publisher"]
