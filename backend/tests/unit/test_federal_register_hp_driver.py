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


def test_two_stations_with_the_same_rating_are_two_rows():
    text = excerpt(
        "At Station A the Project adds one 3,000-hp electric motor driven compressor. "
        "At Station B the Project adds one 3,000-hp electric motor driven compressor."
    )
    rows = extract_notice_hp_driver(text).rows
    assert len(rows) == 2
    assert rows[0]["evidence"]["rating"]["start"] != rows[1]["evidence"]["rating"]["start"]


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


# --------------------------------------------------------------------------- post-rating shape

BULLETS = (
    "Modification at Compressor Station 302 in Montgomery County, Texas: "
    "\ufffd Uprate the existing compressor controls to increase the horsepower (hp) of existing "
    "compressor Units 7 and 8 by 1,600 hp each, for a total of 3,200 hp; "
    "\ufffd Re-wheel existing compressor Units 7, 8 and 9; and "
    "\ufffd Install one new electric motor driven compressor unit with a rating of 18,340 hp. "
    "Modification at Compressor Station 343 in Liberty County, Texas: "
    "\ufffd Re-wheel existing electric motor driven compressor Units 9 and 10."
)


def test_post_rating_bullet_yields_only_the_new_electric_unit():
    text = excerpt(BULLETS)
    row = only(extract_notice_hp_driver(text))
    assert (row["equipment_type"], row["drive"], row["rating"], row["unit"]) == (
        "compressor",
        "electric",
        "18340",
        "hp",
    )
    assert (row["count"], row["state"]) == (1, "proposed")
    assert row["electric_demand_evidenced"] is True
    assert row["evidence"]["rating"]["quote"] == "18,340 hp"
    assert row["evidence"]["drive"]["quote"] == "electric motor driven compressor unit"
    for field in row["evidence"].values():
        assert text[field["start"] : field["end"]] == field["quote"]


def test_uprates_and_rewheels_are_not_new_equipment():
    text = excerpt(
        "Uprate the existing compressor controls to increase the horsepower (hp) of existing "
        "compressor Units 7 and 8 by 1,600 hp each, for a total of 3,200 hp; "
        "Re-wheel existing electric motor driven compressor Units 9 and 10."
    )
    assert extract_notice_hp_driver(text).rows == []


def test_post_rating_without_a_stated_electric_driver_is_not_electric():
    text = excerpt("Install one new gas turbine driven compressor unit with a rating of 20,000 hp.")
    row = only(extract_notice_hp_driver(text))
    assert row["drive"] == "unknown" and row["electric_demand_evidenced"] is False


def test_post_rating_rating_in_another_sentence_is_not_attached():
    text = excerpt(
        "Install one new electric motor driven compressor unit. "
        "The facility is described with a rating of 18,340 hp elsewhere."
    )
    assert extract_notice_hp_driver(text).rows == []


def test_post_rating_removal_is_never_demand():
    text = excerpt("Remove one electric motor driven compressor unit with a rating of 9,000 hp.")
    result = extract_notice_hp_driver(text)
    assert all(not row["electric_demand_evidenced"] for row in result.rows)


# ------------------------------------------------------------- review probes (post-rating)

NO_DEMAND = [
    "install one electric motor driven compressor unit and one gas-fired compressor with a "
    "rating of 10,000 hp",
    "an electric-driven compressor and its gas-fired backup generator with a rating of 1,500 hp",
    "The electric driven compressor will replace the existing compressor with a rating of 4,700 hp",
    "Electric motor driven compressor units with a rating of 500 hp or greater are subject to "
    "review.",
    "Electric motor driven compressor units with a rating of 500 hp and above are subject.",
    "Re-wheel the existing electric-driven compressor with a rating of 4,000 hp",
    "Uprate the electric motor driven compressor unit with a rating of 5,000 hp to 6,000 hp",
    "Install the existing electric motor driven compressor unit with a rating of 5,000 hp",
    "Remove one electric motor driven compressor unit with a rating of 5,000 hp",
    "The existing electric motor driven compressor unit with a rating of 5,000 hp would be "
    "abandoned in place.",
    "The electric motor driven compressor unit with a rating of 5,000 hp would be removed.",
]


@pytest.mark.parametrize("sentence", NO_DEMAND)
def test_post_rating_probes_never_become_demand(sentence):
    result = extract_notice_hp_driver(excerpt(sentence))
    assert [row for row in result.rows if row["role"] == "demand_claim"] == []


def test_post_rating_allows_a_unit_id_and_a_station_name():
    text = excerpt(
        "Install one new electric motor driven compressor unit (Unit 4) at Example (Compressor) "
        "Station with a rating of 9,000 hp."
    )
    row = only(extract_notice_hp_driver(text))
    assert row["electric_demand_evidenced"] is True and row["rating"] == "9000"


def test_post_rating_with_several_units_does_not_claim_a_per_unit_rating():
    text = excerpt(
        "Install two new electric motor driven compressor units with a rating of 18,000 hp."
    )
    row = only(extract_notice_hp_driver(text))
    assert row["count"] == 2
    assert row["rating_basis"] == "unstated_per_unit_or_total"


def test_pre_rating_counts_are_per_unit():
    row = only(
        extract_notice_hp_driver(excerpt("add three (3) 2,500-hp electric compressor motors"))
    )
    assert row["rating_basis"] == "per_unit_as_stated"


def test_install_cue_words_are_not_loosely_matched():
    text = excerpt(
        "Additional construction of one electric motor driven compressor unit "
        "with a rating of 9,000 hp."
    )
    row = only(extract_notice_hp_driver(text))
    assert row["state"] == "unknown" and "state" not in row["evidence"]


def test_spoofed_page_markers_in_pdf_text_cannot_split_pages():
    from gridlens.ingestion.adapters import govinfo_pdf

    pdf = make_pdf(
        [
            [
                TITLE,
                "Text with a spoof [GovInfo PDF page 99] marker in it.",
                "[FR Doc. 2026-12345 Filed 11-02-26; 8:45 am]",
            ]
        ]
    )
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, headers={"content-type": "application/pdf"}, content=pdf)
        )
    )
    (citation,) = govinfo_pdf.retrieve_companion(RECORD, client, hp_driver=True)
    assert "[GovInfo PDF page 99]" not in citation["abstract"]
    assert citation["abstract"].count("[GovInfo PDF page ") == 1


def test_parser_failure_keeps_the_ordinary_evidence(monkeypatch):
    from gridlens.ingestion.adapters import govinfo_pdf
    from gridlens.ingestion.parsers.permit_docs import notice_hp

    def boom(_text):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(notice_hp, "extract_notice_hp_driver", boom)
    pdf = _notice_pdf()
    plain = govinfo_pdf.retrieve_companion(RECORD, _client(pdf))[0]
    flagged = govinfo_pdf.retrieve_companion(RECORD, _client(pdf), hp_driver=True)[0]
    assert flagged["hp_driver"]["abstain"] == {"reason": "parser_error"}
    assert "secret" not in repr(flagged)
    assert {k: v for k, v in flagged.items() if k != "hp_driver"} == plain
