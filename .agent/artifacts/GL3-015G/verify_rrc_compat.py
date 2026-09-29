"""Independent snapshot compatibility check; never calls or relaxes the F parser."""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

KNOWN = {
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


class CompatibilityError(ValueError):
    pass


def _digits(line: bytes, start: int, end: int, label: str) -> str:
    value = line[start:end]
    if len(value) != end - start or not value.isdigit():
        raise CompatibilityError(f"{label} is not ASCII digits at field span [{start},{end})")
    return value.decode("ascii")


def _ascii_text(line: bytes, start: int, end: int, label: str) -> None:
    value = line[start:end]
    if len(value) != end - start or not value.isascii():
        raise CompatibilityError(f"{label} is not ASCII at field span [{start},{end})")


def _date(raw: str, label: str, *, optional: bool) -> str | None:
    if raw == "00000000" and optional:
        return None
    if raw == "00000000":
        raise CompatibilityError(f"required date {label} is zero")
    try:
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8])).isoformat()
    except ValueError as exc:
        raise CompatibilityError(f"invalid calendar date for {label}: {raw}") from exc


def verify_snapshot(payload: bytes) -> dict[str, Any]:
    """Check snapshot-dependent layout/key/date invariants against the accepted profile."""
    result: dict[str, Any] = {
        "decision": "REDIRECT",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }
    try:
        if not payload or not payload.endswith(b"\r\n"):
            raise CompatibilityError("file is not terminated by CRLF")
        remainder = payload.replace(b"\r\n", b"")
        if b"\r" in remainder or b"\n" in remainder:
            raise CompatibilityError("file contains non-CRLF line endings")
        lines = payload[:-2].split(b"\r\n")
        counts: dict[str, int] = {}
        opaque: list[dict[str, Any]] = []
        pairs: list[dict[str, Any]] = []
        prior_root: tuple[int, bytes] | None = None
        keys: set[tuple[str, str]] = set()
        for number, line in enumerate(lines, 1):
            if not line:
                raise CompatibilityError(f"empty line {number}")
            if prior_root is not None and line[:2] != b"02":
                raise CompatibilityError(f"DAROOT line {prior_root[0]} not adjacent to DAPERMIT")
            if line[0] == 0x85:
                opaque.append({"line": number, "bytes": len(line)})
                prior_root = None
                continue
            segment = line[:2]
            name = KNOWN.get(segment)
            if name is None:
                raise CompatibilityError(f"unclassified segment at line {number}")
            counts[name] = counts.get(name, 0) + 1
            if segment == b"01":
                if len(line) != 212:
                    raise CompatibilityError(f"DAROOT length {len(line)} at line {number}")
                _ascii_text(line, 2, 212, "DAROOT mapped fields")
                prior_root = (number, line)
            elif segment == b"02":
                if len(line) != 510:
                    raise CompatibilityError(f"DAPERMIT length {len(line)} at line {number}")
                _ascii_text(line, 2, 510, "DAPERMIT mapped fields")
                if prior_root is None:
                    raise CompatibilityError(f"DAPERMIT at line {number} has no adjacent DAROOT")
                root_line, root = prior_root
                status_number = _digits(root, 2, 9, "root status number")
                permit_number = _digits(line, 2, 9, "permit number")
                sequence = _digits(line, 9, 11, "sequence")
                if _digits(root, 9, 11, "root sequence") != sequence:
                    raise CompatibilityError(f"root/detail sequence mismatch at lines {root_line}/{number}")
                if _digits(root, 112, 119, "root permit number") != permit_number:
                    raise CompatibilityError(f"root/detail permit number mismatch at lines {root_line}/{number}")
                if status_number != permit_number:
                    raise CompatibilityError(f"root/detail status number mismatch at lines {root_line}/{number}")
                status = root[100:101]
                if status != b"A":
                    raise CompatibilityError(f"non-A root status at line {root_line}")
                reported_county = _digits(root, 11, 14, "reported county")
                approved_county = _digits(line, 11, 14, "approved county")
                rec_raw = _digits(line, 121, 129, "received date")
                issue_raw = _digits(line, 129, 137, "issue date")
                root_rec_raw = _digits(root, 58, 66, "root received date")
                root_issue_raw = _digits(root, 119, 127, "root issue date")
                rec = _date(rec_raw, "received", optional=False)
                issue = _date(issue_raw, "issued", optional=False)
                _date(root_rec_raw, "root received", optional=False)
                _date(root_issue_raw, "root issued", optional=False)
                if (rec_raw, issue_raw) != (root_rec_raw, root_issue_raw):
                    raise CompatibilityError(f"root/detail date mismatch at lines {root_line}/{number}")
                optional_dates = {}
                for label, start in (("amended", 137), ("extended", 145), ("spud", 153)):
                    raw = _digits(line, start, start + 8, f"{label} date")
                    optional_dates[label] = {"raw": raw, "date": _date(raw, label, optional=True)}
                api8 = _digits(line, 502, 510, "API8")
                if api8[:3] != approved_county:
                    raise CompatibilityError(f"API county prefix mismatch at line {number}")
                key = (permit_number, sequence)
                if key in keys:
                    raise CompatibilityError(f"duplicate permit-number/sequence at line {number}")
                keys.add(key)
                pairs.append(
                    {
                        "identity": f"{permit_number}/{sequence}",
                        "root_line": root_line,
                        "permit_line": number,
                        "reported_county_code": reported_county,
                        "approved_county_code": approved_county,
                        "received": rec,
                        "issued": issue,
                        "optional_dates": optional_dates,
                        "api8": api8,
                    }
                )
                prior_root = None
            else:
                prior_root = None
        if prior_root is not None:
            raise CompatibilityError(f"unmatched DAROOT line {prior_root[0]}")
        if not pairs:
            raise CompatibilityError("no permit revisions found")
        result.update(
            {
                "decision": "GO",
                "physical_lines": len(lines),
                "classified_segments": sum(counts.values()),
                "segment_counts": counts,
                "opaque_unknown_count": len(opaque),
                "opaque_unknown_lines": opaque,
                "permit_revision_count": len(pairs),
                "unique_permit_number_sequence_keys": len(keys),
                "sample": pairs[:10],
                "limitations": [
                    "Compatibility is established only for this exact file hash.",
                    "35/other opaque 0x85 lines are counted, not decoded; their meaning remains UNKNOWN.",
                    "Other recognized segment families are counted only.",
                    "No pending, completion, production, pad, operator, power-demand, or commercial inference is made.",
                ],
            }
        )
    except CompatibilityError as exc:
        result["reason"] = str(exc)
    return result
