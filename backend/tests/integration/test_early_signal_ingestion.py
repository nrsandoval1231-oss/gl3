"""ERCOT planning and PUCT CCN documents -> stage -> ingestion service -> Evidence/provenance.

Disposable test database only (TEST_DATABASE_URL must end in _test). HTTP is a MockTransport.
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

from _early_signal_fixtures import (  # noqa: E402
    SHEETS,
    Origin,
    documents_html,
    ercot_origin,
    export_xlsx,
    filings_html,
    pdf,
    planning_html,
    search_html,
    tpit_row,
    workbook,
)

import gridlens.ingestion.adapters.early_signal_stage as stage_module  # noqa: E402
import gridlens.ingestion.adapters.ercot_rpg as er  # noqa: E402
import gridlens.ingestion.adapters.puct_ccn_dockets as pc  # noqa: E402
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

WORKER = "early-signal-worker"
CONFIG = StageConfig(max_downloads=6, max_checks=20, extract_seconds=120.0, isolate=False)
TODAY = date(2026, 11, 4)


@pytest.fixture
def stage_db():
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    schema = "early_signal_" + uuid4().hex
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
    monkeypatch.setattr(stage_module, "default_pacer", lambda: (lambda: None))


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


def ercot_listing(origin):
    definition = next(r for r in load_registry() if r["id"] == er.SOURCE_ID)
    return er.retrieve(definition, origin.client(), pacer=lambda: None, today=TODAY)


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
        counts = process_records(
            session,
            job_id,
            WORKER,
            1,
            definition,
            records,
            allow_model=False,
        )
    return {"report": report, "counts": counts, "records": records}


def evidences(factory, source_id, prefix=""):
    with factory() as session:
        rows = session.execute(
            select(Observation.external_id, Evidence)
            .join(Evidence, Evidence.observation_id == Observation.id)
            .where(Observation.source_id == source_id)
            .order_by(Observation.external_id, Evidence.observed_at)
        ).all()
        return [(ext, ev) for ext, ev in rows if ext.startswith(prefix)]


# --------------------------------------------------------------------------- ERCOT


def test_ercot_documents_flow_to_evidence_idempotently_without_creating_needs(
    stage_db, monkeypatch
):
    definition, job_id = setup_source(stage_db, er.SOURCE_ID)
    origin = ercot_origin()
    records = ercot_listing(origin)
    outcome = ingest(stage_db, definition, job_id, er, origin, records, monkeypatch)
    assert outcome["report"].rejections == []
    assert outcome["counts"]["new"] >= 8  # 3 documents + baseline TPIT rows

    status = [
        ev
        for ext, ev in evidences(stage_db, er.SOURCE_ID, "ERCOT-RPG-")
        if ev.url.endswith("RPG.pdf")
    ]
    assert len(status) == 1
    ev = status[0]
    state = ev.provenance["early_signal"]
    assert state["kind"] == "rpg_pdf" and state["stateful"] is True
    assert str(ev.published_at) == "2026-07-17"
    assert f"Source document SHA-256: {state['document']['sha256']}" in ev.abstract
    projects = {p["project_id"]: p for p in state["document"]["extraction"]["projects"]}
    cps = projects["25RPG020"]["fields"]
    assert cps["load"]["value"] == 2000 and cps["load"]["quote"] and cps["load"]["page"] == 2
    assert cps["load"]["basis"] == "calculated"

    with stage_db() as session:
        obs = session.scalars(select(Observation)).all()
        assert all(o.first_seen_at is not None for o in obs)
        # Retained evidence only: nothing in this source creates a project or a power need.
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0
        index = session.get(Source, er.SOURCE_ID).health["early_signal"]["urls"]
        assert all(entry["status"] == "document" for entry in index.values())

    again = ercot_listing(origin)
    replay = ingest(stage_db, definition, job_id, er, origin, again, monkeypatch)
    assert replay["counts"]["new"] == 0 and replay["counts"]["changed"] == 0


def test_tpit_next_month_adds_diff_rows_and_keeps_first_seen(stage_db, monkeypatch):
    definition, job_id = setup_source(stage_db, er.SOURCE_ID)
    origin = ercot_origin()
    ingest(stage_db, definition, job_id, er, origin, ercot_listing(origin), monkeypatch)
    baseline = {
        ext for ext, _ in evidences(stage_db, er.SOURCE_ID, "ERCOT-TPIT-") if "-" in ext[11:]
    }

    sheets = {k: [dict(r) for r in v] for k, v in SHEETS.items()}
    sheets["FutureTPIT100126NoCost"] = [
        r for r in sheets["FutureTPIT100126NoCost"] if r["number"] != "100305"
    ]
    sheets["FutureTPIT100126NoCost"].append(
        tpit_row("120000", title="New data center substation", description="serve a data center")
    )
    second = ercot_origin(tpit_body=workbook(sheets))
    second.put("https://www.ercot.com/gridinfo/planning", planning_html(tpit_listed="Nov 25, 2026"))
    # The monthly workbook is re-asked after its recheck window; age the stored check time.
    with stage_db.begin() as session:
        source = session.get(Source, er.SOURCE_ID)
        health = dict(source.health)
        urls = {
            k: {**v, "at": (datetime.now(UTC) - timedelta(days=2)).isoformat()}
            for k, v in health["early_signal"]["urls"].items()
        }
        source.health = {**health, "early_signal": {**health["early_signal"], "urls": urls}}
    outcome = ingest(stage_db, definition, job_id, er, second, ercot_listing(second), monkeypatch)
    assert outcome["report"].counts.get("updated") == 1

    snapshot = [
        ev
        for ext, ev in evidences(stage_db, er.SOURCE_ID, "ERCOT-TPIT-")
        if ev.provenance.get("early_signal", {}).get("kind") == "tpit"
    ]
    assert len(snapshot) == 2  # same observation, a new evidence version; the old one stays
    old, new = (e.provenance["early_signal"] for e in snapshot)
    assert new["first_seen_at"] == old["first_seen_at"]
    assert new["document"]["replaced_sha256"] == [old["document"]["sha256"]]
    rows = [
        ev.provenance["early_signal"]
        for ext, ev in evidences(stage_db, er.SOURCE_ID, "ERCOT-TPIT-")
        if ev.provenance.get("early_signal", {}).get("kind") == "tpit_row"
        and ev.provenance["early_signal"]["change"] != "baseline"
    ]
    assert {(r["project"], r["change"]) for r in rows} == {
        ("120000", "new"),
        ("100305", "removed"),
    }
    assert baseline  # the baseline rows from month one are still there


def test_process_job_ships_off_and_makes_no_document_request(stage_db, monkeypatch):
    import gridlens.ingestion.service as service

    definition, job_id = setup_source(stage_db, er.SOURCE_ID)
    assert definition["enabled"] is False
    assert definition["query"]["documents"]["enabled"] is False
    origin = ercot_origin()
    records = ercot_listing(origin)
    origin.log.clear()
    monkeypatch.setattr(service, "retrieve_source", lambda *_a, **_k: records)
    with stage_db() as session:
        counts = service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert "application_documents" not in counts
    assert origin.log == []
    for _ext, ev in evidences(stage_db, er.SOURCE_ID):
        assert "early_signal" not in ev.provenance


def test_stage_failures_make_the_run_partial_without_moving_collection_status(
    stage_db, monkeypatch
):
    import gridlens.ingestion.service as service

    definition, job_id = setup_source(stage_db, er.SOURCE_ID)
    origin = ercot_origin()
    records = ercot_listing(origin)
    origin.put(
        "https://www.ercot.com/files/docs/2026/07/17/"
        "6.-StatusUpdate_Combined_CPS-Energy-Large-Load-Additions-Project-and-STEC-Medina-County-"
        "Large-Load-Project_July2026_RPG.pdf",
        b"<html>shell</html>",
        ctype="text/html",
    )
    monkeypatch.setattr(er, "config_from_source", lambda _s: CONFIG)
    monkeypatch.setattr(service, "retrieve_source", lambda *_a, **_k: records)
    with stage_db() as session:
        counts = service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert counts["partial"] is True and counts["parse_failures"] == 1
    assert counts["rejected_records"][0]["error_code"] == "js_shell"
    assert counts["application_documents"]["failure_js_shell"] == 1
    assert "collection_status" not in counts


def test_stage_fault_is_a_typed_error_and_listing_still_ingests(stage_db, monkeypatch):
    import gridlens.ingestion.service as service

    definition, job_id = setup_source(stage_db, er.SOURCE_ID)
    origin = ercot_origin()
    records = ercot_listing(origin)
    monkeypatch.setattr(er, "config_from_source", lambda _s: CONFIG)
    monkeypatch.setattr(service, "retrieve_source", lambda *_a, **_k: records)

    def boom(*_a, **_k):
        raise RuntimeError("SECRET detail that must not be stored")

    monkeypatch.setattr(er, "run_stage", boom)
    with stage_db() as session:
        counts = service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert counts["partial"] is True
    error = counts["rejected_records"][0]
    assert error["error_code"] == "stage_error" and error["raw"] == {"error": "RuntimeError"}
    assert "SECRET" not in repr(counts)


def test_429_rests_the_stage_across_runs_through_source_health(stage_db, monkeypatch):
    from httpx import Response

    definition, job_id = setup_source(stage_db, er.SOURCE_ID)
    origin = ercot_origin()
    records = ercot_listing(origin)
    origin.force = (
        lambda url: Response(429, headers={"retry-after": "900"}) if "/files/docs/" in url else None
    )
    first = ingest(stage_db, definition, job_id, er, origin, records, monkeypatch)
    assert first["report"].counts["aborted_rate_limited"] == 1
    with stage_db() as session:
        health = session.get(Source, er.SOURCE_ID).health["early_signal"]
        assert "not_before" in health
    origin.force = None
    origin.log.clear()
    second = ingest(stage_db, definition, job_id, er, origin, ercot_listing(origin), monkeypatch)
    assert second["report"].counts["skipped_retry_after"] == 1
    assert not [u for u in origin.urls() if "/files/docs/" in u]


def test_a_real_listing_429_stores_not_before_and_the_next_run_skips_the_listing(
    stage_db, monkeypatch
):
    from httpx import Response

    import gridlens.ingestion.service as service
    from gridlens.ingestion.adapters.federal_register import SourceParseError

    definition, job_id = setup_source(stage_db, er.SOURCE_ID)
    origin = ercot_origin()
    origin.force = lambda url: Response(429, headers={"retry-after": "600"})
    monkeypatch.setattr(
        service,
        "retrieve_source",
        lambda source, client, **kw: er.retrieve(source, client, pacer=lambda: None, today=TODAY),
    )
    with stage_db() as session, pytest.raises(SourceParseError) as raised:
        service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert raised.value.acquisition_code == "http_status_429"
    assert len(origin.log) == 1
    with stage_db() as session:
        health = session.get(Source, er.SOURCE_ID).health["early_signal"]
        until = datetime.fromisoformat(health["not_before"])
    assert timedelta(seconds=540) < until - datetime.now(UTC) <= timedelta(seconds=600)
    with stage_db() as session, pytest.raises(SourceParseError):
        service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert len(origin.log) == 1  # resting: no second request


# --------------------------------------------------------------------------- PUCT and links


WHITETAIL = (
    "APPLICATION OF AUSTIN ENERGY TO AMEND ITS CERTIFICATE OF CONVENIENCE AND NECESSITY FOR THE "
    "NEW WHITETAIL SUBSTATION AND 138-KV TRANSMISSION LINE IN TRAVIS COUNTY"
)
UNRELATED = (
    "APPLICATION OF ONCOR ELECTRIC DELIVERY COMPANY LLC TO AMEND ITS CERTIFICATE OF CONVENIENCE "
    "AND NECESSITY FOR THE ELM SUBSTATION 138-KV TRANSMISSION LINE IN HALL COUNTY"
)


def puct_origin():
    rows = [
        ("61000", "4", "AUSTIN ENERGY", WHITETAIL),
        ("61001", "2", "ONCOR ELECTRIC DELIVERY COMPANY LLC", UNRELATED),
    ]
    start = TODAY - timedelta(days=60)
    o = Origin()
    for description in pc.DESCRIPTIONS:
        o.put(pc.search_url(description, start, TODAY), search_html(rows))
        o.put(pc.export_url(description, start, TODAY), export_xlsx(rows))
    for control in ("61000", "61001"):
        o.put(
            pc.filings_url(control),
            filings_html(
                control,
                [("1", "10/20/2026", "UTILITY", "PL", "APPLICATION OF UTILITY TO AMEND ITS CCN")],
            ),
        )
        o.put(pc.doc_page_url(control, "1"), documents_html(control, "1", [("1700001", "PDF")]))
        o.put(
            f"https://interchange.puc.texas.gov/Documents/{control}_1_1700001.PDF",
            pdf([["The proposed project is in the area. Estimated cost is unknown at filing."]]),
        )
    return o


def puct_listing(origin):
    definition = next(r for r in load_registry() if r["id"] == pc.SOURCE_ID)
    return pc.retrieve(definition, origin.client(), pacer=lambda: None, today=TODAY)


def test_puct_dockets_link_only_on_an_exact_key_with_evidence_on_both_sides(stage_db, monkeypatch):
    # First the RPG source holds project 26RPG022 (Whitetail substation, Travis County).
    rpg_def, rpg_job = setup_source(stage_db, er.SOURCE_ID)
    ercot = ercot_origin()
    ingest(stage_db, rpg_def, rpg_job, er, ercot, ercot_listing(ercot), monkeypatch)

    puct_def, puct_job = setup_source(stage_db, pc.SOURCE_ID)
    origin = puct_origin()
    outcome = ingest(stage_db, puct_def, puct_job, pc, origin, puct_listing(origin), monkeypatch)
    report = outcome["report"]
    assert report.rejections == []
    assert report.counts["link_linked"] == 1 and report.counts["link_unknown"] == 1

    rows = evidences(stage_db, pc.SOURCE_ID)
    dockets = {ext: ev for ext, ev in rows if ext.startswith("PUCT-CCN-")}
    links = {ext: ev for ext, ev in rows if ext.startswith("ERCOT-PUCT-LINK-")}
    assert set(dockets) == {"PUCT-CCN-61000", "PUCT-CCN-61001"}
    assert set(links) == {"ERCOT-PUCT-LINK-61000-26RPG022"}
    link = links["ERCOT-PUCT-LINK-61000-26RPG022"].provenance["early_signal"]
    assert link["kind"] == "link" and link["link_basis"] == "deterministic_exact_key"
    (key,) = link["keys"]
    assert (key["substation_norm"], key["county_norm"]) == ("whitetail", "travis")
    assert key["docket"]["substation"]["quote"] and key["project"]["substation"]["quote"]
    assert key["project"]["substation"]["document_sha256"] and key["project"]["county"]["page"] == 1
    docket = dockets["PUCT-CCN-61000"].provenance["early_signal"]
    assert docket["kind"] == "puct_docket" and docket["stateful"] is True
    assert str(dockets["PUCT-CCN-61000"].published_at) == "2026-10-20"

    # Replay: nothing new, nothing changed.
    again = ingest(stage_db, puct_def, puct_job, pc, origin, puct_listing(origin), monkeypatch)
    assert again["counts"]["new"] == 0 and again["counts"]["changed"] == 0

    with stage_db() as session:
        assert session.scalar(select(func.count()).select_from(Project)) == 0
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 0


def test_puct_without_rpg_projects_links_nothing_and_stays_unknown(stage_db, monkeypatch):
    puct_def, puct_job = setup_source(stage_db, pc.SOURCE_ID)
    origin = puct_origin()
    outcome = ingest(stage_db, puct_def, puct_job, pc, origin, puct_listing(origin), monkeypatch)
    assert outcome["report"].counts.get("link_linked", 0) == 0
    assert not [e for e, _ in evidences(stage_db, pc.SOURCE_ID, "ERCOT-PUCT-LINK-")]
    docket = next(ev for ext, ev in evidences(stage_db, pc.SOURCE_ID, "PUCT-CCN-61000"))
    assert docket.provenance["early_signal"]["document"]["extraction"]["fields"][
        "customer_request_mw"
    ] == {"value": None, "basis": "unknown", "reason": "not_stated"}


def test_puct_process_job_ships_off(stage_db, monkeypatch):
    import gridlens.ingestion.service as service

    definition, job_id = setup_source(stage_db, pc.SOURCE_ID)
    assert definition["enabled"] is False and definition["query"]["documents"]["enabled"] is False
    origin = puct_origin()
    records = puct_listing(origin)
    origin.log.clear()
    monkeypatch.setattr(service, "retrieve_source", lambda *_a, **_k: records)
    with stage_db() as session:
        service.process_job(session, job_id, WORKER, 1, definition, origin.client())
    assert origin.log == []
