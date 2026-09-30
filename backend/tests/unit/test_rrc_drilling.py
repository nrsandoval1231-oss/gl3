"""Synthetic framing/admission fixtures; live snapshots are validated separately."""

import base64
from datetime import date

import pytest

from gridlens.domain.permit_interpretation import assess_permit
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.rrc_drilling import parse_snapshot, records_from_snapshots


def snapshot(sequence=99, status="A", *, amended="00000000", operator="EXAMPLE OPERATOR LLC"):
    root, master = bytearray(b" " * 212), bytearray(b" " * 510)

    def put(row, pos, value):
        row[pos - 1 : pos - 1 + len(value)] = value.encode("ascii")

    for pos, value in [
        (1, "01"),
        (3, "0999999"),
        (10, str(sequence)),
        (15, "EXAMPLE LEASE"),
        (49, "123456"),
        (59, "20260901"),
        (67, operator),
        (101, status),
        (113, "0999999"),
        (120, "20260902"),
        (157, "1H"),
    ]:
        put(root, pos, value)
    for pos, value in [
        (1, "02"),
        (3, "0999999" + str(sequence)),
        (12, "001"),
        (66, "01"),
        (130, "20260902"),
        (138, amended),
    ]:
        put(master, pos, value)
    return (
        bytes(root)
        + b"\r\n"
        + bytes(master)
        + b"\r\n08opaque restriction\r\n\x85continued raw bytes\r\n"
    )


def parse(body):
    return parse_snapshot(body, filename="synthetic.dat", today=date(2026, 9, 30))


def test_byte_exact_children_and_latest_amendment_have_one_identity():
    original, amendment = snapshot(), snapshot(98, amended="20260912")
    records = records_from_snapshots([parse(original), parse(amendment)])
    assert len(records) == 1
    record = records[0]
    assert record["document_number"] == "0999999"
    assert record["permit"]["sequence"] == 98
    assert record["event_date"] == "2026-09-12"
    assert base64.b64encode(original).decode() in record["abstract"]
    assert base64.b64encode(amendment).decode() in record["abstract"]
    assert assess_permit(record)["tier"] == "Signal"
    assert "production date" in assess_permit(record)["missing_facts"]
    assert (
        records_from_snapshots([parse(amendment), parse(original)])[0]["source_hash"]
        == record["source_hash"]
    )


@pytest.mark.parametrize(
    "body",
    [
        snapshot()[:-1],
        snapshot() + b"99unknown\r\n",
        snapshot() + snapshot(),
        snapshot().replace(b"02", b"03", 1),
        snapshot().replace(b"20260902", b"20261002"),
    ],
)
def test_bad_framing_duplicate_root_and_future_date_fail_closed(body):
    with pytest.raises(SourceParseError):
        parse(body)


@pytest.mark.parametrize("status", ["W", "D", "E", "C", "X", "Z", "P", "O"])
def test_nonapproved_permit_retained_without_active_signal(status):
    record = records_from_snapshots([parse(snapshot(status=status))])[0]
    assert assess_permit(record)["decision"] == "rejected"


def test_public_download_rejects_stale_missing_and_foreign_redirect():
    import time

    import httpx

    from gridlens.ingestion.adapters.rrc_drilling import PORTAL, _download_listing_file

    def handler(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                text="""<form id="fileList" action="/public/download">
            <input type="hidden" name="view" value="public-state"/>
            <table><tbody id="fileTable_data"><tr><td><a id="file:0">daf420.dat</a></td>
            <td>9/30/26 9:45:25 AM</td></tr></tbody></table></form>""",
            )
        return httpx.Response(302, headers={"location": "https://untrusted.example/file"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(SourceParseError, match="official host"):
        _download_listing_file(
            client, PORTAL, "daf420.dat", date(2026, 9, 30), time.monotonic() + 10
        )
    with pytest.raises(SourceParseError, match="four days"):
        _download_listing_file(
            client, PORTAL, "daf420.dat", date(2026, 10, 6), time.monotonic() + 10
        )
    with pytest.raises(SourceParseError, match="absent"):
        _download_listing_file(
            client, PORTAL, "daf420.dat.08-31-2026", date(2026, 9, 30), time.monotonic() + 10
        )


@pytest.mark.parametrize("flag", ["P", "F"])
def test_master_permit_or_filing_cancellation_prevents_admission(flag):
    body = bytearray(snapshot())
    body[214 + 479] = ord(flag)
    record = records_from_snapshots([parse(bytes(body))])[0]
    assert assess_permit(record)["decision"] == "rejected"


@pytest.mark.parametrize(
    "code, accepted",
    [("01", True), ("07", True), ("14", True), ("09", False), ("15", False), ("05", False)],
)
def test_application_type_is_not_fabricated_new_drilling(code, accepted):
    body = bytearray(snapshot())
    body[214 + 65 : 214 + 67] = code.encode()
    record = records_from_snapshots([parse(bytes(body))])[0]
    result = assess_permit(record)
    assert (result["decision"] == "accepted") == accepted
    assert result["power_activity"] == ("drilling" if code == "01" else "well-permit")
    if code == "14":
        assert "Recompletion" in record["title"]


def test_undocumented_cancellation_flag_fails_closed():
    body = bytearray(snapshot())
    body[214 + 479] = ord("Y")
    with pytest.raises(SourceParseError, match="cancellation flag"):
        parse(bytes(body))
