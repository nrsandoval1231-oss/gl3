from decimal import Decimal, localcontext
from pathlib import Path

from gridlens.domain.equipment_demand import EquipmentClaim
from gridlens.ingestion.parsers.equipment import extract_equipment_claims


def test_extracts_explicit_equipment_row_with_verbatim_offsets():
    text = (
        "SOURCE EXAMPLE — synthetic public-style schedule; not live data.\n"
        "Company: Prairie Example LLC\nFacility: Mock Permian Station\nAs of: 2026-04-01\n"
        "Equipment ID: C-101 | Type: compressor | Drive: electric | Rating: 1,200 hp "
        "mechanical output | Count: 2 | Operating: 1 | State: proposed | Role: duty | "
        "Efficiency: 0.90\n"
    )
    result = extract_equipment_claims(text)

    assert result.company == "Prairie Example LLC"
    assert result.facility == "Mock Permian Station"
    assert result.truncated is False
    assert len(result.claims) == 1
    claim = result.claims[0]
    assert isinstance(claim, EquipmentClaim)
    assert claim.equipment_id == "C-101"
    assert claim.equipment_type == "compressor"
    assert claim.drive == "electric"
    assert claim.rating == Decimal("1200")
    assert claim.unit == "hp"
    assert claim.rating_basis == "mechanical_output"
    assert claim.count == 2
    assert claim.operating_count == 1
    assert claim.state == "proposed"
    assert claim.role == "duty"
    assert claim.efficiency == Decimal("0.90")
    assert text[claim.start : claim.end] == claim.quote
    assert claim.quote.startswith("Equipment ID: C-101")


def test_synthetic_schedule_fixture_is_explicit_and_keeps_unknowns():
    path = Path(__file__).parents[1] / "fixtures/equipment/synthetic_compression_schedule.txt"
    text = path.read_text()
    result = extract_equipment_claims(text)
    assert len(result.claims) == 3
    assert result.issues == []
    assert result.claims[0].drive == "electric"
    assert result.claims[1].drive == "gas_engine"
    assert result.claims[2].drive == "unknown"
    assert result.claims[2].rating_basis == "unknown"
    assert all(text[c.start : c.end] == c.quote for c in result.claims)


def test_keeps_drive_unknown_and_does_not_borrow_nearby_gas_drive():
    text = (
        "ID: P-1 | Type: pump | Drive: gas engine | Rating: 500 hp mechanical output\n"
        "ID: P-2 | Type: pump | Drive: unknown | Rating: 500 hp mechanical output\n"
    )
    claims = extract_equipment_claims(text).claims
    assert [claim.drive for claim in claims] == ["gas_engine", "unknown"]


def test_negation_and_existing_standby_are_scoped_to_each_row():
    text = (
        "ID: C-1 | Type: compressor | Drive: electric | Rating: 2 MW electrical input | "
        "State: existing | Role: standby\n"
        "ID: C-2 | Type: compressor | Drive: not electric (gas engine) | "
        "Rating: 900 hp mechanical output | State: proposed | Role: duty\n"
        "ID: C-3 | Type: compressor | Drive: electric | Rating: 600 kW electrical input | "
        "State: proposed | Role: duty\n"
    )
    claims = extract_equipment_claims(text).claims
    assert [(c.equipment_id, c.drive, c.state, c.role) for c in claims] == [
        ("C-1", "electric", "existing", "standby"),
        ("C-2", "gas_engine", "proposed", "duty"),
        ("C-3", "electric", "proposed", "duty"),
    ]


def test_conflicting_duplicate_ids_and_ratings_are_preserved():
    text = (
        "ID: K-7 | Type: compressor | Drive: electric | Rating: 700 kW electrical input\n"
        "ID: K-7 | Type: compressor | Drive: electric | Rating: 900 kW electrical input\n"
    )
    claims = extract_equipment_claims(text).claims
    assert [claim.rating for claim in claims] == [Decimal("700"), Decimal("900")]
    assert any("Conflicting claims" in issue for issue in extract_equipment_claims(text).issues)


def test_exact_duplicate_lines_deduplicate_and_unsupported_prose_abstains():
    row = "ID: P-8 | Type: pump | Drive: diesel engine | Rating: 50 hp mechanical output"
    result = extract_equipment_claims(f"{row}\n{row}\nOur facility has a large pump package.\n")
    assert len(result.claims) == 1
    assert "large pump package" not in " ".join(c.quote for c in result.claims)


def test_truncates_oversized_input_with_explicit_issue_and_no_partial_claims():
    text = "ID: C-1 | Type: compressor | Drive: electric | Rating: 500 kW electrical input\n" + (
        "x" * 130_000
    )
    result = extract_equipment_claims(text)
    assert result.truncated is True
    assert result.claims == []
    assert result.issues


def test_ambiguous_company_headers_are_omitted_with_issue():
    result = extract_equipment_claims("Company: A\nCompany: B\n")
    assert result.company is None
    assert any("Multiple company headers" in issue for issue in result.issues)


def test_ambiguous_drive_and_trailing_rating_text_abstain():
    rows = [
        "ID: X-1 | Type: pump | Drive: electric or gas engine | Rating: 10 kW electrical input",
        "ID: X-2 | Type: pump | Drive: electric | Rating: 10 hp mechanical output and 20 hp",
    ]
    result = extract_equipment_claims("\n".join(rows))
    assert result.claims == []
    assert len(result.issues) == 2


def test_basis_labels_are_conservative_by_unit_and_efficiency_percent_is_normalized():
    rows = [
        "ID: X-1 | Type: pump | Drive: electric | Rating: 100 hp nameplate",
        "ID: X-2 | Type: pump | Drive: electric | Rating: 100 kW nameplate",
        "ID: X-3 | Type: pump | Drive: electric | Rating: 100 kW electrical input | "
        "Efficiency: 95% | PF: 0.95%",
    ]
    claims = extract_equipment_claims("\n".join(rows)).claims
    assert [claim.rating_basis for claim in claims] == ["unknown", "unknown", "electrical_input"]
    assert claims[2].efficiency == Decimal("0.95")
    assert claims[2].power_factor == Decimal("0.0095")


def test_malformed_negative_count_is_reported_instead_of_becoming_unknown():
    result = extract_equipment_claims(
        "ID: X-4 | Type: pump | Drive: electric | Rating: 100 kW electrical input | Count: -1"
    )
    assert result.claims == []
    assert result.issues


def test_overlong_equipment_row_abstains_and_marks_truncated():
    row = "ID: X-5 | Type: pump | Drive: electric | Rating: 100 kW electrical input"
    text = row + " | note: " + ("x" * 1_300)
    result = extract_equipment_claims(text)
    assert result.truncated is True
    assert result.claims == []
    assert result.issues


def test_explicit_effective_dates_and_as_of_date_are_validated():
    row = (
        "ID: X-6 | Type: compressor | Drive: diesel engine | Rating: 400 hp mechanical output"
        " | Effective from: 2025-01-01 | Effective until: 2025-12-31"
    )
    result = extract_equipment_claims("As of: 2025-06-01\n" + row)
    assert result.as_of == "2025-06-01"
    assert result.claims[0].effective_from.isoformat() == "2025-01-01"
    assert result.claims[0].effective_until.isoformat() == "2025-12-31"

    invalid = extract_equipment_claims("As of: yesterday\n" + row)
    assert invalid.as_of is None
    assert any("Invalid as-of date" in issue for issue in invalid.issues)


def test_contradictory_electric_drive_annotation_is_rejected():
    result = extract_equipment_claims(
        "ID: X-7 | Type: pump | Drive: electric (gas engine) | Rating: 100 kW electrical input"
    )
    assert result.claims == []
    assert any("Contradictory drive" in issue for issue in result.issues)


def test_explicit_unknown_state_is_preserved():
    result = extract_equipment_claims(
        "ID: X-8 | Type: compressor | Drive: unknown | Rating: 50 hp | State: unknown"
    )
    assert len(result.claims) == 1
    assert result.claims[0].state == "unknown"


def test_rating_rejects_malformed_thousands_separators_but_accepts_grouped_values():
    invalid_rows = [
        "ID: X-9 | Type: pump | Drive: electric | Rating: 1,5 kW electrical input",
        "ID: X-10 | Type: pump | Drive: electric | Rating: 1,,000 kW electrical input",
    ]
    invalid = extract_equipment_claims("\n".join(invalid_rows))
    assert invalid.claims == []
    assert len(invalid.issues) == 2

    valid = extract_equipment_claims(
        "ID: X-11 | Type: pump | Drive: electric | Rating: 1,200 kW electrical input"
    )
    assert valid.claims[0].rating == Decimal("1200")


def test_percentage_conversion_is_independent_of_decimal_context():
    row = (
        "ID: X-12 | Type: pump | Drive: electric | Rating: 1.234567 kW electrical input"
        " | Efficiency: 95%"
    )
    with localcontext() as context:
        context.prec = 2
        claim = extract_equipment_claims(row).claims[0]
    assert claim.rating == Decimal("1.234567")
    assert claim.efficiency == Decimal("0.95")


def test_malformed_explicit_as_of_date_is_reported():
    result = extract_equipment_claims("As of: tomorrow\n")
    assert result.as_of is None
    assert any("Invalid as-of date" in issue for issue in result.issues)


def test_mixed_valid_row_and_structured_rows_missing_id_or_rating_report_issues():
    valid = "ID: M-1 | Type: pump | Drive: electric | Rating: 300 kW electrical input"
    missing_id = "Type: pump | Drive: electric | Rating: 200 kW electrical input"
    missing_rating = "ID: M-2 | Type: compressor | Drive: gas engine"
    missing_id_label_colon = (
        "Equipment ID M-3 | Type: compressor | Drive: diesel engine | "
        "Rating: 100 hp mechanical output"
    )
    result = extract_equipment_claims(
        "Company: Example LLC\nFacility: Example Station\n"
        + "\n".join((valid, missing_id, missing_rating, missing_id_label_colon))
    )
    assert [claim.equipment_id for claim in result.claims] == ["M-1"]
    assert len(result.issues) == 3
    assert any("Structured equipment row lacks an ID" in issue for issue in result.issues)
    assert any("Unrecognized or ambiguous equipment row" in issue for issue in result.issues)


def test_mixed_valid_row_and_unstructured_equipment_prose_reports_incomplete_extraction():
    row = "ID: M-4 | Type: pump | Drive: electric | Rating: 100 kW electrical input"
    result = extract_equipment_claims(
        "Company: Pumping Example LLC\n"
        "Facility: Compressor Station 4\n"
        "As of: 2025-01-01\n" + row + "\nAlso install a 200 kW electric pump."
    )
    assert [claim.equipment_id for claim in result.claims] == ["M-4"]
    assert any("Unstructured equipment-like text" in issue for issue in result.issues)
