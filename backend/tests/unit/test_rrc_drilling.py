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


@pytest.mark.parametrize(
    "utc,local_date",
    [
        ("2026-10-01T01:00:00+00:00", date(2026, 9, 30)),
        ("2026-10-01T05:00:00+00:00", date(2026, 10, 1)),
        ("2027-01-01T05:59:59+00:00", date(2026, 12, 31)),
        ("2027-01-01T06:00:00+00:00", date(2027, 1, 1)),
    ],
)
def test_rrc_month_selection_uses_texas_calendar(utc, local_date):
    from datetime import datetime

    from gridlens.ingestion.adapters.rrc_drilling import source_today

    assert source_today(datetime.fromisoformat(utc)) == local_date


def test_rrc_retrieval_requests_previous_texas_month_not_previous_utc_month(monkeypatch):
    from datetime import datetime

    import gridlens.ingestion.adapters.rrc_drilling as adapter

    now = datetime.fromisoformat("2026-10-01T01:00:00+00:00")
    today = adapter.source_today(now)
    monkeypatch.setattr(adapter, "source_today", lambda: today)
    requested = []

    def download(http, portal, filename, selected_day, deadline, **kwargs):
        requested.append((portal, filename, selected_day))
        return snapshot(), "2026-09-30"

    monkeypatch.setattr(adapter, "_download_listing_file", download)
    records = adapter.retrieve(
        {"id": adapter.SOURCE_ID, "endpoint": adapter.PORTAL}, client=object()
    )
    assert records
    assert requested == [
        (adapter.MONTHLY_PORTAL, "daf420.dat.08-31-2026", date(2026, 9, 30)),
        (adapter.PORTAL, "daf420.dat", date(2026, 9, 30)),
    ]


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


def retained_record(*bodies):
    from gridlens.ingestion.adapters.rrc_drilling import PORTAL

    groups = [
        parse_snapshot(body, filename="daf420.dat", today=date(2026, 10, 7), source_url=PORTAL)
        for body in bodies or (snapshot(),)
    ]
    return records_from_snapshots(groups)[0]


def reconstruct(abstract, **kwargs):
    from datetime import UTC, datetime

    from gridlens.ingestion.adapters.rrc_drilling import reconstruct_retained_record

    return reconstruct_retained_record(
        abstract,
        permit_number=kwargs.get("permit_number", "0999999"),
        observed_at=kwargs.get("observed_at", datetime(2026, 10, 7, tzinfo=UTC)),
    )


def mutate_retained(abstract, mutation):
    import json

    prefix, suffix = abstract.split("\nSource segment provenance: ")
    p, r = suffix.split("\nOpaque source bytes (base64; not interpreted): ")
    provenance, raw = json.loads(p), json.loads(r)
    mutation(provenance, raw)
    return (
        prefix
        + "\nSource segment provenance: "
        + json.dumps(provenance, sort_keys=True)
        + "\nOpaque source bytes (base64; not interpreted): "
        + json.dumps(raw, sort_keys=True)
    )


def test_retained_reconstruction_preserves_exact_opaque_children_and_amendments():
    record = retained_record(snapshot(), snapshot(98, amended="20260912"))
    assert reconstruct(record["abstract"]) == record
    assert base64.b64encode(snapshot()).decode() in reconstruct(record["abstract"])["abstract"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p, r: p[0].update(source_url="https://untrusted.example/file"),
        lambda p, r: p[0].update(source_url="https://mft.rrc.texas.gov/other"),
        lambda p, r: p[0].update(filename="../daf420.dat"),
        lambda p, r: p[0].update(filename="daf420.dat.09-30-2026"),
        lambda p, r: p[0].update(ordinal=True),
        lambda p, r: p[0].update(ordinal=0),
        lambda p, r: p[0].update(ordinal=5001),
        lambda p, r: p[0].update(sequence="99"),
        lambda p, r: p[0].update(sequence=98),
        lambda p, r: p[0].update(extra="unsupported"),
        lambda p, r: p.append(dict(p[0])),
        lambda p, r: p.extend(dict(p[0], ordinal=n) for n in range(2, 22)),
        lambda p, r: r.update({next(iter(r)): "%%%"}),
        lambda p, r: r.update({next(iter(r)): base64.b64encode(b"corrupted").decode()}),
        lambda p, r: r.clear(),
        lambda p, r: p[0].update(raw_sha256="0" * 64),
    ],
)
def test_retained_reconstruction_rejects_provenance_corruption(mutation):
    abstract = mutate_retained(retained_record()["abstract"], mutation)
    with pytest.raises(SourceParseError):
        reconstruct(abstract)


def test_retained_reconstruction_rejects_field_tampering_and_wrong_identity():
    record = retained_record()
    with pytest.raises(SourceParseError, match="exactly reconstruct"):
        reconstruct(record["abstract"].replace("operator: EXAMPLE", "operator: TAMPERED"))
    with pytest.raises(SourceParseError, match="permit or sequence"):
        reconstruct(record["abstract"], permit_number="0888888")
    with pytest.raises(SourceParseError):
        reconstruct(record["abstract"], permit_number="bad")


def test_retained_reconstruction_rejects_conflicting_same_sequence():
    record = retained_record(snapshot(), snapshot(operator="OTHER OPERATOR LLC"))
    with pytest.raises(SourceParseError, match="conflicting same-sequence"):
        reconstruct(record["abstract"])


def test_retained_reconstruction_rejects_bounds_dates_and_duplicate_json_keys():
    from datetime import datetime

    record = retained_record()
    with pytest.raises(SourceParseError):
        reconstruct("x" * 750001)
    with pytest.raises(SourceParseError):
        reconstruct(record["abstract"], observed_at=datetime(2026, 10, 7))
    with pytest.raises(SourceParseError, match="future permit date"):
        from datetime import UTC

        reconstruct(record["abstract"], observed_at=datetime(2026, 9, 1, tzinfo=UTC))
    with pytest.raises(SourceParseError, match="duplicate key"):
        reconstruct(record["abstract"].replace('"ordinal": 1', '"ordinal": 1, "ordinal": 1'))


def test_retained_reconstruction_rejects_unreferenced_bytes():
    import hashlib

    raw = snapshot(98)
    abstract = mutate_retained(
        retained_record()["abstract"],
        lambda p, r: r.update({hashlib.sha256(raw).hexdigest(): base64.b64encode(raw).decode()}),
    )
    with pytest.raises(SourceParseError, match="unreferenced"):
        reconstruct(abstract)


def test_retained_monthly_provenance_and_nondefault_ordinal_are_not_independent_proof():
    from gridlens.ingestion.adapters.rrc_drilling import MONTHLY_PORTAL

    rows = parse_snapshot(
        snapshot(),
        filename="daf420.dat.09-30-2026",
        today=date(2026, 10, 7),
        source_url=MONTHLY_PORTAL,
    )
    rows[0]["ordinal"] = 4999
    record = records_from_snapshots([rows])[0]
    assert reconstruct(record["abstract"]) == record
    for filename in ("daf420.dat.09-29-2026", "daf420.dat.02-30-2026", "daf420.dat.10-31-2026"):
        abstract = mutate_retained(
            record["abstract"], lambda p, r, filename=filename: p[0].update(filename=filename)
        )
        with pytest.raises(SourceParseError):
            reconstruct(abstract)


def test_retained_reconstruction_rejects_deeply_nested_json_as_source_parse_error():
    abstract = retained_record()["abstract"]
    prefix, _ = abstract.split("\nSource segment provenance: ")
    malformed = (
        prefix
        + "\nSource segment provenance: "
        + "[" * 2000
        + "0"
        + "]" * 2000
        + "\nOpaque source bytes (base64; not interpreted): {}"
    )
    with pytest.raises(SourceParseError, match="retained content is malformed"):
        reconstruct(malformed)
