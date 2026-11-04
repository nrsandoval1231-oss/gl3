from __future__ import annotations

import pytest

from gridlens.ingestion.parsers.permit_docs.router import route_page

TABLE = (
    "EUG-6 Compressor Engines\n"
    "EU Point Description Horsepower Serial # Const. Date\n"
    "C5 S10 Cooper GMVH-12 2,600 46290 1998"
)
KW_TABLE = "Equipment list for the site follows.\nEU Description kW\nA1 Genset 500 installed"
NARRATIVE = "The station adds three (3) 2,500-hp Siemens electric compressor motors to the site."


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (TABLE, "table"),
        (KW_TABLE, "table"),
        (NARRATIVE, "narrative"),
        (
            "Emissions of NOx are calculated from AP-42 factors for all units on site today.",
            "irrelevant",
        ),
        (
            "The rule applies to engines greater than 500 hp at a major source of emissions.",
            "irrelevant",
        ),
        (
            "RBLC Entries for NOx from Simple Cycle Turbines\nGeneric Power 190MW turbine design",
            "irrelevant",
        ),
        ("Fig. 3", "scan"),
        ("", "scan"),
    ],
)
def test_route(text: str, expected: str) -> None:
    assert route_page(text) == expected


def test_scan_threshold_uses_character_count() -> None:
    assert route_page("x" * 60, chars=10) == "scan"
