"""Synthetic NMED application -> document stage -> ingestion service -> Evidence/provenance.

Disposable test database only (TEST_DATABASE_URL must end in _test). HTTP is a MockTransport.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))

from _nmed_fixtures import (  # noqa: E402
    ELECTRIC_PROSE,
    GENERATOR_ONLY,
    Origin,
    application_pdf,
    url,
)

import gridlens.ingestion.adapters.nmed_application_documents as nad  # noqa: E402
from gridlens.ingestion.registry import load_registry  # noqa: E402
from gridlens.persistence.database import Base  # noqa: E402
from gridlens.persistence.models import Evidence, Job, Observation, Source  # noqa: E402
from gridlens.settings import settings  # noqa: E402

WORKER = "nmed-documents-worker"
DOC = url()
CONFIG = nad.StageConfig(max_downloads=2, max_checks=10, extract_seconds=120.0, isolate=False)


@pytest.fixture
def stage_db():
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    schema = "nmed_documents_" + uuid4().hex
    admin = create_engine(target)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(target, connect_args={"options": f"-csearch_path={schema}"})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _host: "8.8.8.8")
    monkeypatch.setattr(nad, "Pacer", lambda *a, **k: (lambda: None))  # pacing is unit-tested


def setup_source(factory):
    definition = next(row for row in load_registry() if row["id"] == nad.SOURCE_ID)
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
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner=WORKER,
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        return definition, job.id


def ingest(factory, definition, job_id, origin, monkeypatch, urls=(DOC,), config=CONFIG) -> dict:
    """Mirror process_job's order: stage over the retrieved records, then process_records."""
    from gridlens.ingestion.service import _enrich_with_application_documents, process_records

    monkeypatch.setattr(nad, "config_from_source", lambda _source: config)
    records = [nad.record_for(item) for item in urls]
    with factory() as session:
        report = _enrich_with_application_documents(
            session, job_id, WORKER, 1, definition, records, origin.client(), deadline=None
        )
        session.commit()
    with factory() as session:
        counts = process_records(session, job_id, WORKER, 1, definition, records, allow_model=False)
    return {"report": report, "counts": counts, "records": records}


def test_document_flows_to_evidence_with_provenance_and_replays_idempotently(stage_db, monkeypatch):
    definition, job_id = setup_source(stage_db)
    origin = Origin()
    origin.put(DOC, application_pdf())
    outcome = ingest(stage_db, definition, job_id, origin, monkeypatch)
    assert outcome["report"].counts["new"] == 1 and outcome["report"].rejections == []
    assert outcome["counts"]["new"] == 1

    with stage_db() as session:
        observation = session.scalar(select(Observation))
        evidence = session.scalar(select(Evidence))
        assert observation is not None and evidence is not None
        assert "Equipment ID" in (evidence.abstract or "")
        assert evidence.url == DOC and str(evidence.published_at) == "2025-01-01"
        assert observation.first_seen_at is not None and evidence.observed_at is not None
        state = evidence.provenance["nmed_document"]
        assert state["url"] == DOC and state["upload_month"] == "2025-01"
        document = state["document"]
        assert document["extraction"]["line_provenance"]
        for entry in document["extraction"]["line_provenance"].values():
            assert entry["outer_sha256"] == document["sha256"] and entry["page"] >= 1
        # Anything without a stated electric drive is supply, never demand.
        assert document["extraction"]["supply_total"] >= 2
        assert all(row.get("drive") != "electric" for row in document["extraction"]["supply"])
        first_seen = observation.first_seen_at
        index = session.get(Source, nad.SOURCE_ID).health["nmed_documents"]["urls"]
        assert index[DOC]["status"] == "document"

    replay = ingest(stage_db, definition, job_id, origin, monkeypatch)
    assert replay["counts"]["new"] == 0 and replay["counts"]["unchanged"] == 1
    assert replay["report"].counts["unchanged"] == 1
    assert origin.methods().count("GET") == 1  # the PDF was downloaded once
    with stage_db() as session:
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.scalar(select(Observation.first_seen_at)) == first_seen


def test_changed_bytes_add_an_evidence_version_and_keep_the_earlier_one(stage_db, monkeypatch):
    definition, job_id = setup_source(stage_db)
    origin = Origin()
    origin.put(DOC, application_pdf(ELECTRIC_PROSE))
    ingest(stage_db, definition, job_id, origin, monkeypatch)
    origin.put(DOC, application_pdf(ELECTRIC_PROSE, GENERATOR_ONLY), etag='"e2"')
    second = ingest(stage_db, definition, job_id, origin, monkeypatch)
    assert second["counts"]["changed"] == 1
    with stage_db() as session:
        evidence = session.scalars(select(Evidence).order_by(Evidence.observed_at)).all()
        assert len(evidence) == 2
        old, new = (e.provenance["nmed_document"] for e in evidence)
        assert new["document"]["replaced_sha256"] == [old["document"]["sha256"]]
        assert new["first_seen_at"] == old["first_seen_at"]
        assert session.scalar(select(func.count()).select_from(Observation)) == 1


def test_generator_only_document_is_supply_and_an_abstention(stage_db, monkeypatch):
    definition, job_id = setup_source(stage_db)
    origin = Origin()
    origin.put(DOC, application_pdf(GENERATOR_ONLY))
    outcome = ingest(stage_db, definition, job_id, origin, monkeypatch)
    assert outcome["counts"]["new"] == 1
    with stage_db() as session:
        evidence = session.scalar(select(Evidence))
        assert evidence is not None and "Equipment ID" not in (evidence.abstract or "")
        document = evidence.provenance["nmed_document"]["document"]
        assert document["abstain"]["reason"] == "no equipment schedule found"
        assert document["extraction"]["supply"][0]["equipment_type"] == "generator"


def test_process_job_ships_off_and_makes_no_document_request(stage_db, monkeypatch):
    import gridlens.ingestion.service as service

    definition, job_id = setup_source(stage_db)
    assert definition["enabled"] is False
    assert definition["query"]["application_documents"]["enabled"] is False
    origin = Origin()
    origin.put(DOC, application_pdf())
    monkeypatch.setattr(service, "retrieve_source", lambda *_a, **_k: [nad.record_for(DOC)])
    with stage_db() as session:
        counts = service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert counts["new"] == 1 and "application_documents" not in counts
    assert origin.log == []
    with stage_db() as session:
        evidence = session.scalar(select(Evidence))
        assert evidence is not None and "nmed_document" not in evidence.provenance
        assert "Equipment ID" not in (evidence.abstract or "")


def test_process_job_reports_failures_as_partial_without_blocking_the_listing(
    stage_db, monkeypatch
):
    import gridlens.ingestion.service as service

    definition, job_id = setup_source(stage_db)
    monkeypatch.setattr(nad, "config_from_source", lambda _s: CONFIG)
    monkeypatch.setattr(service, "retrieve_source", lambda *_a, **_k: [nad.record_for(DOC)])
    origin = Origin()
    origin.put(DOC, b"<html><script>shell()</script></html>", ctype="text/html")
    with stage_db() as session:
        counts = service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert counts["new"] == 1
    assert counts["partial"] is True and counts["parse_failures"] == 1
    assert counts["rejected_records"][0]["error_code"] == "js_shell"
    assert counts["rejected_records"][0]["stage"] == "nmed_document"
    assert counts["application_documents"]["failure_js_shell"] == 1
    assert "collection_status" not in counts  # the listing's cooldown state is not moved


def test_429_rests_the_stage_across_runs_through_source_health(stage_db, monkeypatch):
    definition, job_id = setup_source(stage_db)
    origin = Origin()
    origin.put(DOC, application_pdf())
    origin.head_status = 429
    first = ingest(stage_db, definition, job_id, origin, monkeypatch)
    assert first["report"].counts["aborted_rate_limited"] == 1
    assert [r["error_code"] for r in first["report"].rejections] == ["http_status_429"]
    with stage_db() as session:
        health = session.get(Source, nad.SOURCE_ID).health["nmed_documents"]
        assert "not_before" in health
    origin.head_status = None
    origin.log.clear()
    second = ingest(stage_db, definition, job_id, origin, monkeypatch)
    assert second["report"].counts["skipped_retry_after"] == 1
    assert origin.log == []  # no request while Retry-After has not passed


def test_stage_fault_is_a_typed_error_and_the_listing_still_ingests(stage_db, monkeypatch):
    import gridlens.ingestion.service as service

    definition, job_id = setup_source(stage_db)
    monkeypatch.setattr(nad, "config_from_source", lambda _s: CONFIG)
    monkeypatch.setattr(service, "retrieve_source", lambda *_a, **_k: [nad.record_for(DOC)])

    def boom(*_a, **_k):
        raise RuntimeError("SECRET detail that must not be stored")

    monkeypatch.setattr(nad, "run_stage", boom)
    with stage_db() as session:
        counts = service.process_job(session, job_id, WORKER, 1, definition, Origin().client())
    assert counts["new"] == 1 and counts["partial"] is True
    error = counts["rejected_records"][0]
    assert error["error_code"] == "stage_error" and error["raw"] == {"error": "RuntimeError"}
    assert "SECRET" not in repr(counts)


def test_a_real_listing_429_stores_not_before_and_the_next_run_skips_the_listing(
    stage_db, monkeypatch
):
    import gridlens.ingestion.service as service
    from gridlens.ingestion.adapters.federal_register import SourceParseError

    definition, job_id = setup_source(stage_db)
    origin = Origin()
    origin.listing = (429, {"retry-after": "600"}, b"")
    with stage_db() as session, pytest.raises(SourceParseError) as raised:
        service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert raised.value.acquisition_code == "http_status_429"
    assert raised.value.acquisition_retry_after_seconds == 600
    assert len(origin.log) == 1
    with stage_db() as session:
        health = session.get(Source, nad.SOURCE_ID).health["nmed_documents"]
        until = datetime.fromisoformat(health["not_before"])
    assert timedelta(seconds=540) < until - datetime.now(UTC) <= timedelta(seconds=600)

    # While not_before is in the future the listing is not requested at all.
    with stage_db() as session, pytest.raises(SourceParseError) as resting:
        service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert resting.value.acquisition_code == "http_status_429"
    assert len(origin.log) == 1  # no second request

    # After it passes the listing is read again.
    with stage_db.begin() as session:
        source = session.get(Source, nad.SOURCE_ID)
        health = dict(source.health)
        health["nmed_documents"] = {
            **health["nmed_documents"],
            "not_before": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        }
        source.health = health
    origin.listing = (200, {"content-type": "text/html"}, b"<html></html>")
    with stage_db() as session:
        service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert len(origin.log) == 2
