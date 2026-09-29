"""Offline reader for the single hash-pinned RRC daily-permit profile."""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

PROFILE_ID = "rrc-drilling-permit-master-daily-v1-observed"
SOURCE_SHA256 = "c0215842369f14d6e725b011649ffa0076f373344e3ce5bb0d2ed411fce79cd6"
MANUAL_SHA256 = "760a25367df8fb3bd7b240a41d9471953e2ee1eab1878d5367c673548adec874"
SOURCE_URL = "https://www.rrc.texas.gov/resource-center/research/data-sets-available-for-download/"
PUBLIC_DRIVE_URL = "https://mft.rrc.texas.gov/webclient/godrive/PublicGoDrive.xhtml"
MANUAL_URL = "https://www.rrc.texas.gov/media/zgccdjpi/drillingpermitmasterpluslatitudeslongitudes_oga049m_july1.pdf"
_KNOWN_SEGMENTS = {
    b"01": "DAROOT",
    b"02": "DAPERMIT",
    b"03": "DAFIELD",
    b"04": "DAFLDSPC",
    b"05": "DAFLDBHL",
    b"06": "DACANRES",
    b"07": "DACANFLD",
    b"08": "DAFRERES",
    b"09": "DAFREFLD",
    b"11": "DAALTADD",
    b"14": "DAW999A1",
    b"15": "DAW999B1",
}


class RRCParseError(ValueError):
    """Input cannot be interpreted under the pinned observed profile."""


def _ascii(line: bytes, start: int, end: int, field: str) -> str:
    try:
        return line[start:end].decode("ascii")
    except UnicodeDecodeError as exc:
        raise RRCParseError(f"line field {field} is not ASCII") from exc


def _digits(line: bytes, start: int, end: int, field: str) -> str:
    value = _ascii(line, start, end, field)
    if not value.isdigit():
        raise RRCParseError(f"line field {field} is not all digits")
    return value


def _date(line: bytes, start: int, field: str, *, required: bool) -> tuple[str, str | None]:
    raw = _digits(line, start, start + 8, field)
    if raw == "00000000":
        if required:
            raise RRCParseError(f"required date {field} is zero")
        return raw, None
    try:
        parsed = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    except ValueError as exc:
        raise RRCParseError(f"date {field} is not a valid CCYYMMDD date") from exc
    return raw, parsed.isoformat()


def parse_daily_permits(
    payload: bytes,
    *,
    expected_sha256: str,
    profile_id: str,
) -> dict[str, Any]:
    """Parse mapped permit revisions; preserve zero dates and quarantine opaque rows.

    This deliberately supports only the exact archive SHA/profile approved in
    GL3-015E. Returned citations are physical 1-based line numbers and mapped
    source byte spans, not semantic inferences.
    """
    if profile_id != PROFILE_ID:
        raise RRCParseError("unsupported RRC profile")
    if expected_sha256 != SOURCE_SHA256:
        raise RRCParseError("expected SHA-256 does not match supported profile")
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RRCParseError("RRC source SHA-256 mismatch")
    without_crlf = payload.replace(b"\r\n", b"")
    if (
        not payload
        or not payload.endswith(b"\r\n")
        or b"\n" in without_crlf
        or b"\r" in without_crlf
    ):
        raise RRCParseError("RRC file must contain nonempty CRLF-delimited lines")

    lines = payload[:-2].split(b"\r\n")
    counts: dict[str, int] = {}
    unknown: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    pending_root: tuple[int, bytes] | None = None
    seen: set[tuple[str, str]] = set()

    for line_number, line in enumerate(lines, start=1):
        if not line:
            raise RRCParseError(f"empty physical line at {line_number}")
        if pending_root is not None and line[:2] != b"02":
            raise RRCParseError(
                f"unmatched DAROOT line {pending_root[0]} interrupted by line {line_number}"
            )
        if line[0] == 0x85:
            unknown.append(
                {
                    "line": line_number,
                    "byte_length": len(line),
                    "raw_line_sha256": hashlib.sha256(line).hexdigest(),
                    "meaning": "UNKNOWN; opaque bytes retained by source file only",
                }
            )
            continue
        segment = line[:2]
        name = _KNOWN_SEGMENTS.get(segment)
        if name is None:
            raise RRCParseError(f"unclassified line {line_number}; not a supported 0x85 row")
        counts[name] = counts.get(name, 0) + 1
        if segment == b"01":
            if len(line) != 212:
                raise RRCParseError(f"DAROOT line {line_number} length is not 212")
            if pending_root is not None:
                raise RRCParseError(f"DAROOT line {line_number} follows an unmatched DAROOT")
            pending_root = (line_number, line)
        elif segment == b"02":
            if len(line) != 510:
                raise RRCParseError(f"DAPERMIT line {line_number} length is not 510")
            if pending_root is None or pending_root[0] != line_number - 1:
                raise RRCParseError(f"DAPERMIT line {line_number} lacks adjacent DAROOT")
            root_number, root = pending_root
            permit_number = _digits(line, 2, 9, "permit_number")
            sequence = _digits(line, 9, 11, "sequence")
            key = (permit_number, sequence)
            if key in seen:
                raise RRCParseError(
                    f"duplicate permit number + sequence {permit_number}/{sequence}"
                )
            seen.add(key)
            if _digits(root, 2, 9, "root_status_number") != permit_number:
                raise RRCParseError(
                    f"root/detail status number mismatch at lines {root_number}/{line_number}"
                )
            if _digits(root, 112, 119, "root_permit_number") != permit_number:
                raise RRCParseError(
                    f"root/detail permit number mismatch at lines {root_number}/{line_number}"
                )
            if _digits(root, 9, 11, "root_sequence") != sequence:
                raise RRCParseError(
                    f"root/detail sequence mismatch at lines {root_number}/{line_number}"
                )
            status = _ascii(root, 100, 101, "application_status")
            if status != "A":
                raise RRCParseError(
                    f"non-approved application status {status!r} at root line {root_number}"
                )
            reported_county = _digits(root, 11, 14, "reported_county_code")
            approved_county = _digits(line, 11, 14, "approved_county_code")
            received_root_raw, received_root = _date(root, 58, "root_received_date", required=True)
            received_raw, received = _date(line, 121, "application_received_date", required=True)
            issued_root_raw, _issued_root = _date(
                root, 119, "root_permit_issued_date", required=True
            )
            issued_raw, issued = _date(line, 129, "permit_issued_date", required=True)
            if (received_root_raw, issued_root_raw) != (received_raw, issued_raw):
                raise RRCParseError(
                    f"root/detail dates mismatch at lines {root_number}/{line_number}"
                )
            amended_raw, amended = _date(line, 137, "permit_amended_date", required=False)
            extended_raw, extended = _date(line, 145, "permit_extended_date", required=False)
            spud_raw, spud = _date(line, 153, "permit_spud_date", required=False)
            api8 = _digits(line, 502, 510, "api8")
            if api8[:3] != approved_county:
                raise RRCParseError(f"API county prefix mismatch at DAPERMIT line {line_number}")
            records.append(
                {
                    "identity": {"permit_number": permit_number, "sequence": sequence},
                    "status": status,
                    "reported_county_code": reported_county,
                    "approved_county_code": approved_county,
                    "reported_lease_name": _ascii(root, 14, 46, "reported_lease_name").strip(),
                    "approved_lease_name": _ascii(line, 14, 46, "approved_lease_name").strip(),
                    "well_number": _ascii(line, 48, 54, "well_number").strip(),
                    "api8": api8,
                    "dates": {
                        "application_received": {"raw": received_raw, "date": received},
                        "permit_issued": {"raw": issued_raw, "date": issued},
                        "permit_amended": {"raw": amended_raw, "date": amended},
                        "permit_extended": {"raw": extended_raw, "date": extended},
                        "permit_spud": {"raw": spud_raw, "date": spud},
                    },
                    "citation": {
                        "source_url": SOURCE_URL,
                        "download_endpoint": PUBLIC_DRIVE_URL,
                        "manual_url": MANUAL_URL,
                        "source_sha256": actual_sha256,
                        "profile_id": profile_id,
                        "lines": {"root": root_number, "permit": line_number},
                        "spans": {
                            "root_status_number": [2, 9],
                            "root_sequence": [9, 11],
                            "reported_county_code": [11, 14],
                            "reported_lease_name": [14, 46],
                            "application_status": [100, 101],
                            "root_permit_number": [112, 119],
                            "root_received_date": [58, 66],
                            "root_permit_issued_date": [119, 127],
                            "permit_number": [2, 9],
                            "sequence": [9, 11],
                            "approved_county_code": [11, 14],
                            "approved_lease_name": [14, 46],
                            "well_number": [48, 54],
                            "application_received": [121, 129],
                            "permit_issued": [129, 137],
                            "permit_amended": [137, 145],
                            "permit_extended": [145, 153],
                            "permit_spud": [153, 161],
                            "api8": [502, 510],
                        },
                    },
                }
            )
            pending_root = None
        else:
            continue

    if pending_root is not None:
        raise RRCParseError("archive ends with an unmatched DAROOT")
    if not records:
        raise RRCParseError("archive contains no supported permit revisions")
    return {
        "source_sha256": actual_sha256,
        "profile_id": profile_id,
        "physical_lines": len(lines),
        "classified_segments": sum(counts.values()),
        "segment_counts": counts,
        "opaque_unknown_count": len(unknown),
        "opaque_unknown_lines": unknown,
        "permit_revision_count": len(records),
        "unique_permit_revision_keys": len(seen),
        "records": records,
    }
