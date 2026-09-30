"""Conservative Taylor planning-event interpretation for data-center Signals."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

_DATA_CENTER = re.compile(r"\b(?:data cent(?:er|re)|server campus|hyperscale)\b", re.I)
_PLANNING_EVENT = re.compile(
    r"\b(?:planning\s+(?:and|&)\s+zoning|planning commission|zoning|development agreement|"
    r"site plan|employment center plan|public hearing|land use application)\b",
    re.I,
)
_WITHDRAWN = re.compile(r"\bwithdrawn\b", re.I)
_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_STREET_ADDRESS = re.compile(r"\b\d{1,6}\s+(?:CR|FM|Hwy|Highway)\s+[\w-]+\b", re.I)


def interpret_taylor_planning(record: dict[str, Any]) -> dict[str, str | None] | None:
    """Return a Signal only for a named, dated data-center planning event.

    Withdrawn notices remain observations but do not create or cancel a need.
    The result deliberately contains no MW, supply, buyer, or project aliases.
    """
    title = str(record.get("title") or "")
    body = str(record.get("abstract") or "")
    category = record.get("category")
    source_geography = record.get("source_geography")
    publication_date = record.get("publication_date")
    if (
        category not in {"Development News", "Development Notices"}
        or source_geography != "Taylor, Texas"
        or _WITHDRAWN.search(f"{title} {body}")
        or not _DATA_CENTER.search(f"{title} {body}")
        or not _PLANNING_EVENT.search(f"{title} {body}")
        or not isinstance(publication_date, str)
        or not _DATE.fullmatch(publication_date)
    ):
        return None
    date.fromisoformat(publication_date)
    project_match = re.search(r"\bProject\s+([A-Z0-9][A-Za-z0-9&'’-]*)\b", title, re.I)
    site_sentence = next(
        (
            sentence
            for sentence in re.split(r"(?<=[.!?])\s+", body)
            if _DATA_CENTER.search(sentence)
            and (
                _STREET_ADDRESS.search(sentence)
                or re.search(r"\bTaylor(?:,\s*Williamson County)?(?:,\s*Texas)?\b", sentence, re.I)
            )
        ),
        None,
    )
    if project_match is None or site_sentence is None:
        return None
    project_name = title
    site_evidence = _STREET_ADDRESS.search(site_sentence)
    site_label = site_evidence.group(0) if site_evidence else "Taylor, Williamson County, Texas"
    return {
        "name": project_name,
        "activity_key": "facility-expansion",
        "rationale": (
            f"Taylor {category.lower()} records a dated data-center planning event for "
            f"{project_name} at source-stated site {site_label}; investigate whether a future "
            "activity-specific power need exists."
        ),
        "location": "Taylor, Texas",
    }
