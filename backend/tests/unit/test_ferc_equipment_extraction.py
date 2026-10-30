import json
import re
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from gridlens.ingestion.parsers.ferc_equipment import extract_ferc_equipment

FIXTURE = Path(__file__).parents[1] / "fixtures/govinfo-complete-notice"


def _real_notice_text() -> tuple[str, str]:
    provenance = json.loads((FIXTURE / "provenance.json").read_text())
    reader = PdfReader(str(FIXTURE / "FR-2024-12869.pdf"))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return text, provenance["official_title"]


def test_extracts_real_notice_as_two_distinct_stations_with_exact_source_spans():
    text, title = _real_notice_text()
    result = extract_ferc_equipment(text, title=title)

    assert len(result.sites) == 2
    first, second = result.sites
    assert (first.facility, first.location) == (
        "Compressor Station 302",
        "Montgomery County, Texas",
    )
    assert (second.facility, second.location) == (
        "Compressor Station 343",
        "Liberty County, Texas",
    )
    assert text[first.heading_start : first.heading_end] == first.heading_quote
    assert text[second.heading_start : second.heading_end] == second.heading_quote

    assert len(first.claims) == 1
    claim = first.claims[0]
    assert (claim.equipment_type, claim.drive, claim.lifecycle_status) == (
        "compressor",
        "electric",
        "proposed",
    )
    assert (claim.count, claim.rating, claim.rating_unit, claim.rating_basis) == (
        1,
        Decimal("18340"),
        "hp",
        "unknown",
    )
    assert claim.source_equipment_id is None
    assert claim.role == "unknown"
    assert text[claim.start : claim.end] == claim.quote
    assert "Install one new electric motor" in claim.quote


def test_uprate_and_rewheel_are_retained_as_unsupported_without_load_totals():
    text, title = _real_notice_text()
    result = extract_ferc_equipment(text, title=title)

    assert [item.activity for item in result.sites[0].unsupported_activities] == [
        "uprate",
        "rewheel",
    ]
    assert [item.activity for item in result.sites[1].unsupported_activities] == ["rewheel"]
    for site in result.sites:
        for item in site.unsupported_activities:
            assert text[item.start : item.end] == item.quote
    assert "1,600 hp each" in result.sites[0].unsupported_activities[0].quote
    assert "total of 3,200 hp" in result.sites[0].unsupported_activities[0].quote
    assert "Units 7, 8 and 9" in re.sub(
        r"\s+", " ", result.sites[0].unsupported_activities[1].quote
    )
    assert "Units 9 and 10" in re.sub(r"\s+", " ", result.sites[1].unsupported_activities[0].quote)
    # Unit uprates and re-wheels are not interpreted as additional equipment claims.
    assert sum(len(site.claims) for site in result.sites) == 1


def test_handles_govinfo_single_line_page_markers_and_keeps_offsets_in_that_text():
    raw, title = _real_notice_text()
    single_line = "[GovInfo PDF page 1] " + re.sub(r"\s+", " ", raw).strip()
    result = extract_ferc_equipment(single_line, title=title)

    assert len(result.sites) == 2
    claim = result.sites[0].claims[0]
    assert single_line[claim.start : claim.end] == claim.quote
    assert "[GovInfo PDF page 1]" in single_line[: claim.start]


def test_rejects_wrong_title_and_unsupported_station_heading_layout():
    text, title = _real_notice_text()
    wrong_title = extract_ferc_equipment(text, title="Unrelated FERC filing")
    assert wrong_title.sites == []
    assert wrong_title.issues

    unsupported_heading = re.sub(
        r"Modifications and Installations at\s+Compressor Station 302",
        "Work at Compressor Station 302",
        text,
    )
    result = extract_ferc_equipment(unsupported_heading, title=title)
    assert result.sites == []
    assert result.issues


def test_reports_title_body_party_variation_as_unresolved_attribution():
    text, title = _real_notice_text()
    result = extract_ferc_equipment(text, title=title)
    assert result.source_party_name == "Natural Gas Pipeline Company of America LLC"
    assert result.source_party_span_source == "title"
    assert result.body_applicant_name == "Natural Gas Company of America LLC"
    assert result.body_applicant_start is not None
    assert result.body_applicant_end is not None
    assert (
        text[result.body_applicant_start : result.body_applicant_end] == result.body_applicant_quote
    )
    assert any("body applicant name" in issue for issue in result.attribution_issues)


def test_installation_clause_fullmatch_rejects_negation_and_trailing_contradictions():
    text, title = _real_notice_text()
    clause_pattern = re.compile(
        r"Install one new electric motor\s+driven compressor unit with a rating of\s+18,340 hp\."
    )
    clause = "Install one new electric motor driven compressor unit with a rating of 18,340 hp."
    for replacement in (
        "Do not " + clause[0].lower() + clause[1:],
        clause[:-1] + ", but installation has been cancelled.",
        clause[:-1] + " and 20,000 hp.",
        clause.replace("electric motor driven", "electric motor driven gas engine driven"),
    ):
        altered = clause_pattern.sub(replacement, text, count=1)
        result = extract_ferc_equipment(altered, title=title)
        assert result.sites
        assert result.sites[0].claims == ()
        assert any(
            "Unresolved activity" in issue or "Negated installation" in issue
            for issue in result.issues
        )


def test_only_bounded_explicit_counts_and_well_formed_rating_lexemes_are_claimed():
    text, title = _real_notice_text()
    clause = "Install one new electric motor driven compressor unit with a rating of 18,340 hp."
    clause_pattern = re.compile(
        r"Install one new electric motor\s+driven compressor unit with a rating of\s+18,340 hp\."
    )
    two_units = re.sub(
        clause_pattern,
        "Install two new electric motor driven compressor units with a rating of 18,340 hp.",
        text,
        count=1,
    )
    result = extract_ferc_equipment(two_units, title=title)
    assert result.sites[0].claims[0].count == 2

    malformed_rating = clause_pattern.sub(clause.replace("18,340", "18,34"), text, count=1)
    result = extract_ferc_equipment(malformed_rating, title=title)
    assert result.sites[0].claims == ()
    assert any("Unresolved activity" in issue for issue in result.issues)

    unsupported_count = clause_pattern.sub(clause.replace("one", "six"), text, count=1)
    result = extract_ferc_equipment(unsupported_count, title=title)
    assert result.sites[0].claims == ()
    assert any("Unresolved activity" in issue for issue in result.issues)


def test_claim_keys_are_stable_across_wrapping_and_offsets():
    raw, title = _real_notice_text()
    normalized = "[GovInfo PDF page 1] " + re.sub(r"\s+", " ", raw).strip()
    raw_claim = extract_ferc_equipment(raw, title=title).sites[0].claims[0]
    normalized_claim = extract_ferc_equipment(normalized, title=title).sites[0].claims[0]
    assert raw_claim.claim_key == normalized_claim.claim_key
    assert raw_claim.id_basis == "derived_semantic_key"
    assert raw_claim.source_equipment_id is None


def test_nonlayout_prose_before_station_heading_or_bullets_abstains():
    text, title = _real_notice_text()
    gap_after_scope = re.sub(
        r"(facilities and activities:)\s*",
        r"\1 The following installations will not proceed. ",
        text,
        count=1,
    )
    result = extract_ferc_equipment(gap_after_scope, title=title)
    assert result.sites == []
    assert result.issues

    after_boilerplate = re.sub(
        r"The Commission mailed a copy",
        "The Commission mailed a copy. The project has been cancelled. "
        "The Commission mailed a copy",
        text,
        count=1,
    )
    result = extract_ferc_equipment(after_boilerplate, title=title)
    assert any("Contradiction statement retained" in issue for issue in result.issues)


def test_duplicate_physical_station_headings_abstain():
    text, title = _real_notice_text()
    duplicate = re.sub(
        r"Modification at Compressor Station\s+343 in\s+Liberty County, Texas:",
        "Modification at Compressor Station 302 in Montgomery County, Texas:",
        text,
        count=1,
    )
    result = extract_ferc_equipment(duplicate, title=title)
    assert result.sites == []
    assert any("Duplicate station headings" in issue for issue in result.issues)


def test_mixed_rewheel_and_new_installation_is_not_hidden_as_rewheel():
    text, title = _real_notice_text()
    mixed = re.sub(
        r"Re-wheel existing electric motor\s+driven compressor Units 9 and 10\.",
        "Re-wheel the existing units; install one new electric motor driven "
        "compressor unit with a rating of 20,000 hp.",
        text,
        count=1,
    )
    result = extract_ferc_equipment(mixed, title=title)
    assert result.sites[1].claims == ()
    assert result.sites[1].unsupported_activities[0].activity == "mixed_activity"
    assert any("Mixed re-wheel and installation" in issue for issue in result.issues)


def test_duplicate_unidentified_installation_assertions_block_ambiguous_deduplication():
    text, title = _real_notice_text()
    clause_pattern = re.compile(
        r"Install one new electric motor\s+driven compressor unit with a rating of\s+18,340 hp\."
    )
    duplicate = clause_pattern.sub(
        "Install one new electric motor driven compressor unit with a rating of 18,340 hp. "
        "• Install one new electric motor driven compressor unit with a rating of 18,340 hp.",
        text,
        count=1,
    )
    result = extract_ferc_equipment(duplicate, title=title)
    assert len(result.sites[0].claims) == 1
    assert any("Repeated unidentified installation assertion" in issue for issue in result.issues)
    assert any(
        item.activity == "duplicate_unidentified_installation"
        for item in result.sites[0].unsupported_activities
    )


def test_title_party_offsets_are_relative_to_original_title_value():
    text, title = _real_notice_text()
    padded_title = f"  {title}  "
    result = extract_ferc_equipment(text, title=padded_title)
    assert result.source_party_quote == result.source_party_name
    assert result.source_party_start is not None
    assert result.source_party_end is not None
    assert (
        padded_title[result.source_party_start : result.source_party_end]
        == result.source_party_quote
    )

    gap_after_heading = re.sub(
        r"(Compressor Station 302 in Montgomery\s+County, Texas:)\s*",
        r"\1 The installation below has been cancelled. ",
        text,
        count=1,
    )
    result = extract_ferc_equipment(gap_after_heading, title=title)
    assert result.sites == []
    assert result.issues
