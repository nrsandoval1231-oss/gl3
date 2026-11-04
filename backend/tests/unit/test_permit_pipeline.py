from __future__ import annotations

from decimal import Decimal

from _permit_pdf import make_pdf

from gridlens.ingestion.parsers.equipment import extract_equipment_claims
from gridlens.ingestion.parsers.permit_docs import (
    VERSION,
    extract_from_pages,
    extract_permit_document,
)
from gridlens.ingestion.parsers.permit_docs.text_layer import TextLayerLimits

# West Edmond (OK DEQ permit memorandum 2017-0987-C M-2): prose says 2,500-hp electric
# motors; the EUG-17 table lists the driven Ariel compressors at 5,200 rated hp.
WEST_EDMOND_PROSE = (
    "OGS requests authorization to add three (3) 2,500-hp Siemens electric compressor motors "
    "and the three (3) associated Ariel KBZ compressors, one (1) 2,500-hp Waukesha 9394 GSI "
    "emergency generator, and associated fugitive components."
)
WEST_EDMOND_TABLE = (
    "EUG-17: Affected Compressors\n"
    "Operating Rated Manufacture Serial\n"
    "Emission Unit Description\n"
    "Speed Horsepower Date Number\n"
    "C-0701, Ariel Model KBZ 1,000 RPM 5,200 2022 F66626\n"
    "C-0801, Ariel Model KBZ 1,000 RPM 5,200 2022 F66698\n"
    "C-0901, Ariel Model KBZ 1,000 RPM 5,200 2022 F66773\n"
)
KWARGS = {
    "document_hash": "sha256:abc",
    "company": "ONEOK Gas Storage, L.L.C.",
    "facility": "West Edmond Station",
    "as_of": "2026-01-15",
}


def test_round_trip_through_the_existing_parser() -> None:
    result = extract_from_pages([WEST_EDMOND_PROSE, WEST_EDMOND_TABLE], **KWARGS)
    assert result.schedule_text.splitlines()[:3] == [
        "Company: ONEOK Gas Storage, L.L.C.",
        "Facility: West Edmond Station",
        "As of: 2026-01-15",
    ]
    parsed = extract_equipment_claims(result.schedule_text)
    assert parsed.issues == [] and parsed.has_schedule
    assert (parsed.company, parsed.facility, parsed.as_of) == (
        "ONEOK Gas Storage, L.L.C.",
        "West Edmond Station",
        "2026-01-15",
    )
    assert parsed.claims == result.claims  # identical dataclasses, offsets and quotes included
    (claim,) = parsed.claims
    assert (claim.drive, claim.rating, claim.unit, claim.count, claim.state) == (
        "electric",
        Decimal("2500"),
        "hp",
        3,
        "proposed",
    )
    assert claim.rating_basis == "mechanical_output" and claim.equipment_type == "compressor"


def test_west_edmond_trap_keeps_motor_and_compressor_ratings_apart() -> None:
    result = extract_from_pages([WEST_EDMOND_PROSE, WEST_EDMOND_TABLE], **KWARGS)
    ratings = {(r.equipment_id, r.rating, r.drive) for r in result.demand_rows + result.supply_rows}
    # motors: 2,500 hp electric. Table compressors: 5,200 hp, drive NOT stated in the table.
    assert any(rating == Decimal("2500") and drive == "electric" for _, rating, drive in ratings)
    table = {i: (rating, drive) for i, rating, drive in ratings if i.startswith("C-")}
    assert table == {
        "C-0701": (Decimal("5200"), "unknown"),
        "C-0801": (Decimal("5200"), "unknown"),
        "C-0901": (Decimal("5200"), "unknown"),
    }
    assert not any(c.rating == Decimal("5200") for c in result.claims)
    assert not any(c.rating == Decimal("2500") and c.drive != "electric" for c in result.claims)
    # linked only through the permit's own words ("associated Ariel")
    motors = next(r for r in result.demand_rows if r.drive == "electric")
    assert motors.linked_to == ("C-0701", "C-0801", "C-0901")


def test_table_alone_yields_no_demand_claim_and_no_electric_mw() -> None:
    result = extract_from_pages([WEST_EDMOND_TABLE], **KWARGS)
    assert result.claims == [] and result.demand_rows == []
    assert len(result.supply_rows) == 3  # retained with provenance, not dropped
    assert "Equipment ID" not in result.schedule_text


def test_unknown_is_not_zero() -> None:
    result = extract_from_pages(
        ["Three (3) 5,200-hp Ariel compressors are part of the project and listed in the table."],
        **KWARGS,
    )
    assert result.claims == []
    assert result.rows_by_role == {"demand_claim": 0, "supply_other": 1}
    (row,) = result.supply_rows
    assert row.drive == "unknown" and row.count == 3
    empty = extract_from_pages(
        ["Nothing about equipment appears on this page at all, really."], **KWARGS
    )
    assert empty.verified == 0 and empty.claims == [] and empty.schedule_text == ""


def test_explicit_non_electric_drive_is_kept_but_never_electric() -> None:
    result = extract_from_pages(
        [
            "The site adds two (2) 900-hp electric-driven pumps and four (4) 300-hp "
            "gas engine-driven "
            "pumps."
        ],
        **KWARGS,
    )
    assert [(c.equipment_type, c.drive, c.count) for c in result.claims] == [
        ("pump", "electric", 2)
    ]


def test_repeated_mentions_are_not_double_counted() -> None:
    result = extract_from_pages(
        [WEST_EDMOND_PROSE, "Summary: " + WEST_EDMOND_PROSE.replace("add three", "include three")],
        **KWARGS,
    )
    assert len(result.claims) == 1 and result.duplicates >= 1


def test_provenance_maps_schedule_lines_to_verbatim_quotes() -> None:
    result = extract_from_pages([WEST_EDMOND_PROSE], **KWARGS)
    ((line_index, prov),) = result.provenance.items()
    assert result.schedule_text.splitlines()[line_index].startswith("Equipment ID: ")
    assert prov["verifier"] == "exact-span-v1" and prov["document_hash"] == "sha256:abc"
    assert prov["page"] == 1 and prov["quote"] in WEST_EDMOND_PROSE
    assert prov["fields"]["drive"]["quote"] == "electric compressor motors"
    assert result.version == VERSION == "permit-doc-extract-v1"


def test_scanned_pages_need_ocr_and_produce_no_rows() -> None:
    result = extract_from_pages(["", WEST_EDMOND_PROSE, "  "], **KWARGS)
    assert result.scanned_pages == 2 and result.needs_ocr_pages == [1, 3]
    assert any("OCR" in issue for issue in result.issues)
    assert len(result.claims) == 1


def test_pdf_end_to_end_and_failure_modes() -> None:
    pdf = make_pdf(
        [
            [
                "OGS requests authorization to add three (3) 2,500-hp Siemens electric compressor",
                "motors for injection at the station.",
            ],
            [],
        ]
    )
    ok = extract_permit_document(pdf, **KWARGS)
    assert ok.failure is None and ok.pages == 2 and ok.scanned_pages == 1
    assert [(c.drive, c.count) for c in ok.claims] == [("electric", 3)]
    bbox = ok.provenance[next(iter(ok.provenance))]
    assert bbox["page"] == 1

    corrupt = extract_permit_document(b"not a pdf at all", **KWARGS)
    assert corrupt.failure is not None and corrupt.failure.code == "unreadable"
    assert corrupt.claims == [] and corrupt.schedule_text == ""

    big = extract_permit_document(pdf, limits=TextLayerLimits(max_bytes=10), **KWARGS)
    assert big.failure is not None and big.failure.code == "too_large"

    only_scan = extract_permit_document(make_pdf([[], []]), **KWARGS)
    assert only_scan.failure is None and only_scan.scanned_pages == 2 and only_scan.claims == []
    assert only_scan.verified == 0


def test_invalid_as_of_is_dropped_with_an_issue() -> None:
    result = extract_from_pages([WEST_EDMOND_PROSE], **{**KWARGS, "as_of": "Jan 2026"})
    assert "As of" not in result.schedule_text
    assert any("as_of" in i for i in result.issues)


def test_company_header_cannot_inject_extra_fields() -> None:
    result = extract_from_pages(
        [WEST_EDMOND_PROSE], **{**KWARGS, "company": "A | Drive: electric" + chr(10) + "B"}
    )
    first = result.schedule_text.splitlines()[0]
    assert first.startswith("Company: ") and "|" not in first
    assert len(result.schedule_text.splitlines()) == 4
