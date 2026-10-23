"""ERCOT monthly Large Load Interconnection Status deck.

The Large Load Integration hub is the stable page. It does not list projects.
The status deck parsed here is the March 13, 2026 TAC PDF, which is a queue
summary. Chart-only pages do not become projects. Later meeting packets checked
on October 23, 2026 did not link a newer status PDF.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import datetime
from typing import Any

import httpx
from pypdf import PdfReader

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.public_source_http import read_public_response

SOURCE_ID = "texas-ercot-large-load-status"
HUB_URL = "https://www.ercot.com/services/rq/large-load-integration"
STATUS_PDF = "https://www.ercot.com/files/docs/2026/03/12/March-TAC-Report.pdf"
ALLOWED_HOSTS = frozenset({"www.ercot.com"})
MAX_RESPONSE_BYTES = 2_000_000
MAX_PDF_PAGES = 30
_TITLE = "Large Load Interconnection Status Update"
_DATE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{1,2}),\s+(20\d{2})\b"
)
_FACTS = (
    ("new_submissions", re.compile(r"\breceived\s+(\d[\d,]*)\s+new\s+LLI\s+submissions", re.I)),
    (
        "new_submission_mw",
        re.compile(r"approximately\s+(\d[\d,]*)\s+MW\s+of\s+new\s+Large\s+Load", re.I),
    ),
    (
        "approved_to_energize_mw",
        re.compile(r"(\d[\d,]*)\s+MW\s+that\s+have\s+received\s+Approval\s+to\s+Energize", re.I),
    ),
    (
        "observed_nonsimultaneous_mw",
        re.compile(r"non-simultaneous monthly peak consumption of\s+(\d[\d,]*)\s+MW", re.I),
    ),
    (
        "observed_simultaneous_mw",
        re.compile(
            r"(?<!non-)simultaneous monthly peak consumption of\s+(\d[\d,]*)\s+MW",
            re.I,
        ),
    ),
)


def parse_status_text(text: str) -> dict[str, Any]:
    collapsed = " ".join(text.split())
    if _TITLE not in collapsed:
        raise SourceParseError("ERCOT status PDF is not the large-load interconnection update")
    found = _DATE.search(collapsed)
    if not found:
        raise SourceParseError("ERCOT status PDF does not state its report date")
    event_date = datetime.strptime(" ".join(found.groups()), "%B %d %Y").date().isoformat()
    facts: dict[str, int] = {}
    for name, pattern in _FACTS:
        match = pattern.search(collapsed)
        if match:
            facts[name] = int(match.group(1).replace(",", ""))
    return {"event_date": event_date, "facts": facts, "title": _TITLE}


def parse_status_pdf(body: bytes) -> dict[str, Any]:
    try:
        reader = PdfReader(io.BytesIO(body))
    except Exception as exc:
        raise SourceParseError("ERCOT status PDF could not be read") from exc
    if reader.is_encrypted or len(reader.pages) > MAX_PDF_PAGES:
        raise SourceParseError("ERCOT status PDF is encrypted or longer than its page bound")
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        raise SourceParseError("ERCOT status PDF has no extractable text")
    return parse_status_text(text)


def _record(parsed: dict[str, Any]) -> dict[str, Any]:
    facts = parsed["facts"]
    row_id = f"ERCOT-LLI-{parsed['event_date']}"
    lines = [
        parsed["title"],
        f"Report date: {parsed['event_date']}",
        "The hub page does not list interconnection projects.",
        "Figures below are queue totals stated in the deck, not a project or a site load.",
    ]
    labels = {
        "new_submissions": "New LLI submissions stated in the deck",
        "new_submission_mw": "Approximate MW of those submissions by 2036",
        "approved_to_energize_mw": "MW approved to energize",
        "observed_nonsimultaneous_mw": "Observed non-simultaneous monthly peak MW",
        "observed_simultaneous_mw": "Observed simultaneous monthly peak MW",
    }
    for key, label in labels.items():
        lines.append(f"{label}: {facts[key]}" if key in facts else f"{label}: not stated")
    semantic = {"event_date": parsed["event_date"], "facts": facts, "pdf": STATUS_PDF}
    return {
        "document_number": row_id,
        "title": f"{parsed['title']} — {parsed['event_date']}",
        "abstract": "\n".join(lines),
        "publication_date": parsed["event_date"],
        "event_date": parsed["event_date"],
        "event_date_label": "ERCOT large-load status deck date",
        "html_url": STATUS_PDF,
        "extraction_location": "ERCOT Large Load Interconnection Status PDF",
        "source_hash": hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "permit": {
            "source_type": SOURCE_ID,
            "row_id": row_id,
            "applicant": "ERCOT Large Load Integration",
            "facility": parsed["title"],
            "permit_numbers": [row_id],
            "permit_type": "ERCOT large-load interconnection status",
            "status": None,
            "description": parsed["title"],
            "location": None,
            "state": None,
            "data_center": False,
            "power_signals": [],
            "stated_queue_totals": facts,
            "document_links": {"status PDF": STATUS_PDF, "LLI hub": HUB_URL},
            "source_fields": {
                "event_date": "date printed on the status deck",
                "stated_queue_totals": "sentences extracted from the deck",
                "location": "not a project site; the deck is a system queue summary",
            },
        },
    }


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != HUB_URL:
        raise SourceParseError("ERCOT status source ID or endpoint is not configured")
    query = source.get("query", {})
    if (
        query.get("max_response_bytes") != MAX_RESPONSE_BYTES
        or query.get("status_pdf") != STATUS_PDF
    ):
        raise SourceParseError("ERCOT status query bounds are invalid")
    http = client or httpx.Client(timeout=60, follow_redirects=False, trust_env=False)
    try:
        _, hub = read_public_response(
            http,
            HUB_URL,
            max_bytes=MAX_RESPONSE_BYTES,
            allowed_media_types={"text/html"},
            allowed_hosts=ALLOWED_HOSTS,
        )
        if b"Large Load Integration" not in hub:
            raise SourceParseError("ERCOT hub page is not the large-load integration page")
        _, pdf = read_public_response(
            http,
            STATUS_PDF,
            max_bytes=MAX_RESPONSE_BYTES,
            allowed_media_types={"application/pdf"},
            allowed_hosts=ALLOWED_HOSTS,
        )
        return [_record(parse_status_pdf(pdf))]
    finally:
        if client is None:
            http.close()
