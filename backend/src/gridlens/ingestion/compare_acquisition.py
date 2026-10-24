"""Operator-run, immutable five-case native versus Firecrawl comparison.

Native captures are supplied by the existing source adapters. This module only
validates those captures and optionally requests one exact eligible HTML URL.
It never writes canonical project or evidence state.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select

from gridlens.ingestion.adapters.buying_chain_public import validate_public_url

CAPTURE_FIELDS = {
    "case_id",
    "source_id",
    "external_id",
    "capture_id",
    "capture_hash",
    "capture_kind",
    "evidence_id",
    "evidence_content_hash",
    "url",
    "content_type",
    "title",
    "text",
    "observed_at",
    "content_hash",
}
REQUIRED_CAPTURE_FIELDS = CAPTURE_FIELDS - {
    "evidence_id",
    "evidence_content_hash",
    "external_id",
}
MAX_CAPTURE_BYTES = 30_000_000
MAX_CASES = 5
FIRECRAWL_MAX_TEXT_CHARS = 30_000
HTML_TYPES = ("text/html", "application/xhtml+xml")


def load_manifest(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(cases, list) or len(cases) != MAX_CASES:
        raise ValueError("Comparison manifest must contain exactly five cases")
    ids = [case.get("case_id") for case in cases if isinstance(case, dict)]
    if len(ids) != MAX_CASES or len(set(ids)) != MAX_CASES:
        raise ValueError("Comparison case identifiers must be unique")
    for case in cases:
        _exact_url(case.get("url"))
        if not all(
            isinstance(case.get(key), str) and case[key].strip()
            for key in ("case_id", "source_id", "media_type")
        ):
            raise ValueError("Manifest case identity is incomplete")
        if case.get("identity_kind") not in {"native_record_id", "capture_label"}:
            raise ValueError("Manifest must distinguish publisher IDs from capture labels")
        if case.get("identity_kind") == "native_record_id" and not isinstance(
            case.get("external_id"), str
        ):
            raise ValueError("Native record identity requires its publisher external ID")
        if (
            type(case.get("max_bytes")) is not int
            or not 1 <= case["max_bytes"] <= MAX_CAPTURE_BYTES
        ):
            raise ValueError("Manifest source byte bound is invalid")
    return data


def _exact_url(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Exact source URL is required")
    url = validate_public_url(value)
    if url != value or urlsplit(url).fragment:
        raise ValueError("Source URL must be an exact credential-free HTTPS URL")
    return url


def validate_capture(case: dict[str, Any], capture: dict[str, Any]) -> dict[str, Any]:
    if not REQUIRED_CAPTURE_FIELDS.issubset(capture):
        raise ValueError("Native capture is missing required immutable capture fields")
    if any(
        capture.get(key) != case.get(key) for key in ("case_id", "source_id", "external_id", "url")
    ):
        raise ValueError("Native capture identity or exact URL does not match manifest")
    if (
        capture.get("content_type", "").split(";", 1)[0].strip().lower()
        != case.get("media_type", "").split(";", 1)[0].strip().lower()
    ):
        raise ValueError("Native capture media type does not match manifest")
    text = capture.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Native capture must contain complete nonempty bounded text")
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_CAPTURE_BYTES:
        raise ValueError("Native capture exceeds byte bound; truncation is prohibited")
    raw_size = capture.get("raw_size_bytes")
    if raw_size is not None and (
        type(raw_size) is not int or not 0 <= raw_size <= case["max_bytes"]
    ):
        raise ValueError("Raw capture exceeds the existing source adapter byte bound")
    if not isinstance(capture.get("title"), str) or not capture["title"].strip():
        raise ValueError("Native capture title is required")
    if not isinstance(capture.get("capture_id"), str) or not capture["capture_id"].strip():
        raise ValueError("Native capture identifier is required")
    if capture.get("capture_kind") not in {"COMPLETE_DOCUMENT", "RECORD_EXCERPT"}:
        raise ValueError(
            "Native capture kind must distinguish complete document from record excerpt"
        )
    if capture.get("evidence_id") is not None and (
        not isinstance(capture["evidence_id"], str)
        or not re.fullmatch(r"[0-9a-fA-F-]{36}", capture["evidence_id"])
    ):
        raise ValueError("Evidence ID must be a UUID when supplied")
    if capture.get("evidence_content_hash") is not None and not re.fullmatch(
        r"[0-9a-f]{64}", str(capture["evidence_content_hash"])
    ):
        raise ValueError("Evidence content hash must be a SHA-256 digest when supplied")
    if not isinstance(capture.get("observed_at"), str):
        raise ValueError("Native capture observation timestamp is required")
    observed = datetime.fromisoformat(capture["observed_at"].replace("Z", "+00:00"))
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("Native capture timestamp must include timezone")
    digest = hashlib.sha256(encoded).hexdigest()
    if capture.get("content_hash") != digest or capture.get("capture_hash") != digest:
        raise ValueError("Native capture text hash does not match content")
    if capture.get("text_sha256") is not None and capture["text_sha256"] != digest:
        raise ValueError("Native text SHA-256 does not match captured text")
    content_type = capture.get("content_type")
    if not isinstance(content_type, str) or not content_type.strip():
        raise ValueError("Native capture content type is required")
    return {
        **capture,
        "observed_at": observed.astimezone(UTC).isoformat(),
        "eligible_html": content_type.split(";", 1)[0].strip().lower() in HTML_TYPES,
    }


def normalize_capture(case: dict[str, Any], capture: dict[str, Any]) -> dict[str, Any]:
    """Accept the source receipt envelope while keeping raw and text hashes distinct."""
    normalized = dict(capture)
    normalized.setdefault("url", normalized.get("exact_url"))
    normalized.setdefault("observed_at", normalized.get("observed_utc"))
    normalized.setdefault("content_type", normalized.get("content_type"))
    normalized.setdefault("content_hash", normalized.get("text_sha256"))
    normalized.setdefault("capture_hash", normalized.get("text_sha256"))
    normalized.setdefault("title", case.get("title") or case["case_id"])
    normalized.setdefault("evidence_id", None)
    normalized.setdefault("evidence_content_hash", None)
    scope = normalized.get("capture_kind", normalized.get("scope"))
    normalized["capture_kind"] = {
        "complete": "COMPLETE_DOCUMENT",
        "complete_document": "COMPLETE_DOCUMENT",
        "record": "RECORD_EXCERPT",
        "record_excerpt": "RECORD_EXCERPT",
    }.get(str(scope).casefold(), scope)
    normalized["capture_id"] = normalized.get("capture_id", normalized.get("id"))
    incomplete = (
        normalized.get("capture_kind") == "INCOMPLETE" or normalized.get("status") == "INCOMPLETE"
    )
    if (
        not incomplete
        and normalized.get("text") is None
        and isinstance(normalized.get("extracted_text_path"), str)
    ):
        text_path = Path(normalized["extracted_text_path"])
        if text_path.is_file():
            normalized["text"] = text_path.read_text(encoding="utf-8")
    if not incomplete and normalized.get("text") is not None:
        normalized.setdefault(
            "content_hash", hashlib.sha256(normalized["text"].encode("utf-8")).hexdigest()
        )
        normalized.setdefault(
            "capture_hash", hashlib.sha256(normalized["text"].encode("utf-8")).hexdigest()
        )
    allowed = CAPTURE_FIELDS | {
        "raw_sha256",
        "raw_path",
        "text_sha256",
        "extraction_method",
        "parsed_facts",
        "latency_ms",
        "http_status",
        "raw_size_bytes",
        "limits",
        "status",
        "error",
        "error_code",
        "eligible_html",
    }
    return {key: value for key, value in normalized.items() if key in allowed}


def extract_fields(text: str, terms: list[str]) -> dict[str, list[str]]:
    """Return only exact matched text spans, never inferred values."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    recovered: dict[str, list[str]] = {}
    for term in terms:
        if not isinstance(term, str) or not term.strip():
            continue
        matches = [line for line in lines if re.search(re.escape(term), line, re.IGNORECASE)]
        recovered[term] = matches
    return recovered


def _fact_values(value: Any, tokens: list[str], path: str = "") -> list[tuple[str, str]]:
    if not tokens:
        return [(path, value)] if isinstance(value, str) and value.strip() else []
    token, *tail = tokens
    if token == "[]":
        if not isinstance(value, list):
            return []
        return [
            pair
            for index, item in enumerate(value)
            for pair in _fact_values(item, tail, f"{path}[{index}]")
        ]
    if token.endswith("[]"):
        key = token[:-2]
        items = value.get(key) if isinstance(value, dict) else None
        if not isinstance(items, list):
            return []
        return [
            pair
            for index, item in enumerate(items)
            for pair in _fact_values(item, tail, f"{path}.{key}[{index}]")
        ]
    next_value = value.get(token) if isinstance(value, dict) else None
    return _fact_values(next_value, tail, f"{path}.{token}" if path else token)


def recover_facts(text: str, parsed_facts: Any, paths: list[str]) -> dict[str, Any]:
    """Check selected adapter fact values against literal source text."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    facts = []
    for path in paths:
        for fact_path, value in _fact_values(parsed_facts, path.split(".")):
            matches = [line for line in lines if value.casefold() in line.casefold()]
            facts.append(
                {
                    "path": fact_path,
                    "value": value,
                    "status": "MATCH" if matches else "UNVERIFIED",
                    "matched_text": matches,
                }
            )
    matches_count = sum(item["status"] == "MATCH" for item in facts)
    return {
        "status": "EVALUATED" if facts else "NOT_EVALUATED",
        "matches": matches_count,
        "denominator": len(facts),
        "facts": facts,
    }


def compare_case(
    case: dict[str, Any], capture: dict[str, Any], *, firecrawl: dict[str, Any] | None = None
) -> dict[str, Any]:
    native = validate_capture(case, capture)
    row = {
        "case_id": case["case_id"],
        "native": {
            "status": "CAPTURED",
            "source_id": native["source_id"],
            "external_id": native["external_id"],
            "capture_id": native["capture_id"],
            "capture_kind": native["capture_kind"],
            "evidence_id": native.get("evidence_id"),
            "evidence_content_hash": native.get("evidence_content_hash"),
            "url": native["url"],
            "content_hash": native["content_hash"],
            "capture_hash": native["capture_hash"],
            "raw_sha256": native.get("raw_sha256"),
            "raw_path": native.get("raw_path"),
            "raw_size_bytes": native.get("raw_size_bytes"),
            "extraction_method": native.get("extraction_method"),
            "parsed_facts": native.get("parsed_facts"),
            "http_status": native.get("http_status"),
            "observed_at": native["observed_at"],
            "latency_ms": native.get("latency_ms"),
            "content_type": native["content_type"],
            "title": native["title"],
            "text": native["text"],
            "field_recovery": extract_fields(native["text"], case.get("recovery_terms", [])),
            "fact_recovery": recover_facts(
                native["text"], native.get("parsed_facts"), case.get("recovery_fact_paths", [])
            ),
        },
        "firecrawl": {
            "status": "NOT_NEEDED" if not native["eligible_html"] else "NOT_RUN",
            "logical_call_id": None,
            "latency_ms": None,
            "actual_cost_usd": None,
            "reserved_cost_usd": None,
        },
    }
    if firecrawl is not None:
        if firecrawl.get("status") == "COMPLETED" and isinstance(firecrawl.get("text"), str):
            firecrawl["fact_recovery"] = recover_facts(
                firecrawl["text"], native.get("parsed_facts"), case.get("recovery_fact_paths", [])
            )
        elif firecrawl.get("status") == "UNSUPPORTED":
            firecrawl["fact_recovery"] = {
                "status": "UNSUPPORTED",
                "matches": 0,
                "denominator": 0,
                "facts": [],
            }
        row["firecrawl"] = firecrawl
    return row


def scrape_html(case: dict[str, Any], *, api_key: str, cost_cap_usd: Decimal) -> dict[str, Any]:
    """One ledger-backed exact HTML scrape. Cached/unknown logical calls never repeat."""
    from uuid import UUID

    from gridlens.ingestion.adapters.pursuit_acquisition import extract_public_document
    from gridlens.integrations.legacy_calls import perform_legacy_call
    from gridlens.persistence.database import SessionLocal
    from gridlens.persistence.models import LogicalCall
    from gridlens.settings import settings

    if not case.get("eligible_html"):
        return {
            "status": "NOT_NEEDED",
            "logical_call_id": None,
            "latency_ms": 0,
            "actual_cost_usd": None,
            "reserved_cost_usd": "0",
        }
    if isinstance(case.get("text"), str) and len(case["text"]) > FIRECRAWL_MAX_TEXT_CHARS:
        return {
            "status": "NOT_NEEDED",
            "disposition": "SKIPPED_NATIVE_TEXT_EXCEEDS_PROVIDER_BOUND",
            "logical_call_id": None,
            "latency_ms": 0,
            "actual_cost_usd": None,
            "reserved_cost_usd": "0",
        }
    if (
        not api_key
        or settings.firecrawl_scrape_cost_usd is None
        or not cost_cap_usd.is_finite()
        or cost_cap_usd <= 0
    ):
        return {
            "status": "INCOMPLETE",
            "error_code": "MISSING_PROVIDER_OR_COST_CONFIGURATION",
            "logical_call_id": None,
            "latency_ms": 0,
            "actual_cost_usd": None,
            "reserved_cost_usd": None,
        }
    unit_cost = settings.firecrawl_scrape_cost_usd
    if unit_cost > Decimal(str(cost_cap_usd)):
        return {
            "status": "INCOMPLETE",
            "error_code": "COST_CAP_TOO_LOW",
            "logical_call_id": None,
            "latency_ms": 0,
            "actual_cost_usd": None,
            "reserved_cost_usd": None,
        }
    url = _exact_url(case["url"])
    task_key = f"m2-acquisition:{case['case_id']}:{hashlib.sha256(url.encode()).hexdigest()}"
    started = time.monotonic()

    def invoke():
        document = extract_public_document(
            url, api_key=api_key, deadline=time.monotonic() + 30, before_request=lambda _: None
        )
        return (
            {
                "url": document.url,
                "title": document.title,
                "text": document.text,
                "observed_at": document.observed_at.isoformat(),
                "content_hash": hashlib.sha256(document.text.encode()).hexdigest(),
                "content_type": "text/html",
            },
            None,
            None,
        )

    try:
        with SessionLocal() as session:
            prior = session.scalar(
                select(LogicalCall).where(
                    LogicalCall.task_type == "FIRECRAWL_SCRAPE_V2", LogicalCall.task_key == task_key
                )
            )
        result = perform_legacy_call(
            task_type="FIRECRAWL_SCRAPE_V2",
            task_key=task_key,
            payload={"url": url, "formats": ["markdown"], "max_bytes": 750_000},
            source_id=None,
            project_id=None,
            job_id=None,
            worker_id=None,
            fence_token=0,
            existing_call_id=prior.id if prior is not None and prior.status != "NOT_SENT" else None,
            invoke=invoke,
        )
    except Exception as exc:
        # The shared ledger retains sent calls as unknown; do not turn errors into retries.
        with SessionLocal() as session:
            logical = session.scalar(
                select(LogicalCall).where(
                    LogicalCall.task_type == "FIRECRAWL_SCRAPE_V2", LogicalCall.task_key == task_key
                )
            )
        return {
            "status": "UNKNOWN"
            if type(exc).__name__ == "LegacyCallUnknown"
            or logical
            and logical.status in {"SENT_OUTCOME_UNKNOWN", "UNKNOWN"}
            else "INCOMPLETE",
            "error_code": str(exc)
            if type(exc).__name__ in {"LegacyCallUnknown", "LegacyCallBlocked"}
            else type(exc).__name__,
            "logical_call_id": str(logical.id) if logical else None,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "actual_cost_usd": str(logical.actual_cost_usd)
            if logical and logical.actual_cost_usd is not None
            else None,
            "reserved_cost_usd": str(logical.max_cost_usd)
            if logical and logical.max_cost_usd is not None
            else str(unit_cost),
        }
    with SessionLocal() as session:
        logical = session.get(LogicalCall, UUID(str(result.logical_call_id)))
        actual = (
            str(logical.actual_cost_usd)
            if logical and logical.actual_cost_usd is not None
            else None
        )
        reserved = (
            str(logical.max_cost_usd)
            if logical and logical.max_cost_usd is not None
            else str(unit_cost)
        )
    payload = result.result
    if not isinstance(payload.get("text"), str) or payload.get("url") != url:
        return {
            "status": "INCOMPLETE",
            "error_code": "INVALID_CACHED_RESPONSE",
            "logical_call_id": str(result.logical_call_id),
            "latency_ms": round((time.monotonic() - started) * 1000),
            "actual_cost_usd": actual,
            "reserved_cost_usd": reserved,
        }
    return {
        "status": "COMPLETED",
        "logical_call_id": str(result.logical_call_id),
        "latency_ms": round((time.monotonic() - started) * 1000),
        "actual_cost_usd": actual,
        "reserved_cost_usd": reserved,
        "cached": result.cached,
        "url": url,
        "content_hash": payload.get("content_hash"),
        "observed_at": payload.get("observed_at"),
        "title": payload.get("title"),
        "text": payload["text"],
        "field_recovery": extract_fields(payload["text"], case.get("recovery_terms", [])),
    }


def report_complete(rows: list[dict[str, Any]]) -> bool:
    if len(rows) != MAX_CASES or len({row.get("case_id") for row in rows}) != MAX_CASES:
        return False
    return all(
        row.get("native", {}).get("status") == "CAPTURED"
        and row.get("firecrawl", {}).get("status") in {"COMPLETED", "NOT_NEEDED", "UNSUPPORTED"}
        for row in rows
    )
