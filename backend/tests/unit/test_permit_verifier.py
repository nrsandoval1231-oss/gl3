from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from gridlens.ingestion.parsers.permit_docs.models import ExtractedRow, FieldEvidence
from gridlens.ingestion.parsers.permit_docs.narrative import extract_narrative
from gridlens.ingestion.parsers.permit_docs.text_layer import CanonicalText
from gridlens.ingestion.parsers.permit_docs.verifier import verify_rows

TEXT = (
    "OGS requests authorization to add three (3) 2,500-hp Siemens electric compressor\n"
    "motors and associated equipment for the facility."
)


def _row() -> tuple[CanonicalText, ExtractedRow]:
    canon = CanonicalText.from_page_texts([TEXT])
    rows, _ = extract_narrative(canon, {1: "narrative"})
    assert len(rows) == 1
    return canon, rows[0]


def _with(row: ExtractedRow, name: str, **changes: object) -> ExtractedRow:
    evidence = dict(row.evidence)
    evidence[name] = replace(evidence[name], **changes)  # type: ignore[arg-type]
    return replace(row, evidence=evidence)


def test_genuine_row_verifies_across_a_line_wrap() -> None:
    canon, row = _row()
    # the drive quote spans the line break: whitespace differences are tolerated
    assert "\n" in row.evidence["drive"].quote or "compressor" in row.evidence["drive"].quote
    report = verify_rows([row], canon)
    assert report.verified == [row] and report.rejected == []


@pytest.mark.parametrize(
    ("name", "changes", "reason"),
    [
        ("rating", {"value": "2600"}, "rating"),
        ("unit", {"value": "kW"}, "unit"),
        ("count", {"value": "4"}, "count"),
        ("drive", {"value": "gas_engine"}, "drive"),
        ("type", {"value": "pump"}, "type"),
        ("rating", {"quote": "2,501-hp"}, "quote does not match"),
        ("rating", {"start": 0, "end": 5, "quote": "OGS r"}, "rating"),
        ("state", {"value": "existing"}, "state"),
    ],
)
def test_mismatched_values_or_spans_are_rejected_and_reported(
    name: str, changes: dict[str, object], reason: str
) -> None:
    canon, row = _row()
    bad = _with(row, name, **changes)
    if name == "rating":
        bad = replace(bad, rating=Decimal(bad.evidence["rating"].value))
    report = verify_rows([bad], canon)
    assert report.verified == [] and len(report.rejected) == 1
    assert reason in report.rejected[0][1]


def test_fuzzy_quotes_are_not_accepted() -> None:
    canon, row = _row()
    fuzzy = _with(row, "type", quote="compressor motor")  # not at that span, different text
    assert verify_rows([fuzzy], canon).verified == []


def test_span_must_stay_on_its_page() -> None:
    canon = CanonicalText.from_page_texts([TEXT, TEXT])
    rows, _ = extract_narrative(canon, {1: "narrative", 2: "narrative"})
    moved = _with(rows[0], "rating", page=2)
    assert verify_rows([moved], canon).verified == []


def test_asserted_value_without_evidence_is_rejected() -> None:
    canon, row = _row()
    evidence = {k: v for k, v in row.evidence.items() if k != "drive"}
    assert "drive" in verify_rows([replace(row, evidence=evidence)], canon).rejected[0][1]


def test_unknown_value_with_stray_evidence_is_rejected() -> None:
    canon, row = _row()
    stray = replace(row, drive="unknown")
    assert verify_rows([stray], canon).verified == []


def test_synthetic_id_must_match_its_span() -> None:
    canon, row = _row()
    forged = _with(row, "id", value="N1-999")
    forged = replace(forged, equipment_id="N1-999")
    assert verify_rows([forged], canon).verified == []


def test_field_evidence_dataclass_is_frozen() -> None:
    ev = FieldEvidence("id", "A", "A", 0, 1, 1)
    with pytest.raises(AttributeError):
        ev.value = "B"  # type: ignore[misc]
