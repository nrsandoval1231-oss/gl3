#!/usr/bin/env python3
"""Read-only validator for the retained RRC daily permit archive (GL3-015E)."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
import sys


DATA_SHA256 = "c0215842369f14d6e725b011649ffa0076f373344e3ce5bb0d2ed411fce79cd6"
MANUAL_SHA256 = "760a25367df8fb3bd7b240a41d9471953e2ee1eab1878d5367c673548adec874"
TYPE_NAMES = {
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
EXPECTED_LENGTHS = {b"01": 212, b"02": 510}
SPANS = {
    "root_status_number": (2, 9),
    "root_sequence": (9, 11),
    "root_reported_county": (11, 14),
    "root_reported_lease": (14, 46),
    "root_received_date": (58, 66),
    "root_application_status": (100, 101),
    "root_permit_number": (112, 119),
    "root_permit_issued_date": (119, 127),
    "permit_number": (2, 9),
    "permit_sequence": (9, 11),
    "permit_approved_county": (11, 14),
    "permit_approved_lease": (14, 46),
    "permit_well_number": (48, 54),
    "permit_received_date": (121, 129),
    "permit_issued_date": (129, 137),
    "permit_amended_date": (137, 145),
    "permit_extended_date": (145, 153),
    "permit_spud_date": (153, 161),
    "permit_api8": (502, 510),
}


def split_crlf(data: bytes) -> list[bytes]:
    if not data.endswith(b"\r\n"):
        raise ValueError("archive must end in CRLF")
    body = data.replace(b"\r\n", b"")
    if b"\r" in body or b"\n" in body:
        raise ValueError("archive contains a non-CRLF line break")
    rows = data[:-2].split(b"\r\n")
    if any(not row for row in rows):
        raise ValueError("archive contains an empty physical line")
    return rows


def classify(row: bytes) -> tuple[str, str | None]:
    """Do not decode unclassified rows; report only their first-byte hex."""
    if row.startswith(b"\x85"):
        return "UNKNOWN", "85"
    record_type = row[:2]
    if record_type in EXPECTED_LENGTHS and len(row) != EXPECTED_LENGTHS[record_type]:
        raise ValueError(
            f"malformed type {record_type.decode('ascii')} length {len(row)}; "
            f"expected {EXPECTED_LENGTHS[record_type]}"
        )
    if record_type in TYPE_NAMES:
        return TYPE_NAMES[record_type], None
    return "UNKNOWN", row[:2].hex()


def ascii_span(row: bytes, name: str) -> str:
    start, end = SPANS[name]
    return row[start:end].decode("ascii", errors="strict")


def normalized_date(raw: bytes, name: str) -> str | None:
    value = ascii_span(raw, name)
    if len(value) != 8 or not value.isdigit():
        raise ValueError(f"{name}: expected 8 ASCII digits, got {value!r}")
    if value == "00000000":
        return None
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8])).isoformat()
    except ValueError as exc:
        raise ValueError(f"{name}: invalid calendar date {value}") from exc


def text_span(row: bytes, name: str) -> str:
    # Keep exact bytes in the archive; this is display normalization only.
    return ascii_span(row, name).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data",
        type=Path,
        default=Path(".artifacts/GL3-015D/raw/rrc-daily-permit-current-month.bin"),
    )
    parser.add_argument(
        "--manual",
        type=Path,
        default=Path(".artifacts/GL3-015D/raw/drilling-permit-daily-manual.pdf"),
    )
    parser.add_argument(
        "--samples",
        type=Path,
        default=Path(".agent/artifacts/GL3-015D/sample-validation.json"),
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path(".agent/artifacts/GL3-015E/field-map.json"),
    )
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()

    data = args.data.read_bytes()
    manual = args.manual.read_bytes()
    data_hash = hashlib.sha256(data).hexdigest()
    manual_hash = hashlib.sha256(manual).hexdigest()
    if data_hash != DATA_SHA256:
        raise ValueError(f"archive hash mismatch: {data_hash}")
    if manual_hash != MANUAL_SHA256:
        raise ValueError(f"manual hash mismatch: {manual_hash}")
    profile = json.loads(args.profile.read_text(encoding="utf-8-sig"))
    if profile["source_sha256"] != DATA_SHA256 or profile["manual_sha256"] != MANUAL_SHA256:
        raise ValueError("field profile is not bound to the retained archive/manual")
    field_entries = {field["name"]: field for field in profile["fields"]}
    profile_expectations = {
        "record_type": (0, 2),
        "status_number / permit_number": (2, 9),
        "sequence": (9, 11),
        "reported_county_code": (11, 14),
        "approved_county_code": (11, 14),
        "reported_lease_name": (14, 46),
        "approved_lease_name": (14, 46),
        "well_number": (48, 54),
        "application_status": (100, 101),
        "root_permit_number": (112, 119),
        "root_permit_issued_date": (119, 127),
        "permit_issued_date": (129, 137),
        "permit_amended_date": (137, 145),
        "permit_extended_date": (145, 153),
        "permit_spud_date": (153, 161),
        "api8": (502, 510),
    }
    for name, span in profile_expectations.items():
        if tuple(field_entries[name]["observed_span"]) != span:
            raise ValueError(f"profile span mismatch for {name}")
    received_spans = field_entries["application_received_date"]["observed_span"]
    if received_spans != {"type_01": [58, 66], "type_02": [121, 129]}:
        raise ValueError("profile span mismatch for application_received_date")
    rows = split_crlf(data)

    # Guard the fail-closed behaviors with in-process fixtures.
    if classify(b"\x85") != ("UNKNOWN", "85"):
        raise AssertionError("0x85 fixture must remain uninterpreted UNKNOWN")
    try:
        classify(b"02short")
    except ValueError as exc:
        if "malformed type 02" not in str(exc):
            raise
    else:
        raise AssertionError("malformed known segment must fail")
    try:
        split_crlf(b"01bad\n")
    except ValueError:
        pass
    else:
        raise AssertionError("non-CRLF input must fail")

    classifications = [classify(row) for row in rows]
    segment_counts = Counter(name for name, _ in classifications if name != "UNKNOWN")
    unknown_rows = [
        {"line": i + 1, "prefix_hex": prefix, "meaning": "UNKNOWN"}
        for i, (name, prefix) in enumerate(classifications)
        if name == "UNKNOWN"
    ]
    if len(rows) != 29494 or sum(segment_counts.values()) != 29459:
        raise AssertionError("physical/classified segment totals changed")
    if len(unknown_rows) != 35 or any(x["prefix_hex"] != "85" for x in unknown_rows):
        raise AssertionError("unexpected unclassified-row profile")

    positions_01 = [i for i, row in enumerate(rows) if row[:2] == b"01"]
    positions_02 = [i for i, row in enumerate(rows) if row[:2] == b"02"]
    pairs: list[tuple[int, bytes, bytes]] = []
    for i in positions_01:
        if i + 1 >= len(rows) or rows[i + 1][:2] != b"02":
            raise AssertionError(f"type-01 at physical line {i + 1} lacks adjacent type-02")
        pairs.append((i + 1, rows[i], rows[i + 1]))
    if len(pairs) != 884 or len(positions_02) != 884:
        raise AssertionError("root/permit record counts changed")
    if {i + 1 for i in positions_02} != {line + 1 for line, _, _ in pairs}:
        raise AssertionError("a type-02 record is not paired to its immediately preceding root")

    pair_keys: list[tuple[str, str]] = []
    api_records: dict[str, list[tuple[int, str, str, str]]] = defaultdict(list)
    seq_counts: Counter[str] = Counter()
    seq_amended: Counter[tuple[str, bool]] = Counter()
    county_disagreements: list[dict[str, str | int]] = []
    crosscheck = Counter()
    date_presence = Counter()
    lengths_by_type: dict[str, Counter[int]] = defaultdict(Counter)
    for row, (name, _) in zip(rows, classifications, strict=True):
        if name != "UNKNOWN":
            lengths_by_type[name][len(row)] += 1

    for root_line, root_row, permit_row in pairs:
        # All mapped cells must be ASCII; preserve source padding for comparisons.
        root_row.decode("ascii", errors="strict")
        permit_row.decode("ascii", errors="strict")
        number = ascii_span(permit_row, "permit_number")
        sequence = ascii_span(permit_row, "permit_sequence")
        api8 = ascii_span(permit_row, "permit_api8")
        if not (number.isdigit() and sequence.isdigit() and api8.isdigit()):
            raise AssertionError(f"nonnumeric permit key/API at line {root_line + 1}")
        pair_keys.append((number, sequence))
        seq_counts[sequence] += 1
        if root_row[2:11] != permit_row[2:11]:
            raise AssertionError(f"status number/sequence mismatch at line {root_line}")
        crosscheck["status_sequence"] += 1
        if root_row[112:119] != permit_row[2:9]:
            raise AssertionError(f"root permit-number mismatch at line {root_line}")
        crosscheck["root_permit_number"] += 1
        if root_row[14:46] != permit_row[14:46]:
            raise AssertionError(f"lease field mismatch at line {root_line}")
        crosscheck["lease_name"] += 1
        if root_row[58:66] != permit_row[121:129]:
            raise AssertionError(f"application received date mismatch at line {root_line}")
        crosscheck["received_date"] += 1
        if root_row[119:127] != permit_row[129:137]:
            raise AssertionError(f"permit issue date mismatch at line {root_line}")
        crosscheck["permit_issued_date"] += 1
        if root_row[100:101] != b"A":
            raise AssertionError(f"type-02 root is not approved at line {root_line}")
        crosscheck["approved_status"] += 1

        reported_county = ascii_span(root_row, "root_reported_county")
        approved_county = ascii_span(permit_row, "permit_approved_county")
        if reported_county != approved_county:
            county_disagreements.append(
                {
                    "root_line": root_line,
                    "permit_line": root_line + 1,
                    "status_number": number,
                    "root_reported_county": reported_county,
                    "permit_approved_county": approved_county,
                }
            )
        if api8[:3] != approved_county:
            raise AssertionError(f"API county prefix differs from approved county at {root_line + 1}")
        crosscheck["api_county_prefix"] += 1

        received = normalized_date(permit_row, "permit_received_date")
        issued = normalized_date(permit_row, "permit_issued_date")
        amended = normalized_date(permit_row, "permit_amended_date")
        extended = normalized_date(permit_row, "permit_extended_date")
        spud = normalized_date(permit_row, "permit_spud_date")
        for name, value in (("received", received), ("issued", issued), ("amended", amended), ("extended", extended), ("spud", spud)):
            date_presence[name] += value is not None
        seq_amended[(sequence, amended is not None)] += 1
        api_records[api8].append((root_line + 1, number, sequence, approved_county))

    if len(set(pair_keys)) != 884:
        raise AssertionError("permit number + sequence is not unique within this snapshot")
    if len(county_disagreements) != 3:
        raise AssertionError("reported/approved county difference count changed")
    if seq_counts != Counter({"99": 647, "98": 190, "97": 43, "96": 4}):
        raise AssertionError(f"sequence distribution changed: {seq_counts}")
    if any(seq_amended[(seq, False)] for seq in ("98", "97", "96")):
        raise AssertionError("amendment sequence without amended date observed")
    if seq_amended[("99", True)]:
        raise AssertionError("original sequence 99 has amended date in this snapshot")

    repeated_api = {api: recs for api, recs in api_records.items() if len(recs) > 1}
    same_number_revisions = sum(
        len({x[1] for x in recs}) == 1 and len({x[2] for x in recs}) > 1
        for recs in repeated_api.values()
    )
    cross_number_repeats = [
        {"api8": api, "records": [{"line": x[0], "permit_number": x[1], "sequence": x[2]} for x in recs]}
        for api, recs in repeated_api.items()
        if len({x[1] for x in recs}) > 1
    ]
    if len(repeated_api) != 16 or sum(len(v) - 1 for v in repeated_api.values()) != 16:
        raise AssertionError("API repeat profile changed")

    prior_samples = json.loads(args.samples.read_text(encoding="utf-8-sig"))["sample"]
    sample_results = []
    for sample in prior_samples:
        root_row = rows[sample["root_row"] - 1]
        permit_row = rows[sample["permit_row"] - 1]
        if root_row[:2] != b"01" or permit_row[:2] != b"02" or root_row[2:11] != permit_row[2:11]:
            raise AssertionError(f"sample rows not a paired 01/02 identity: {sample['permit_row']}")
        values = {
            "status_number": ascii_span(permit_row, "permit_number"),
            "sequence": ascii_span(permit_row, "permit_sequence"),
            "status": root_row[100:101].decode("ascii"),
            "county_code": ascii_span(permit_row, "permit_approved_county"),
            "lease_name": text_span(permit_row, "permit_approved_lease"),
            "well_number": text_span(permit_row, "permit_well_number"),
            "application_received": ascii_span(permit_row, "permit_received_date"),
            "permit_issued": ascii_span(permit_row, "permit_issued_date"),
            "permit_amended": normalized_date(permit_row, "permit_amended_date"),
            "spud_date": normalized_date(permit_row, "permit_spud_date"),
            "api8": ascii_span(permit_row, "permit_api8"),
        }
        expected = dict(sample)
        for key, val in values.items():
            if key == "permit_amended" and expected[key] is not None:
                expected[key] = f"{expected[key][:4]}-{expected[key][4:6]}-{expected[key][6:8]}"
            if key == "spud_date" and expected[key] is not None:
                expected[key] = f"{expected[key][:4]}-{expected[key][4:6]}-{expected[key][6:8]}"
            if expected[key] != val:
                raise AssertionError(f"sample mismatch row {sample['permit_row']} {key}: {val!r}")
        sample_results.append({"root_line": sample["root_row"], "permit_line": sample["permit_row"], "identity": f"{values['status_number']}/{values['sequence']}"})

    receipt = {
        "packet": "GL3-015E",
        "profile_version": "rrc-daily-master-v1-observed",
        "decision": "GO",
        "scope": "type-01/type-02 field map for this exact retained archive only",
        "data_sha256": data_hash,
        "data_bytes": len(data),
        "manual_sha256": manual_hash,
        "manual_bytes": len(manual),
        "physical_lines": len(rows),
        "classified_segments": sum(segment_counts.values()),
        "segment_counts": dict(sorted(segment_counts.items())),
        "unknown_lines": {"count": len(unknown_rows), "prefix_hex": "85", "meaning": "UNKNOWN; not decoded or interpreted", "length_counts": dict(sorted(Counter(len(rows[x['line'] - 1]) for x in unknown_rows).items()))},
        "record_lengths_by_type": {k: dict(sorted(v.items())) for k, v in sorted(lengths_by_type.items())},
        "type_01_records": len(positions_01),
        "type_02_records": len(positions_02),
        "adjacent_pairs_checked": len(pairs),
        "cross_checks": dict(crosscheck),
        "reported_vs_approved_county": {"matches": len(pairs) - len(county_disagreements), "differences": county_disagreements, "semantics": "manual distinguishes operator-reported root county from approved permit county; these are not forced equal"},
        "unique_permit_number_sequence_keys": len(set(pair_keys)),
        "sequence_counts": dict(sorted(seq_counts.items())),
        "sequence_amended_date_counts": {f"{seq}:{'present' if present else 'zero'}": count for (seq, present), count in sorted(seq_amended.items())},
        "date_nonzero_counts": dict(date_presence),
        "api8": {"distinct": len(api_records), "repeated_value_groups": len(repeated_api), "extra_records_in_repeat_groups": sum(len(v) - 1 for v in repeated_api.values()), "same_permit_different_sequence_groups": same_number_revisions, "different_permit_number_groups": cross_number_repeats},
        "prior_sample_identities_revalidated": sample_results,
        "malformed_unclassified_self_tests": "PASS: 0x85 remains UNKNOWN; malformed type-02 length rejects; non-CRLF input rejects",
        "boundary_cases": {"first_line": {"line": 1, "type": rows[0][:2].decode("ascii"), "length": len(rows[0])}, "last_line": {"line": len(rows), "type": classifications[-1][0], "length": len(rows[-1])}, "api_span": list(SPANS["permit_api8"]), "api_end_is_record_end": SPANS["permit_api8"][1] == EXPECTED_LENGTHS[b"02"]},
        "offset_resolution": {"root_rule": "observed 0-based start = official 1-based POS - 1", "permit_rule": "observed 0-based start = official 1-based POS - 3 for fields after the leading two-byte type id", "basis": "manual DAPERMIT layout shows record-id fields at POS 1 and POS 3; actual 510-byte daily segment contains the leading POS-1 type id and status/permit number begins at observed byte 2. The additional two bytes are absent in this daily serialization.", "manual_footer_filler": "UNKNOWN/unmapped: manual page II.17 lists RRC-TAPE-FILLER at POS 503 overlapping API-NUMBER at POS 505; this irrelevant filler field is not interpreted or included in the profile."},
        "validated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    output = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(output, encoding="utf-8")
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
