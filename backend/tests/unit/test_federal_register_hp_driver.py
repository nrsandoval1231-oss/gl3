"""Federal Register notice hp/driver evidence: verified quotes, explicit electric drive only.

No network and no database: the parser reads a bounded excerpt, and the govinfo flag test uses
a synthetic text PDF through an httpx MockTransport.
"""

from __future__ import annotations

import hashlib

import httpx
import pytest
from _permit_pdf import make_pdf

from gridlens.ingestion.adapters import govinfo_pdf
from gridlens.ingestion.adapters.federal_register import SourceParseError, _validate_query
from gridlens.ingestion.parsers.permit_docs.notice_hp import extract_notice_hp_driver
from gridlens.ingestion.registry import load_registry

PAGE = "[GovInfo PDF page {n}] "


def excerpt(*pages: str, first: int = 12) -> str:
    return " ".join(PAGE.format(n=first + i) + text for i, text in enumerate(pages))


def only(result):
    assert len(result.rows) == 1, result.rows
    return result.rows[0]


def test_explicit_electric_motor_is_demand_with_verified_quote_and_page():
    text = excerpt(
        "Compressor Station 9 Project. The Project would add three (3) 2,500-hp Siemens "
        "electric compressor motors and associated piping at the station in Eddy County, "
        "New Mexico."
    )
    row = only(extract_notice_hp_driver(text))
    assert row["electric_demand_evidenced"] is True
    assert row["role"] == "demand_claim"
    assert (row["rating"], row["unit"], row["count"], row["drive"]) == ("2500", "hp", 3, "electric")
    for field in row["evidence"].values():
        assert field["page"] == 12
        assert text[field["start"] : field["end"]] == field["quote"]
    assert "electric compressor motors" in row["evidence"]["drive"]["quote"]


def test_rating_without_a_stated_driver_is_not_electric_demand():
    # The West Edmond trap: the driven compressor's rated hp says nothing about its driver.
    text = excerpt("The station has three 5,200-hp Ariel compressors in service.")
    row = only(extract_notice_hp_driver(text))
    assert row["drive"] == "unknown"
    assert row["electric_demand_evidenced"] is False
    assert row["role"] == "supply_other"
    assert "drive" not in row["evidence"]


def test_rating_beside_a_combustion_driver_is_supply_only():
    text = excerpt("The Project includes one 20,000-hp gas turbine driving a compressor.")
    result = extract_notice_hp_driver(text)
    assert all(not row["electric_demand_evidenced"] for row in result.rows)


def test_prose_motor_and_compressor_ratings_are_separate_rows():
    text = excerpt(
        "FERC staff reviewed one 2,500-hp electric compressor motor. A separate 5,200-hp "
        "compressor is listed in the existing inventory."
    )
    result = extract_notice_hp_driver(text)
    by_rating = {row["rating"]: row for row in result.rows}
    assert by_rating["2500"]["electric_demand_evidenced"] is True
    assert by_rating["5200"]["electric_demand_evidenced"] is False


def test_removed_electric_equipment_is_not_demand():
    text = excerpt("The Project would remove one 1,000-hp electric motor from service.")
    result = extract_notice_hp_driver(text)
    assert all(not row["electric_demand_evidenced"] for row in result.rows)


def test_thresholds_and_ranges_are_not_ratings():
    text = excerpt("Units greater than 1,000-hp electric motors are not covered by this notice.")
    assert extract_notice_hp_driver(text).rows == []


def test_no_equipment_phrase_abstains_instead_of_reporting_zero():
    result = extract_notice_hp_driver(excerpt("The Commission issued an environmental assessment."))
    assert result.rows == []
    assert result.abstain is not None
    assert "unknown is not zero" in result.abstain["note"]


@pytest.mark.parametrize("bad", ["", "   ", "no page marker 2,500-hp electric motor"])
def test_missing_text_or_markers_abstain(bad):
    result = extract_notice_hp_driver(bad)
    assert result.rows == []
    assert result.abstain is not None


def test_oversize_excerpt_abstains():
    result = extract_notice_hp_driver(excerpt("x" * 130_000))
    assert result.abstain is not None and result.rows == []


def test_multi_page_quotes_cite_the_right_pdf_page():
    text = excerpt(
        "Background text without equipment.",
        "The Project would install one 3,000-hp electric motor driven compressor.",
        first=40,
    )
    row = only(extract_notice_hp_driver(text))
    assert {field["page"] for field in row["evidence"].values()} == {41}
    for field in row["evidence"].values():
        assert text[field["start"] : field["end"]] == field["quote"]


def test_repeated_mention_is_one_unit():
    text = excerpt(
        "The Project adds one 3,000-hp electric motor driven compressor. "
        "As noted, the one 3,000-hp electric motor driven compressor is new."
    )
    assert len(extract_notice_hp_driver(text).rows) == 1


# --------------------------------------------------------------------------- flag plumbing

TITLE = "Example Pipeline Company, LLC; Notice of Availability of the Environmental Assessment"
NUMBER = "2026-12345"
URL = f"https://www.govinfo.gov/content/pkg/FR-2026-11-02/pdf/{NUMBER}.pdf"
RECORD = {
    "document_number": NUMBER,
    "title": TITLE,
    "publication_date": "2026-11-02",
    "html_url": "https://www.federalregister.gov/d/2026-12345",
    "pdf_url": URL,
}


def _notice_pdf() -> bytes:
    return make_pdf(
        [
            [
                TITLE,
                "The Project would add one (1) 3,000-hp electric motor driven compressor.",
                "[FR Doc. 2026-12345 Filed 11-02-26; 8:45 am]",
            ]
        ]
    )


def _client(body: bytes) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_companion_is_unchanged_without_the_flag():
    pdf = _notice_pdf()
    default = govinfo_pdf.retrieve_companion(RECORD, _client(pdf))
    assert len(default) == 1
    assert "hp_driver" not in default[0]
    assert default[0]["content_hash"] == hashlib.sha256(pdf).hexdigest()


def test_companion_adds_evidence_only_behind_the_flag():
    pdf = _notice_pdf()
    off = govinfo_pdf.retrieve_companion(RECORD, _client(pdf))[0]
    on = govinfo_pdf.retrieve_companion(RECORD, _client(pdf), hp_driver=True)[0]
    assert {k: v for k, v in on.items() if k != "hp_driver"} == off
    block = on["hp_driver"]
    assert block["version"].startswith("fr-notice-hp-driver")
    row = only_dict(block["rows"])
    assert row["electric_demand_evidenced"] is True
    for field in row["evidence"].values():
        assert on["abstract"][field["start"] : field["end"]] == field["quote"]


def only_dict(rows):
    assert len(rows) == 1
    return rows[0]


def _eis_source(**extra):
    source = next(row for row in load_registry() if row["id"] == "federal-register-eis")
    query = {**source["query"], **extra}
    return {**source, "query": query}


def test_registry_ships_with_the_flag_absent_or_false():
    source = next(row for row in load_registry() if row["id"] == "federal-register-eis")
    assert source["query"].get("hp_driver_evidence", False) is False


def test_flag_must_be_a_boolean_on_the_reviewed_source_only():
    _validate_query(_eis_source(hp_driver_evidence=True))
    for bad in ("yes", 1, None):
        with pytest.raises(SourceParseError):
            _validate_query(_eis_source(hp_driver_evidence=bad))
    other = {**_eis_source(hp_driver_evidence=True), "id": "some-other-source"}
    with pytest.raises(SourceParseError):
        _validate_query(other)
