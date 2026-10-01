from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from gridlens.domain.permit_interpretation import assess_permit, evaluator_version
from gridlens.domain.signal_admission import admit_standalone, admitted_from_source
from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.ma_cultivation import retrieve
from gridlens.ingestion.adapters.retained_permits import facts as retained_facts
from gridlens.ingestion.registry import load_registry
from gridlens.intelligence.buying_chain_extraction import extract_retained_permit_organizations

TODAY = date(2026, 10, 1)
SOURCE = next(item for item in load_registry() if item["id"] == "ma-ccc-cultivation-applications")


def _row(
    *,
    number: str = "MCN100001",
    status: str = "PENDING",
    submitted: str = "Thu Sep 03 2026 13:29:32 GMT-0400 (Eastern Daylight Time)",
    original: str = "Mon Jun 15 2026 18:22:28 GMT-0400 (Eastern Daylight Time)",
    commence: str = "",
    license_status: str = "Incomplete",
) -> dict:
    return {
        "LICENSE_NUMBER": "MC100001",
        "APPLICATION_NUMBER": number,
        "LICENSE_TYPE": "Marijuana Cultivator",
        "APPLICATION_STATUS": status,
        "APPROVED_LICENSE_STAGE": "IN PROCESS",
        "SUBMITTED_DATE": submitted,
        "ORIGINAL_SUBMITTED_DATE": original,
        "BUSINESS_NAME": "Rhythm of Life Cannabis LLC",
        "BUSINESS_EMAIL": "licensing@rhythm.example",
        "BUSINESS_PHONE": "508-555-0100",
        "ESTABLISHMENT_ADDRESS_1": "616 Douglas Street",
        "ESTABLISHMENT_ADDRESS_2": "",
        "ESTABLISHMENT_CITY": "Uxbridge",
        "ESTABLISHMENT_STATE": "MA",
        "ESTABLISHMENT_ZIP": "01569",
        "LICENSE_STATUS": license_status,
        "COMMENCE_OPERATIONS_DATE": commence,
        "APPLICATION_APPROVED_DATE": "",
        "APPLICATION_DENIED_DATE": "",
        "CNB_DATE_OF_FINAL_LICENSURE": "",
        "LIC_START_DATE": "",
        "LIC_ORIGINAL_START_DATE": "",
        "LIC_EXPIRATION_DATE": "",
        "LIC_REVOCATION_DATE": "",
        "LIC_REVOKE_DATE": "",
        "LIC_SURRENDERED_DATE": "",
        "LIC_SURRENDER_DATE": "",
        "LIC_SUSPENDED_START_DATE": "",
        "LIC_SUSPENDED_END_DATE": "",
        "LIC_SUSPENSION_START_DATE": "",
        "LIC_SUSPENSION_END_DATE": "",
        "CCCLastUpdated": "2026-09-22",
        "EIN_TIN": "99-9999999",
        "PERSONAL_CONTACT_EMAIL": "private@example.invalid",
    }


def _mock(rows: list[dict], *, content_type: str = "application/json") -> httpx.Client:
    body = json.dumps(rows).encode()
    return httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, headers={"content-type": content_type}, content=body
            )
        )
    )


def test_registry_has_one_bounded_official_ccc_source() -> None:
    assert SOURCE["retrieval_method"] == "ma-cultivation-applications"
    assert SOURCE["family"] == "cultivation-license-applications"
    assert SOURCE["endpoint"] == (
        "https://masscannabiscontrol.com/resource/l_applications_all_details.json"
    )


def test_snapshot_replay_is_stable_and_only_whitelisted_facts_are_retained() -> None:
    row = _row()
    first = retrieve(SOURCE, _mock([row]), today=TODAY)[0]
    second = retrieve(SOURCE, _mock([row]), today=TODAY)[0]
    assert first["document_number"] == second["document_number"] == "MCN100001"
    assert first["source_hash"] == second["source_hash"]
    assert first["source_snapshot_hash"] == second["source_snapshot_hash"]
    assert "applicant_org: Rhythm of Life Cannabis LLC" in first["abstract"]
    assert "616 Douglas Street" in first["abstract"]
    assert "EIN" not in first["abstract"] and "private@example.invalid" not in first["abstract"]
    assert "EIN" not in json.dumps(first["permit"])
    assert first["event_date"] == "2026-09-03"
    assert first["event_date_label"] == "Application resubmitted date"
    assert first["extraction_location"].startswith("CCC snapshot SHA-256 ")
    assert "business_email: licensing@rhythm.example" in first["abstract"]
    assert "business_phone: 508-555-0100" in first["abstract"]


def test_application_identity_does_not_change_when_status_or_submitted_date_changes() -> None:
    initial = retrieve(SOURCE, _mock([_row()]), today=TODAY)[0]
    amended = retrieve(
        SOURCE,
        _mock(
            [
                _row(
                    status="REOPENED",
                    submitted="Wed Sep 30 2026 11:00:00 GMT-0400 (Eastern Daylight Time)",
                )
            ]
        ),
        today=TODAY,
    )[0]
    assert initial["document_number"] == amended["document_number"]
    assert initial["source_hash"] != amended["source_hash"]
    assert amended["event_date"] == "2026-09-30"
    assert amended["event_date_label"] == "Application resubmitted date"


def test_retained_facts_and_organization_extraction_keep_applicant_role_explicit() -> None:
    record = retrieve(SOURCE, _mock([_row()]), today=TODAY)[0]
    assessment = assess_permit(record, as_of=TODAY)
    facts = retained_facts(SOURCE["id"], record["abstract"])
    assert any(
        fact["label"] == "Applicant organization (CCC cultivation application)" for fact in facts
    )
    assert any(fact["label"].startswith("CCC-listed applicant business email") for fact in facts)
    document = PublicDocument(
        url=record["html_url"], title=record["title"], text=record["abstract"]
    )
    extracted = extract_retained_permit_organizations(document, SOURCE["id"])
    assert len(extracted) == 1
    assert extracted[0].organization == "Rhythm of Life Cannabis LLC"
    assert extracted[0].category == "unknown"
    assert extracted[0].public_contacts == []
    assert "buying authority" in extracted[0].reason
    persisted_assessment = {**assessment, "evidence_hash": record["source_hash"]}
    source = SimpleNamespace(
        id=SOURCE["id"], family=SOURCE["family"], retrieval_method=SOURCE["retrieval_method"]
    )
    evidence = SimpleNamespace(
        title=record["title"],
        abstract=record["abstract"],
        published_at=None,
        event_date=date.fromisoformat(record["event_date"]),
        url=record["html_url"],
        content_hash=record["source_hash"],
    )
    assert admitted_from_source(source, persisted_assessment, evidence).admitted


@pytest.mark.parametrize(
    ("changes", "accepted"),
    [
        ({}, True),
        ({"status": "APPROVED"}, False),
        ({"status": "WITHDRAWN"}, False),
        ({"status": "REOPENED"}, True),
        ({"status": "PENDING", "commence": "2026-09-30"}, False),
        ({"status": "PENDING", "license_status": "Revoked"}, False),
        (
            {
                "status": "PENDING",
                "submitted": "Wed Sep 30 2025 11:00:00 GMT-0400 (Eastern Daylight Time)",
                "original": "Mon Jun 15 2024 18:22:28 GMT-0400 (Eastern Daylight Time)",
            },
            False,
        ),
    ],
)
def test_assessment_keeps_application_event_separate_from_operations(
    changes: dict, accepted: bool
) -> None:
    row = _row(**changes)
    record = retrieve(SOURCE, _mock([row]), today=TODAY)[0]
    assessment = assess_permit(record, as_of=TODAY)
    assert (assessment["decision"] == "accepted") is accepted
    assert assessment["power_activity"] == "cultivation-license-application"
    assert assessment["missing_facts"] == [
        "construction status",
        "load",
        "rental need",
        "buyer",
        "buying authority",
    ]
    assert evaluator_version(record) == "ma-cultivation-application-v1"
    if accepted:
        assert assessment["subject"] == "Rhythm of Life Cannabis LLC"
        assert assessment["location"] == "616 Douglas Street, Uxbridge, MA, 01569"
        admission = admit_standalone(
            source_id=SOURCE["id"],
            family=SOURCE["family"],
            retrieval_method=SOURCE["retrieval_method"],
            accepted=True,
            activity=assessment["power_activity"],
            title=record["title"],
            abstract=record["abstract"],
            dated=True,
            citation_url=record["html_url"],
            identified_project=True,
        )
        assert admission.admitted


@pytest.mark.parametrize(
    "rows",
    [
        [_row(), _row()],
        [_row(), _row(number="MCN100002", status="PENDING", submitted="not a date")],
    ],
)
def test_duplicate_identity_or_malformed_application_event_fails_the_snapshot(
    rows: list[dict],
) -> None:
    with pytest.raises(SourceParseError):
        retrieve(SOURCE, _mock(rows), today=TODAY)


def test_stale_snapshot_bad_endpoint_and_non_json_fail_closed() -> None:
    with pytest.raises(SourceParseError, match="stale"):
        retrieve(SOURCE, _mock([_row()]), today=date(2026, 11, 1))
    with pytest.raises(SourceParseError, match="official resource"):
        retrieve({**SOURCE, "endpoint": "https://example.com/data"}, _mock([_row()]), today=TODAY)
    with pytest.raises(SourceParseError, match="content type"):
        retrieve(SOURCE, _mock([_row()], content_type="text/html"), today=TODAY)
