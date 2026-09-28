from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.domain.permit_interpretation import assess_permit
from gridlens.ingestion.adapters import georgia_air_permits
from gridlens.ingestion.registry import load_registry
from gridlens.ingestion.service import process_job
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    Job,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def integration_db():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and (target.database == "test" or target.database.endswith("_test"))
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


def assessment_record(description: str) -> dict:
    return {
        "document_number": "knack-record-1",
        "title": "Northstar Data Center Campus",
        "publication_date": None,
        "event_date": "2026-09-26",
        "event_date_label": "Application received date (source-stated)",
        "html_url": georgia_air_permits.LISTING_URL,
        "permit": {
            "source_type": "georgia-air-draft-title-v",
            "row_id": "SIP-30169",
            "record_id": "knack-record-1",
            "address": "Augusta",
            "state": "GA",
            "status": (
                "Listed in current Georgia EPD Draft Title V permits view; "
                "project status unconfirmed"
            ),
            "description": description,
            "current_scope": description,
            "current_scope_pages": [1],
            "source_fields": {"facility": "field_1", "application_number": "field_8"},
            "document_links": {},
        },
    }


def test_partial_utility_campus_is_signal_with_reported_values_separate():
    record = assessment_record(
        "Northstar is a named campus with 100 MW planned capacity; only 20 MW utility "
        "service is available."
    )
    result = assess_permit(record)
    assert result["decision"] == "accepted"
    assert result["tier"] == "Signal"
    assert result["subject"] == "Northstar Data Center Campus"
    assert len(result["reported_power_facts"]) == 2
    assert "required_mw" not in result
    assert "100 MW" not in result["rental_hypothesis"]
    assert "20 MW" not in result["rental_hypothesis"]


def test_missing_energization_date_keeps_plausible_project_signal():
    record = assessment_record(
        "Northstar campus construction includes a proposed data center; energization date "
        "is not stated."
    )
    result = assess_permit(record)
    assert result["decision"] == "accepted"
    assert result["event_date_label"] == "Application received date (source-stated)"
    assert result["missing_facts"]
    assert "energization date" in result["reason"]


def test_standby_generation_is_discovery_signal_without_confirmed_gap():
    record = assessment_record(
        "The project proposes installation of 12 emergency generators at the named data center."
    )
    result = assess_permit(record)
    assert result["decision"] == "accepted"
    assert result["tier"] == "Signal"
    assert "does not establish rental MW" in result["reason"]


def test_operating_facility_with_new_phase_is_not_closed_by_operational_text():
    record = assessment_record(
        "Facility is operational; proposed additional generators support phase 2 expansion."
    )
    assert assess_permit(record)["decision"] == "accepted"


def test_application_withdrawal_closes_same_application_despite_historical_proposal():
    record = assessment_record("Application has been withdrawn. Proposed new data center.")
    result = assess_permit(record)
    assert result["decision"] == "rejected"
    assert "withdrawal" in result["reason"]


def test_renewal_without_new_activity_is_evidence_only():
    record = assessment_record(
        "Title V renewal for an existing facility. No change in emissions associated with "
        "this modification."
    )
    assert assess_permit(record)["decision"] == "rejected"


@pytest.mark.parametrize(
    "description",
    [
        "Construction of the facility is planned to begin in Q2 2026; application increases "
        "quarry production capacity.",
        "The proposed facility modification involves adding a 475 ton-per-hour portable "
        "stone processing plant.",
        "The application proposes to construct a landfill gas processing facility for a new "
        "RNG plant.",
        "The existing plant will replace the drum dryer and baghouse; this physical equipment "
        "work is proposed.",
        "The new quarry will consist of drilling, crushing, screening and associated material "
        "handling equipment.",
    ],
)
def test_current_named_site_physical_construction_or_equipment_work_is_signal(description):
    result = assess_permit(assessment_record(description))
    assert result["decision"] == "accepted"
    assert result["tier"] == "Signal"


def test_historical_later_page_modifications_do_not_override_current_renewal_purpose():
    full_excerpt = (
        "Page 1: Purpose of Application. Routine Title V renewal; no current physical changes.\n"
        "Page 44: Historical 2004 permit modification proposed new drawing machines and silos."
    )
    current_scope = georgia_air_permits._current_scope_excerpt(full_excerpt)
    assert "Page 44" not in current_scope
    result = assess_permit(assessment_record(current_scope))
    assert result["decision"] == "rejected"


def test_current_scope_uses_purpose_and_explicit_planned_site_activity_only():
    colonial = (
        "Page 1: Existing Permits: In 2021 the company constructed and operated a new facility. "
        "Purpose of Application: This renewal does not propose any changes in production "
        "process or equipment. "
        "Updated Equipment List: historical inventory."
    )
    southwire = (
        "Page 1: Existing Permits: In 2018, proposed installation of new equipment was approved. "
        "Purpose of Application: Routine renewal; no current physical changes. "
        "Equipment List: prior permit inventory."
    )
    walker = (
        "Page 1: Construction of the Facility is planned to begin in Q2 2026. "
        "Purpose of Application: Increasing permitted production capacity to 688 tons per hour. "
        "Updated Equipment List: proposed equipment updates."
    )

    colonial_scope = georgia_air_permits._current_scope_excerpt(colonial)
    southwire_scope = georgia_air_permits._current_scope_excerpt(southwire)
    walker_scope = georgia_air_permits._current_scope_excerpt(walker)

    assert "constructed and operated" not in colonial_scope
    assert "any changes" in colonial_scope.casefold()
    assert "2018" not in southwire_scope and "prior permit inventory" not in southwire_scope
    assert "2018" not in southwire_scope
    assert "Page 1 background prospective activity" in walker_scope
    assert "planned to begin in Q2 2026" in walker_scope
    assert assess_permit(assessment_record(colonial_scope))["decision"] == "rejected"
    assert assess_permit(assessment_record(southwire_scope))["decision"] == "rejected"
    assert assess_permit(assessment_record(walker_scope))["decision"] == "accepted"


@pytest.mark.parametrize(
    ("current_scope", "decision"),
    [
        (
            "Purpose of Application: In addition, the application does not propose any changes "
            "in the production process or equipment. Therefore there will be no emissions "
            "increase.",
            "rejected",
        ),
        (
            "Purpose of Application: Application 30323 requests replacing the existing permitted "
            "drum dryer and baghouse with a like-kind new drum dryer and baghouse.",
            "accepted",
        ),
    ],
)
def test_current_purpose_classifies_real_no_change_and_equipment_replacement(
    current_scope, decision
):
    result = assess_permit(assessment_record(current_scope))
    assert result["decision"] == decision


def test_live_current_scope_fixtures_classify_current_work_without_historical_leakage():
    fixtures = json.loads(
        (Path(__file__).parents[1] / "fixtures/georgia_air_current_scopes.json").read_text(
            encoding="utf-8"
        )
    )
    for fixture in fixtures:
        record = assessment_record(fixture["current_scope"])
        record["title"] = fixture["title"]
        result = assess_permit(record)
        assert result["decision"] == fixture["expected"], fixture["title"]


def test_missing_current_scope_does_not_fall_back_to_historical_description():
    record = assessment_record("Proposed new data center and 40 emergency generators.")
    record["permit"].pop("current_scope")
    assert assess_permit(record)["decision"] == "rejected"


def test_abbreviated_month_application_date_is_source_event_not_publication_date():
    assert georgia_air_permits._source_date("Oct 27, 2025", "bad source date") == "2025-10-27"


def test_official_pdf_is_bound_to_the_listed_site_and_application(monkeypatch):
    class Page:
        def extract_text(self):
            return (
                "Application No. 30169. QTS ATL3 Campus, Augusta, Georgia. Greenfield data center; "
                "proposed 224 emergency generators. Date Title V Application Received: "
                "June 17, 2026."
            )

    class Reader:
        pages = [Page()]
        is_encrypted = False

        def __init__(self, stream, strict):
            assert strict is True
            assert stream.read().startswith(b"%PDF-")

    monkeypatch.setattr(georgia_air_permits, "PdfReader", Reader)
    content = b"%PDF-1.7 test payload"
    digest = __import__("hashlib").sha256(content).hexdigest()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=content, headers={"content-type": "application/pdf"}
        )
    )
    with httpx.Client(transport=transport) as client:
        document = georgia_air_permits._extract_document(
            client,
            "https://epd.georgia.gov/document/document/30169-nar/download",
            "narrative",
            {"bytes": 0, "pdf_count": 0},
            "QTS ATL3",
            "SIP-30169",
            "Augusta",
        )
    assert document is not None
    assert document["content_hash"] == digest
    assert document["extraction_location"].startswith("PDF pages 1")
    with httpx.Client(transport=transport) as client:
        with pytest.raises(
            georgia_air_permits.SourceParseError,
            match="does not bind the listed facility/application",
        ):
            georgia_air_permits._extract_document(
                client,
                "https://epd.georgia.gov/document/document/30169-nar/download",
                "narrative",
                {"bytes": 0, "pdf_count": 0},
                "Different Facility",
                "99999",
                "Augusta",
            )


def test_valid_multisection_georgia_pdf_is_retained_with_page_citations(monkeypatch):
    class Page:
        def __init__(self, page_number):
            self.page_number = page_number

        def extract_text(self):
            if self.page_number not in {1, 2, 3, 98, 99, 100, 101, 102}:
                return "Routine permit boilerplate without current-work keywords."
            return (
                "QTS ATL3 Campus, Augusta, Georgia, application 30169; proposed data center "
                "generators."
            )

    class Reader:
        pages = [Page(index) for index in range(1, 103)]
        is_encrypted = False

        def __init__(self, stream, strict):
            assert strict

    monkeypatch.setattr(georgia_air_permits, "PdfReader", Reader)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=b"%PDF-1.7 valid", headers={"content-type": "application/pdf"}
        )
    )
    state = {"bytes": 0, "pdf_count": 0, "pdf_pages": 0}
    with httpx.Client(transport=transport) as client:
        document = georgia_air_permits._extract_document(
            client,
            "https://epd.georgia.gov/document/document/30169-nar/download",
            "narrative",
            state,
            "QTS ATL3",
            "SIP-30169",
            "Augusta",
        )
    assert document is not None
    assert state["pdf_pages"] == 102
    assert document["extraction_location"].startswith("PDF pages 1")
    assert len(document["extraction_location"]) <= 100


def test_georgia_pdf_page_caps_fail_explicitly(monkeypatch):
    class Page:
        def extract_text(self):
            return "QTS ATL3 Campus, application 30169; proposed data center generators."

    class Reader:
        pages = [Page() for _ in range(201)]
        is_encrypted = False

        def __init__(self, stream, strict):
            assert strict

    monkeypatch.setattr(georgia_air_permits, "PdfReader", Reader)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=b"%PDF-1.7 too-large", headers={"content-type": "application/pdf"}
        )
    )
    with (
        httpx.Client(transport=transport) as client,
        pytest.raises(georgia_air_permits.SourceParseError, match="per-document limit 200"),
    ):
        georgia_air_permits._extract_document(
            client,
            "https://epd.georgia.gov/document/document/30169-nar/download",
            "narrative",
            {"bytes": 0, "pdf_count": 0, "pdf_pages": 0},
            "QTS ATL3",
            "SIP-30169",
            "Augusta",
        )


def test_georgia_pdf_total_page_cap_fails_explicitly(monkeypatch):
    class Page:
        def extract_text(self):
            return "QTS ATL3 Campus, application 30169; proposed data center generators."

    class Reader:
        pages = [Page()]
        is_encrypted = False

        def __init__(self, stream, strict):
            assert strict

    monkeypatch.setattr(georgia_air_permits, "PdfReader", Reader)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=b"%PDF-1.7 total-cap", headers={"content-type": "application/pdf"}
        )
    )
    with (
        httpx.Client(transport=transport) as client,
        pytest.raises(georgia_air_permits.SourceParseError, match="total run page limit 5000"),
    ):
        georgia_air_permits._extract_document(
            client,
            "https://epd.georgia.gov/document/document/30169-nar/download",
            "narrative",
            {"bytes": 0, "pdf_count": 0, "pdf_pages": 5000},
            "QTS ATL3",
            "SIP-30169",
            "Augusta",
        )


def test_pdf_identity_accepts_legal_suffix_punctuation_with_site_match(monkeypatch):
    class Page:
        def extract_text(self):
            return (
                "Graphic Packaging International, LLC - Perry Carton Facility. "
                "905 West Perry Parkway, Perry, Georgia. Proposed generator addition."
            )

    class Reader:
        pages = [Page()]
        is_encrypted = False

        def __init__(self, stream, strict):
            assert strict

    monkeypatch.setattr(georgia_air_permits, "PdfReader", Reader)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=b"%PDF-1.7 identity", headers={"content-type": "application/pdf"}
        )
    )
    with httpx.Client(transport=transport) as client:
        document = georgia_air_permits._extract_document(
            client,
            "https://epd.georgia.gov/document/document/30169-pn/download",
            "public notice",
            {"bytes": 0, "pdf_count": 0, "pdf_pages": 0},
            "Graphic Packaging International - Perry Carton Facility",
            "SIP-846571",
            "Perry",
        )
    assert document is not None
    with (
        httpx.Client(transport=transport) as client,
        pytest.raises(
            georgia_air_permits.SourceParseError,
            match="bind the listed facility/application to its site",
        ),
    ):
        georgia_air_permits._extract_document(
            client,
            "https://epd.georgia.gov/document/document/30169-pn/download",
            "public notice",
            {"bytes": 0, "pdf_count": 0, "pdf_pages": 0},
            "Graphic Packaging International - Perry Carton Facility",
            "SIP-846571",
            "Savannah",
        )


def test_pdf_identity_normalizes_dotted_company_initials():
    assert georgia_air_permits._identity_tokens("Interfor US - Perry Mill") == (
        georgia_air_permits._identity_tokens("Interfor U.S. Inc.-Perry Mill")
    )


def test_georgia_job_retains_null_publication_and_replays_with_pdf_evidence(
    integration_db, monkeypatch
):
    engine = integration_db
    factory = sessionmaker(engine, expire_on_commit=False)
    definition = next(row for row in load_registry() if row["id"] == "georgia-air-draft-title-v")
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
                cadence_hours=24,
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=definition["id"],
            status="running",
            lease_owner="test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    application = {
        "application": {
            "id": georgia_air_permits.APP_ID,
            "home_scene": {"key": "scene_1"},
            "objects": [
                {
                    "fields": [
                        {"key": "field_1", "name": "Facility Name"},
                        {"key": "field_2", "name": "Location"},
                        {"key": "field_3", "name": "Public Comment Deadline"},
                        {"key": "field_4", "name": "Application Link"},
                        {"key": "field_5", "name": "Narrative"},
                        {"key": "field_6", "name": "Draft Permit"},
                        {"key": "field_7", "name": "Public Notice"},
                        {"key": "field_8", "name": "Application Number"},
                    ]
                }
            ],
        }
    }
    raw_pdf = b"%PDF-1.7 QTS narrative"
    scenario = {"pdf_version": b"v1", "notice_id": "30169", "fail_document": None}

    class Page:
        def extract_text(self):
            return (
                "Application No. 30169. QTS ATL3 Campus, Augusta, Georgia. "
                "Purpose of Application: Construct a greenfield data center with 224 emergency "
                "generators. "
                "Date Title V Application Received: June 17, 2026."
            )

    class Reader:
        pages = [Page()]
        is_encrypted = False

        def __init__(self, stream, strict):
            assert strict
            assert stream.read().startswith(b"%PDF-")

    monkeypatch.setattr(georgia_air_permits, "PdfReader", Reader)

    fetched_paths: list[str] = []

    def handler(request):
        if request.url.host == "api.knack.com" and request.url.path.endswith("/records"):
            return httpx.Response(
                200,
                json={
                    "total_records": 1,
                    "total_pages": 1,
                    "records": [
                        {
                            "id": "knack-qts-1",
                            "field_1": "QTS ATL3 Campus",
                            "field_2": "Augusta",
                            "field_3": "10/16/2026",
                            "field_3_raw": {"date": "10/16/2026"},
                            "field_8": "SIP-30169",
                            "field_5_raw": {
                                "url": "https://epd.georgia.gov/document/document/30169-nar/download"
                            },
                            "field_6_raw": {
                                "url": "https://epd.georgia.gov/document/document/30169-draft/download"
                            },
                            "field_7_raw": {
                                "url": (
                                    "https://epd.georgia.gov/document/document/"
                                    f"{scenario['notice_id']}-pn/download"
                                )
                            },
                        }
                    ],
                },
            )
        if request.url.host == "api.knack.com":
            return httpx.Response(200, json=application)
        fetched_paths.append(request.url.path)
        if scenario["fail_document"] and scenario["fail_document"] in request.url.path:
            return httpx.Response(503, text="temporary required-document failure")
        return httpx.Response(
            200,
            content=raw_pdf + scenario["pdf_version"] + request.url.path.encode(),
            headers={"content-type": "application/pdf"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with factory() as session:
            first = process_job(session, job_id, "test", 1, definition, client)
        with factory() as session:
            replay = process_job(session, job_id, "test", 1, definition, client)
    assert first["signals"] == 1
    assert first["permit_accepted"] == 1
    assert replay["unchanged"] == 1
    assert fetched_paths == [
        "/document/document/30169-nar/download",
        "/document/document/30169-draft/download",
        "/document/document/30169-nar/download",
        "/document/document/30169-draft/download",
    ]
    with factory() as session:
        observation = session.scalar(select(Observation))
        assert observation is not None and observation.published_at is None
        assert session.scalar(select(Project.name)) == "QTS ATL3 Campus"
        need = session.scalar(select(PowerNeed))
        assert need is not None and need.tier == "Signal" and need.required_mw is None
        assert session.scalar(select(func.count()).select_from(Evidence)) == 3
        evidence = session.scalars(select(Evidence).order_by(Evidence.observed_at)).all()
        assert evidence[0].event_date_label == "Application received date (source-stated)"
        assert evidence[1].published_at is None
        assert all("30169-pn" not in row.url for row in evidence)
        assert (
            "Public notice URL (retained reference, not fetched)".casefold()
            in observation.abstract.casefold()
        )
        interpretation = session.scalar(select(Interpretation))
        assert interpretation is not None
        assert interpretation.status == "accepted"
        assert interpretation.evaluator_version == "georgia-air-discovery-v1"
        original_hash = observation.content_hash

    scenario["pdf_version"] = b"v2-changed-required-pdf"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with factory() as session:
            changed_pdf = process_job(session, job_id, "test", 1, definition, client)
    assert changed_pdf["changed"] == 1
    assert changed_pdf["signals"] == 0  # Existing activity was updated, not rediscovered.
    with factory() as session:
        observation = session.scalar(select(Observation))
        assert observation is not None and observation.content_hash != original_hash
        assert session.scalar(select(func.count()).select_from(Evidence)) == 6
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
        interpretation = session.scalar(select(Interpretation))
        assert interpretation is not None
        assert interpretation.status == "accepted"
        assert interpretation.assessment is not None
        assert interpretation.assessment["previous_decisions"]
        changed_pdf_hash = observation.content_hash

    fetched_before_notice_revision = len(fetched_paths)
    scenario["notice_id"] = "30170"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with factory() as session:
            changed_notice = process_job(session, job_id, "test", 1, definition, client)
    assert changed_notice["changed"] == 1
    assert fetched_paths[fetched_before_notice_revision:] == [
        "/document/document/30169-nar/download",
        "/document/document/30169-draft/download",
    ]
    with factory() as session:
        observation = session.scalar(select(Observation))
        assert observation is not None and observation.content_hash != changed_pdf_hash
        assert "30170-pn/download" in (observation.abstract or "")
        assert session.scalar(select(func.count()).select_from(Evidence)) == 7
        evidence = session.scalars(select(Evidence)).all()
        assert all("30170-pn" not in row.url for row in evidence)
        latest_hash = observation.content_hash
        latest_abstract = observation.abstract

    scenario["fail_document"] = "-draft"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with factory() as session:
            with pytest.raises(
                georgia_air_permits.SourceParseError,
                match="Georgia source request failed",
            ):
                process_job(session, job_id, "test", 1, definition, client)
    with factory() as session:
        observation = session.scalar(select(Observation))
        assert observation is not None and observation.content_hash == latest_hash
        assert observation.abstract == latest_abstract
        assert session.scalar(select(func.count()).select_from(Evidence)) == 7
        assert session.scalar(select(func.count()).select_from(PowerNeed)) == 1
