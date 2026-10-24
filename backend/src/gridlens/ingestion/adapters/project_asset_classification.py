"""Source-native project asset classifications independent of achieved milestones."""

from __future__ import annotations

import re

TDLR_TABS_SOURCE = "texas-tdlr-tabs-data-centers"
_DATA_CENTER = re.compile(r"\bdata\s*cent(?:er|re)s?\b|\bhyperscale\b", re.IGNORECASE)
_NEGATED_DATA_CENTER = re.compile(
    r"\b(?:not|no longer|isn't|is not)\s+(?:a\s+)?data\s*cent(?:er|re)\b",
    re.IGNORECASE,
)


def classify_project_asset(source_id: str, title: str, abstract: str | None) -> str | None:
    """Return an asset type stated by the source record, never a lifecycle event.

    TDLR TABS is a project-registration source. Its explicit data-center project
    name/scope supports industry filtering even when the registration does not
    establish that construction or another milestone has started.
    """
    if source_id != TDLR_TABS_SOURCE:
        return None
    text = f"{title}\n{abstract or ''}"
    if _NEGATED_DATA_CENTER.search(text) or not _DATA_CENTER.search(text):
        return None
    return "data_center"
