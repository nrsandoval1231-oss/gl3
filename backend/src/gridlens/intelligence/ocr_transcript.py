"""Validation and bounded storage shape for unverified scanned-PDF transcripts."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from uuid import UUID

MAX_TRANSCRIPT_RESULT_BYTES = 65_536
_PUBLIC_RESULT_KEYS = {
    "schema_version",
    "status",
    "authority",
    "evidence_id",
    "original_document_hash",
    "source_url",
    "page_count",
    "pages",
    "transcript_hash",
    "method",
    "version",
    "actual_model",
    "provider_response_id",
    "logical_call_id",
    "preflight_counted_input_tokens",
    "usage",
}


def public_ocr_transcript(result: Any) -> dict[str, Any] | None:
    """Project only the text transcript and nonbinary metadata to API history."""
    if not isinstance(result, dict) or not _PUBLIC_RESULT_KEYS.issuperset(result):
        return None
    pages = result.get("pages")
    page_count = result.get("page_count")
    if (
        result.get("status") != "OCR_UNVERIFIED"
        or type(page_count) is not int
        or not 1 <= page_count <= 5
        or not isinstance(pages, list)
        or len(pages) != page_count
    ):
        return None
    safe_pages = []
    for index, page in enumerate(pages, start=1):
        if (
            not isinstance(page, dict)
            or page.get("page") != index
            or type(page.get("page")) is not int
            or not isinstance(page.get("text"), str)
        ):
            return None
        safe_pages.append({"page": index, "text": page["text"]})
    safe = {key: result[key] for key in _PUBLIC_RESULT_KEYS - {"pages", "usage"} if key in result}
    safe["pages"] = safe_pages
    usage = result.get("usage")
    if isinstance(usage, dict):
        safe["usage"] = {
            key: usage[key]
            for key in (
                "input_tokens",
                "output_tokens",
                "counted_input_tokens_are_billable_usage",
                "actual_cost_usd",
            )
            if key in usage
        }
    encoded = json.dumps(safe, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return safe if len(encoded) <= MAX_TRANSCRIPT_RESULT_BYTES else None


def public_ocr_grounded_result(result: Any) -> dict[str, Any] | None:
    """Expose bounded follow-on candidates while retaining their OCR uncertainty."""
    if (
        not isinstance(result, dict)
        or result.get("status") != "OCR_UNVERIFIED"
        or result.get("authority") != "ADVISORY_ONLY"
        or result.get("canonical_promotion") != "PROHIBITED"
        or result.get("independent_source_check") != "REQUIRED"
        or not isinstance(result.get("candidates"), list)
        or len(result["candidates"]) > 20
    ):
        return None
    allowed = {
        "field",
        "value",
        "unit",
        "original_value",
        "original_unit",
        "precision",
        "date_precision",
        "evidence_id",
        "evidence_hash",
        "quote",
        "section",
        "page",
        "span_start",
        "span_end",
        "publisher",
        "published_date",
        "speaker",
        "speaker_organization",
        "speaker_role",
        "support",
        "status",
        "verification_status",
        "source_url",
        "source_id",
    }
    candidates: list[dict[str, Any]] = []
    for item in result["candidates"]:
        if not isinstance(item, dict) or item.get("verification_status") != "OCR_UNVERIFIED":
            return None
        candidate = {key: value for key, value in item.items() if key in allowed}
        if (
            not isinstance(candidate.get("quote"), str)
            or len(candidate["quote"]) > 600
            or not isinstance(candidate.get("evidence_hash"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", candidate["evidence_hash"])
        ):
            return None
        candidates.append(candidate)
    reference = result.get("ocr_transcript_reference")
    if (
        not isinstance(reference, dict)
        or not isinstance(reference.get("logical_call_id"), str)
        or not isinstance(reference.get("transcript_hash"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", reference["transcript_hash"])
        or reference.get("version") != "scanned-pdf-transcript-v1"
    ):
        return None
    list_limits = {
        "hypotheses": 8,
        "contradictions": 8,
        "unresolved_questions": 12,
        "candidate_orgs": 8,
        "proposed_queries": 8,
    }
    for key, limit in list_limits.items():
        value = result.get(key)
        if (
            not isinstance(value, list)
            or len(value) > limit
            or any(not isinstance(text, str) or not 1 <= len(text) <= 500 for text in value)
        ):
            return None
    usage = result.get("usage")
    safe_usage = None
    if isinstance(usage, dict):
        safe_usage = {
            key: usage[key]
            for key in (
                "input_tokens",
                "output_tokens",
                "counted_input_tokens_are_billable_usage",
                "actual_cost_usd",
            )
            if key in usage
        }
        if (
            any(
                safe_usage.get(key) is not None
                and (type(safe_usage[key]) is not int or safe_usage[key] < 0)
                for key in ("input_tokens", "output_tokens")
            )
            or safe_usage.get("counted_input_tokens_are_billable_usage") is not False
        ):
            return None
    pursuit = result.get("suggested_pursuit")
    if pursuit is not None and (
        not isinstance(pursuit, dict)
        or set(pursuit) != {"title", "rationale"}
        or any(
            not isinstance(pursuit[key], str) or not 1 <= len(pursuit[key]) <= 400
            for key in pursuit
        )
    ):
        return None
    safe = {
        "schema_version": result.get("schema_version"),
        "candidates": candidates,
        "hypotheses": result.get("hypotheses", []),
        "contradictions": result.get("contradictions", []),
        "unresolved_questions": result.get("unresolved_questions", []),
        "candidate_orgs": result.get("candidate_orgs", []),
        "proposed_queries": result.get("proposed_queries", []),
        "suggested_pursuit": result.get("suggested_pursuit"),
        "status": "OCR_UNVERIFIED",
        "authority": "ADVISORY_ONLY",
        "canonical_promotion": "PROHIBITED",
        "independent_source_check": "REQUIRED",
        "ocr_transcript_reference": {
            "logical_call_id": reference.get("logical_call_id"),
            "transcript_hash": reference["transcript_hash"],
            "version": reference.get("version"),
        },
        "actual_model": result.get("actual_model"),
        "provider_response_id": result.get("provider_response_id"),
        "usage": safe_usage,
    }
    encoded = json.dumps(safe, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return safe if len(encoded) <= MAX_TRANSCRIPT_RESULT_BYTES else None


def validate_ocr_transcript(
    output: Any,
    *,
    expected_pages: int,
    evidence_id: UUID | str,
    original_document_hash: str,
    source_url: str,
    logical_call_id: UUID | str,
    actual_model: str,
    provider_response_id: str | None,
) -> dict[str, Any]:
    if not isinstance(output, dict) or set(output) != {"pages"}:
        raise ValueError("OCR result keys mismatch")
    pages = output["pages"]
    if not isinstance(pages, list) or len(pages) != expected_pages:
        raise ValueError("OCR must return every expected page")
    validated: list[dict[str, Any]] = []
    for expected_number, page in enumerate(pages, start=1):
        if (
            not isinstance(page, dict)
            or set(page) != {"page", "text"}
            or type(page["page"]) is not int
            or page["page"] != expected_number
            or not isinstance(page["text"], str)
        ):
            raise ValueError("OCR page sequence or shape is invalid")
        validated.append(page)
    transcript_bytes = json.dumps(
        validated, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    if len(transcript_bytes) > MAX_TRANSCRIPT_RESULT_BYTES:
        raise ValueError("OCR transcript exceeds the durable result limit")
    transcript_hash = hashlib.sha256(transcript_bytes).hexdigest()
    result = {
        "schema_version": "scanned-pdf-transcript-v1",
        "status": "OCR_UNVERIFIED",
        "authority": "ADVISORY_ONLY",
        "evidence_id": str(evidence_id),
        "original_document_hash": original_document_hash,
        "source_url": source_url,
        "page_count": expected_pages,
        "pages": validated,
        "transcript_hash": transcript_hash,
        "method": "OpenAI Responses inline PDF input",
        "version": "scanned-pdf-transcript-v1",
        "actual_model": actual_model,
        "provider_response_id": provider_response_id,
        "logical_call_id": str(logical_call_id),
    }
    encoded_result = json.dumps(
        result, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    if len(encoded_result) > MAX_TRANSCRIPT_RESULT_BYTES:
        raise ValueError("OCR logical-call result exceeds the durable result limit")
    return result
