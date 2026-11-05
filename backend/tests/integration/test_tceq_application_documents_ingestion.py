"""Synthetic PDF portfolio -> application-document stage -> ingestion service -> EvidencePackage.

Disposable test database only (TEST_DATABASE_URL must end in _test). HTTP is a MockTransport.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))

from _permit_pdf import make_pdf  # noqa: E402
from _tceq_portfolio import make_portfolio, pi1_workbook  # noqa: E402

import gridlens.ingestion.adapters.tceq_application_documents as docs  # noqa: E402
from gridlens.ingestion.adapters.tceq_nsr_pending import _record  # noqa: E402
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

BASE = "https://www.tceq.texas.gov/assets/public/permitting/air/reports/applications/"
ELECTRIC = [
    "The applicant will install three (3) 2,500-hp electric motor-driven compressors at the plant."
]
GENERATORS = ["The project will install four (4) 2,000-kW natural gas-fired generators."]
WORKER = "tceq-documents-worker"


@pytest.fixture
def stage_db():
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    schema = "tceq_documents_" + uuid4().hex
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


def nsr_record() -> dict:
    received = date.today() - timedelta(days=20)
    row = {
        "project": "900001",
        "applicant": "Prairie Example LLC",
        "facility": "PRAIRIE DATA CENTER",
        "permits": ["189001"],
        "received": received,
        "application_stage": "Technically Complete",
        "notice_url": "https://www.tceq.texas.gov/notice#900001",
        "application_url": f"{BASE}900001-tc.pdf",
        "notice_href": "/notice#900001",
        "application_href": "/assets/public/permitting/air/reports/applications/900001-tc.pdf",
    }
    summary = {
        "city": "Abilene",
        "county": "Taylor",
        "purpose": "This permit will authorize onsite power generation for a data center.",
        "text": (
            "Plain Language Summary for permit 189001. Prairie Example LLC will build a data "
            "center in Abilene, Taylor County, with onsite power generation."
        ),
    }
    return _record(row, summary)


def portfolio(inner_pages: list[list[str]]) -> bytes:
    workbook = pi1_workbook(
        [("G1", "1", "Generator 1", "Engine: Internal Combustion Engine")],
        description="Data center with one proposed natural gas generator.",
    )
    return make_portfolio(
        [
            ("0-READ THIS FIRST_.pdf", make_pdf([["Read this first"]])),
            ("1-900001-tc.pdf", make_pdf(inner_pages)),
            ("20260101-01_workbook.xlsx", workbook),
        ]
    )


def stage_client(body: bytes, etag: str = '"v1"') -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        headers = {
            "content-type": "application/pdf",
            "etag": etag,
            "last-modified": "Mon, 02 Nov 2026 10:00:00 GMT",
            "content-length": str(len(body)),
        }
        if request.method == "HEAD":
            return httpx.Response(200, headers=headers)
        return httpx.Response(200, headers=headers, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def setup_source(factory):
    definition = next(row for row in load_registry() if row["id"] == "texas-tceq-nsr-pending")
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


def ingest(factory, definition, job_id, body: bytes, monkeypatch, etag: str = '"v1"') -> dict:
    """Mirror process_job's order: stage over the retrieved records, then process_records."""
    from gridlens.ingestion.service import _enrich_with_application_documents, process_records

    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _host: "8.8.8.8")
    monkeypatch.setattr(
        docs, "Pacer", lambda *a, **k: (lambda: None)
    )  # no real sleeping; pacing itself is unit-tested with a fake clock
    config_definition = {
        **definition,
        "query": {
            **definition["query"],
            "application_documents": {"max_downloads": 1, "max_checks": 5, "extract_seconds": 120},
        },
    }
    monkeypatch.setattr(
        docs,
        "config_from_source",
        lambda _source: docs.StageConfig(1, 5, 120.0, isolate=False),
    )
    records = [nsr_record()]
    with factory() as session:
        report = _enrich_with_application_documents(
            session,
            job_id,
            WORKER,
            1,
            config_definition,
            records,
            stage_client(body, etag),
            deadline=None,
        )
        session.commit()
    with factory() as session:
        counts = process_records(session, job_id, WORKER, 1, definition, records, allow_model=False)
    return {"report": report, "counts": counts, "records": records}


def test_electric_compressor_schedule_flows_to_an_equipment_package(stage_db, monkeypatch):
    definition, job_id = setup_source(stage_db)
    outcome = ingest(stage_db, definition, job_id, portfolio([ELECTRIC]), monkeypatch)
    assert outcome["report"].counts["new"] == 1 and outcome["report"].rejections == []
    assert outcome["counts"]["permit_accepted"] == 1

    with stage_db() as session:
        observation = session.scalar(select(Observation))
        evidence = session.scalar(select(Evidence))
        assert observation is not None and evidence is not None
        assert "Equipment ID" in (evidence.abstract or "")
        assert evidence.abstract == observation.abstract
        assert evidence.published_at is None  # TCEQ states no publication date
        assert evidence.event_date is not None and evidence.observed_at is not None
        assert observation.first_seen_at is not None
        assert "pp.1-1" in evidence.extraction_location
        state = evidence.provenance["application_document"]
        assert state["document"]["extraction"]["line_provenance"]
        assert state["document"]["manifest"] and state["document"]["workbooks"]
        first_seen = observation.first_seen_at

        need = session.scalar(select(PowerNeed))
        assert need is not None
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
        assert package.payload["company"] == "Prairie Example LLC"
        assert package.payload["facility"] == "PRAIRIE DATA CENTER"
        # The workbook's generator count is supply context, never an equipment claim.
        assert all(item["equipment_type"] in {"compressor", "pump"} for item in claims)

    # Idempotent replay: same document, unchanged evidence, no new package, first-seen kept.
    replay = ingest(stage_db, definition, job_id, portfolio([ELECTRIC]), monkeypatch)
    assert replay["counts"]["unchanged"] == 1 and replay["counts"]["new"] == 0
    with stage_db() as session:
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
        assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 1
        assert session.scalar(select(Observation.first_seen_at)) == first_seen


def test_generator_only_portfolio_keeps_supply_in_provenance_and_adds_no_demand(
    stage_db, monkeypatch
):
    definition, job_id = setup_source(stage_db)
    outcome = ingest(stage_db, definition, job_id, portfolio([GENERATORS]), monkeypatch)
    assert outcome["counts"]["permit_accepted"] == 1
    with stage_db() as session:
        evidence = session.scalar(select(Evidence))
        assert evidence is not None
        assert "Equipment ID" not in (evidence.abstract or "")
        document = evidence.provenance["application_document"]["document"]
        assert document["status"] == "no_equipment_schedule"
        assert document["abstain"]["reason"] == "no equipment schedule found"
        supply = document["extraction"]["supply"]
        assert supply and supply[0]["equipment_type"] == "generator"
        assert document["workbooks"][0]["units_by_type"] == {"Engine": 1}
        for package in session.scalars(select(EvidencePackage)):
            assert package.payload.get("equipment") in (None, [])
            assert package.payload.get("status") != "SUPPORTED"
        need = session.scalar(select(PowerNeed))
        assert need is not None and need.required_mw is None


def test_prior_state_is_read_back_and_a_failed_refetch_keeps_the_accepted_schedule(
    stage_db, monkeypatch
):
    from gridlens.ingestion.tceq_document_stage import load_prior_states

    definition, job_id = setup_source(stage_db)
    ingest(stage_db, definition, job_id, portfolio([ELECTRIC]), monkeypatch)
    with stage_db() as session:
        prior = load_prior_states(session, definition["id"])
    assert set(prior) == {"900001"}
    assert prior["900001"]["document"]["status"] == "extracted"

    shell = b"<html><script>window.__shell()</script></html>"

    def shell_client() -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            headers = {"content-type": "text/html", "etag": '"v2"', "content-length": "46"}
            return httpx.Response(
                200, headers=headers, content=b"" if request.method == "HEAD" else shell
            )

        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    record = nsr_record()
    report = docs.run_stage(
        [record],
        prior,
        client=shell_client(),
        config=docs.StageConfig(1, 5, 120.0, isolate=False),
        pacer=lambda: None,
        now=lambda: datetime.now(UTC),
    )
    assert report.rejections[0]["error_code"] == "js_shell"
    assert "Equipment ID" in record["abstract"]  # accepted schedule preserved
    assert record["application_document"]["last_attempt"]["code"] == "js_shell"


def test_process_job_reports_document_failures_as_partial_without_blocking_the_listing(
    stage_db, monkeypatch
):
    """A failing document is visible in the job counts; the base record still ingests."""
    import gridlens.ingestion.service as service

    definition, job_id = setup_source(stage_db)
    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _h: "8.8.8.8")
    monkeypatch.setattr(docs, "Pacer", lambda *a, **k: (lambda: None))
    monkeypatch.setattr(
        docs, "config_from_source", lambda _s: docs.StageConfig(1, 5, 120.0, isolate=False)
    )
    monkeypatch.setattr(service, "retrieve_source", lambda *_a, **_k: [nsr_record()])
    shell = b"<html><script>shell()</script></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        headers = {"content-type": "text/html", "content-length": str(len(shell))}
        return httpx.Response(
            200, headers=headers, content=b"" if request.method == "HEAD" else shell
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    with stage_db() as session:
        counts = service.process_job(session, job_id, WORKER, 1, definition, client)
    assert counts["new"] == 1 and counts["permit_accepted"] == 1
    assert counts["partial"] is True and counts["parse_failures"] == 1
    assert counts["rejected_records"][0]["error_code"] == "js_shell"
    assert counts["rejected_records"][0]["stage"] == "tceq_application_document"
    assert counts["application_documents"]["failure_js_shell"] == 1
    with stage_db() as session:
        evidence = session.scalar(select(Evidence))
        assert evidence is not None
        assert evidence.provenance["application_document"]["last_attempt"]["code"] == "js_shell"
        assert "Equipment ID" not in (evidence.abstract or "")


def test_an_unexpected_stage_fault_is_reported_and_keeps_retained_schedules(stage_db, monkeypatch):
    from gridlens.ingestion.service import _enrich_with_application_documents

    definition, job_id = setup_source(stage_db)
    ingest(stage_db, definition, job_id, portfolio([ELECTRIC]), monkeypatch)

    def explode(*_args, **_kwargs):
        raise RuntimeError("disk full /secret/path")

    monkeypatch.setattr(docs, "run_stage", explode)
    monkeypatch.setattr(docs, "config_from_source", lambda _s: docs.StageConfig(1, 5, 120.0))
    record = nsr_record()
    with stage_db() as session:
        report = _enrich_with_application_documents(
            session, job_id, WORKER, 1, definition, [record], None, deadline=None
        )
        session.commit()
    assert report.rejections[0]["error_code"] == "stage_error"
    assert report.rejections[0]["raw"] == {"error": "RuntimeError"}  # no message or path
    assert "Equipment ID" in record["abstract"]  # the retained schedule is not dropped


# ----------------------------------------------------------------------------- review regressions


def _patch_stage(monkeypatch):
    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _h: "8.8.8.8")
    monkeypatch.setattr(docs, "Pacer", lambda *a, **k: (lambda: None))
    monkeypatch.setattr(
        docs, "config_from_source", lambda _s: docs.StageConfig(1, 5, 120.0, isolate=False)
    )


def test_slow_extractor_cannot_consume_the_persistence_reserve(stage_db, monkeypatch):
    """B1: a finite job deadline, an extractor that uses all the time it is given."""
    import time

    import gridlens.ingestion.service as service

    definition, job_id = setup_source(stage_db)
    _patch_stage(monkeypatch)
    monkeypatch.setattr(docs, "persist_reserve", lambda _n: 4.0)
    monkeypatch.setattr(docs, "STAGE_MARGIN_SECONDS", 1.0)
    monkeypatch.setattr(docs, "CHILD_GRACE_SECONDS", 0.0)
    monkeypatch.setattr(docs, "HTTP_READ_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(docs, "HEAVY_RESERVE_SECONDS", 1.0)
    monkeypatch.setattr(docs, "MIN_EXTRACT_SECONDS", 1.0)
    monkeypatch.setattr(docs, "MIN_UNPACK_SECONDS", 1.0)
    monkeypatch.setattr(docs, "MIN_WORKBOOK_SECONDS", 1.0)
    monkeypatch.setattr(docs, "HEAD_MARGIN_SECONDS", 0.0)
    monkeypatch.setattr(service, "retrieve_source", lambda *_a, **_k: [nsr_record()])
    used = {}

    def slow_extract(_path, _name, _sha, _link, budget, _isolate):
        used["budget"] = budget
        time.sleep(budget)  # a worst case: the extractor takes everything it is allowed
        raise docs.DocumentFailure("text_layer_time_budget")

    monkeypatch.setattr(docs, "_extract_pdf", slow_extract)
    deadline = time.monotonic() + 12.0
    with stage_db() as session:
        counts = service.process_job(
            session,
            job_id,
            WORKER,
            1,
            definition,
            stage_client(portfolio([ELECTRIC])),
            deadline=deadline,
        )
    assert time.monotonic() < deadline  # persistence finished inside the job deadline
    assert used["budget"] <= 12.0 - 4.0 - 1.0  # never more than the stage's own share
    assert counts["new"] == 1 and counts["permit_accepted"] == 1  # the listing persisted
    assert counts["application_documents"]["failure_text_layer_time_budget"] == 1
    with stage_db() as session:
        evidence = session.scalar(select(Evidence))
        assert evidence is not None and "application_document" not in evidence.provenance
        health = session.get(Source, definition["id"]).health or {}
        assert health["application_documents_attempts"]["900001"]["attempts"] in (0, 1)


def test_a_rate_limited_acquisition_makes_no_document_requests(stage_db, monkeypatch):
    """B2: the stage is skipped entirely when the listing run was throttled."""
    from gridlens.ingestion.service import _enrich_with_application_documents

    definition, job_id = setup_source(stage_db)
    _patch_stage(monkeypatch)
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.method)
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    record = nsr_record()
    acquisition = {
        "records": [record],
        "partial": True,
        "rejected_count": 0,
        "rejected_records": [],
        "source_rate_limited": True,
        "source_http_status": 429,
    }
    with stage_db() as session:
        report = _enrich_with_application_documents(
            session, job_id, WORKER, 1, definition, acquisition, client, deadline=None
        )
        session.commit()
    assert requests == []
    assert report.counts == {"skipped_source_rate_limited": 1}


def test_stage_is_off_unless_the_registry_enables_it(stage_db):
    """S3: the shipped registry entry has the stage disabled; it never runs."""
    from gridlens.ingestion.service import _enrich_with_application_documents

    definition, job_id = setup_source(stage_db)
    assert definition["query"]["application_documents"]["enabled"] is False
    with stage_db() as session:
        assert (
            _enrich_with_application_documents(
                session, job_id, WORKER, 1, definition, [nsr_record()], None, deadline=None
            )
            is None
        )


def test_changed_bytes_and_revalidation_are_persisted_correctly(stage_db, monkeypatch):
    """S7: DB-backed change detection: changed bytes -> new evidence; same bytes -> none."""
    definition, job_id = setup_source(stage_db)
    ingest(stage_db, definition, job_id, portfolio([ELECTRIC]), monkeypatch)
    with stage_db() as session:
        first_hash = session.scalar(select(Evidence.content_hash))
        first_seen = session.scalar(select(Observation.first_seen_at))
        assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 1

    # Re-validation with the same bytes: nothing new.
    same = ingest(stage_db, definition, job_id, portfolio([ELECTRIC]), monkeypatch)
    assert same["counts"]["unchanged"] == 1
    with stage_db() as session:
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1

    # Changed bytes (the schedule is gone): a second evidence version, first-seen kept,
    # the earlier evidence and package preserved.
    changed = ingest(stage_db, definition, job_id, portfolio([GENERATORS]), monkeypatch, '"v2"')
    assert changed["counts"]["changed"] == 1
    with stage_db() as session:
        versions = session.scalars(select(Evidence).order_by(Evidence.observed_at)).all()
        assert len(versions) == 2 and versions[0].content_hash == first_hash
        assert "Equipment ID" in (versions[0].abstract or "")
        assert "Equipment ID" not in (versions[1].abstract or "")
        assert session.scalar(select(Observation.first_seen_at)) == first_seen
        assert session.scalar(select(func.count()).select_from(EvidencePackage)) >= 1


def test_retry_after_from_a_429_is_honoured_by_the_next_run(stage_db, monkeypatch):
    """A 429 with Retry-After rests the stage; the next run makes no request until it passes."""
    from gridlens.ingestion.service import _enrich_with_application_documents
    from gridlens.ingestion.tceq_document_stage import NOT_BEFORE_KEY

    definition, job_id = setup_source(stage_db)
    _patch_stage(monkeypatch)
    requests: list[str] = []

    def limited(request: httpx.Request) -> httpx.Response:
        requests.append(request.method)
        return httpx.Response(429, headers={"retry-after": "3600"})

    def enrich(handler):
        client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
        with stage_db() as session:
            report = _enrich_with_application_documents(
                session, job_id, WORKER, 1, definition, [nsr_record()], client, deadline=None
            )
            session.commit()
        return report

    first = enrich(limited)
    assert first.counts["aborted_rate_limited"] == 1 and len(requests) == 1
    with stage_db() as session:
        stored = session.get(Source, definition["id"]).health[NOT_BEFORE_KEY]
    assert datetime.fromisoformat(stored) > datetime.now(UTC) + timedelta(minutes=50)
    requests.clear()
    second = enrich(limited)
    assert requests == [] and second.counts == {"skipped_retry_after": 1}
    # Once the stored time has passed the stage runs again and clears the marker.
    with stage_db.begin() as session:
        source = session.get(Source, definition["id"])
        source.health = {
            **source.health,
            NOT_BEFORE_KEY: (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        }
    third = enrich(lambda request: httpx.Response(404))
    assert "skipped_retry_after" not in third.counts
    with stage_db() as session:
        assert NOT_BEFORE_KEY not in (session.get(Source, definition["id"]).health or {})
