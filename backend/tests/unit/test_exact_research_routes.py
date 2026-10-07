"""Offline native-route parity and bounds; no live-source validation implied."""

import time
from datetime import UTC, datetime

import httpx
import pytest

from gridlens.ingestion.adapters import boston_permits, el_paso_permits, federal_register
from gridlens.ingestion.adapters.bounded_http import ResponseTooLarge
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.pursuit_acquisition import acquire_registered_record
from gridlens.ingestion.adapters.socrata_permits import render_record

NEW_SOURCES = [
    "seattle-building-permits",
    "boston-building-permits",
    "el-paso-new-commercial-permits",
    "federal-register-eis",
]


def row_for(source_id, identity="2026-0001"):
    if source_id == "seattle-building-permits":
        return {
            "permitnum": identity,
            "issueddate": "2026-01-01",
            "description": "New commercial data center construction",
            "statuscurrent": "Issued",
            "originaladdress1": "100 Example Avenue",
            "permitclassmapped": "Commercial",
            "permittypemapped": "New Construction",
            "permittypedesc": "Building",
        }
    if source_id == "boston-building-permits":
        return {
            "_id": 123,
            "permitnumber": identity,
            "issued_date": "2026-01-01",
            "description": "New commercial data center construction",
            "status": "Open",
            "address": "100 Example Avenue",
            "city": "Boston",
            "state": "MA",
        }
    if source_id == "el-paso-new-commercial-permits":
        return {
            "OBJECTID": 123,
            "B1_ALT_ID": identity,
            "ISSUEDATE": 1767225600000,
            "B1_APPL_ST": "Issued",
            "SITEADDR_S": "100 Example Avenue",
            "Descriptio": "New commercial data center",
        }
    return {
        "document_number": identity,
        "title": "Environmental Impact Statement",
        "publication_date": "2026-01-01",
        "abstract": "Official notice",
        "html_url": f"https://www.federalregister.gov/documents/2026/01/01/{identity}/notice",
    }


def payload_for(source_id, rows):
    if source_id == "seattle-building-permits":
        return rows
    if source_id == "boston-building-permits":
        return {"success": True, "result": {"records": rows}}
    if source_id == "el-paso-new-commercial-permits":
        return {"features": [{"attributes": row} for row in rows]}
    return rows[0] if len(rows) == 1 else rows


@pytest.mark.parametrize("source_id", NEW_SOURCES)
def test_one_native_get_exact_id_and_shared_canonical_rendering(source_id):
    row = row_for(source_id)
    debited = []
    calls = []

    def handler(request):
        assert len(debited) == 1
        calls.append(request)
        assert request.method == "GET"
        if source_id == "seattle-building-permits":
            assert request.url.params["$where"] == "permitnum='2026-0001'"
            assert request.url.params["$limit"] == "2"
        elif source_id == "boston-building-permits":
            assert "WHERE permitnumber = '2026-0001' LIMIT 2" in request.url.params["sql"]
            assert boston_permits.RESOURCE_ID in request.url.params["sql"]
        elif source_id == "el-paso-new-commercial-permits":
            assert request.url.params["where"] == "B1_ALT_ID = '2026-0001'"
            assert request.url.params["resultRecordCount"] == "2"
            assert request.url.params["returnGeometry"] == "false"
        else:
            assert request.url.path == "/api/v1/documents/2026-0001.json"
        return httpx.Response(200, json=payload_for(source_id, [row]))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        source, record = acquire_registered_record(
            source_id,
            "2026-0001",
            deadline=time.monotonic() + 5,
            before_request=debited.append,
            client=client,
        )
    if source_id == "seattle-building-permits":
        expected = render_record(source, row)
    elif source_id == "boston-building-permits":
        expected = boston_permits.render_record(row)
    elif source_id == "el-paso-new-commercial-permits":
        expected = el_paso_permits._row(row, datetime.now(UTC).date())
    else:
        expected = federal_register.render_record(row)
    assert record == expected
    assert record["document_number"] == "2026-0001"
    assert len(calls) == len(debited) == 1


@pytest.mark.parametrize("source_id", NEW_SOURCES)
@pytest.mark.parametrize("failure", ["empty", "multiple", "foreign"])
def test_exact_native_response_rejects_unbound_identity(source_id, failure):
    row = row_for(source_id)
    rows = (
        []
        if failure == "empty"
        else [row, row]
        if failure == "multiple"
        else [row_for(source_id, "2026-9999")]
    )
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=payload_for(source_id, rows))
        )
    ) as client:
        with pytest.raises(SourceParseError):
            acquire_registered_record(
                source_id, "2026-0001", deadline=time.monotonic() + 5, client=client
            )


@pytest.mark.parametrize("source_id", NEW_SOURCES)
@pytest.mark.parametrize("failure", ["injection", "expired", "debit", "bytes"])
def test_new_routes_preserve_all_preflight_and_response_bounds(source_id, failure):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=b"x" * 100, headers={"content-type": "application/json"})

    def debit(_):
        if failure == "debit":
            raise RuntimeError("No persisted budget remains")

    expected = {
        "injection": ValueError,
        "expired": TimeoutError,
        "debit": RuntimeError,
        "bytes": ResponseTooLarge,
    }[failure]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(expected):
            acquire_registered_record(
                source_id,
                "x' OR 1=1" if failure == "injection" else "2026-0001",
                deadline=time.monotonic() + (-1 if failure == "expired" else 5),
                before_request=debit,
                client=client,
                max_bytes=10,
            )
    assert len(calls) == int(failure == "bytes")


@pytest.mark.parametrize("source_id", NEW_SOURCES)
def test_source_endpoint_cannot_drift_to_other_native_or_arbitrary_host(monkeypatch, source_id):
    from gridlens.ingestion.adapters import pursuit_acquisition
    from gridlens.ingestion.registry import load_registry

    definition = next(s for s in load_registry() if s["id"] == source_id)
    monkeypatch.setattr(
        pursuit_acquisition,
        "load_registry",
        lambda: [{**definition, "endpoint": "https://example.com/unreviewed"}],
    )
    with pytest.raises(SourceParseError, match="reviewed native"):
        acquire_registered_record(
            source_id,
            "2026-0001",
            deadline=time.monotonic() + 5,
            before_request=lambda _: pytest.fail("No request to altered endpoint"),
        )
