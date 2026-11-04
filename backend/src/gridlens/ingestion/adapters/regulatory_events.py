"""Dated, evidence-backed regulatory event feed (no network).

Events live in ``config/regulatory/events.v1.json``. Each carries an official source URL, a date,
a verbatim quote and a fixed effect from a closed vocabulary; the quote was read on the official
page on ``verified_on`` (2026-11-04 for all four shipped events: the Governor's August 3 audit
order, the September 14 TWDB directive, the September 21 letter to TCEQ, and TCEQ's October 19
reply). The reader makes no request, so nothing here can drift from the file, and adding or
changing an event is a reviewed change.

The model is deterministic and small: event -> affected scope -> status label, through a fixed
table. ``pause_issuance`` gives "pending — paused" for a filing in the event's scope that is
explicitly a data-center project and still pending; ``audit_required`` gives "pending — audit
required". Nothing is inferred beyond the quote: a filing that is not explicitly a data-center
project gets no label (unknown), an event with a conditional effect gives no label, no end date is
assumed (only a later ``lift_pause`` event in the same scope clears a pause), and a missing permit
is never read as a decision.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.sector_common import candidate_record, clean, require_source

SOURCE_ID = "regulatory-event-feed"
ENDPOINT = "https://gov.texas.gov/news/"
EVENTS_PATH = Path(__file__).resolve().parents[5] / "config" / "regulatory" / "events.v1.json"
OFFICIAL_HOSTS = frozenset({"gov.texas.gov", "www.tceq.texas.gov"})
MAX_EVENTS = 100
# effect -> (status label for matching pending filings, or None)
EFFECT_LABELS: dict[str, str | None] = {
    "pause_issuance": "pending — paused",
    "lift_pause": None,
    "audit_required": "pending — audit required",
    "conditional_ineligibility": None,
}
_SCOPE_KEYS = {"state", "agency", "subject", "instrument"}
_EVENT_KEYS = {"id", "date", "issuer", "source_url", "quote", "effect", "scope", "verified_on"}


def valid_query(source: dict[str, Any]) -> bool:
    return (
        source.get("id") == SOURCE_ID
        and source.get("endpoint") == ENDPOINT
        and source.get("cadence_hours") == 24
        and source.get("family") == "structured-government"
        and source.get("query") == {"max_events": MAX_EVENTS}
    )


def validate_event(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict) or set(event) != _EVENT_KEYS:
        raise SourceParseError("Regulatory event has unexpected fields")
    for key in ("id", "issuer", "source_url", "quote", "effect"):
        if not isinstance(event[key], str) or not event[key].strip():
            raise SourceParseError("Regulatory event field is empty")
    try:
        date.fromisoformat(event["date"])
        date.fromisoformat(event["verified_on"])
    except (TypeError, ValueError) as exc:
        raise SourceParseError("Regulatory event date is invalid") from exc
    parts = urlsplit(event["source_url"])
    if (
        parts.scheme != "https"
        or parts.hostname not in OFFICIAL_HOSTS
        or parts.username
        or parts.port
    ):
        raise SourceParseError("Regulatory event source is not an official https URL")
    if event["effect"] not in EFFECT_LABELS:
        raise SourceParseError("Regulatory event effect is not in the closed vocabulary")
    scope = event["scope"]
    if (
        not isinstance(scope, dict)
        or set(scope) != _SCOPE_KEYS
        or not all(isinstance(v, str) and v for v in scope.values())
    ):
        raise SourceParseError("Regulatory event scope is invalid")
    if len(event["quote"]) > 600 or "\n" in event["quote"]:
        raise SourceParseError("Regulatory event quote is too long or multi-line")
    return event


def load_events(path: Path = EVENTS_PATH) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SourceParseError("Regulatory event file is unreadable") from exc
    events = raw.get("events") if isinstance(raw, dict) and raw.get("version") == 1 else None
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise SourceParseError("Regulatory event file is invalid")
    checked = [validate_event(item) for item in events]
    if len({e["id"] for e in checked}) != len(checked):
        raise SourceParseError("Regulatory event IDs are not unique")
    return sorted(checked, key=lambda e: (e["date"], e["id"]))


def status_for(
    filing: dict[str, Any], events: list[dict[str, Any]], as_of: date
) -> dict[str, Any] | None:
    """Status label for one filing, or None (unknown). ``filing`` keys: ``state``, ``agency``,
    ``instrument``, ``data_center_explicit`` (the filing itself says so), ``pending``."""
    if filing.get("data_center_explicit") is not True or filing.get("pending") is not True:
        return None
    relevant = [
        e
        for e in events
        if date.fromisoformat(e["date"]) <= as_of
        and e["scope"]["subject"] == "data_center_projects"
        and e["scope"]["state"] == filing.get("state")
        and e["scope"]["agency"] == filing.get("agency")
        and e["scope"]["instrument"] == filing.get("instrument")
        and e["effect"] in ("pause_issuance", "lift_pause", "audit_required")
    ]
    if not relevant:
        return None
    latest = max(relevant, key=lambda e: (e["date"], e["id"]))
    label = EFFECT_LABELS[latest["effect"]]
    if label is None:
        return None
    return {
        "label": label,
        "event_id": latest["id"],
        "event_date": latest["date"],
        "source_url": latest["source_url"],
        "quote": latest["quote"],
    }


def build_record(event: dict[str, Any]) -> dict[str, Any]:
    scope = event["scope"]
    label = EFFECT_LABELS[event["effect"]]
    lines = [
        f"{event['issuer']}, {event['date']}: {event['effect'].replace('_', ' ')}",
        f'Quote: "{event["quote"]}"',
        f"Scope: {scope['state']} / {scope['agency']} / {scope['subject']} / {scope['instrument']}",
        "Status label for matching pending filings: " + (label or "none (no label is inferred)"),
        f"Source: {event['source_url']} (read {event['verified_on']})",
        "A dated official statement; it is not a decision on any single filing.",
    ]
    return candidate_record(
        source_id=SOURCE_ID,
        row_id=event["id"],
        title=f"{event['issuer']} {event['date']} — {event['effect'].replace('_', ' ')}",
        abstract_lines=lines,
        url=event["source_url"],
        extraction_location="verbatim quote on the official source page",
        semantic={"event": event},
        publication_date=event["date"],
        event_date=event["date"],
        event_date_label="Date of the official statement",
        permit={
            "applicant": event["issuer"],
            "facility": event["id"],
            "status": clean(label, 60),
            "location": None,
            "state": scope["state"],
            "permit_type": "Regulatory event",
            "regulatory_event": {
                "effect": event["effect"],
                "scope": scope,
                "label": label,
                "quote": event["quote"],
                "verified_on": event["verified_on"],
            },
            "source_fields": {"event_date": "date of the official statement"},
        },
    )


def retrieve(
    source: dict[str, Any], client: httpx.Client | None = None, *, path: Path = EVENTS_PATH
) -> list[dict[str, Any]]:
    require_source(source, SOURCE_ID, ENDPOINT)
    if not valid_query(source):
        raise SourceParseError("Regulatory event feed configuration is invalid")
    return [build_record(event) for event in load_events(path)]
