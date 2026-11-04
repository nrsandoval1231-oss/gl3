from __future__ import annotations

import pytest

from gridlens.ingestion.parsers.permit_docs.narrative import extract_narrative
from gridlens.ingestion.parsers.permit_docs.router import route_page
from gridlens.ingestion.parsers.permit_docs.text_layer import CanonicalText


def _rows(text: str):
    canon = CanonicalText.from_page_texts([text.ljust(60)])
    routes = {1: "narrative"}
    rows, issues = extract_narrative(canon, routes)  # type: ignore[arg-type]
    return rows


def test_west_edmond_electric_motors_with_count_and_state() -> None:
    rows = _rows(
        "OGS requests authorization to add three (3) 2,500-hp Siemens electric compressor "
        "motors and the three (3) associated Ariel KBZ compressors, one (1) 2,500-hp "
        "Waukesha 9394 GSI emergency generator, and fugitive components."
    )
    motors, generator = rows
    assert (motors.equipment_type, motors.drive, str(motors.rating), motors.unit) == (
        "compressor",
        "electric",
        "2500",
        "hp",
    )
    assert motors.count == 3 and motors.state == "proposed"
    assert motors.link_hint == "Ariel"
    assert (generator.equipment_type, generator.drive, generator.count) == (
        "generator",
        "unknown",
        1,
    )


@pytest.mark.parametrize(
    "phrase",
    [
        "two (2) 4,000-hp electrically driven compressors",
        "two (2) 4,000-hp electric-driven compressors",
        "two (2) 4,000-hp electric motor-driven compressors",
    ],
)
def test_electric_driver_phrases(phrase: str) -> None:
    (row,) = _rows(f"The station will use {phrase} for injection.")
    assert row.drive == "electric" and row.equipment_type == "compressor" and row.count == 2


def test_combustion_rows_are_not_electric() -> None:
    rows = _rows(
        "The site has two (2) 1,350-hp Cooper GMVA-10 compressor engines and one (1) 1,599-hp "
        "Solar Saturn turbine and a 4,000-hp reciprocating engine."
    )
    assert [(r.equipment_type, r.drive) for r in rows] == [
        ("engine", "unknown"),
        ("turbine", "unknown"),
        ("engine", "unknown"),
    ]
    assert rows[0].count == 2


def test_no_electric_wording_means_unknown_drive_and_no_inference() -> None:
    (row,) = _rows("Three (3) 5,200-hp Ariel compressors are listed for the project.")
    assert row.equipment_type == "compressor" and row.drive == "unknown"


def test_negated_electric_is_not_electric() -> None:
    rows = _rows("The plan has two (2) 900-hp non-electric compressors in service.")
    assert all(r.drive != "electric" for r in rows)


@pytest.mark.parametrize(
    "text",
    [
        "Engines greater than 500 hp at a major source must comply with Subpart ZZZZ.",
        "Units rated >500 hp compressors are subject to the rule.",
        "Engines of 250 hp or greater compressors apply.",
        "Compressors between 500 and 1,000 hp compressors are covered.",
        "Rated 500 to 1,000 hp engines are affected.",
        "Emission factors of 0.5 g/hp-hr for engines were used.",
        "Fuel use of 7,000 Btu/hp-hr engine heat rate applies.",
    ],
)
def test_threshold_and_non_rating_text_is_excluded(text: str) -> None:
    assert _rows(text) == []


def test_state_requires_a_close_unambiguous_cue() -> None:
    far = _rows(
        "After the proposed construction, the station will consist of two (2) 1,350-hp Cooper "
        "GMVA-10 compressor engines."
    )
    assert far[0].state == "unknown"
    existing = _rows("The existing two (2) 1,350-hp Cooper compressor engines remain.")
    assert existing[0].state == "existing"


def test_router_sends_narrative_pages_here() -> None:
    assert route_page("OGS will add three (3) 2,500-hp Siemens electric compressor motors.") == (
        "narrative"
    )


def test_bare_number_word_and_mmbtu_heater() -> None:
    engines, heater = _rows(
        "Two 2,000-hp Cooper-Bessemer GMVH-10 compressor engines (E1 and E2) are located "
        "here, with an associated 2.40-MMBTUH glycol regeneration heater."
    )
    assert (engines.equipment_type, engines.count, str(engines.rating)) == ("engine", 2, "2000")
    assert (heater.equipment_type, heater.unit, str(heater.rating), heater.count) == (
        "heater",
        "MMBtu/hr",
        "2.40",
        None,
    )
