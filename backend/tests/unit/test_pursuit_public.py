"""Official research identity, relationship, transport and budget gates."""

import json
import time

import httpx
import pytest

from gridlens.ingestion.adapters import pursuit_public as reader
from gridlens.ingestion.adapters.bounded_http import ResponseTooLarge
from gridlens.intelligence.pursuits import _organization_involvement

NUMBER = "TABS2026000001"
URL = reader.TABS + "/TABS/Search/Print/" + NUMBER
HTML = f"""<html><title>Project Details</title><body>
<div class="project-details-project"><dl>
<dt>Project Number:</dt><dd>{NUMBER}</dd>
<dt>Project Name:</dt><dd>Example Site</dd>
<dt>Location Address:</dt><dd>123 Test Lane</dd><dd>Austin, TX</dd>
<dt>Scope of Work:</dt><dd>Construction of a charging facility.</dd>
<dt>Start Date:</dt><dd>1/6/2026</dd>
<dt>Completion Date:</dt><dd>12/31/2026</dd>
</dl></div>
<div class="project-details-contact"><dl><dt>Contact Name:</dt><dd>Filer Name</dd></dl></div>
<div class="project-details-owner"><dl>
<dt>Owner Name:</dt><dd>Example Owner LLC</dd>
<dt>Contact Name:</dt><dd>Owner Contact</dd>
<dt>Owner Phone:</dt><dd>512-555-0100</dd></dl></div>
</body></html>""".encode()


def test_tabs_preserves_named_relationships_and_planned_dates():
    doc = reader._tabs_document(URL, HTML, "text/html")
    facts = doc.structured[0]
    assert facts["address"] == "123 Test Lane Austin, TX"
    assert facts["filing_person"] == "Filer Name"
    assert facts["owner_contact"] == "Owner Contact"
    assert facts["start"] == "1/6/2026"
    assert "planned" in facts["timing_basis"]
    assert "unverified" in facts["timing_basis"]
    assert doc.published_at is None
    assert "buying_authority" not in facts


def test_pursuit_company_role_does_not_borrow_a_co_listed_contractor_role():
    facts = [
        {"owner_company_name": "Owner LLC"},
        {"contractor_company_name": "Builder Inc", "contractor_trade": "electrical"},
    ]
    owner = _organization_involvement("owner", facts, "Owner LLC")
    contractor = _organization_involvement("contractor", facts, "Builder Inc")
    assert "owner / occupant" in owner
    assert "contractor" not in owner
    assert "electrical" in contractor


def test_tabs_refuses_wrong_project_identity_or_missing_scope():
    with pytest.raises(ValueError, match="identity"):
        reader._tabs_document(URL, HTML.replace(NUMBER.encode(), b"TABS2026000002"), "text/html")
    with pytest.raises(ValueError, match="scope"):
        reader._tabs_document(URL, HTML.replace(b"Scope of Work:", b"Other Label:"), "text/html")


def test_exact_austin_refuses_injection_empty_or_wrong_record(monkeypatch):
    calls = []
    monkeypatch.setattr(
        reader, "_read", lambda *a, **k: calls.append(a) or ("application/json", b"[]")
    )
    with pytest.raises(ValueError, match="exact Austin"):
        reader.retrieve_austin("2026-000001 EP' OR 1=1", time.monotonic() + 10)
    assert calls == []
    with pytest.raises(ValueError, match="identity"):
        reader.retrieve_austin("2026-000001 EP", time.monotonic() + 10)
    monkeypatch.setattr(
        reader,
        "_read",
        lambda *a, **k: ("application/json", b'[{"permit_number":"2026-000002 EP"}]'),
    )
    with pytest.raises(ValueError, match="identity"):
        reader.retrieve_austin("2026-000001 EP", time.monotonic() + 10)


def test_tdlr_address_discovery_bounded_and_no_implied_merge(monkeypatch):
    captured = []

    def response(*args, **kwargs):
        captured.append(kwargs["data"])
        return "application/json", json.dumps({"data": [{"ProjectNumber": NUMBER}]}).encode()

    monkeypatch.setattr(reader, "_read", response)
    assert reader.tdlr_urls("123 Test", time.monotonic() + 10) == [URL]
    assert captured[0]["length"] == "2"
    assert captured[0]["LocationAddress"] == "123 Test"
    monkeypatch.setattr(
        reader,
        "_read",
        lambda *a, **k: (
            "application/json",
            json.dumps({"data": [{"ProjectNumber": NUMBER}] * 3}).encode(),
        ),
    )
    with pytest.raises(ValueError, match="bounded"):
        reader.tdlr_urls("123 Test", time.monotonic() + 10)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tdlr.texas.gov.evil.example/TABS/Search/Print/" + NUMBER,
        "https://user@www.tdlr.texas.gov/TABS/Search/Print/" + NUMBER,
        "https://www.tdlr.texas.gov/redirect?url=https://localhost",
        "http://www.tdlr.texas.gov/TABS/Search/Print/" + NUMBER,
    ],
)
def test_official_retriever_rejects_external_or_arbitrary_paths(url):
    with pytest.raises(ValueError, match="Unsupported"):
        reader.retrieve_official(url, time.monotonic() + 10)


def test_transport_counts_request_and_refuses_redirect_or_oversize(monkeypatch):
    actual_client = httpx.Client
    response = {"status": 302, "headers": {"location": "https://evil.example"}, "content": b""}
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            response["status"], headers=response["headers"], content=response["content"]
        )
    )
    monkeypatch.setattr(
        reader.httpx, "Client", lambda **kwargs: actual_client(transport=transport, **kwargs)
    )
    attempts = []
    with pytest.raises(httpx.HTTPStatusError, match="302"):
        reader._read("GET", URL, time.monotonic() + 10, lambda: attempts.append(1))
    assert attempts == [1]
    response.update(status=200, headers={"content-length": str(reader.MAX_BYTES + 1)})
    with pytest.raises(ResponseTooLarge):
        reader._read("GET", URL, time.monotonic() + 10, lambda: attempts.append(1))
    assert attempts == [1, 1]

    def no_budget():
        raise RuntimeError("request budget exhausted")

    with pytest.raises(RuntimeError, match="budget"):
        reader._read("GET", URL, time.monotonic() + 10, no_budget)
    with pytest.raises(TimeoutError):
        reader._read("GET", URL, time.monotonic() - 1, lambda: attempts.append(1))
    assert attempts == [1, 1]


@pytest.mark.parametrize(
    "filename",
    [
        "../daf420.dat.08-31-2026",
        "daf420.dat.08-30-2026",
        "daf420.dat.02-30-2026",
        "daf420.dat.10-31-2026",
        "daf420.dat.08-31-2026?redirect=localhost",
    ],
)
def test_archive_rejects_non_eom_future_and_arbitrary_filenames(monkeypatch, filename):
    from datetime import date

    monkeypatch.setattr(reader, "source_today", lambda: date(2026, 10, 1))
    calls = []
    with pytest.raises(ValueError):
        reader.retrieve_rrc_archive(filename, time.monotonic() + 10, lambda: calls.append(1))
    assert calls == []


def test_archive_retrieval_preserves_explicit_historical_portal_and_date(monkeypatch):
    from datetime import date

    today = date(2026, 10, 1)
    archive = date(2026, 8, 31)
    captured = []
    monkeypatch.setattr(reader, "source_today", lambda: today)

    def download(client, portal, filename, as_of, deadline, *, archive_date):
        captured.append((portal, filename, as_of, archive_date))
        assert client.hook is not None
        client.hook()
        return b"synthetic framed source", "2026-09-01"

    def parse(body, *, filename, today, source_url):
        assert filename == "daf420.dat.08-31-2026"
        assert source_url == reader.MONTHLY_PORTAL
        return [{"issued": "2026-08-06", "amended": None}]

    monkeypatch.setattr(reader, "_download_listing_file", download)
    monkeypatch.setattr(reader, "parse_snapshot", parse)
    monkeypatch.setattr(reader, "records_from_snapshots", lambda rows: rows[0])
    attempts = []
    result = reader.retrieve_rrc_archive(
        "daf420.dat.08-31-2026", time.monotonic() + 10, lambda: attempts.append(1)
    )
    assert captured == [(reader.MONTHLY_PORTAL, "daf420.dat.08-31-2026", today, archive)]
    assert attempts == [1]
    assert result == [{"issued": "2026-08-06", "amended": None}]
