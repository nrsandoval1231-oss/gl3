import pytest

from gridlens.api.app import _csv_cell


@pytest.mark.parametrize("prefix", [" ", "\t", "\r", "\n", "\x00", "\x1b", "\x7f"])
@pytest.mark.parametrize("formula", ["=1+1", "+SUM(A1:A2)", "-1", "@cmd"])
def test_csv_neutralizes_formulas_after_leading_whitespace_or_controls(prefix, formula):
    assert _csv_cell(f"{prefix}{formula}") == f"'{prefix}{formula}"


def test_csv_preserves_non_formula_values_and_unknowns():
    assert _csv_cell("UNKNOWN") == "UNKNOWN"
    assert _csv_cell("https://example.test/source") == "https://example.test/source"
