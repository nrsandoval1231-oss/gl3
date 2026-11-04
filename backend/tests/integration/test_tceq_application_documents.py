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


def stage_client(body: bytes) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        headers = {
            "content-type": "application/pdf",
            "etag": '"v1"',
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


def ingest(factory, definition, job_id, body: bytes, monkeypatch) -> dict:
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
            stage_client(body),
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
