"""Synthetic OK DEQ memo -> document stage -> ingestion service -> EvidencePackage.

Disposable test database only (TEST_DATABASE_URL must end in _test). HTTP is a MockTransport.
"""

from __future__ import annotations

import dataclasses
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))

from _okdeq_fixtures import (  # noqa: E402
    GENERATORS,
    WEST_EDMOND_PROSE,
    Origin,
    listing_record,
    memo_pdf,
)

import gridlens.ingestion.adapters.ok_deq_documents as okd  # noqa: E402
from gridlens.ingestion.registry import load_registry  # noqa: E402
from gridlens.persistence.database import Base  # noqa: E402
from gridlens.persistence.models import (  # noqa: E402
    Evidence,
    EvidencePackage,
    Job,
    Observation,
    PowerNeed,
    Source,
)
from gridlens.settings import settings  # noqa: E402

# Admission needs a stated event date (a public-comment window start); the stage does not
# change that rule, so rows without one keep the document as evidence only.
COMMENT_START = "2026-10-04"
WORKER = "okdeq-documents-worker"
SOURCE_ID = "oklahoma-deq-public-review"
CONFIG = okd.StageConfig(
    max_downloads=2, max_checks=10, extract_seconds=120.0, seed_keys=(8406,), isolate=False
)


@pytest.fixture
def stage_db():
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    schema = "okdeq_documents_" + uuid4().hex
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
    monkeypatch.setattr(okd, "Pacer", lambda *a, **k: (lambda: None))  # pacing is unit-tested


def setup_source(factory):
    definition = next(row for row in load_registry() if row["id"] == SOURCE_ID)
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


def ingest(factory, definition, job_id, origin, monkeypatch, config=CONFIG) -> dict:
    """Mirror process_job's order: stage over the retrieved records, then process_records."""
    from gridlens.ingestion.service import _enrich_with_application_documents, process_records

    monkeypatch.setattr(okd, "config_from_source", lambda _source: config)
    records = [listing_record(event_date=COMMENT_START)]
    with factory() as session:
        report = _enrich_with_application_documents(
            session, job_id, WORKER, 1, definition, records, origin.client(), deadline=None
        )
        session.commit()
    with factory() as session:
        counts = process_records(session, job_id, WORKER, 1, definition, records, allow_model=False)
    return {"report": report, "counts": counts, "records": records}


def test_west_edmond_memo_flows_to_one_electric_compressor_claim(stage_db, monkeypatch):
    definition, job_id = setup_source(stage_db)
    origin = Origin()
    origin.put(8406, memo_pdf())
    outcome = ingest(stage_db, definition, job_id, origin, monkeypatch)
    assert outcome["report"].counts["new"] == 1 and outcome["report"].rejections == []
    assert outcome["counts"]["permit_accepted"] == 1

    with stage_db() as session:
        observation = session.scalar(select(Observation))
        evidence = session.scalar(select(Evidence))
        assert observation is not None and evidence is not None
        assert "Equipment ID" in (evidence.abstract or "")
        assert evidence.abstract == observation.abstract
        assert evidence.published_at is None and evidence.observed_at is not None
        assert observation.first_seen_at is not None
        assert "storedpermits/8406.pdf pp.2-2" in evidence.extraction_location
        state = evidence.provenance["okdeq_document"]
        assert state["permit_norm"] == "2017-0987-C M-2" and state["current_key"] == 8406
        document = state["document"]
        assert document["extraction"]["line_provenance"]
        assert document["memo"]["permit_number"]["quote"] == "2017-0987-C (M-2)"
        assert {s["equipment_id"] for s in document["extraction"]["supply"]} >= {"C-0701"}
        first_seen = observation.first_seen_at

        assert session.scalar(select(PowerNeed)) is not None
        package = session.scalar(select(EvidencePackage))
        assert package is not None
        claims = package.payload["equipment"]
        assert len(claims) == 1
        claim = claims[0]
        assert (claim["equipment_type"], claim["drive"], claim["unit"]) == (
            "compressor",
            "electric",
            "hp",
        )
        assert claim["count"] == 3 and claim["state"] == "proposed"
        assert observation.abstract[claim["start"] : claim["end"]] == claim["quote"]
        assert package.payload["company"] == "ONEOK Gas Storage, L.L.C."
        assert package.payload["facility"] == "West Edmond Compressor Station"
        # The Ariel table rows (5,200 hp, drive unstated) never become claims.
        assert all(item["rating"] != "5200" for item in claims)
        assert (str(claim["rating"]), claim["unit"]) == ("2500", "hp")
        assert claim["rating_basis"] == "mechanical_output"

    # Idempotent replay with the retained state: no new evidence, no second package.
    replay = ingest(stage_db, definition, job_id, origin, monkeypatch)
    assert replay["counts"]["unchanged"] == 1 and replay["counts"]["new"] == 0
    assert replay["report"].counts["unchanged"] == 1
    assert origin.count("GET") == 1
    with stage_db() as session:
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 1
        assert session.scalar(select(Observation.first_seen_at)) == first_seen
        source = session.get(Source, SOURCE_ID)
        keys = source.health["okdeq_documents"]["keys"]
        assert keys["8406"]["status"] == "document" and keys["8406"]["permit"] == "2017-0987-C M-2"


def test_a_newer_key_with_the_same_permit_adds_a_version_and_preserves_history(
    stage_db, monkeypatch
):
    from gridlens.ingestion.okdeq_document_stage import load_index, load_prior_states

    definition, job_id = setup_source(stage_db)
    origin = Origin()
    origin.put(8406, memo_pdf())
    ingest(stage_db, definition, job_id, origin, monkeypatch)
    with stage_db() as session:
        prior = load_prior_states(session, SOURCE_ID)
        assert set(prior) == {"2017-0987-C M-2"}
        first_seen = prior["2017-0987-C M-2"]["versions"][0]["first_seen_at"]

    origin.put(8450, memo_pdf(body=[[WEST_EDMOND_PROSE.replace("three (3)", "two (2)", 1)]]))
    config = dataclasses.replace(CONFIG, seed_keys=(8406, 8450))
    second = ingest(stage_db, definition, job_id, origin, monkeypatch, config)
    assert second["counts"]["changed"] == 1
    with stage_db() as session:
        evidence = session.scalars(select(Evidence).order_by(Evidence.observed_at)).all()
        assert len(evidence) == 2  # the earlier evidence version is preserved, not overwritten
        state = evidence[-1].provenance["okdeq_document"]
        assert [v["key"] for v in state["versions"]] == [8406, 8450]
        assert state["versions"][0]["first_seen_at"] == first_seen
        assert state["current_key"] == 8450
        assert evidence[0].provenance["okdeq_document"]["current_key"] == 8406
        assert session.scalar(select(func.count()).select_from(Observation)) == 1
        index = load_index(session, SOURCE_ID)
        assert set(index["keys"]) == {"8406", "8450"}


def test_generator_memo_adds_supply_in_provenance_and_no_demand(stage_db, monkeypatch):
    definition, job_id = setup_source(stage_db)
    origin = Origin()
    origin.put(8406, memo_pdf(body=[[GENERATORS]]))
    outcome = ingest(stage_db, definition, job_id, origin, monkeypatch)
    assert outcome["counts"]["new"] == 1
    with stage_db() as session:
        evidence = session.scalar(select(Evidence))
        assert evidence is not None and "Equipment ID" not in (evidence.abstract or "")
        document = evidence.provenance["okdeq_document"]["document"]
        assert document["abstain"]["reason"] == "no equipment schedule found"
        assert document["extraction"]["supply"][0]["equipment_type"] == "generator"
        for package in session.scalars(select(EvidencePackage)):
            assert package.payload.get("equipment") in (None, [])


def test_a_failed_refetch_keeps_the_accepted_schedule(stage_db, monkeypatch):
    from gridlens.ingestion.okdeq_document_stage import load_index, load_prior_states

    definition, job_id = setup_source(stage_db)
    origin = Origin()
    origin.put(8406, memo_pdf())
    ingest(stage_db, definition, job_id, origin, monkeypatch)
    origin.put(8406, b"<html><script>shell()</script></html>", ctype="text/html", etag='"e2"')
    with stage_db() as session:
        prior = load_prior_states(session, SOURCE_ID)
        index = load_index(session, SOURCE_ID)
    record = listing_record(event_date=COMMENT_START)
    report = okd.run_stage(
        [record],
        prior,
        client=origin.client(),
        config=CONFIG,
        index=index,
        pacer=lambda: None,
        now=lambda: datetime.now(UTC) + timedelta(days=1),
    )
    assert [r["error_code"] for r in report.rejections] == ["js_shell"]
    assert "Equipment ID" in record["abstract"]  # accepted schedule preserved
    assert record["okdeq_document"]["document"]["status"] == "extracted"
    # The index still remembers the accepted document.
    assert report.index["keys"]["8406"]["status"] == "document"


def test_process_job_ships_off_and_makes_no_document_request(stage_db, monkeypatch):
    import gridlens.ingestion.service as service

    definition, job_id = setup_source(stage_db)
    assert definition["query"]["application_documents"]["enabled"] is False
    origin = Origin()
    origin.put(8406, memo_pdf())
    monkeypatch.setattr(
        service, "retrieve_source", lambda *_a, **_k: [listing_record(event_date=COMMENT_START)]
    )
    with stage_db() as session:
        counts = service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert counts["new"] == 1 and "application_documents" not in counts
    assert origin.log == []
    with stage_db() as session:
        evidence = session.scalar(select(Evidence))
        assert evidence is not None and "okdeq_document" not in evidence.provenance
        assert "Equipment ID" not in (evidence.abstract or "")


def test_process_job_reports_document_failures_as_partial_without_blocking_the_listing(
    stage_db, monkeypatch
):
    import gridlens.ingestion.service as service

    definition, job_id = setup_source(stage_db)
    monkeypatch.setattr(okd, "config_from_source", lambda _s: CONFIG)
    monkeypatch.setattr(
        service, "retrieve_source", lambda *_a, **_k: [listing_record(event_date=COMMENT_START)]
    )
    origin = Origin()
    origin.put(8406, b"<html><script>shell()</script></html>", ctype="text/html")
    with stage_db() as session:
        counts = service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert counts["new"] == 1
    assert counts["partial"] is True and counts["parse_failures"] == 1
    assert counts["rejected_records"][0]["error_code"] == "js_shell"
    assert counts["rejected_records"][0]["stage"] == "okdeq_document"
    assert counts["application_documents"]["failure_js_shell"] == 1
    assert "collection_status" not in counts  # the listing's cooldown state is not moved


def test_stage_fault_is_a_typed_error_and_the_listing_still_ingests(stage_db, monkeypatch):
    import gridlens.ingestion.service as service

    definition, job_id = setup_source(stage_db)
    monkeypatch.setattr(okd, "config_from_source", lambda _s: CONFIG)
    monkeypatch.setattr(
        service, "retrieve_source", lambda *_a, **_k: [listing_record(event_date=COMMENT_START)]
    )

    def boom(*_a, **_k):
        raise RuntimeError("SECRET detail that must not be stored")

    monkeypatch.setattr(okd, "run_stage", boom)
    with stage_db() as session:
        counts = service.process_job(session, job_id, WORKER, 1, definition, Origin().client())
    assert counts["new"] == 1 and counts["partial"] is True
    error = counts["rejected_records"][0]
    assert error["error_code"] == "stage_error" and error["raw"] == {"error": "RuntimeError"}
    assert "SECRET" not in repr(counts)


def test_a_rate_limited_listing_makes_no_document_requests(stage_db, monkeypatch):
    from gridlens.ingestion.service import _enrich_with_application_documents

    definition, job_id = setup_source(stage_db)
    monkeypatch.setattr(okd, "config_from_source", lambda _s: CONFIG)
    origin = Origin()
    origin.put(8406, memo_pdf())
    acquisition = {
        "records": [listing_record(event_date=COMMENT_START)],
        "partial": True,
        "rejected_count": 0,
        "rejected_records": [],
        "source_rate_limited": True,
        "source_http_status": 429,
    }
    with stage_db() as session:
        report = _enrich_with_application_documents(
            session, job_id, WORKER, 1, definition, acquisition, origin.client(), deadline=None
        )
        session.commit()
    assert origin.log == []
    assert report.counts == {"skipped_source_rate_limited": 1}


def test_a_failed_job_stage_never_marks_the_source_unhealthy(stage_db, monkeypatch):
    """The stage keeps its own attempt index in source health and no other health field."""
    definition, job_id = setup_source(stage_db)
    origin = Origin()
    origin.put(8406, memo_pdf())
    ingest(stage_db, definition, job_id, origin, monkeypatch)
    with stage_db() as session:
        health = session.get(Source, SOURCE_ID).health
    assert set(health) == {"okdeq_documents"}


def test_retry_after_is_stored_in_health_and_honoured_by_the_next_run(stage_db, monkeypatch):
    from gridlens.ingestion.service import _enrich_with_application_documents

    definition, job_id = setup_source(stage_db)
    monkeypatch.setattr(okd, "config_from_source", lambda _s: CONFIG)
    origin = Origin()
    origin.put(8406, memo_pdf())
    origin.head_status = 429  # Retry-After: 120

    def enrich():
        with stage_db() as session:
            report = _enrich_with_application_documents(
                session,
                job_id,
                WORKER,
                1,
                definition,
                [listing_record(event_date=COMMENT_START)],
                origin.client(),
                deadline=None,
            )
            session.commit()
        return report

    assert enrich().counts["aborted_rate_limited"] == 1
    with stage_db() as session:
        assert "not_before" in session.get(Source, SOURCE_ID).health["okdeq_documents"]
    origin.log.clear()
    assert enrich().counts == {
        "skipped_retry_after": 1,
        "in_scope": 1,
        "downloads": 0,
        "frontier": 0,
    }
    assert origin.log == []
