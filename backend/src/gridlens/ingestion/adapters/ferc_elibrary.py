"""FERC eLibrary: public-reference policy only. This module makes no request.

Finding (2026-11-04, see ``docs/engineering/widen-document-sources-20261103.md``): FERC publishes
no API, feed or documented machine-readable listing for eLibrary. The public site is an
Angular application over an internal JSON service that needs a client token embedded in its own
script; ``www.ferc.gov`` answers a bot challenge. Calling the internal service or the challenged
host is not a documented public path, so GridLens does not fetch FERC eLibrary. What is safe and
useful today is:

* turn a docket identity that a Federal Register notice already states (``CPyy-nnn[-sss]``)
  into a *reference* to the public eLibrary docket-sheet page, for a person to open; and
* refuse, for every future caller, anything that is or looks like CEII or privileged material.

FERC Critical Energy/Electric Infrastructure Information (CEII) and privileged filings must never
be touched. ``reject_nonpublic`` is the one gate; it rejects on URL parts and on free text.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit

HOST = "elibrary.ferc.gov"
DOCKET_SHEET_PATH = "/eLibrary/docketsheet"
FILE_LIST_PATH = "/eLibrary/filelist"
_PUBLIC_PATHS = {DOCKET_SHEET_PATH: {"docket_number"}, FILE_LIST_PATH: {"accession_number"}}
# FERC marks non-public material in several spellings; any hit, anywhere, is a rejection.
_NONPUBLIC = re.compile(
    r"ceii|critical[\s_.-]*(?:energy|electric)|\bprivileged\b|non[\s_.-]*public|\bnonpub"
    r"|\bprivlg|\bpriv[_-]|protected[\s_.-]*material",
    re.I,
)
_CP_DOCKET = re.compile(r"CP(?P<year>\d{2})-(?P<number>\d{1,5})(?:-(?P<suffix>\d{3}))?")
_ACCESSION = re.compile(r"\d{14}")
MAX_REFERENCES = 16


class NonPublicRejected(ValueError):
    """The URL or text is, or may be, CEII or privileged. Never fetch, store or quote it."""


def reject_nonpublic(*values: object) -> None:
    """Raise ``NonPublicRejected`` when any value carries a CEII or privileged marker."""
    for value in values:
        if isinstance(value, str) and _NONPUBLIC.search(value):
            raise NonPublicRejected("FERC non-public marker rejected")


def normalize_cp_docket(text: str) -> str | None:
    """``CP22-123`` or ``CP22-123-000`` in canonical form, else None (not a CP docket)."""
    match = _CP_DOCKET.fullmatch(text.strip().upper())
    if match is None:
        return None
    base = f"CP{match['year']}-{int(match['number'])}"
    return f"{base}-{match['suffix']}" if match["suffix"] else base


def docket_sheet_url(docket: str) -> str:
    """Public eLibrary docket-sheet reference for a CP docket. Not fetched by GridLens."""
    reject_nonpublic(docket)
    normalized = normalize_cp_docket(docket)
    if normalized is None:
        raise ValueError("not a CP docket")
    return f"https://{HOST}{DOCKET_SHEET_PATH}?docket_number={normalized}"


def is_public_elibrary_url(url: str) -> bool:
    """Exact public eLibrary page shapes only; CEII/privileged markers are rejected."""
    try:
        reject_nonpublic(url)
        parts = urlsplit(url)
        query = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
    except (NonPublicRejected, ValueError):
        return False
    allowed = _PUBLIC_PATHS.get(parts.path)
    if (
        parts.scheme != "https"
        or parts.hostname != HOST
        or parts.port not in (None, 443)
        or parts.username
        or parts.password
        or parts.fragment
        or allowed is None
        or len(query) != 1
        or query[0][0] not in allowed
    ):
        return False
    key, value = query[0]
    if key == "docket_number":
        return normalize_cp_docket(value) == value
    return _ACCESSION.fullmatch(value) is not None


def docket_references(docket_context: dict[str, Any] | None) -> list[dict[str, str]]:
    """References derived from a notice's SOURCE_BOUND docket context (CP dockets only).

    ``docket_context`` is ``ferc_equipment_interpretation.source_docket_context`` output. An
    UNKNOWN or conflicting context yields nothing: no docket is guessed.
    """
    if not isinstance(docket_context, dict) or docket_context.get("status") != "SOURCE_BOUND":
        return []
    out: list[dict[str, str]] = []
    for key, level in (("normalized_full", "full"), ("normalized_root", "root_only")):
        value = docket_context.get(key)
        if not isinstance(value, str):
            continue
        normalized = normalize_cp_docket(value)
        if normalized is None:
            continue
        try:
            url = docket_sheet_url(normalized)
        except (ValueError, NonPublicRejected):
            continue
        out.append(
            {
                "docket": normalized,
                "identity_level": level,
                "docket_sheet_url": url,
                "access": "reference_only_not_fetched",
            }
        )
        break  # the full docket when stated, else the root; never both
    return out[:MAX_REFERENCES]
