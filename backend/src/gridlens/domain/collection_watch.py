"""Deterministic topic matching for the collection-only cannabis news watch."""

from __future__ import annotations

from sqlalchemy import and_, func, or_

_CULTIVATION = (
    ("cultivat", "cultivation-related"),
    ("grow facility", "grow facility"),
    ("grow operation", "grow operation"),
    ("grower", "grower"),
)
_LICENSING = (("licens", "licensing"),)
_FACILITY = (("facility", "facility"), ("facilities", "facilities"), ("greenhouse", "greenhouse"))


def _joined_text(title_column, excerpt_column):
    return func.concat(title_column, " ", excerpt_column)


def candidate_expression(title_column, excerpt_column):
    """Build SQL watch paging criteria from the same tokens used for display."""
    text_column = _joined_text(title_column, excerpt_column)

    def any_term(terms: tuple[tuple[str, str], ...]):
        return or_(*(text_column.ilike(f"%{term}%") for term, _ in terms))

    return or_(any_term(_CULTIVATION), and_(any_term(_LICENSING), any_term(_FACILITY)))


def matched_terms(title: str, excerpt: str | None) -> list[str]:
    """Return the same substring matches used by the SQL predicate."""
    text = f"{title} {excerpt or ''}".casefold()
    cultivation = [label for term, label in _CULTIVATION if term in text]
    licensing = [label for term, label in _LICENSING if term in text]
    facility = [label for term, label in _FACILITY if term in text]
    if not (cultivation or (licensing and facility)):
        return []
    return list(dict.fromkeys([*cultivation, *licensing, *facility]))
