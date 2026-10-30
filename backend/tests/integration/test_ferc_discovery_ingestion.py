"""Historical captured Federal Register discovery through canonical ingestion."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.registry import load_registry
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    EvidencePackage,
    Interpretation,
    Job,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "federal-register-ferc-discovery"
EIS_CAPTURE = FIXTURE_DIR / "eis-2024-05-31_2024-06-30.json"
FERC_EA_CAPTURE = FIXTURE_DIR / "ferc-ea-2024-05-31_2024-06-30.json"
PROVENANCE_PATH = FIXTURE_DIR / "provenance.json"
PDF_PATH = FIXTURE_DIR.parent / "govinfo-complete-notice" / "FR-2024-12869.pdf"
QUERY_AS_OF = date(2024, 6, 30)
QUERY_START = date(2024, 5, 31)
TARGET_DOCUMENT = "2024-12869"


@pytest.fixture
def ferc_discovery_db():
    """Use a disposable PostgreSQL schema for real discovery/ingestion tests."""
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    schema = "ferc_discovery_ingestion_" + uuid4().hex
    admin = create_engine(target)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(target, connect_args={"options": f"-csearch_path={schema}"})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    definition = next(row for row in load_registry() if row["id"] == "federal-register-eis")
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
            lease_owner="ferc-discovery-test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=15),
        )
        session.add(job)
        session.flush()
        job_id = job.id
    try:
        yield factory, definition, job_id
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


class _CaptureDate(date):
    @classmethod
    def today(cls):
        return QUERY_AS_OF


def _capture_payload(path: Path) -> dict:
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    entry = next(capture for capture in provenance["captures"] if capture["file"] == path.name)
    content = path.read_bytes()
    assert len(content) == entry["response_bytes"]
    assert hashlib.sha256(content).hexdigest() == entry["sha256"]
    payload = json.loads(content)
    assert isinstance(payload, dict) and isinstance(payload.get("results"), list)
    assert len(payload["results"]) == entry["count"]
    assert (
        any(
            row.get("document_number") == provenance["target_document_number"]
            for row in payload["results"]
        )
        is entry["target_document_present"]
    )
    return payload


def _http_client(monkeypatch, *, eis_payload=None, ea_payload=None):
    """Replay captured API responses and the authentic GovInfo PDF over HTTP."""
    import gridlens.ingestion.adapters.federal_register as federal_register
    import gridlens.ingestion.service as service
    from gridlens.ingestion.adapters.govinfo_pdf import retrieve_companion

    _capture_payload(EIS_CAPTURE)
    _capture_payload(FERC_EA_CAPTURE)
    eis_bytes = (
        EIS_CAPTURE.read_bytes()
        if eis_payload is None
        else json.dumps(eis_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    ea_bytes = (
        FERC_EA_CAPTURE.read_bytes()
        if ea_payload is None
        else json.dumps(ea_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    pdf_bytes = PDF_PATH.read_bytes()
    pdf_provenance = json.loads((PDF_PATH.parent / "provenance.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(pdf_bytes).hexdigest() == pdf_provenance["sha256"]

    requests: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "www.federalregister.gov":
            term = request.url.params.get("conditions[term]")
            agency = request.url.params.get("conditions[agencies][]")
            if term == "environmental impact statement" and agency is None:
                return httpx.Response(
                    200, content=eis_bytes, headers={"content-type": "application/json"}
                )
            if (
                term == "environmental assessment"
                and agency == "federal-energy-regulatory-commission"
            ):
                return httpx.Response(
                    200, content=ea_bytes, headers={"content-type": "application/json"}
                )
            return httpx.Response(400, json={"error": "unexpected Federal Register query"})
        if request.url.host == "www.govinfo.gov" and request.url.path.endswith("/2024-12869.pdf"):
            return httpx.Response(
                200, content=pdf_bytes, headers={"content-type": "application/pdf"}
            )
        return httpx.Response(404, text="Fixture does not include this companion PDF")

    monkeypatch.setattr(federal_register, "date", _CaptureDate)
    real_retrieve_companion = retrieve_companion

    def retrieve_target_companion(record, client=None, **kwargs):
        # The retained real companion is only for the target notice. Other
        # candidate PDFs are outside this fixture; let their metadata ingest.
        if record.get("document_number") != TARGET_DOCUMENT:
            return []
        return real_retrieve_companion(record, client, **kwargs)

    monkeypatch.setattr(service, "retrieve_companion", retrieve_target_companion)
    return httpx.Client(transport=httpx.MockTransport(responder)), requests


def _assert_historical_query_requests(requests: list[httpx.Request]) -> None:
    api_requests = [
        request for request in requests if request.url.host == "www.federalregister.gov"
    ]
    assert len(api_requests) == 2
    by_term = {request.url.params["conditions[term]"]: request.url for request in api_requests}
    assert set(by_term) == {"environmental impact statement", "environmental assessment"}
    for url in by_term.values():
        assert url.params["conditions[publication_date][gte]"] == QUERY_START.isoformat()
        assert url.params["conditions[publication_date][lte]"] == QUERY_AS_OF.isoformat()
        assert url.params["conditions[type][]"] == "NOTICE"
        assert url.params["per_page"] == "100"
        assert url.params["page"] == "1"
    assert by_term["environmental assessment"].params["conditions[agencies][]"] == (
        "federal-energy-regulatory-commission"
    )
    assert "conditions[agencies][]" not in by_term["environmental impact statement"].params


def _run(factory, definition, job_id, client):
    from gridlens.ingestion.service import process_job

    with factory() as session:
        return process_job(
            session,
            job_id,
            "ferc-discovery-test",
            1,
            definition,
            client,
            deadline=None,
        )


def _synthetic_cross_query_conflict(eis_payload: dict) -> dict:
    """Create a labeled conflict variant without editing captured source files."""
    changed = copy.deepcopy(eis_payload)
    target = next(row for row in changed["results"] if row["document_number"] == "2024-13932")
    target["title"] += " [SYNTHETIC CONFLICT TEST VARIANT]"
    return changed


def test_historical_dual_query_discovery_ingests_ferc_ea_and_is_idempotent(
    ferc_discovery_db, monkeypatch
):
    """Real API JSON and matching PDF produce one unknown-quantity FERC Signal."""
    from gridlens.intelligence.equipment_intelligence import current_equipment_investigation

    factory, definition, job_id = ferc_discovery_db
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    assert provenance["query_as_of"] == QUERY_AS_OF.isoformat()
    assert provenance["window_days"] == 30
    assert provenance["target_document_number"] == TARGET_DOCUMENT
    client, requests = _http_client(monkeypatch)
    try:
        first = _run(factory, definition, job_id, client)
        _assert_historical_query_requests(requests)
        assert first["retrieved_records"] == 86
        assert first["attempt_fetched"] == 86
        assert first["attempt_duplicate"] == 0
        assert first.get("partial") is not True
        assert first.get("collection_status") != "PARTIAL"

        with factory() as session:
            observation = session.scalar(
                select(Observation).where(Observation.external_id == TARGET_DOCUMENT)
            )
            need = session.scalar(select(PowerNeed))
            assert observation is not None and need is not None
            assert need.project_id is not None
            project = session.get(Project, need.project_id)
            assert project is not None
            assert project.name == "Compressor Station 302"
            assert project.location == "Montgomery County, Texas"
            assert need.required_mw is None and need.supply == "Unknown"
            assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
            pdf_provenance = json.loads(
                (PDF_PATH.parent / "provenance.json").read_text(encoding="utf-8")
            )
            evidence = session.scalar(
                select(Evidence).where(Evidence.url == pdf_provenance["source_url"])
            )
            assert evidence is not None
            assert evidence.content_hash == pdf_provenance["sha256"]
            assert evidence.published_at == date(2024, 6, 12)
            interpretation = session.scalar(
                select(Interpretation).where(Interpretation.observation_id == observation.id)
            )
            assert interpretation is not None
            assert interpretation.assessment["decision"] == "accepted"
            assert interpretation.assessment["project_hint"] == "Compressor Station 302"
            assert isinstance(interpretation.assessment.get("native_equipment"), dict)
            current = current_equipment_investigation(session, need.id, project.id)
            assert current is not None
            assert current["status"] == "PARTIAL"
            assert current["classification"] == "UNKNOWN"
            assert current["demand"]["connected_kw"] is None
            assert current["demand"]["coincident_kw"] is None
            assert current["claim_candidates"][0]["verification_state"] == "UNVERIFIED"
            assert current["claim_candidates"][0]["rating"] == {
                "value": "18340",
                "unit": "hp",
                "basis": "unknown",
            }
            assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 1
            original_observation_hash = observation.content_hash
            original_evidence_hash = evidence.content_hash

        # Replay the exact captured source pages and authentic PDF; canonical
        # observations and demand package remain stable.
        requests.clear()
        second = _run(factory, definition, job_id, client)
        _assert_historical_query_requests(requests)
        assert second["new"] == 0
        assert second["changed"] == 0
        assert second["signals"] == 0
        with factory() as session:
            observation = session.scalar(
                select(Observation).where(Observation.external_id == TARGET_DOCUMENT)
            )
            assert observation is not None and observation.content_hash == original_observation_hash
            assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
            assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 1
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(Evidence)
                    .where(Evidence.url == pdf_provenance["source_url"])
                )
                == 1
            )
            assert session.scalar(select(func.count()).select_from(NeedObservation)) == 1
            evidence = session.scalar(
                select(Evidence).where(Evidence.url == pdf_provenance["source_url"])
            )
            assert evidence is not None and evidence.content_hash == original_evidence_hash
    finally:
        client.close()


def test_zero_result_ferc_query_lane_is_healthy_not_partial(ferc_discovery_db, monkeypatch):
    """An empty valid FERC EA lane does not make the successful EIS lane partial."""
    factory, definition, job_id = ferc_discovery_db
    empty_ea = {"count": 0, "total_pages": 0, "results": []}
    client, requests = _http_client(monkeypatch, ea_payload=empty_ea)
    try:
        counts = _run(factory, definition, job_id, client)
        _assert_historical_query_requests(requests)
        assert counts["retrieved_records"] == 72
        assert counts.get("partial") is not True
        assert counts.get("collection_status") != "PARTIAL"
        with factory() as session:
            assert (
                session.scalar(
                    select(Observation).where(Observation.external_id == TARGET_DOCUMENT)
                )
                is None
            )
    finally:
        client.close()


def test_cross_query_conflicts_quarantine_all_variants_and_preserve_history(
    ferc_discovery_db, monkeypatch
):
    """Conflicting metadata for one overlapped ID is rejected, not arbitrarily selected."""
    factory, definition, job_id = ferc_discovery_db
    client, requests = _http_client(monkeypatch)
    try:
        initial = _run(factory, definition, job_id, client)
        assert initial.get("partial") is not True
        with factory() as session:
            prior = session.scalar(
                select(Observation).where(Observation.external_id == "2024-13932")
            )
            assert prior is not None
            prior_title, prior_hash = prior.title, prior.content_hash

        # Only this in-memory EIS response changes; the retained JSON capture and
        # authentic PDF remain byte-for-byte untouched.
        changed_eis = _synthetic_cross_query_conflict(_capture_payload(EIS_CAPTURE))
        conflict_client, conflict_requests = _http_client(monkeypatch, eis_payload=changed_eis)
        try:
            result = _run(factory, definition, job_id, conflict_client)
        finally:
            conflict_client.close()
        _assert_historical_query_requests(conflict_requests)
        assert result.get("partial") is True
        assert result["collection_status"] == "PARTIAL"
        assert result["attempt_rejected"] == 2
        assert result["attempt_processed"] == 85
        assert len(result["rejected_records"]) == 2
        assert {item["identity"] for item in result["rejected_records"]} == {"2024-13932"}
        with factory() as session:
            prior = session.scalar(
                select(Observation).where(Observation.external_id == "2024-13932")
            )
            assert prior is not None
            assert prior.title == prior_title and prior.content_hash == prior_hash
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(Observation)
                    .where(Observation.external_id == "2024-13932")
                )
                == 1
            )
            assert (
                session.scalar(
                    select(Observation).where(Observation.external_id == TARGET_DOCUMENT)
                )
                is not None
            )
    finally:
        client.close()
