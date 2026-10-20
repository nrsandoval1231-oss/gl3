"""Allowlisted public-acquisition diagnostics, safe across process and DB boundaries.

Never persist arbitrary exception messages, request URLs, response bodies or headers.
Only reviewed constant parser messages, bounded HTTP statuses and named stages survive.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx

_PARSE_CODES = {
    "Boston permit rows have duplicate identity or bad order": "boston_row_order",
    "Boston permit row lacks stable identity or site fields": "boston_row_identity",
    "Boston issue-date pages ended before the declared count": "boston_incomplete_page",
    "Chicago permit row key is not numeric": "chicago_row_key",
    "Permit segment rows are out of stable key order": "permit_row_order",
    "Permit segment row did not advance its keyset": "permit_cursor_not_advanced",
    "Permit segment response schema changed": "permit_schema_changed",
    "TCEQ listing row lacks applicant, facility, permit or project": "tceq_row_identity",
    "TCEQ link is outside the official host": "tceq_unapproved_link",
    "TCEQ listing heading changed or page is not the NSR listing": "tceq_listing_identity",
    "TCEQ listing application row is missing a required link": "tceq_missing_link",
    "TCEQ eCID row lacks a validated application project path": "tceq_ecid_project_path",
    "TCEQ notice and application project identities conflict": "tceq_identity_conflict",
    "TCEQ listing has duplicate project identity": "tceq_duplicate_project",
    "TCEQ notice link is outside the official notice path": "tceq_unapproved_notice",
    "TCEQ application link is outside the official application path": "tceq_unapproved_application",
    "TCEQ listing application row has an invalid column count": "tceq_row_schema",
    "CEQAnet search page lacks its document count": "ceqanet_missing_count",
    "CEQAnet result row does not have five columns": "ceqanet_row_schema",
    "CEQAnet document link contains an invalid control character": "ceqanet_link_control",
    "CEQAnet document link contains a traversal segment": "ceqanet_link_traversal",
    "CEQAnet result row lacks a document link or received date": "ceqanet_row_link_or_date",
    "CEQAnet result count exceeds its bound": "ceqanet_result_limit",
    "CEQAnet document page lacks its SCH number or title": "ceqanet_document_identity",
    "CEQAnet source ID or endpoint is not configured": "ceqanet_configuration",
    "CEQAnet query bounds are invalid": "ceqanet_query_bounds",
    "CEQAnet document bound is invalid": "ceqanet_document_bounds",
    "CEQAnet document link is outside the approved official path": "ceqanet_unapproved_link",
    "CEQAnet single-result documents exceed the run bound": "ceqanet_document_limit",
    "CEQAnet single-result document identity or date is invalid": "ceqanet_single_identity",
    "CEQAnet single-result document escaped its search window or type": "ceqanet_single_scope",
    "CEQAnet titled document exceeds remaining fetch budget": "ceqanet_document_limit",
    "CEQAnet acquisition requires redirects disabled": "ceqanet_redirect_configuration",
    "Georgia source response exceeds its byte limit": "georgia_response_limit",
    "Georgia source Content-Length is malformed": "georgia_content_length",
    "Georgia public-comment deadline is malformed": "georgia_deadline",
    "Georgia document link is outside the approved EPD path": "georgia_unapproved_link",
    "Georgia document count exceeded the run bound": "georgia_document_limit",
    "Georgia retrieval exceeded total run byte limit": "georgia_run_byte_limit",
    "Georgia EPD document is not a PDF": "georgia_document_not_pdf",
    "Georgia PDF is encrypted": "georgia_pdf_encrypted",
    "Georgia PDF is empty": "georgia_pdf_empty",
    "Georgia PDF does not bind the listed facility/application to its site location": (
        "georgia_document_site_identity"
    ),
    "Georgia PDF has no extractable source page text": "georgia_pdf_no_text",
    "Georgia air source ID or listing endpoint is not configured": "georgia_configuration",
    "Georgia air source bounds are invalid": "georgia_query_bounds",
    "Georgia Knack metadata is not JSON": "georgia_metadata_content_type",
    "Georgia Knack application schema is malformed": "georgia_metadata_schema",
    "Georgia Knack app identity changed": "georgia_metadata_identity",
    "Georgia Knack source field map changed": "georgia_field_map",
    "Georgia listing exceeded bounds or returned non-JSON": "georgia_listing_bounds_or_type",
    "Georgia listing response is malformed": "georgia_listing_schema",
    "Georgia listing is empty or exceeds its record bound": "georgia_listing_count",
    "Georgia listing exceeds its page bound": "georgia_listing_page_limit",
    "Georgia listing changed during pagination": "georgia_listing_changed",
    "Georgia listing ended before its declared page count": "georgia_listing_incomplete",
    "Georgia listing row has invalid shape": "georgia_row_schema",
    "Georgia listing row lacks stable identity or site fields": "georgia_row_identity",
    "Georgia listing row lacks a required narrative or draft permit": "georgia_missing_document",
}
_RUNTIME_CODES = {
    "acquisition_failed",
    "resource_limits_unavailable",
    "windows_job_api_unavailable",
    "windows_job_create_failed",
    "windows_job_limit_setup_failed",
    "windows_current_process_failed",
    "windows_job_assignment_failed",
    "windows_job_handle_missing",
    "windows_job_limit_query_failed",
    "acquisition_result_not_serializable",
    "acquisition_result_too_large",
    "acquisition_process_failed",
    "acquisition_result_too_large_or_truncated",
    "acquisition_result_invalid",
    "network_error",
    "acquisition_timeout",
    "response_too_large",
    "source_parse_error",
    "publisher_stale",
    "ceqanet_count_mismatch",
    "ceqanet_title_limit",
    "ceqanet_document_unreadable",
    "ceqanet_document_failures",
    "georgia_pdf_page_limit",
    "georgia_run_page_limit",
}
_KNOWN_CODES = _RUNTIME_CODES | set(_PARSE_CODES.values())
_STAGES = {
    "ceqanet_listing",
    "ceqanet_document",
    "georgia_metadata",
    "georgia_listing",
    "georgia_document",
    "public_acquisition",
}
_DYNAMIC_CODES = (
    (
        r"Houston publisher has not posted a weekly report since "
        r"\d{4}-\d{2}-\d{2} \(over 30 days\)",
        "publisher_stale",
    ),
    (r"CEQAnet listed \d+ documents but the table holds \d+", "ceqanet_count_mismatch"),
    (r"CEQAnet has \d+ data-center titles, above the per-run bound", "ceqanet_title_limit"),
    (
        r"CEQAnet document \d{10} names a data center but could not be read",
        "ceqanet_document_unreadable",
    ),
    (r"CEQAnet document pages failed for \d+ of \d+ documents", "ceqanet_document_failures"),
    (r"Georgia PDF page count \d+ exceeds per-document limit \d+", "georgia_pdf_page_limit"),
    (r"Georgia PDFs exceed total run page limit \d+", "georgia_run_page_limit"),
)


def _valid_code(value: Any) -> bool:
    return isinstance(value, str) and (
        value in _KNOWN_CODES or re.fullmatch(r"http_status_[1-5]\d{2}", value) is not None
    )


def _chain(error: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = error
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        yield current
        current = current.__cause__


def acquisition_diagnostics(error: BaseException) -> dict[str, str | int]:
    """Return only bounded allowlisted fields, including through a parser wrapper."""
    chain = list(_chain(error))
    result: dict[str, str | int] = {}
    for item in chain:
        stage = getattr(item, "acquisition_stage", None)
        if isinstance(stage, str) and stage in _STAGES:
            result["error_stage"] = stage
            break
    for item in chain:
        retained_code = getattr(item, "acquisition_code", None)
        if isinstance(retained_code, str) and _valid_code(retained_code):
            result["error_code"] = retained_code
            if retained_code.startswith("http_status_"):
                result["http_status"] = int(retained_code.removeprefix("http_status_"))
            return result
        if isinstance(item, httpx.HTTPStatusError):
            status = item.response.status_code
            if type(status) is int and 100 <= status <= 599:
                result.update(error_code=f"http_status_{status}", http_status=status)
                return result
    for item in chain:
        if isinstance(item, httpx.TimeoutException | TimeoutError):
            result["error_code"] = "acquisition_timeout"
            return result
        if isinstance(item, httpx.RequestError):
            result["error_code"] = "network_error"
            return result
        message = str(item)[:500]
        code = _PARSE_CODES.get(message)
        if code is None:
            code = next(
                (value for pattern, value in _DYNAMIC_CODES if re.fullmatch(pattern, message)), None
            )
        if code is None and message in _RUNTIME_CODES:
            code = message
        if code is not None:
            result["error_code"] = code
            return result
    from gridlens.ingestion.adapters.bounded_http import ResponseTooLarge
    from gridlens.ingestion.adapters.federal_register import SourceParseError

    if any(isinstance(item, ResponseTooLarge) for item in chain):
        result["error_code"] = "response_too_large"
        return result

    result["error_code"] = (
        "source_parse_error" if isinstance(error, SourceParseError) else "acquisition_failed"
    )
    return result


def acquisition_error_message(error: BaseException) -> str:
    diagnostics = acquisition_diagnostics(error)
    code = diagnostics["error_code"]
    if code == "source_parse_error":
        return "Acquisition source response could not be parsed"
    stage = diagnostics.get("error_stage")
    return f"Source acquisition failed: {code}" + (f" [{stage}]" if stage else "")


@contextmanager
def acquisition_stage(stage: str) -> Iterator[None]:
    if stage not in _STAGES:
        raise ValueError("Unknown acquisition diagnostic stage")
    try:
        yield
    except Exception as error:
        if getattr(error, "acquisition_stage", None) not in _STAGES:
            error.acquisition_stage = stage  # type: ignore[attr-defined]
        raise
