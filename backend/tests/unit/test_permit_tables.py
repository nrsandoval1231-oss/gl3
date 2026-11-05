from __future__ import annotations

from gridlens.ingestion.parsers.permit_docs.router import route_page
from gridlens.ingestion.parsers.permit_docs.tables import extract_tables
from gridlens.ingestion.parsers.permit_docs.text_layer import CanonicalText

PAGE_A = """EUG-2 Compressor Engines Previously Classified as Grandfathered
Const.
EU Point Description Horsepower Serial #
Date
C1 S1 Cooper GMVA-10 1,350 45756 1963
C2 S2 Cooper GMVA-10 1,350 45755 1963
EUG-7 Existing Generators
Const.
EU Point Description Horsepower Serial #
Date
G1 S5 Caterpillar G379 415 72B694 1978
EUG-9 Glycol Regeneration Heaters
EU Point Description Size (MMBTUH) Construction Date
H5 H5 Glycol regeneration heater 2.4 1997
EUG-10 Storage Tanks
EU Point Description Size (gallons) Construction Date
2-W-6 2-W-6 Waste oil tank 9,020 1998
"""

PAGE_B = """EUG-17: Affected Compressors
Operating Rated Manufacture Serial
Emission Unit Description
Speed Horsepower Date Number
C-0701, Ariel Model KBZ 1,000 RPM 5,200 2022 F66626
C-0801, Ariel Model KBZ 1,000 RPM 5,200 2022 F66698
"""

STITCH_1 = """EUG-5 Engines
EU Point Description Horsepower Serial # Const. Date
E1 S1 Waukesha L7042 588 W1 2010
"""
STITCH_2 = """E2 S2 Waukesha L7042 1,232 W2 2011
E3 S3 Waukesha L7042 750 W3 2012
This paragraph is ordinary prose describing the application in many plain words.
E4 S4 Waukesha L7042 900 W4 2013
"""


def _rows(pages: list[str]):
    canon = CanonicalText.from_page_texts(pages)
    routes = {p.page: route_page(p.text, p.chars) for p in canon.pages}
    return extract_tables(canon, routes)


def test_header_keyed_rows_with_group_type_and_state() -> None:
    rows, _ = _rows([PAGE_A])
    by_id = {r.equipment_id: r for r in rows}
    assert set(by_id) == {"C1", "C2", "G1", "H5"}  # tank gallons column is not a rating
    c1 = by_id["C1"]
    assert (c1.equipment_type, str(c1.rating), c1.unit, c1.count, c1.drive) == (
        "engine",
        "1350",
        "hp",
        None,
        "unknown",
    )
    assert by_id["G1"].equipment_type == "generator" and by_id["G1"].state == "existing"
    assert by_id["H5"].unit == "MMBtu/hr" and str(by_id["H5"].rating) == "2.4"


def test_trailing_columns_come_from_the_header() -> None:
    rows, _ = _rows([PAGE_B])
    assert [(r.equipment_id, str(r.rating)) for r in rows] == [
        ("C-0701", "5200"),
        ("C-0801", "5200"),
    ]
    assert all(r.equipment_type == "compressor" and r.drive == "unknown" for r in rows)
    assert "1,000 RPM" not in {r.evidence["rating"].quote for r in rows}


def test_continuation_rows_inherit_the_previous_header_until_prose() -> None:
    rows, _ = _rows([STITCH_1, STITCH_2])
    assert [r.equipment_id for r in rows] == ["E1", "E2", "E3"]
    assert [r.stitched for r in rows] == [False, True, True]
    assert rows[1].evidence["unit"].page == 1 and rows[1].evidence["rating"].page == 2


def test_threshold_text_is_never_a_row() -> None:
    page = """EU Point Description Horsepower Serial # Const. Date
E1 S1 Engines > 500 hp 500 W1 2010
E2 S2 Engines greater than 500 750 W2 2011
E3 S3 Waukesha engine 600 W3 2012
"""
    rows, issues = _rows([page])
    assert [r.equipment_id for r in rows] == ["E3"]
    assert any("Threshold" in i for i in issues)


def test_row_not_fitting_the_header_shape_is_skipped_not_guessed() -> None:
    page = """EU Point Description Horsepower Serial # Const. Date
E1 S1 Waukesha engine 600 W3
E2 S2 Waukesha engine 600 W3 2012
"""
    rows, _ = _rows([page])
    assert [r.equipment_id for r in rows] == ["E2"]


def test_row_without_a_stated_type_is_reported() -> None:
    page = "EU Point Description Horsepower Serial # Const. Date\nX1 S1 Mystery 600 W3 2012\n"
    rows, issues = _rows([page])
    assert rows == [] and any("No equipment type" in i for i in issues)
