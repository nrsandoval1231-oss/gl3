"""Hand-labelled regression cases for the independent review of the permit extraction core.

Each case is a small text with the answer written by hand from its words (B = blocker,
S = should-fix in the review).
"""

from __future__ import annotations

import sys
import time
from dataclasses import replace

import pytest
from _permit_pdf import make_pdf

from gridlens.ingestion.parsers.equipment import extract_equipment_claims
from gridlens.ingestion.parsers.permit_docs import (
    extract_from_pages,
    extract_permit_document,
    text_layer,
)
from gridlens.ingestion.parsers.permit_docs.models import FieldEvidence
from gridlens.ingestion.parsers.permit_docs.narrative import extract_narrative
from gridlens.ingestion.parsers.permit_docs.router import route_page
from gridlens.ingestion.parsers.permit_docs.tables import extract_tables
from gridlens.ingestion.parsers.permit_docs.text_layer import (
    CanonicalText,
    TextLayerFailure,
    TextLayerLimits,
    build_canonical_text,
)
from gridlens.ingestion.parsers.permit_docs.verifier import verify_rows

K = {"document_hash": "sha256:test"}


def run(*pages: str):
    return extract_from_pages(list(pages), **K)


def ids(rows) -> list[str]:
    return [r.equipment_id for r in rows]


# ---------------------------------------------------------------- B2
def test_b2_capacity_row_never_takes_type_or_drive_from_another_units_line() -> None:
    result = run(
        "Table 2-A Rated Capacity\n"
        "ENG-1 Waukesha 7042 S1 1380 HP 1380 HP\n"
        "Electric Motor Driven Compressor C-2\n"
        "C-2 Toshiba M1 S2 1500 HP 1500 HP\n"
    )
    everything = result.demand_rows + result.supply_rows
    assert "ENG-1" not in ids(everything)  # no stated type of its own: unknown, so no row
    assert [(c.equipment_id, c.equipment_type, c.drive) for c in result.claims] == [
        ("C-2", "compressor", "electric")
    ]


def test_b2_numeric_row_numbers_are_not_blocked_by_unit_words_on_their_own_line() -> None:
    page = (
        "Table 2-A Rated Capacity\n"
        "1 Natural Gas Fired Solar T-4002 OHB16-C1819 3961 hp 3123 hp 1/1/1972\n"
        "Field Unit 3 Turbine (Pkg # 3020005) 1/1/1972 1\n"
        "3 Natural Gas Fired Solar T-4702 OHG17-C5915 4680 hp 3779 hp 8/1/1981\n"
        "Field Unit 2 Turbine (Pkg # CC81338) 8/1/1981 3\n"
    )
    result = run(page)
    assert {(r.equipment_id, r.equipment_type) for r in result.supply_rows} == {
        ("1", "turbine"),
        ("3", "turbine"),
    }


# ---------------------------------------------------------------- B3
def test_b3_rating_never_pairs_with_a_noun_on_the_next_line() -> None:
    result = run(
        "Heat input is rated at 1,380 hp for the unit listed below in the table\n"
        "Electric motor-driven compressor C-9 is a different unit at another site.\n"
    )
    assert result.verified == 0 and result.claims == []


def test_b3_table_rows_are_not_re_read_as_prose() -> None:
    text = "Combustion Turbine #1(a) 224 MW 1 CT1 S1\nCombustion Turbine #2(a) 224 MW 2 CT2 S2\n"
    canon = CanonicalText.from_page_texts([text])
    rows, _ = extract_narrative(canon, {1: "narrative"}, consumed=[(0, len(text))])
    assert rows == []
    again, _ = extract_narrative(canon, {1: "narrative"})
    assert again == []  # and without the consumed spans there is still no cross-line pairing


# ---------------------------------------------------------------- B4
def test_b4_rblc_listing_of_other_facilities_yields_nothing() -> None:
    text = (
        "RBLC search results for other facilities, Rated Capacity listed\n"
        "Electric motor driven compressor at Acme Station TX-0999\n"
        "TX-0999 Siemens M1 S9 5000 HP 5000 HP\n"
    )
    assert route_page(text) == "irrelevant"
    result = run(text)
    assert result.claims == [] and result.supply_rows == [] and result.verified == 0


# ---------------------------------------------------------------- B5
TABLE_PAGE = (
    "EUG-2 Electric motor driven compressors\n"
    "EU Point Description Horsepower Const. Date\n"
    "C-1 1 Ariel JGK compressor 1500 2024\n"
    "C-2 2 Ariel JGK compressor 1500 2024\n"
    "C-3 3 Ariel JGK compressor 1500 2024\n"
)


def test_b5_unit_in_prose_and_table_is_counted_once() -> None:
    prose = "The applicant will install three (3) 1,500 hp electric motor-driven compressors."
    result = run(prose, TABLE_PAGE)
    assert sorted(c.equipment_id for c in result.claims) == ["C-1", "C-2", "C-3"]
    assert any("Conflict" in i for i in result.issues)
    assert extract_equipment_claims(result.schedule_text).claims == result.claims


def test_b5_prose_that_states_more_units_than_the_table_wins_alone() -> None:
    prose = "The applicant will install five (5) 1,500 hp electric motor-driven compressors."
    result = run(prose, TABLE_PAGE)
    assert [(c.count, c.drive) for c in result.claims] == [(5, "electric")]
    assert ids(result.supply_rows) == []
    assert any("kept the prose row only" in i for i in result.issues)


def test_b5_two_distinct_prose_units_with_different_ratings_are_both_kept() -> None:
    result = run(
        "Site A will add one (1) 1,500 hp electric motor-driven compressor. Site B will add "
        "one (1) 2,000 hp electric motor-driven compressor."
    )
    assert sorted(str(c.rating) for c in result.claims) == ["1500", "2000"]


# ---------------------------------------------------------------- B6 / S3
@pytest.mark.parametrize(
    "text",
    [
        "Equipment authorized by this permit includes the following units:\n"
        "(4) 1,000-hp electric motor-driven pump",
        "The facility will include the following equipment: (4) 1,000-hp electric "
        "motor-driven pump for inlet service.",
        "Authorized units are:\n(4) 1,000-hp electric motor-driven pump at the main plant site.",
        "Unit count is four\n1,000-hp electric motor-driven pump at the main plant site.",
        "There are four units. 1,000-hp electric motor-driven pump at the main plant site.",
        "The station has four\n(4)\n1,000-hp electric motor-driven pump at the main plant site.",
    ],
)
def test_b6_s3_list_numbers_and_distant_words_are_not_counts(text: str) -> None:
    (claim,) = run(text).claims
    assert claim.count is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The plant has four (4) 1,000-hp electric motor-driven pumps installed.", 4),
        ("It adds boilers, (4) 1,000-hp electric motor-driven pumps at the plant site.", 4),
        ("The station adds two\n(2) 1,000-hp electric motor-driven pumps at the plant.", 2),
        ("The plant has two 1,000-hp electric motor-driven pumps installed.", 2),
    ],
)
def test_b6_real_counts_still_count(text: str, expected: int) -> None:
    (claim,) = run(text).claims
    assert claim.count == expected


# ---------------------------------------------------------------- S1
def _verified_table_row():
    canon = CanonicalText.from_page_texts([TABLE_PAGE])
    rows, _ = extract_tables(canon, {1: "table"})
    return canon, rows


def test_s1_table_rows_carry_only_their_own_group_title_and_line() -> None:
    canon, rows = _verified_table_row()
    assert verify_rows(rows, canon).rejected == []
    # a quote lifted from a different row's line is real text but not this row's evidence
    other_line = canon.text.index("C-2 2 Ariel JGK compressor")
    word = other_line + canon.text[other_line:].index("compressor")
    bad = replace(
        rows[0],
        evidence={
            **rows[0].evidence,
            "type": FieldEvidence("type", "compressor", "compressor", word, word + 10, 1),
        },
    )
    assert "neither on the row line" in verify_rows([bad], canon).rejected[0][1]


def test_s1_group_title_must_be_the_nearest_one() -> None:
    page = TABLE_PAGE + "EUG-3 Fugitives\n" + "C-9 9 Ariel compressor 1500 2024\n"
    canon = CanonicalText.from_page_texts([page])
    rows, _ = extract_tables(canon, {1: "table"})
    first = rows[0]
    moved = replace(
        first,
        equipment_id="C-9",
        evidence={
            **first.evidence,
            "id": replace(
                first.evidence["id"],
                value="C-9",
                quote="C-9",
                start=canon.text.index("C-9 9"),
                end=canon.text.index("C-9 9") + 3,
            ),
        },
    )
    # the row's rating/type quotes now disagree with its id line: rejected, not silently kept
    assert verify_rows([moved], canon).verified == []


def test_s1_unknown_evidence_keys_are_rejected() -> None:
    canon, rows = _verified_table_row()
    extra = replace(
        rows[0],
        evidence={**rows[0].evidence, "voltage": FieldEvidence("voltage", "480", "480", 0, 3, 1)},
    )
    assert "unknown evidence key" in verify_rows([extra], canon).rejected[0][1]


def test_s1_narrative_type_must_sit_in_the_ratings_own_phrase() -> None:
    text = "The site has a 1,000-hp unit. Later text mentions an electric motor-driven pump here."
    canon = CanonicalText.from_page_texts([text])
    rows, _ = extract_narrative(canon, {1: "narrative"})
    assert rows == []  # extractor never pairs across the sentence
    good = CanonicalText.from_page_texts(
        ["A pump sat idle. The site has a 1,000-hp electric motor-driven pump installed today."]
    )
    (row,) = extract_narrative(good, {1: "narrative"})[0]
    early = good.text.index("pump")  # a real "pump", but in the previous sentence
    forged = replace(
        row,
        evidence={
            **row.evidence,
            "type": FieldEvidence("type", "pump", "pump", early, early + 4, 1),
        },
    )
    rejected = verify_rows([forged], good).rejected
    assert rejected and "not after the rating" in rejected[0][1]


# ---------------------------------------------------------------- S2
@pytest.mark.parametrize(
    "text",
    [
        "The project will replace two (2) existing 1,000 hp electric motor-driven compressors.",
        "The applicant will remove the existing 1,200 hp electric motor-driven compressor now.",
        "The retired 1,200 hp electric motor-driven compressor is decommissioned permanently.",
        "Existing 900 hp electric motor-driven pumps will be decommissioned at the old plant.",
    ],
)
def test_s2_equipment_leaving_service_is_never_existing_demand(text: str) -> None:
    result = run(text)
    states = {c.state for c in result.claims} | {r.state for r in result.supply_rows}
    assert states and states <= {"retired", "unknown"}


def test_s2_removal_in_an_earlier_sentence_does_not_leak() -> None:
    (claim,) = run(
        "The project removes nothing at the site; a 1,000 hp electric motor-driven pump is new."
    ).claims
    assert claim.state != "retired"


# ---------------------------------------------------------------- NIT title drive
def test_title_drive_applies_only_to_rows_of_the_titles_own_noun() -> None:
    page = (
        "EUG-3 Electric motor driven compressors\n"
        "EU Point Description Horsepower Const. Date\n"
        "E-1 1 Caterpillar G3606 engine 1775 2020\n"
        "C-9 2 Ariel compressor 1500 2020\n"
    )
    result = run(page)
    by_id = {r.equipment_id: r for r in result.demand_rows + result.supply_rows}
    assert by_id["E-1"].drive == "unknown" and by_id["E-1"].equipment_type == "engine"
    assert by_id["C-9"].drive == "electric"
    ambiguous = run(page.replace("compressors\n", "compressors and engines\n", 1))
    assert all(r.drive == "unknown" for r in ambiguous.demand_rows + ambiguous.supply_rows)


# ---------------------------------------------------------------- S4 / S5
def _pdf() -> bytes:
    return make_pdf(
        [
            [
                "OGS requests authorization to add three (3) 2,500-hp Siemens electric compressor",
                "motors for injection at the station.",
            ]
        ]
    )


def test_s4_provenance_carries_a_bbox_for_every_field() -> None:
    result = extract_permit_document(_pdf(), **K, isolate=False)
    (prov,) = result.provenance.values()
    for name, field in prov["fields"].items():
        x0, top, x1, bottom = field["bbox"]
        assert 0 <= x0 < x1 and 0 <= top < bottom <= 792, name
    # the drive quote wraps onto the second line, but its first character is on line one
    assert prov["fields"]["rating"]["bbox"] == prov["fields"]["count"]["bbox"]


def test_s4_page_text_seam_has_no_geometry_and_says_so() -> None:
    (prov,) = run(
        "It has a 1,000-hp electric motor-driven pump installed in the plant."
    ).provenance.values()
    assert all(f["bbox"] is None for f in prov["fields"].values())


def test_s5_isolated_extraction_works_and_reports_typed_failures() -> None:
    ok = extract_permit_document(_pdf(), **K)
    assert ok.failure is None and [c.count for c in ok.claims] == [3]
    bad = extract_permit_document(b"%PDF-1.4 garbage", **K)
    assert bad.failure is not None and bad.failure.code in {"unreadable", "worker_failed"}


def test_s5_wall_clock_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(text_layer, "_SPAWN_GRACE_SECONDS", 0.0)
    started = time.monotonic()
    result = build_canonical_text(_pdf(), TextLayerLimits(max_seconds=0.0))
    assert isinstance(result, TextLayerFailure) and result.code == "time_budget"
    assert time.monotonic() - started < 10


@pytest.mark.skipif(sys.platform == "win32", reason="RLIMIT_AS does not exist on Windows")
def test_s5_memory_cap_is_a_typed_failure() -> None:
    result = build_canonical_text(_pdf(), TextLayerLimits(max_memory_bytes=64 * 1024 * 1024))
    assert isinstance(result, TextLayerFailure)
    assert result.code in {"memory_limit", "worker_failed", "unreadable"}


# ---------------------------------------------------------------- pathological input
@pytest.mark.parametrize(
    "text",
    [
        "1 hp " * 24000,
        "Table 2-A Rated Capacity\nA1 x " + "1 " * 50000 + "\n",
        "Rated Capacity\nA1 " + "9" * 100000 + " HP",
        "Rated Capacity\nA1 x" + " " * 40000 + "z",
        "greater than " + "1 " * 20000 + "hp engine",
        ("EU Point Description Horsepower Serial Date\n" + "E1 x 1 2020 S\n") * 3000,
    ],
    ids=["hp-dense", "digits", "long-number", "spaces", "threshold", "header-lines"],
)
def test_pathological_text_is_fast(text: str) -> None:
    started = time.perf_counter()
    run(text[:119000])
    assert time.perf_counter() - started < 3.0
