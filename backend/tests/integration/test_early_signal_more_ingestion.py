"""WS4b sources -> stage -> ingestion service -> Evidence/provenance (disposable test database).

Disposable test database only (TEST_DATABASE_URL must end in _test). HTTP is a MockTransport.
Every source is evidence only: enabling one must create no Project, PowerNeed or card.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))

from _early_more_fixtures import (  # noqa: E402
    DC_ROW,
    HASKELL_AGENDA,
    LD_ROW,
    OCC_GOOGLE,
    TCEQ_NOTICE,
    haskell_origin,
    occ_origin,
    registry_origin,
    registry_row,
    tceq_origin,
)

import gridlens.ingestion.adapters.comptroller_dc_registry as cr  # noqa: E402
import gridlens.ingestion.adapters.county_abatement_agendas as ca  # noqa: E402
import gridlens.ingestion.adapters.early_signal_stage as stage_module  # noqa: E402
import gridlens.ingestion.adapters.ok_occ_dc_notices as oc  # noqa: E402
import gridlens.ingestion.adapters.tceq_water_rights as tw  # noqa: E402
from gridlens.ingestion.adapters.early_signal_stage import StageConfig  # noqa: E402
from gridlens.ingestion.registry import load_registry  # noqa: E402
from gridlens.persistence.database import Base  # noqa: E402
from gridlens.persistence.models import (  # noqa: E402
    Evidence,
    Job,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings  # noqa: E402

WORKER = "early-signal-more-worker"
CONFIG = StageConfig(max_downloads=6, max_checks=20, extract_seconds=120.0, isolate=False)
TODAY = date(2026, 11, 4)
ORIGINS = {
    cr: registry_origin,
    oc: occ_origin,
    ca: haskell_origin,
    tw: tceq_origin,
}
MODULES = list(ORIGINS)


@pytest.fixture
def stage_db():
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    schema = "early_more_" + uuid4().hex
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
    monkeypatch.setattr(stage_module, "default_pacer", lambda: lambda: None)


def setup_source(factory, source_id):
    definition = next(row for row in load_registry() if row["id"] == source_id)
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


def listing(module, origin):
    definition = next(r for r in load_registry() if r["id"] == module.SOURCE_ID)
    return module.retrieve(definition, origin.client(), pacer=lambda: None, today=TODAY)


def ingest(factory, definition, job_id, module, origin, records, monkeypatch, config=CONFIG):
    """Mirror process_job's order: stage over the retrieved records, then process_records."""
    from gridlens.ingestion.service import _enrich_with_application_documents, process_records

    monkeypatch.setattr(module, "config_from_source", lambda _source: config)
    with factory() as session:
        report = _enrich_with_application_documents(
            session, job_id, WORKER, 1, definition, records, origin.client(), deadline=None
        )
        session.commit()
    with factory() as session:
        counts = process_records(session, job_id, WORKER, 1, definition, records, allow_model=False)
    return {"report": report, "counts": counts, "records": records}


def evidences(factory, source_id):
    with factory() as session:
        rows = session.execute(
            select(Observation.external_id, Evidence)
            .join(Evidence, Evidence.observation_id == Observation.id)
            .where(Observation.source_id == source_id)
            .order_by(Observation.external_id, Evidence.observed_at)
        ).all()
        return list(rows)


# --------------------------------------------------------------------------- evidence only


@pytest.mark.parametrize("module", MODULES)
def test_each_source_flows_to_evidence_idempotently_and_creates_no_project_or_need(
    stage_db, monkeypatch, module
):
    definition, job_id = setup_source(stage_db, module.SOURCE_ID)
    origin = ORIGINS[module]()
    records = listing(module, origin)
    outcome = ingest(stage_db, definition, job_id, module, origin, records, monkeypatch)
    assert outcome["counts"]["new"] >= 1
    rows = evidences(stage_db, module.SOURCE_ID)
    assert rows and all(ev.url and ev.abstract for _ext, ev in rows)
    with stage_db() as session:
        assert all(o.first_seen_at is not None for o in session.scalars(select(Observation)))
        # Retained evidence only: nothing in these sources creates a project or a power need.
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
    again = listing(module, origin)
    replay = ingest(stage_db, definition, job_id, module, origin, again, monkeypatch)
    assert replay["counts"]["new"] == 0 and replay["counts"]["changed"] == 0
    assert len(evidences(stage_db, module.SOURCE_ID)) == len(rows)


def test_occ_documents_carry_quoted_form_fields_into_provenance(stage_db, monkeypatch):
    definition, job_id = setup_source(stage_db, oc.SOURCE_ID)
    origin = occ_origin()
    outcome = ingest(stage_db, definition, job_id, oc, origin, listing(oc, origin), monkeypatch)
    assert outcome["report"].counts["new"] == 1
    by_url = {ev.url: ev for _ext, ev in evidences(stage_db, oc.SOURCE_ID)}
    google = by_url[OCC_GOOGLE]
    state = google.provenance["early_signal"]
    assert state["stateful"] is True and state["kind"] == "occ_notice"
    fields = state["document"]["extraction"]["fields"]
    assert fields["land_purchase_date"]["value"] == "2026-08-21"
    assert fields["land_purchase_date"]["quote"] == "Land Purchase Date: 8/21/2026"
    assert f"Source document SHA-256: {state['document']['sha256']}" in google.abstract
    assert str(google.published_at) == "2026-10-15"
    # The scanned notice stays a listing-only observation, not an empty document record.
    scanned = [ev for url, ev in by_url.items() if "emerald" in url][0]
    assert "early_signal" not in scanned.provenance
    assert "McGarry" not in repr([ev.abstract for ev in by_url.values()])


def test_agenda_and_water_documents_carry_quotes_into_provenance(stage_db, monkeypatch):
    definition, job_id = setup_source(stage_db, ca.SOURCE_ID)
    origin = haskell_origin()
    ingest(stage_db, definition, job_id, ca, origin, listing(ca, origin), monkeypatch)
    agenda = next(ev for _e, ev in evidences(stage_db, ca.SOURCE_ID) if ev.url == HASKELL_AGENDA)
    items = agenda.provenance["early_signal"]["document"]["extraction"]["items"]
    assert items[0]["fields"]["entity"]["value"] == "Crusoe Energy Systems, LLC"
    # The scanned June agenda was never stored as an empty record.
    assert len(evidences(stage_db, ca.SOURCE_ID)) == 1

    definition, job_id = setup_source(stage_db, tw.SOURCE_ID)
    origin = tceq_origin()
    ingest(stage_db, definition, job_id, tw, origin, listing(tw, origin), monkeypatch)
    by_url = {ev.url: ev for _e, ev in evidences(stage_db, tw.SOURCE_ID)}
    notice = by_url[TCEQ_NOTICE].provenance["early_signal"]["document"]["extraction"]
    assert [v["value"] for v in notice["volumes"]] == ["27.75", 1000]
    assert len(by_url) == 2  # the row without a notice is still a listing observation


def test_registry_changed_row_adds_an_evidence_version_and_keeps_the_earlier_one(
    stage_db, monkeypatch
):
    definition, job_id = setup_source(stage_db, cr.SOURCE_ID)
    origin = registry_origin(dc_rows=[DC_ROW], ld_rows=[LD_ROW])
    ingest(stage_db, definition, job_id, cr, origin, listing(cr, origin), monkeypatch)
    with stage_db() as session:
        first_seen = {o.external_id: o.first_seen_at for o in session.scalars(select(Observation))}
    changed = registry_row(
        "ALE60 Data Center",
        "01/01/2021",
        "COPT San Antonio LP",
        "DC046706-OW1",
        "Amazon Data Services Inc.",
        "DC046706-OC1",
        "A New Operator LLC",
        "DC046706-OP1",
    )
    later = registry_origin(dc_rows=[changed], ld_rows=[LD_ROW])
    replay = ingest(stage_db, definition, job_id, cr, later, listing(cr, later), monkeypatch)
    assert replay["counts"]["changed"] == 1 and replay["counts"]["new"] == 0
    rows = [ev for ext, ev in evidences(stage_db, cr.SOURCE_ID) if ext == "TXCOMP-DC046706"]
    assert len(rows) == 2 and "A New Operator LLC" in rows[-1].abstract
    assert "A New Operator LLC" not in rows[0].abstract
    with stage_db() as session:
        again = {o.external_id: o.first_seen_at for o in session.scalars(select(Observation))}
    assert again == first_seen  # first_seen_at is never rewritten


# --------------------------------------------------------------------------- ships off


@pytest.mark.parametrize("module", [oc, ca, tw])
def test_process_job_ships_off_and_makes_no_document_request(stage_db, monkeypatch, module):
    import gridlens.ingestion.service as service

    definition, job_id = setup_source(stage_db, module.SOURCE_ID)
    assert definition["enabled"] is False
    assert definition["query"]["documents"]["enabled"] is False
    origin = ORIGINS[module]()
    records = listing(module, origin)
    origin.log.clear()
    monkeypatch.setattr(service, "retrieve_source", lambda *_a, **_k: records)
    with stage_db() as session:
        counts = service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert "application_documents" not in counts
    assert origin.log == []
    for _ext, ev in evidences(stage_db, module.SOURCE_ID):
        assert "early_signal" not in ev.provenance


def test_county_agenda_records_are_withheld_when_documents_are_off(stage_db, monkeypatch):
    import gridlens.ingestion.service as service

    definition, job_id = setup_source(stage_db, ca.SOURCE_ID)
    origin = haskell_origin()
    records = listing(ca, origin)
    assert records
    monkeypatch.setattr(service, "retrieve_source", lambda *_a, **_k: records)
    with stage_db() as session:
        counts = service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert counts["new"] == 0 and evidences(stage_db, ca.SOURCE_ID) == []


@pytest.mark.parametrize("module", [cr, oc, tw])
def test_listing_facts_stand_on_their_own_when_documents_are_off(stage_db, monkeypatch, module):
    import gridlens.ingestion.service as service

    definition, job_id = setup_source(stage_db, module.SOURCE_ID)
    origin = ORIGINS[module]()
    records = listing(module, origin)
    monkeypatch.setattr(service, "retrieve_source", lambda *_a, **_k: records)
    with stage_db() as session:
        counts = service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert counts["new"] == len(records) >= 1


# --------------------------------------------------------------------------- faults and 429


def test_stage_fault_is_a_typed_error_and_listing_still_ingests(stage_db, monkeypatch):
    import gridlens.ingestion.service as service

    definition, job_id = setup_source(stage_db, oc.SOURCE_ID)
    origin = occ_origin()
    records = listing(oc, origin)
    monkeypatch.setattr(oc, "config_from_source", lambda _s: CONFIG)
    monkeypatch.setattr(service, "retrieve_source", lambda *_a, **_k: records)

    def boom(*_a, **_k):
        raise RuntimeError("SECRET detail that must not be stored")

    monkeypatch.setattr(oc, "run_stage", boom)
    with stage_db() as session:
        counts = service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert counts["partial"] is True and counts["new"] == len(records)
    error = counts["rejected_records"][0]
    assert error["error_code"] == "stage_error" and error["raw"] == {"error": "RuntimeError"}
    assert "SECRET" not in repr(counts)


def test_429_rests_the_stage_across_runs_through_source_health(stage_db, monkeypatch):
    from httpx import Response

    definition, job_id = setup_source(stage_db, tw.SOURCE_ID)
    origin = tceq_origin()
    origin.force = (
        lambda url: Response(429, headers={"retry-after": "900"}) if "/notice/" in url else None
    )
    first = ingest(stage_db, definition, job_id, tw, origin, listing(tw, origin), monkeypatch)
    assert first["report"].counts["aborted_rate_limited"] == 1
    with stage_db() as session:
        assert "not_before" in session.get(Source, tw.SOURCE_ID).health["early_signal"]
    origin.force = None
    origin.log.clear()
    second = ingest(stage_db, definition, job_id, tw, origin, listing(tw, origin), monkeypatch)
    assert second["report"].counts["skipped_retry_after"] == 1
    assert not [u for u in origin.urls() if "/notice/" in u]


@pytest.mark.parametrize("module", MODULES)
def test_a_real_listing_429_stores_not_before_and_the_next_run_skips_the_listing(
    stage_db, monkeypatch, module
):
    from httpx import Response

    import gridlens.ingestion.service as service
    from gridlens.ingestion.adapters.federal_register import SourceParseError

    definition, job_id = setup_source(stage_db, module.SOURCE_ID)
    origin = ORIGINS[module]()
    origin.force = lambda url: Response(429, headers={"retry-after": "600"})
    monkeypatch.setattr(
        service,
        "retrieve_source",
        lambda source, client, **kw: module.retrieve(
            source, client, pacer=lambda: None, today=TODAY
        ),
    )
    with stage_db() as session, pytest.raises(SourceParseError) as raised:
        service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert raised.value.acquisition_code == "http_status_429"
    assert len(origin.log) == 1
    with stage_db() as session:
        health = session.get(Source, module.SOURCE_ID).health["early_signal"]
        until = datetime.fromisoformat(health["not_before"])
    assert timedelta(seconds=540) < until - datetime.now(UTC) <= timedelta(seconds=600)
    with stage_db() as session, pytest.raises(SourceParseError):
        service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert len(origin.log) == 1  # resting: no second request
