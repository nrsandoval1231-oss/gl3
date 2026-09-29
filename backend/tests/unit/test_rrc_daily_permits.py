from __future__ import annotations

import hashlib

import pytest

from gridlens.ingestion.adapters import rrc_daily_permits as rrc


def _root(number: str = "0918584", sequence: str = "99") -> bytearray:
    row = bytearray(b" " * 212)
    row[0:2] = b"01"
    row[2:9] = number.encode()
    row[9:11] = sequence.encode()
    row[11:14] = b"001"
    row[14:46] = b"MUSTANG".ljust(32)
    row[58:66] = b"20260910"
    row[100:101] = b"A"
    row[112:119] = number.encode()
    row[119:127] = b"20260914"
    return row


def _permit(number: str = "0918584", sequence: str = "99", api: str = "00132879") -> bytearray:
    row = bytearray(b" " * 510)
    row[0:2] = b"02"
    row[2:9] = number.encode()
    row[9:11] = sequence.encode()
    row[11:14] = b"001"
    row[14:46] = b"MUSTANG".ljust(32)
    row[48:54] = b"1".ljust(6)
    row[121:129] = b"20260910"
    row[129:137] = b"20260914"
    row[137:161] = b"00000000" * 3
    row[502:510] = api.encode()
    return row


@pytest.fixture
def pinned(monkeypatch):
    def parse(lines: list[bytes]) -> dict:
        payload = b"\r\n".join(lines) + b"\r\n"
        digest = hashlib.sha256(payload).hexdigest()
        monkeypatch.setattr(rrc, "SOURCE_SHA256", digest)
        monkeypatch.setattr(rrc, "PROFILE_ID", "test-profile")
        return rrc.parse_daily_permits(
            payload, expected_sha256=digest, profile_id="test-profile"
        )

    return parse


def test_parses_key_dates_count_and_opaque_rows_without_decoding(pinned):
    lines = [bytes(_root()), bytes(_permit()), b"03other", b"\x85opaque"]
    result = pinned(lines)
    assert pinned(lines) == result
    assert result["permit_revision_count"] == result["unique_permit_revision_keys"] == 1
    assert result["segment_counts"] == {"DAROOT": 1, "DAPERMIT": 1, "DAFIELD": 1}
    assert result["physical_lines"] == 4
    assert result["classified_segments"] == 3
    assert result["opaque_unknown_count"] == 1
    assert result["opaque_unknown_lines"][0]["line"] == 4
    assert "raw_bytes" not in result["opaque_unknown_lines"][0]
    record = result["records"][0]
    assert record["identity"] == {"permit_number": "0918584", "sequence": "99"}
    assert record["api8"] == "00132879"
    assert record["dates"]["permit_spud"] == {"raw": "00000000", "date": None}
    assert record["citation"]["lines"] == {"root": 1, "permit": 2}


def test_rejects_unsupported_profile_and_hash_mismatch(monkeypatch):
    payload = b"01" + b"x" * 210 + b"\r\n"
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(rrc, "SOURCE_SHA256", digest)
    monkeypatch.setattr(rrc, "PROFILE_ID", "pinned")
    with pytest.raises(rrc.RRCParseError, match="unsupported"):
        rrc.parse_daily_permits(payload, expected_sha256=digest, profile_id="other")
    with pytest.raises(rrc.RRCParseError, match="source SHA-256 mismatch"):
        rrc.parse_daily_permits(
            payload + b"changed", expected_sha256=digest, profile_id="pinned"
        )


@pytest.mark.parametrize(
    "line, message",
    [
        (b"01" + b"x" * 209, "DAROOT line 1 length"),
        (b"01" + b"x" * 210 + b"\n", "CRLF"),
    ],
)
def test_rejects_malformed_delimiters_or_known_lengths(monkeypatch, line, message):
    payload = line if line.endswith((b"\r\n", b"\n")) else line + b"\r\n"
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(rrc, "SOURCE_SHA256", digest)
    monkeypatch.setattr(rrc, "PROFILE_ID", "pinned")
    with pytest.raises(rrc.RRCParseError, match=message):
        rrc.parse_daily_permits(payload, expected_sha256=digest, profile_id="pinned")


@pytest.mark.parametrize(
    "permit_mutation, message",
    [
        (lambda row: row.__setitem__(slice(2, 9), b"0918585"), "mismatch"),
        (lambda row: row.__setitem__(slice(129, 137), b"20260230"), "valid CCYYMMDD"),
        (lambda row: row.__setitem__(slice(121, 129), b"00000000"), "required date"),
        (lambda row: row.__setitem__(slice(502, 510), b"99932879"), "API county"),
    ],
)
def test_rejects_bad_key_and_dates(monkeypatch, permit_mutation, message):
    root, permit = _root(), _permit()
    permit_mutation(permit)
    payload = bytes(root) + b"\r\n" + bytes(permit) + b"\r\n"
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(rrc, "SOURCE_SHA256", digest)
    monkeypatch.setattr(rrc, "PROFILE_ID", "pinned")
    with pytest.raises(rrc.RRCParseError, match=message):
        rrc.parse_daily_permits(payload, expected_sha256=digest, profile_id="pinned")


def test_rejects_non_ascii_mapped_field(monkeypatch):
    root, permit = _root(), _permit()
    root[100] = 0xFF
    payload = bytes(root) + b"\r\n" + bytes(permit) + b"\r\n"
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(rrc, "SOURCE_SHA256", digest)
    monkeypatch.setattr(rrc, "PROFILE_ID", "pinned")
    with pytest.raises(rrc.RRCParseError, match="not ASCII"):
        rrc.parse_daily_permits(payload, expected_sha256=digest, profile_id="pinned")


def test_rejects_root_permit_number_mismatch(monkeypatch):
    root, permit = _root(), _permit()
    root[112:119] = b"0918585"
    payload = bytes(root) + b"\r\n" + bytes(permit) + b"\r\n"
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(rrc, "SOURCE_SHA256", digest)
    monkeypatch.setattr(rrc, "PROFILE_ID", "pinned")
    with pytest.raises(rrc.RRCParseError, match="permit number mismatch"):
        rrc.parse_daily_permits(payload, expected_sha256=digest, profile_id="pinned")


@pytest.mark.parametrize("interruption", [b"\x85opaque", b"03other"])
def test_rejects_root_interrupted_before_permit(pinned, interruption):
    with pytest.raises(rrc.RRCParseError, match="interrupted"):
        pinned([bytes(_root()), interruption, bytes(_permit())])


def test_rejects_nonapproved_root_status(pinned):
    root = _root()
    root[100:101] = b"P"
    with pytest.raises(rrc.RRCParseError, match="non-approved application status"):
        pinned([bytes(root), bytes(_permit())])


def test_rejects_duplicate_revision_but_keeps_distinct_sequence_and_api(pinned):
    base = [bytes(_root()), bytes(_permit())]
    with pytest.raises(rrc.RRCParseError, match="duplicate permit number"):
        pinned(base + [bytes(_root()), bytes(_permit())])
    result = pinned(
        base
        + [
            bytes(_root(sequence="98")),
            bytes(_permit(sequence="98", api="00132879")),
        ]
    )
    assert result["permit_revision_count"] == 2
    assert len({row["api8"] for row in result["records"]}) == 1
