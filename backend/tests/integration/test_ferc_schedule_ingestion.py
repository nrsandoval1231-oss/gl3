"""Authentic FERC environmental-review schedule evidence through ingestion."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
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

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "ferc-review-schedule"
SCHEDULE_RECORD_PATH = FIXTURE_DIR / "federal-register-record.json"
SCHEDULE_CAPTURE_PATH = FIXTURE_DIR / "federal-register-api-capture.json"
SCHEDULE_CAPTURE_PROVENANCE_PATH = FIXTURE_DIR / "federal-register-api-capture-provenance.json"
SCHEDULE_PROVENANCE_PATH = FIXTURE_DIR / "provenance.json"
SCHEDULE_PDF_PATH = FIXTURE_DIR / "FR-2024-00135.pdf"
AVAILABILITY_PDF_PATH = (
    Path(__file__).parents[1] / "fixtures" / "govinfo-complete-notice" / "FR-2024-12869.pdf"
)
AVAILABILITY_METADATA_PATH = (
    Path(__file__).parents[1]
    / "fixtures"
    / "federal-register-ferc-discovery"
    / "ferc-ea-2024-05-31_2024-06-30.json"
)


@pytest.fixture
def ferc_schedule_db():
    """Use an isolated schema in the configured disposable test database."""
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    schema = "ferc_schedule_ingestion_" + uuid4().hex
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
            lease_owner="ferc-schedule-worker",
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


def _source_records() -> tuple[dict, dict, dict[str, bytes]]:
    schedule_capture = json.loads(SCHEDULE_CAPTURE_PATH.read_text(encoding="utf-8"))
    schedule_provenance = json.loads(SCHEDULE_CAPTURE_PROVENANCE_PATH.read_text(encoding="utf-8"))
    schedule_capture_bytes = SCHEDULE_CAPTURE_PATH.read_bytes()
    assert hashlib.sha256(schedule_capture_bytes).hexdigest() == schedule_provenance["sha256"]
    assert len(schedule_capture_bytes) == schedule_provenance["bytes"]

    schedule_record = json.loads(SCHEDULE_RECORD_PATH.read_text(encoding="utf-8"))
    assert schedule_record == next(
        row for row in schedule_capture["results"] if row["document_number"] == "2024-00135"
    )
    schedule_provenance = json.loads(SCHEDULE_PROVENANCE_PATH.read_text(encoding="utf-8"))
    schedule_pdf = SCHEDULE_PDF_PATH.read_bytes()
    assert len(schedule_pdf) == schedule_provenance["pdf_bytes"]
    assert hashlib.sha256(schedule_pdf).hexdigest() == schedule_provenance["pdf_sha256"]
    assert schedule_record["pdf_url"] == schedule_provenance["pdf_url"]

    availability_capture = json.loads(AVAILABILITY_METADATA_PATH.read_text(encoding="utf-8"))
    availability_record = next(
        row for row in availability_capture["results"] if row["document_number"] == "2024-12869"
    )
    availability_pdf = AVAILABILITY_PDF_PATH.read_bytes()
    api_bytes = {
        schedule_record["pdf_url"]: schedule_pdf,
        availability_record["pdf_url"]: availability_pdf,
    }
    return schedule_record, availability_record, api_bytes


def _mock_client(api_bytes: dict[str, bytes]) -> httpx.Client:
    def serve(request: httpx.Request) -> httpx.Response:
        content = api_bytes.get(str(request.url))
        if content is None:
            return httpx.Response(404, request=request)
        return httpx.Response(
            200,
            content=content,
            headers={"content-type": "application/pdf"},
            request=request,
        )

    return httpx.Client(transport=httpx.MockTransport(serve), follow_redirects=False)


def _run(factory, definition, job_id, record, client):
    from gridlens.ingestion.service import process_records

    with factory() as session:
        return process_records(
            session,
            job_id,
            "ferc-schedule-worker",
            1,
            definition,
            [record],
            client=client,
            allow_model=False,
        )


@pytest.mark.parametrize(
    "order",
    [
        ("schedule", "availability"),
        ("availability", "schedule"),
    ],
)
def test_authentic_schedule_and_availability_share_one_unknown_need_without_double_count(
    ferc_schedule_db,
    monkeypatch,
    order,
):
    from gridlens.domain.ferc_equipment_interpretation import EVALUATOR_VERSION
    from gridlens.ingestion.adapters.govinfo_pdf import retrieve_companion
    from gridlens.intelligence.equipment_intelligence import current_equipment_investigation

    factory, definition, job_id = ferc_schedule_db
    schedule, availability, api_bytes = _source_records()
    schedule_provenance = json.loads(SCHEDULE_PROVENANCE_PATH.read_text(encoding="utf-8"))
    records = {"schedule": schedule, "availability": availability}
    monkeypatch.setattr(logging.getLogger("pypdf"), "level", logging.ERROR)
    with _mock_client(api_bytes) as client:
        for key in order:
            counts = _run(factory, definition, job_id, records[key], client)
            assert counts["pdf_enriched"] == 1

        with factory() as session:
            needs = list(session.scalars(select(PowerNeed)))
            projects = list(session.scalars(select(Project)))
            observations = list(session.scalars(select(Observation)))
            evidence = list(session.scalars(select(Evidence)))
            packages = list(
                session.scalars(
                    select(EvidencePackage).where(
                        EvidencePackage.schema_version == "equipment-demand-v1"
                    )
                )
            )
            assert len(projects) == 1
            assert len(needs) == 1
            assert projects[0].name == "Compressor Station 302"
            assert projects[0].location == "Montgomery County, Texas"
            assert needs[0].active is True
            assert needs[0].required_mw is None
            assert needs[0].start_window is None
            assert needs[0].duration is None
            need_id, project_id = needs[0].id, projects[0].id
            assert {row.external_id for row in observations} == {"2024-00135", "2024-12869"}
            assert len(evidence) == 4  # two Federal Register records and their PDF companions
            assert len(packages) == 2
            assert len({package.evidence_id for package in packages}) == 2
            assert session.scalar(select(func.count()).select_from(NeedObservation)) == 2

            evidence_by_document = {
                observation.external_id: next(
                    row
                    for row in evidence
                    if row.observation_id == observation.id
                    and row.url
                    == records[
                        "schedule" if observation.external_id == "2024-00135" else "availability"
                    ]["pdf_url"]
                )
                for observation in observations
            }
            schedule_evidence = evidence_by_document["2024-00135"]
            availability_evidence = evidence_by_document["2024-12869"]
            equipment_quote = (
                "Install one new electric motor driven (EMD) compressor unit "
                "with a rating of 18,340 hp."
            )
            assert schedule_evidence.url == schedule["pdf_url"]
            assert schedule_evidence.published_at.isoformat() == "2024-01-08"
            assert availability_evidence.url == availability["pdf_url"]
            assert availability_evidence.published_at.isoformat() == "2024-06-12"
            assert equipment_quote in schedule_evidence.abstract
            assert "Install one new electric motor" in availability_evidence.abstract
            assert "18,340 hp" in availability_evidence.abstract
            assert "Issuance of EA June 6, 2024" in schedule_evidence.abstract
            assert (
                "Federal Authorization Decision Deadline 2 September 4, 2024"
                in schedule_evidence.abstract
            )
            assert schedule_evidence.event_date is None
            assert availability_evidence.event_date is None

            schedule_observation_id = session.scalar(
                select(Observation.id).where(Observation.external_id == "2024-00135")
            )
            schedule_interpretation = session.scalar(
                select(Interpretation).where(
                    Interpretation.observation_id == schedule_observation_id
                )
            )
            assert schedule_interpretation is not None
            native_schedule = schedule_interpretation.assessment["native_equipment"]
            assert schedule_interpretation.evaluator_version == EVALUATOR_VERSION
            assert native_schedule["notice_kind"] == "environmental_review_schedule"
            assert native_schedule["docket_context"]["status"] == "SOURCE_BOUND"
            assert native_schedule["docket_context"]["normalized_full"] == "CP24-8-000"
            docket_refs = native_schedule["docket_context"]["references"]
            assert docket_refs
            assert all(
                schedule_evidence.abstract[ref["start"] : ref["end"]] == ref["quote"]
                for ref in docket_refs
            )
            assert all(
                item["scope"] == "context_only" for item in native_schedule["project_activities"]
            )
            assert any(
                "unscoped_appurtenant_facilities" in item["activity"]
                for item in native_schedule["project_activities"]
            )

            package_by_document = {
                observation.external_id: next(
                    package
                    for package in packages
                    if package.evidence_id == evidence_by_document[observation.external_id].id
                )
                for observation in observations
            }
            schedule_package = package_by_document["2024-00135"]
            availability_package = package_by_document["2024-12869"]
            assert (
                schedule_package.payload["native_site_assertion"]["notice_kind"]
                == "environmental_review_schedule"
            )
            assert (
                availability_package.payload["native_site_assertion"]["notice_kind"]
                == "environmental_assessment_availability"
            )
            assert schedule_package.payload["native_site_assertion"]["current_status"] == "UNKNOWN"
            assert (
                availability_package.payload["native_site_assertion"]["current_status"] == "UNKNOWN"
            )
            for package, source_evidence in (
                (schedule_package, schedule_evidence),
                (availability_package, availability_evidence),
            ):
                docket = package.payload["native_site_assertion"]["docket"]
                assert docket["status"] == "SOURCE_BOUND"
                assert docket["normalized_full"] == "CP24-8-000"
                assert all(
                    source_evidence.abstract[ref["start"] : ref["end"]] == ref["quote"]
                    for ref in docket["references"]
                )
            package_snapshots = {
                str(package.evidence_id): json.loads(json.dumps(package.payload))
                for package in packages
            }
            evidence_snapshots = {
                str(row.id): (row.content_hash, row.abstract, row.url, row.published_at)
                for row in evidence
            }

        with factory() as session:
            investigation = current_equipment_investigation(session, need_id, project_id)
            assert investigation is not None
            # Existing policy does not add or silently corroborate assertions
            # across dated source signatures, even when the ratings agree.
            assert investigation["status"] == "ABSTAINED"
            assert investigation["classification"] == "UNKNOWN"
            assert investigation["demand"] is None
            assert any(
                "overlapping or conflicting equipment schedules" in question
                for question in investigation["unresolved_questions"]
            )
            assert investigation["expected_start"] == []
            assert investigation["decision_maker"] is None
            assert investigation["native_site_assertion"]["current_status"] == "UNKNOWN"
            assert investigation["lifecycle"] == ["proposed"]
            assert investigation["native_site_assertion"]["company_identity"] == "UNKNOWN"
            assert investigation["native_source_context"]["notice_kind"] in {
                "environmental_review_schedule",
                "environmental_assessment_availability",
            }
            # Each source reports the same 18,340 hp unit; citations do not turn
            # either proposal into verified equipment or additive electrical demand.
            assert investigation["claim_candidates"]
            assert all(
                candidate["verification_state"] == "UNVERIFIED"
                and candidate["rating"] == {"value": "18340", "unit": "hp", "basis": "unknown"}
                for candidate in investigation["claim_candidates"]
            )
            cited_urls = {item["url"] for item in investigation["evidence"]}
            assert schedule["pdf_url"] in cited_urls
            assert availability["pdf_url"] in cited_urls

        # An unchanged replay is the maintained hook for evaluator/parser
        # upgrades. Make one cache stale and verify the authentic evidence rows
        # and immutable demand packages remain available after re-evaluation.
        with factory.begin() as session:
            stale = session.scalar(
                select(Interpretation).where(
                    Interpretation.observation_id
                    == select(Observation.id)
                    .where(Observation.external_id == "2024-00135")
                    .scalar_subquery()
                )
            )
            assert stale is not None
            stale.evaluator_version = "ferc-equipment-legacy-test"
        with factory() as session:
            before_replay = current_equipment_investigation(session, need_id, project_id)
            assert before_replay is not None
            visible_urls = {item["url"] for item in before_replay["evidence"]}
            assert schedule["pdf_url"] not in visible_urls
            assert availability["pdf_url"] in visible_urls
        _run(factory, definition, job_id, schedule, client)
        with factory() as session:
            refreshed = session.scalar(
                select(Interpretation).where(
                    Interpretation.observation_id
                    == select(Observation.id)
                    .where(Observation.external_id == "2024-00135")
                    .scalar_subquery()
                )
            )
            assert refreshed is not None and refreshed.evaluator_version == EVALUATOR_VERSION
            assert session.scalar(select(func.count()).select_from(Evidence)) == 4
            refreshed_packages = list(
                session.scalars(
                    select(EvidencePackage).where(
                        EvidencePackage.schema_version == "equipment-demand-v1"
                    )
                )
            )
            assert len(refreshed_packages) == 2
            assert {
                str(package.evidence_id): json.loads(json.dumps(package.payload))
                for package in refreshed_packages
            } == package_snapshots
            refreshed_evidence = list(session.scalars(select(Evidence)))
            assert {
                str(row.id): (row.content_hash, row.abstract, row.url, row.published_at)
                for row in refreshed_evidence
            } == evidence_snapshots

        # A source correction that makes the CS302 alias disagree with its
        # station number is a structural scope conflict. The injected text and
        # synthetic hash are explicitly test-only; original evidence is kept.
        captured = retrieve_companion(schedule, client)[0]
        original_heading = "Compressor Station 302 (CS 302)"
        corrected_heading = "Compressor Station 302 (CS 343)"
        assert original_heading in captured["abstract"]
        corrected_text = captured["abstract"].replace(original_heading, corrected_heading, 1)
        synthetic_hash = hashlib.sha256(
            b"GL3 SYNTHETIC TEXT MUTATION - TEST ONLY\0ferc-schedule-alias-correction\0"
            + corrected_text.encode("utf-8")
        ).hexdigest()
        import gridlens.ingestion.service as service

        def retrieve_with_alias_correction(record, client_arg=None, **kwargs):
            rows = retrieve_companion(record, client_arg, **kwargs)
            if record["document_number"] != "2024-00135" or not rows:
                return rows
            return [{**rows[0], "abstract": corrected_text, "content_hash": synthetic_hash}]

        monkeypatch.setattr(service, "retrieve_companion", retrieve_with_alias_correction)
        _run(factory, definition, job_id, schedule, client)

        with factory() as session:
            needs = list(session.scalars(select(PowerNeed)))
            assert len(needs) == 1 and needs[0].active is True
            assert needs[0].required_mw is None
            need_observation_ids = set(session.scalars(select(NeedObservation.observation_id)))
            availability_observation = session.scalar(
                select(Observation).where(Observation.external_id == "2024-12869")
            )
            schedule_observation = session.scalar(
                select(Observation).where(Observation.external_id == "2024-00135")
            )
            assert availability_observation is not None and schedule_observation is not None
            assert availability_observation.id in need_observation_ids
            # NeedObservation is a historical association. The rejected
            # schedule stays linked for audit, while current publication below
            # must use only the independently supported availability notice.
            assert schedule_observation.id in need_observation_ids
            schedule_interpretation = session.scalar(
                select(Interpretation).where(
                    Interpretation.observation_id == schedule_observation.id
                )
            )
            assert schedule_interpretation is not None
            assert schedule_interpretation.status != "accepted"
            assert session.scalar(select(func.count()).select_from(Evidence)) == 5
            original_schedule_evidence = session.scalar(
                select(Evidence).where(
                    Evidence.observation_id == schedule_observation.id,
                    Evidence.content_hash == schedule_provenance["pdf_sha256"],
                )
            )
            assert original_schedule_evidence is not None
            assert original_schedule_evidence.abstract.startswith(
                f"[GovInfo PDF page 1] {schedule['title']}"
            )
            assert (
                session.scalar(select(Evidence.id).where(Evidence.content_hash == synthetic_hash))
                is not None
            )

        with factory() as session:
            investigation_after_correction = current_equipment_investigation(
                session, need_id, project_id
            )
            assert investigation_after_correction is not None
            assert investigation_after_correction["demand"]["connected_kw"] is None
            assert investigation_after_correction["demand"]["coincident_kw"] is None
            current_urls = {item["url"] for item in investigation_after_correction["evidence"]}
            assert schedule["pdf_url"] not in current_urls
            assert availability["pdf_url"] in current_urls


def test_unchanged_availability_replay_replaces_synthetic_legacy_v1_package(
    ferc_schedule_db,
    monkeypatch,
):
    """Replay repairs an explicitly synthetic obsolete-version receipt in place."""
    from gridlens.domain.ferc_equipment_interpretation import EVALUATOR_VERSION
    from gridlens.ingestion.parsers.ferc_equipment import VERSION as CURRENT_EXTRACTOR_VERSION
    from gridlens.intelligence.equipment_intelligence import current_equipment_investigation

    factory, definition, job_id = ferc_schedule_db
    _schedule, availability, api_bytes = _source_records()
    monkeypatch.setattr(logging.getLogger("pypdf"), "level", logging.ERROR)
    with _mock_client(api_bytes) as client:
        _run(factory, definition, job_id, availability, client)

        with factory.begin() as session:
            need = session.scalar(select(PowerNeed))
            project = session.scalar(select(Project))
            observation = session.scalar(
                select(Observation).where(Observation.external_id == "2024-12869")
            )
            assert need is not None and project is not None and observation is not None
            evidence = session.scalar(
                select(Evidence).where(
                    Evidence.observation_id == observation.id,
                    Evidence.url == availability["pdf_url"],
                )
            )
            assert evidence is not None
            interpretation = session.scalar(
                select(Interpretation).where(Interpretation.observation_id == observation.id)
            )
            package = session.scalar(
                select(EvidencePackage).where(
                    EvidencePackage.evidence_id == evidence.id,
                    EvidencePackage.schema_version == "equipment-demand-v1",
                )
            )
            assert interpretation is not None and package is not None
            need_id, project_id = need.id, project.id
            observation_id, evidence_id = observation.id, evidence.id
            legacy_package_id = package.id

            # Test setup only: this marked availability receipt simulates an
            # obsolete extractor/evaluator version; it does
            # not claim to reproduce a captured historical v1 package payload.
            legacy_key = hashlib.sha256(
                b"GL3 SYNTHETIC LEGACY PACKAGE KEY - TEST ONLY\0"
                + str(package.package_key).encode("ascii")
            ).hexdigest()
            legacy_payload = json.loads(json.dumps(package.payload))
            legacy_payload["extractor_version"] = "ferc-compressor-station-notice-v1"
            legacy_payload["input_fingerprint"] = legacy_key
            package.package_key = legacy_key
            package.extractor_version = "ferc-compressor-station-notice-v1"
            package.payload = legacy_payload
            interpretation.evaluator_version = "ferc-equipment-v1-synthetic-legacy"
            legacy_snapshot = {
                "id": package.id,
                "package_key": package.package_key,
                "extractor_version": package.extractor_version,
                "payload": json.loads(json.dumps(package.payload)),
                "evidence_id": package.evidence_id,
                "observation_id": package.observation_id,
                "project_id": package.project_id,
                "need_id": package.need_id,
            }
            evidence_snapshot = {
                "id": evidence.id,
                "content_hash": evidence.content_hash,
                "abstract": evidence.abstract,
                "url": evidence.url,
                "published_at": evidence.published_at,
            }

        with factory() as session:
            assert current_equipment_investigation(session, need_id, project_id) is None

        # Reacquire the unchanged Federal Register record and authentic PDF
        # through the ordinary adapter/ingestion path.
        _run(factory, definition, job_id, availability, client)

        with factory() as session:
            needs = list(session.scalars(select(PowerNeed)))
            projects = list(session.scalars(select(Project)))
            observations = list(session.scalars(select(Observation)))
            assert len(needs) == 1 and needs[0].id == need_id and needs[0].active is True
            assert len(projects) == 1 and projects[0].id == project_id
            assert len(observations) == 1 and observations[0].id == observation_id
            assert session.scalar(select(func.count()).select_from(Evidence)) == 2
            current_evidence = session.get(Evidence, evidence_id)
            assert current_evidence is not None
            assert {
                "id": current_evidence.id,
                "content_hash": current_evidence.content_hash,
                "abstract": current_evidence.abstract,
                "url": current_evidence.url,
                "published_at": current_evidence.published_at,
            } == evidence_snapshot

            current_interpretation = session.scalar(
                select(Interpretation).where(Interpretation.observation_id == observation_id)
            )
            assert current_interpretation is not None
            assert current_interpretation.evaluator_version == EVALUATOR_VERSION
            assert current_interpretation.status == "accepted"

            packages = list(
                session.scalars(
                    select(EvidencePackage).where(
                        EvidencePackage.evidence_id == evidence_id,
                        EvidencePackage.schema_version == "equipment-demand-v1",
                    )
                )
            )
            assert len(packages) == 2
            legacy = next(row for row in packages if row.id == legacy_package_id)
            assert {
                "id": legacy.id,
                "package_key": legacy.package_key,
                "extractor_version": legacy.extractor_version,
                "payload": json.loads(json.dumps(legacy.payload)),
                "evidence_id": legacy.evidence_id,
                "observation_id": legacy.observation_id,
                "project_id": legacy.project_id,
                "need_id": legacy.need_id,
            } == legacy_snapshot
            current = next(row for row in packages if row.id != legacy_package_id)
            assert current.package_key != legacy.package_key
            assert current.extractor_version == CURRENT_EXTRACTOR_VERSION
            assert current.payload["native_site_assertion"]["notice_kind"] == (
                "environmental_assessment_availability"
            )
            assert session.scalar(select(func.count()).select_from(NeedObservation)) == 1

            investigation = current_equipment_investigation(session, need_id, project_id)
            assert investigation is not None
            assert [item["url"] for item in investigation["evidence"]] == [availability["pdf_url"]]
            assert investigation["native_site_assertion"]["current_status"] == "UNKNOWN"
            assert investigation["expected_start"] == []
            assert investigation["decision_maker"] is None
            assert investigation["demand"] is not None
            for field in ("connected_kw", "coincident_kw", "incremental_kw", "energy_mwh"):
                assert investigation["demand"][field] is None
