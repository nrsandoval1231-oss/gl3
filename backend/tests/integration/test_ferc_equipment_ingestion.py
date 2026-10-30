"""Real GovInfo notice admission through normal ingestion and card projection."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

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

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "govinfo-complete-notice"
PDF_PATH = FIXTURE_DIR / "FR-2024-12869.pdf"
PROVENANCE_PATH = FIXTURE_DIR / "provenance.json"
PR153_BASELINE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "equipment-demand-pr153-baseline.json"
)


@pytest.fixture
def ferc_equipment_db():
    """Use an isolated schema in the configured disposable test database."""
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    schema = "ferc_equipment_ingestion_" + uuid4().hex
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
            lease_owner="ferc-equipment-worker",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
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


def _record(provenance: dict) -> dict:
    return {
        "document_number": provenance["document_number"],
        "title": provenance["official_title"],
        "abstract": None,
        "publication_date": provenance["publication_date"],
        # Federal Register's canonical document path is keyed by the official
        # publication date and document number; no title slug is synthesized.
        "html_url": (
            "https://www.federalregister.gov/documents/"
            f"{provenance['publication_date'].replace('-', '/')}/{provenance['document_number']}"
        ),
        "pdf_url": provenance["source_url"],
    }


def _install_fixture_pdf(monkeypatch):
    """Route the ordinary companion retrieval call through the retained real PDF."""
    from gridlens.ingestion.adapters.govinfo_pdf import retrieve_companion

    content = PDF_PATH.read_bytes()
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    assert hashlib.sha256(content).hexdigest() == provenance["sha256"]
    assert len(content) == provenance["response_bytes"]

    def retrieve(record, _client=None, **_kwargs):
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    content=content,
                    headers={"content-type": "application/pdf"},
                )
            ),
            timeout=15.0,
        )
        try:
            return retrieve_companion(record, client)
        finally:
            client.close()

    monkeypatch.setattr("gridlens.ingestion.service.retrieve_companion", retrieve)
    return provenance


def _capture_fixture_pdf(record: dict) -> dict[str, str]:
    """Return extraction from the authentic retained PDF fixture without network access."""
    from gridlens.ingestion.adapters.govinfo_pdf import retrieve_companion

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=PDF_PATH.read_bytes(),
                headers={"content-type": "application/pdf"},
            )
        ),
        timeout=15.0,
    ) as client:
        rows = retrieve_companion(record, client)
    assert len(rows) == 1
    return rows[0]


def _install_synthetic_text_mutation(monkeypatch, captured: dict, *, label: str, text: str) -> str:
    """Mutate only captured text for negative/correction DB tests.

    The retained PDF binary is never modified. The synthetic content hash is a
    test-only version key and does not claim that the source published these words.
    """
    synthetic_hash = hashlib.sha256(
        b"GL3 SYNTHETIC TEXT MUTATION - TEST ONLY\0"
        + label.encode("utf-8")
        + b"\0"
        + text.encode("utf-8")
    ).hexdigest()
    mutated = {**captured, "abstract": text, "content_hash": synthetic_hash}
    monkeypatch.setattr(
        "gridlens.ingestion.service.retrieve_companion",
        lambda *_args, **_kwargs: [mutated],
    )
    return synthetic_hash


def _seed_pr153_baseline_snapshot(factory, baseline: dict) -> None:
    """Restore the actual PR153 package snapshot without running current ingestion."""
    definition = next(row for row in load_registry() if row["id"] == baseline["source"]["id"])
    source_data = {
        key: definition[key]
        for key in (
            "id",
            "publisher",
            "endpoint",
            "family",
            "geography",
            "industries",
            "retrieval_method",
            "cadence_hours",
        )
    }
    project_data = baseline["project"]
    need_data = baseline["need"]
    observation_data = baseline["observation"]
    evidence_data = baseline["evidence"]
    interpretation_data = baseline["interpretation"]
    package_data = baseline["package"]
    project_id = project_data["id"]
    need_id = need_data["id"]
    observation_id = observation_data["id"]
    evidence_id = evidence_data["id"]
    with factory.begin() as session:
        session.add(Source(**source_data, health={}))
        session.flush()
        project = Project(
            id=project_id,
            identity_key=project_data["identity_key"],
            name=project_data["name"],
            location=project_data["location"],
            source_id=source_data["id"],
            external_id=observation_data["external_id"],
            region_status=project_data["region_status"],
        )
        session.add(project)
        session.flush()
        session.add(
            PowerNeed(
                id=need_id,
                project_id=project_id,
                activity_key=need_data["activity_key"],
                tier=need_data["tier"],
                rationale="Baseline PR153 evidence-bound equipment schedule.",
                required_mw=need_data["required_mw"],
                supply=need_data["supply"],
                active=need_data["active"],
            )
        )
        session.add(
            Observation(
                id=observation_id,
                source_id=source_data["id"],
                external_id=observation_data["external_id"],
                title=evidence_data["title"],
                abstract=evidence_data["abstract"],
                published_at=date.fromisoformat(evidence_data["published_at"]),
                url=evidence_data["url"],
                content_hash=observation_data["content_hash"],
            )
        )
        session.flush()
        session.add(
            Evidence(
                id=evidence_id,
                observation_id=observation_id,
                content_hash=evidence_data["content_hash"],
                title=evidence_data["title"],
                abstract=evidence_data["abstract"],
                url=evidence_data["url"],
                published_at=date.fromisoformat(evidence_data["published_at"]),
                observed_at=datetime.fromisoformat(evidence_data["observed_at"]),
                extraction_location=evidence_data["extraction_location"],
                event_date=(
                    date.fromisoformat(evidence_data["event_date"])
                    if evidence_data.get("event_date")
                    else None
                ),
            )
        )
        session.add(
            Interpretation(
                observation_id=observation_id,
                content_hash=observation_data["content_hash"],
                evaluator_version=interpretation_data["evaluator_version"],
                assessment=interpretation_data["assessment"],
                status=interpretation_data["status"],
            )
        )
        session.flush()
        session.add(NeedObservation(need_id=need_id, observation_id=observation_id))
        session.add(
            EvidencePackage(
                id=package_data["id"],
                package_key=package_data["package_key"],
                schema_version=package_data["schema_version"],
                evidence_id=evidence_id,
                observation_id=observation_id,
                project_id=project_id,
                need_id=need_id,
                evidence_hash=package_data["evidence_hash"],
                extractor_version=package_data["extractor_version"],
                question_contract=package_data["question_contract"],
                provider=package_data["provider"],
                model=package_data["model"],
                processing_status=package_data["processing_status"],
                payload=package_data["payload"],
            )
        )


def _run(factory, definition, job_id, record):
    from gridlens.ingestion.service import process_records

    with factory() as session:
        return process_records(
            session,
            job_id,
            "ferc-equipment-worker",
            1,
            definition,
            [record],
            allow_model=False,
        )


def test_real_ferc_notice_admits_only_new_electric_station_with_unknown_quantity(
    ferc_equipment_db,
    monkeypatch,
):
    from gridlens.api.app import opportunity_projection
    from gridlens.domain.ferc_equipment_interpretation import assess_ferc_equipment
    from gridlens.ingestion.parsers.ferc_equipment import extract_ferc_equipment
    from gridlens.intelligence.equipment_intelligence import current_equipment_investigation
    from gridlens.intelligence.opportunity_intelligence import attach_cards

    factory, definition, job_id = ferc_equipment_db
    provenance = _install_fixture_pdf(monkeypatch)
    record = _record(provenance)

    # The retained complete notice contains one proposed new electric unit at
    # CS302 and an existing-facility re-wheel at CS343. Preserve original bytes,
    # extracted text and quote spans throughout admission and projection.
    from gridlens.ingestion.adapters.govinfo_pdf import retrieve_companion

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=PDF_PATH.read_bytes(),
                headers={"content-type": "application/pdf"},
            )
        ),
        timeout=15.0,
    ) as client:
        retained = retrieve_companion(record, client)
    assert len(retained) == 1
    text_body = retained[0]["abstract"]
    extraction = extract_ferc_equipment(text_body, title=provenance["official_title"])
    assert [site.facility for site in extraction.sites] == [
        "Compressor Station 302",
        "Compressor Station 343",
    ]
    assert [claim.lifecycle_status for claim in extraction.sites[0].claims] == ["proposed"]
    assert extraction.sites[1].claims == ()
    assessment = assess_ferc_equipment(provenance["official_title"], text_body)
    assert assessment is not None and assessment["decision"] == "accepted"
    assert assessment["subject"] == "Compressor Station 302"
    assert assessment["location"] == "Montgomery County, Texas"

    first = _run(factory, definition, job_id, record)
    assert first["signals"] == 1
    with factory() as session:
        session.execute(text("SET LOCAL TIME ZONE 'America/Chicago'"))
        needs = list(session.scalars(select(PowerNeed)))
        assert len(needs) == 1
        need = needs[0]
        need_id, project_id = need.id, need.project_id
        project = session.get(Project, project_id)
        assert project is not None
        assert project.name == "Compressor Station 302"
        assert project.location == "Montgomery County, Texas"
        assert "343" not in project.name
        assert need.required_mw is None
        assert need.supply == "Unknown"
        assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 1

        observation = session.scalar(select(Observation))
        evidence = session.scalar(
            select(Evidence).where(Evidence.content_hash == provenance["sha256"])
        )
        interpretation = session.scalar(select(Interpretation))
        assert observation is not None and evidence is not None and interpretation is not None
        assert evidence.title == provenance["official_title"]
        assert evidence.url == provenance["source_url"]
        assert evidence.content_hash == provenance["sha256"]
        assert evidence.published_at.isoformat() == provenance["publication_date"]
        assert evidence.observed_at is not None
        assert "18,340 hp" in evidence.abstract
        assert "FR Doc. 2024–12869" not in evidence.abstract
        assert evidence.abstract.startswith(f"[GovInfo PDF page 1] {provenance['official_title']}")
        assert interpretation.assessment["evidence_hash"] == evidence.content_hash
        assert interpretation.assessment["project_hint"] == "Compressor Station 302"

        investigation = current_equipment_investigation(session, need_id, project_id)
        assert investigation is not None
        assert investigation["facility"] == "Compressor Station 302"
        assert investigation["status"] == "PARTIAL"
        assert investigation["classification"] == "UNKNOWN"
        assert investigation["demand"] is not None
        for field in ("connected_kw", "coincident_kw", "incremental_kw", "energy_mwh"):
            assert investigation["demand"][field] is None
        assert investigation["demand"]["items"][0]["status"] == "unknown"
        assert len(investigation["claim_candidates"]) == 1
        candidate = investigation["claim_candidates"][0]
        assert candidate["verification_state"] == "UNVERIFIED"
        assert candidate["drive_type"] == "electric"
        assert candidate["lifecycle_status"] == "proposed"
        assert candidate["count"] == 1
        assert candidate["rating"] == {"value": "18340", "unit": "hp", "basis": "unknown"}
        assert candidate["evidence"]["observed_at"].endswith(("Z", "+00:00"))
        assert candidate["evidence"]["retrieved_at"].endswith(("Z", "+00:00"))
        assert candidate["equipment_id"]
        assert investigation["residual_gap_kw"] is None
        assert investigation["supply_constraint_evidence"] == []
        assert investigation["decision_maker"] is None
        assert investigation["native_site_assertion"]["current_status"] == "UNKNOWN"
        assert investigation["native_site_assertion"]["company_identity"] == "UNKNOWN"
        source_context = investigation["native_source_context"]
        assert source_context["classification"] == "CONTEXT_ONLY_EXCEPT_SELECTED_SITE"
        assert [site["facility"] for site in source_context["sites"]] == [
            "Compressor Station 302",
            "Compressor Station 343",
        ]
        assert source_context["sites"][0]["scope"] == "selected_equipment_demand_site"
        assert source_context["sites"][1]["scope"] == "context_only_site"
        cs343_rewheel = source_context["sites"][1]["unsupported_activities"][0]
        assert cs343_rewheel["activity"] == "rewheel"
        assert cs343_rewheel["quote"] == (
            "Re-wheel existing electric motor driven compressor Units 9 and 10."
        )
        assert (
            evidence.abstract[cs343_rewheel["start"] : cs343_rewheel["end"]]
            == cs343_rewheel["quote"]
        )
        assert investigation["lifecycle"] == ["proposed"]
        assert investigation["expected_start"] == []
        assert investigation["as_of"] == provenance["publication_date"]
        for equipment in investigation["equipment"]:
            assert evidence.abstract[equipment["start"] : equipment["end"]] == equipment["quote"]
        assert any(
            "source-party identity" in item for item in investigation["unresolved_questions"]
        )

        items = opportunity_projection(
            session,
            selected_need_ids={need_id},
            include_operator_fact_refs=True,
        )
        assert len(items) == 1
        attach_cards(session, items, {})
        card = items[0]["intelligence_card"]
        assert card["equipment_demand"]["classification"] == "UNKNOWN"
        assert card["qualification"] == "Signal"
        assert card["power_gap"] is None
        demand_field = next(
            field for field in card["fields"] if field["key"] == "calculatedEquipmentDemand"
        )
        assert demand_field["status"] == "Research in progress"
        assert demand_field["sources"][0]["reference"].startswith("equipment-evidence:")
        assert not any(
            field.get("value") in {"18340 MW", "18,340 MW", "18.34 MW"} for field in card["fields"]
        )

        # Publication on the UTC retrieval date remains valid even when the
        # database-local date is still the prior day.
        from gridlens.domain.signal_admission import admitted_from_source

        evidence.observed_at = datetime(2024, 6, 12, 1, 0, tzinfo=UTC).astimezone(
            ZoneInfo("America/Chicago")
        )
        assert evidence.observed_at.date().isoformat() == "2024-06-11"
        assert admitted_from_source(
            session.get(Source, definition["id"]), interpretation.assessment, evidence
        ).admitted
        from gridlens.intelligence.equipment_intelligence import _payload

        local_midnight_payload = _payload(
            need,
            project,
            observation,
            evidence,
            session.get(Source, definition["id"]),
            interpretation,
        )
        assert local_midnight_payload is not None
        assert local_midnight_payload["status"] == "PARTIAL"
        assert (
            "Resolve a schedule or publication date after source retrieval."
            not in (local_midnight_payload["unresolved_questions"])
        )

    _run(factory, definition, job_id, record)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
        assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 1
        need = session.get(PowerNeed, need_id)
        assert need is not None and need.project_id == project_id
        assert need.required_mw is None and need.supply == "Unknown"

    # Simulate a lost advisory package and retry the unchanged observation.
    # The existing unchanged-record hook repairs the missing package from the
    # same immutable PDF without creating another version or Need.
    with factory.begin() as session:
        package = session.scalar(select(EvidencePackage))
        assert package is not None
        package_key, old_payload = package.package_key, json.loads(json.dumps(package.payload))
        session.delete(package)
    _run(factory, definition, job_id, record)
    with factory() as session:
        repaired = session.scalar(select(EvidencePackage))
        assert repaired is not None
        assert repaired.package_key == package_key
        assert repaired.payload == old_payload
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1


def test_ferc_native_replay_reinterprets_stale_cached_evaluator(ferc_equipment_db, monkeypatch):
    """An unchanged notice refreshes a stale interpretation version and package."""
    from gridlens.domain.ferc_equipment_interpretation import EVALUATOR_VERSION
    from gridlens.intelligence.equipment_intelligence import current_equipment_investigation

    factory, definition, job_id = ferc_equipment_db
    provenance = _install_fixture_pdf(monkeypatch)
    record = _record(provenance)
    _run(factory, definition, job_id, record)

    with factory.begin() as session:
        need = session.scalar(select(PowerNeed))
        package = session.scalar(select(EvidencePackage))
        interpretation = session.scalar(select(Interpretation))
        assert need is not None and package is not None and interpretation is not None
        need_id, project_id = need.id, need.project_id
        # Represent a cached context-only result from an older evaluator while
        # preserving the authentic source PDF and metadata for reprocessing.
        interpretation.evaluator_version = "context-only-v1"
        interpretation.assessment = {
            "decision": "context_only",
            "semantic_hash": interpretation.content_hash,
            "context": "Synthetic stale cache marker for test only.",
        }
        package_key = package.package_key

    counts = _run(factory, definition, job_id, record)
    assert counts.get("context_only", 0) == 0
    with factory() as session:
        interpretation = session.scalar(select(Interpretation))
        assert interpretation is not None
        assert interpretation.evaluator_version == EVALUATOR_VERSION
        assert interpretation.status == "accepted"
        assert interpretation.assessment["decision"] == "accepted"
        assert interpretation.assessment["evidence_hash"] == provenance["sha256"]
        assert current_equipment_investigation(session, need_id, project_id) is not None
        package = session.scalar(select(EvidencePackage))
        assert package is not None and package.package_key == package_key
        assert package.payload["binding"]["evaluator_version"] == EVALUATOR_VERSION


def test_ferc_native_demand_disappears_when_pdf_refresh_is_missing_or_source_changes(
    ferc_equipment_db,
    monkeypatch,
):
    import gridlens.ingestion.service as service
    from gridlens.intelligence.equipment_intelligence import current_equipment_investigation

    factory, definition, job_id = ferc_equipment_db
    provenance = _install_fixture_pdf(monkeypatch)
    record = _record(provenance)
    _run(factory, definition, job_id, record)
    with factory() as session:
        need = session.scalar(select(PowerNeed))
        assert need is not None
        pair = (need.id, need.project_id)
        assert current_equipment_investigation(session, *pair) is not None

    # A metadata replay without a companion cannot keep a prior retained PDF
    # current; historical evidence remains immutable while projection retracts.
    monkeypatch.setattr(service, "retrieve_companion", lambda *_args, **_kwargs: [])
    _run(factory, definition, job_id, {**record, "pdf_url": None})
    with factory() as session:
        assert current_equipment_investigation(session, *pair) is None
        evidence = session.scalar(
            select(Evidence).where(Evidence.content_hash == provenance["sha256"])
        )
        assert evidence is not None and evidence.url == provenance["source_url"]

    # Reacquire, then mutate the retained citation to a different valid GovInfo
    # document on the same publication date. The stale native binding is hidden.
    _install_fixture_pdf(monkeypatch)
    _run(factory, definition, job_id, record)
    with factory.begin() as session:
        evidence = session.scalar(
            select(Evidence).where(Evidence.content_hash == provenance["sha256"])
        )
        assert evidence is not None
        evidence.url = "https://www.govinfo.gov/content/pkg/FR-2024-06-12/pdf/2024-12870.pdf"
    with factory() as session:
        assert current_equipment_investigation(session, *pair) is None


def test_synthetic_multisite_conflict_retracts_prior_admission_and_keeps_history(
    ferc_equipment_db,
    monkeypatch,
):
    """Synthetic captured-text mutation checks the DB path for ambiguous scope."""
    from gridlens.intelligence.equipment_intelligence import current_equipment_investigation

    factory, definition, job_id = ferc_equipment_db
    provenance = _install_fixture_pdf(monkeypatch)
    record = _record(provenance)
    _run(factory, definition, job_id, record)
    captured = _capture_fixture_pdf(record)
    original = captured["abstract"]
    existing_station_activity = "Re-wheel existing electric motor driven compressor Units 9 and 10."
    assert existing_station_activity in original
    # This synthetic variant makes CS343 a second proposed electric site. It
    # modifies only extracted text returned by the mock; FR-2024-12869.pdf stays
    # the authentic, hash-checked fixture on disk.
    two_new_sites = original.replace(
        existing_station_activity,
        "Install one new electric motor driven compressor unit with a rating of 100 hp.",
        1,
    )
    assert two_new_sites != original
    synthetic_hash = _install_synthetic_text_mutation(
        monkeypatch, captured, label="two-qualifying-stations", text=two_new_sites
    )

    with factory() as session:
        need = session.scalar(select(PowerNeed))
        assert need is not None
        need_id, project_id = need.id, need.project_id
        old_package = session.scalar(select(EvidencePackage))
        assert old_package is not None
        old_package_id = old_package.id
        old_package_payload = json.loads(json.dumps(old_package.payload))

    _run(factory, definition, job_id, record)

    with factory() as session:
        need = session.get(PowerNeed, need_id)
        assert need is not None and need.active is False
        assert (
            session.scalar(
                select(func.count()).select_from(PowerNeed).where(PowerNeed.active.is_(True))
            )
            == 0
        )
        assert current_equipment_investigation(session, need_id, project_id) is None
        # A rejected correction retracts current support but does not rewrite
        # the package or either source-evidence version already retained.
        package = session.get(EvidencePackage, old_package_id)
        assert package is not None and package.payload == old_package_payload
        assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(Evidence)
                .where(Evidence.content_hash == provenance["sha256"])
            )
            == 1
        )
        synthetic_evidence = session.scalar(
            select(Evidence).where(Evidence.content_hash == synthetic_hash)
        )
        assert synthetic_evidence is not None
        assert "100 hp" in synthetic_evidence.abstract


def test_synthetic_positive_site_rebind_retires_old_site_without_claim_leakage(
    ferc_equipment_db,
    monkeypatch,
):
    """Synthetic text correction rebinds one record to a distinct physical site."""
    from gridlens.intelligence.equipment_intelligence import current_equipment_investigation

    factory, definition, job_id = ferc_equipment_db
    provenance = _install_fixture_pdf(monkeypatch)
    record = _record(provenance)
    _run(factory, definition, job_id, record)
    captured = _capture_fixture_pdf(record)
    original = captured["abstract"]
    cs302_install = (
        "Install one new electric motor driven compressor unit with a rating of 18,340 hp."
    )
    cs343_rewheel = "Re-wheel existing electric motor driven compressor Units 9 and 10."
    assert cs302_install in original and cs343_rewheel in original

    # Test-only captured-text variant: CS302's proposed electric unit is
    # reported as a gas-engine-driven unit, and CS343 has one new electric unit.
    # This verifies site rekeying without altering or misrepresenting the real PDF.
    moved_site_text = original.replace(
        cs302_install,
        "Install one new gas engine driven compressor unit with a rating of 18,340 hp.",
        1,
    ).replace(
        cs343_rewheel,
        "Install one new electric motor driven compressor unit with a rating of 100 hp.",
        1,
    )
    assert moved_site_text != original
    synthetic_hash = _install_synthetic_text_mutation(
        monkeypatch, captured, label="positive-site-rebind-to-cs343", text=moved_site_text
    )

    with factory() as session:
        old_need = session.scalar(select(PowerNeed))
        assert old_need is not None
        old_need_id, old_project_id = old_need.id, old_need.project_id
        old_project = session.get(Project, old_project_id)
        assert old_project is not None
        old_identity_key = old_project.identity_key
        old_package = session.scalar(select(EvidencePackage))
        assert old_package is not None
        old_package_id = old_package.id
        old_package_payload = json.loads(json.dumps(old_package.payload))

    _run(factory, definition, job_id, record)

    with factory() as session:
        needs = list(session.scalars(select(PowerNeed)))
        assert len(needs) == 2
        old_need = session.get(PowerNeed, old_need_id)
        assert old_need is not None and old_need.active is False
        new_needs = [need for need in needs if need.active]
        assert len(new_needs) == 1
        new_need = new_needs[0]
        new_project = session.get(Project, new_need.project_id)
        assert new_project is not None
        assert new_project.id != old_project_id
        assert new_project.identity_key != old_identity_key
        assert new_project.name == "Compressor Station 343"
        assert new_project.location == "Liberty County, Texas"
        assert current_equipment_investigation(session, old_need_id, old_project_id) is None
        current = current_equipment_investigation(session, new_need.id, new_project.id)
        assert current is not None and current["status"] == "PARTIAL"
        assert current["facility"] == "Compressor Station 343"
        assert current["classification"] == "UNKNOWN"
        assert len(current["equipment"]) == 1
        assert current["equipment"][0]["drive"] == "electric"
        assert current["equipment"][0]["quote"] == (
            "Install one new electric motor driven compressor unit with a rating of 100 hp."
        )
        assert "18,340 hp" not in current["equipment"][0]["quote"]
        assert len(current["claim_candidates"]) == 1
        assert current["claim_candidates"][0]["project_id"] == str(new_project.id)

        # The previous package remains immutable history; the replacement uses
        # only its new site and synthetic corrected evidence version.
        retained_old_package = session.get(EvidencePackage, old_package_id)
        assert retained_old_package is not None
        assert retained_old_package.payload == old_package_payload
        assert session.scalar(select(func.count()).select_from(Project)) == 2
        assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 2
        new_package = session.scalar(
            select(EvidencePackage).where(EvidencePackage.need_id == new_need.id)
        )
        assert new_package is not None
        assert new_package.evidence_hash == synthetic_hash
        assert new_package.payload["facility"] == "Compressor Station 343"


def test_baseline_pr153_package_remains_current_without_ingestion_replay(ferc_equipment_db):
    """The current SQL read accepts the actual pre-native PR153 package snapshot."""
    from gridlens.intelligence.equipment_intelligence import current_equipment_investigation

    factory, _definition, _job_id = ferc_equipment_db
    baseline = json.loads(PR153_BASELINE_PATH.read_text(encoding="utf-8"))
    _seed_pr153_baseline_snapshot(factory, baseline)

    with factory() as session:
        session.execute(text("SET LOCAL TIME ZONE 'America/Chicago'"))
        need_id = baseline["need"]["id"]
        project_id = baseline["project"]["id"]
        package = session.scalar(select(EvidencePackage))
        assert package is not None
        assert (
            package.package_key
            == "74764c7ad5e7a265e4e869a9424e389d493ff8bfb14d6a40bbc19adcf83bf636"
        )
        assert package.payload == baseline["package"]["payload"]
        assert package.package_key == package.payload["input_fingerprint"]
        for native_only_key in (
            "equipment_identity",
            "native_site_assertion",
            "native_source_context",
            "claim_candidates",
        ):
            assert native_only_key not in package.payload

        current = current_equipment_investigation(session, need_id, project_id)
        assert current == baseline["current"]
        assert current["binding"] == baseline["package"]["payload"]["binding"]
        assert current["input_fingerprint"] == package.package_key
        assert current["demand"]["coincident_kw"].startswith("828.555")
        assert current["demand"]["connected_kw"].startswith("1657.110")
        assert current["unresolved_questions"] == [
            "Identify the equipment procurement decision-maker and purchase timing."
        ]
        assert current["equipment"] == baseline["package"]["payload"]["equipment"]
        assert current["demand"] == baseline["package"]["payload"]["demand"]
        assert current["company"] == baseline["package"]["payload"]["company"]
        assert current["classification"] == baseline["package"]["payload"]["classification"]
        assert current["status"] == baseline["package"]["payload"]["status"]


@pytest.mark.parametrize("context_only_interpretation", [False, True])
def test_native_observation_revised_to_generic_context_retracts_unsupported_need(
    ferc_equipment_db,
    monkeypatch,
    context_only_interpretation,
):
    """A nonmatching title cannot preserve native FERC demand support."""
    from gridlens.intelligence.equipment_intelligence import current_equipment_investigation

    factory, definition, job_id = ferc_equipment_db
    provenance = _install_fixture_pdf(monkeypatch)
    record = _record(provenance)
    _run(factory, definition, job_id, record)
    with factory() as session:
        need = session.scalar(select(PowerNeed))
        package = session.scalar(select(EvidencePackage))
        assert need is not None and package is not None
        need_id, project_id, package_id = need.id, need.project_id, package.id
        old_payload = json.loads(json.dumps(package.payload))
        assert current_equipment_investigation(session, need_id, project_id) is not None

    # This is a synthetic metadata revision only. It exercises both an
    # uninterpretable generic title and a valid generic mine interpretation
    # that the Federal Register source must retain as context-only. No updated
    # source document or PDF is represented by this synthetic record.
    generic_revision = {
        **record,
        "title": (
            "Silver Ridge Mine: Synthetic Test Notice"
            if context_only_interpretation
            else "Environmental Assessment Availability Notice"
        ),
        "abstract": (
            "The proposed Mine Plan of Operations would develop the mine, with dewatering "
            "and ventilation shafts."
            if context_only_interpretation
            else None
        ),
        "html_url": "https://example.test/synthetic-federal-register-context",
        "pdf_url": None,
    }
    counts = _run(factory, definition, job_id, generic_revision)
    assert counts.get("context_only", 0) == (1 if context_only_interpretation else 0)

    with factory() as session:
        need = session.get(PowerNeed, need_id)
        assert need is not None and need.active is False
        assert current_equipment_investigation(session, need_id, project_id) is None
        retained = session.get(EvidencePackage, package_id)
        assert retained is not None and retained.payload == old_payload
        assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(Evidence)
                .where(Evidence.content_hash == provenance["sha256"])
            )
            == 1
        )
        current_interpretation = session.scalar(select(Interpretation))
        assert current_interpretation is not None
        assert current_interpretation.assessment is not None
        assert current_interpretation.assessment.get("native_equipment") is None
        if context_only_interpretation:
            assert current_interpretation.assessment["decision"] == "context_only"
            assert current_interpretation.evaluator_version == "context-only-v1"
        else:
            assert current_interpretation.assessment.get("decision") != "accepted"
