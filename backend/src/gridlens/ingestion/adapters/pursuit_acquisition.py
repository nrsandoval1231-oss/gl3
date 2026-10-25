"""Exact registered-record retrieval and optional URL-only public discovery.

Search snippets never enter evidence admission. Each outbound attempt is debited
by the caller before issuing it; neither adapter retries or follows redirects.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from gridlens.ingestion.adapters import boston_permits, el_paso_permits, federal_register
from gridlens.ingestion.adapters.bounded_http import (
    ResponseTooLarge,
    _DeadlineStream,
    read_bounded_response,
    remaining_seconds,
    run_isolated,
)
from gridlens.ingestion.adapters.buying_chain_public import validate_public_url
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.socrata_permits import MAPS, SYSTEM_FIELD_SELECTS, render_record
from gridlens.ingestion.registry import load_registry

# These are existing reviewed sources, not a new authority or discovery list.
EXACT_ENDPOINTS = {
    "austin-building-permits": "https://data.austintexas.gov/resource/3syk-w9eu.json",
    "seattle-building-permits": "https://data.seattle.gov/resource/76t5-zqzr.json",
    "chicago-building-permits": "https://data.cityofchicago.org/resource/ydr8-5enu.json",
    "boston-building-permits": "https://data.boston.gov/api/3/action/datastore_search_sql",
    "el-paso-new-commercial-permits": el_paso_permits.LAYER,
    "federal-register-eis": "https://www.federalregister.gov/api/v1/documents.json",
}
SUPPORTED_SOURCES = frozenset(EXACT_ENDPOINTS)


def _request_for(source: dict, external_id: str) -> tuple[str, dict[str, str | int]]:
    source_id = source["id"]
    endpoint = source["endpoint"]
    if endpoint != EXACT_ENDPOINTS[source_id]:
        raise SourceParseError("Exact research endpoint differs from reviewed native endpoint")
    if source_id in MAPS:
        params: dict[str, str | int] = {
            "$where": f"{MAPS[source_id]['row']}='{external_id}'",
            "$limit": 2,
        }
        if source_id in SYSTEM_FIELD_SELECTS:
            params["$select"] = SYSTEM_FIELD_SELECTS[source_id]
        return endpoint, params
    if source_id == "boston-building-permits":
        return endpoint, {
            "sql": (
                f'SELECT {boston_permits.FIELDS} FROM "{boston_permits.RESOURCE_ID}" '
                f"WHERE permitnumber = '{external_id}' LIMIT 2"
            )
        }
    if source_id == "el-paso-new-commercial-permits":
        return endpoint + "/query", {
            "where": f"B1_ALT_ID = '{external_id}'",
            "outFields": ",".join(el_paso_permits.FIELDS),
            "returnGeometry": "false",
            "resultRecordCount": 2,
            "f": "json",
        }
    # Verified against the publisher's OpenAPI document:
    # https://www.federalregister.gov/api/v1/documentation.json
    # GET /documents/{document_number}.{format}; no API key required.
    if not re.fullmatch(r"[0-9]{4}-[0-9]{4,6}", external_id):
        raise ValueError("Invalid Federal Register document number")
    return endpoint.removesuffix(".json") + f"/{external_id}.json", {}


def _render_exact(source: dict, external_id: str, payload: Any) -> dict[str, Any]:
    source_id = source["id"]
    if source_id in MAPS:
        rows, identity = payload, MAPS[source_id]["row"]
    elif source_id == "boston-building-permits":
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise SourceParseError("Exact Boston response was unsuccessful")
        result = payload.get("result")
        rows = result.get("records") if isinstance(result, dict) else None
        identity = "permitnumber"
    elif source_id == "el-paso-new-commercial-permits":
        if (
            not isinstance(payload, dict)
            or payload.get("error")
            or payload.get("exceededTransferLimit")
        ):
            raise SourceParseError("Exact ArcGIS response failed or exceeded its result bound")
        features = payload.get("features")
        rows = (
            [row.get("attributes") if isinstance(row, dict) else None for row in features]
            if isinstance(features, list)
            else None
        )
        identity = "B1_ALT_ID"
    else:
        rows, identity = [payload], "document_number"
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise SourceParseError("Exact response must contain exactly one record")
    row = rows[0]
    if str(row.get(identity)) != external_id:
        raise SourceParseError("Exact response escaped its stable identifier")
    if source_id in MAPS:
        return render_record(source, row)
    if source_id == "boston-building-permits":
        return boston_permits.render_record(row)
    if source_id == "el-paso-new-commercial-permits":
        return el_paso_permits._row(row, datetime.now(UTC).date())
    return federal_register.render_record(row)


def acquire_registered_record(
    source_id: str,
    external_id: str,
    *,
    deadline: float,
    before_request: Callable[[str], None] | None = None,
    client: httpx.Client | None = None,
    max_bytes: int = 750_000,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch exactly one existing stable ID from its reviewed registry endpoint."""
    if source_id not in SUPPORTED_SOURCES:
        raise ValueError("Exact research adapter is unavailable for this source")
    if not re.fullmatch(r"[A-Za-z0-9 /_.-]{1,100}", external_id):
        raise ValueError("Invalid stable native record identifier")
    if not 1 <= max_bytes <= 750_000:
        raise ValueError("Document byte budget is outside research bounds")
    source = next(s for s in load_registry() if s["id"] == source_id)
    endpoint, params = _request_for(source, external_id)
    remaining_seconds(deadline)
    url = str(httpx.URL(endpoint, params=params))
    if before_request is not None:
        before_request(url)
    if client is None:
        return run_isolated(
            "gridlens.ingestion.adapters.pursuit_acquisition:_acquire_registered_direct",
            (source_id, external_id),
            {"deadline": deadline, "max_bytes": max_bytes},
            deadline=deadline,
        )
    http = client or httpx.Client(timeout=20, follow_redirects=False)
    try:
        remaining_seconds(deadline)
        headers, body = read_bounded_response(http, endpoint, max_bytes, params, deadline=deadline)
        if "json" not in headers.get("content-type", "").lower():
            raise SourceParseError("Exact native response was not JSON")
        return source, _render_exact(source, external_id, json.loads(body))
    finally:
        if client is None:
            http.close()


def discover_urls(
    query: str,
    *,
    api_key: str | None,
    deadline: float,
    before_request: Callable[[str], None],
    limit: int = 10,
    client: httpx.Client | None = None,
) -> list[str]:
    """One Firecrawl v2 search; caller owns persisted search and credit limits.

    Contract: https://docs.firecrawl.dev/api-reference/endpoint/search
    Only web URLs are returned. No scrape, agent, login, or model endpoint.
    A search requests at most ten results (published price: two credits).
    """
    if not api_key:
        raise ValueError("Firecrawl discovery is not configured")
    if not query.strip() or len(query) > 1000 or not 1 <= limit <= 10:
        raise ValueError("Search exceeds bounded query or result limit")
    remaining = remaining_seconds(deadline)
    assert remaining is not None
    endpoint = "https://api.firecrawl.dev/v2/search"
    before_request(endpoint)
    if client is None:
        return run_isolated(
            "gridlens.ingestion.adapters.pursuit_acquisition:_discover_direct",
            (query,),
            {"api_key": api_key, "deadline": deadline, "limit": limit},
            deadline=deadline,
        )
    http = client or httpx.Client(timeout=min(20, remaining), follow_redirects=False)
    try:
        with http.stream(
            "POST",
            endpoint,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "query": query,
                "limit": limit,
                "sources": [{"type": "web"}],
                "timeout": max(1, int(min(20, remaining) * 1000)),
            },
            timeout=min(20, remaining),
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared and (not declared.isdigit() or int(declared) > 200_000):
                raise ResponseTooLarge("Search response exceeds declared byte bound")
            # Share the existing raw-stream deadline check, including compressed
            # chunks that may yield no decoded text until much later.
            assert isinstance(response.stream, httpx.SyncByteStream)
            response.stream = _DeadlineStream(response.stream, deadline)
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                remaining_seconds(deadline)
                size += len(chunk)
                if size > 200_000:
                    raise ResponseTooLarge("Search response exceeds 200000 bytes")
                chunks.append(chunk)
            remaining_seconds(deadline)
        payload = json.loads(b"".join(chunks))
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise SourceParseError("Public discovery failed")
        data = payload.get("data")
        rows = data.get("web") if isinstance(data, dict) else None
        if not isinstance(rows, list) or len(rows) > limit:
            raise SourceParseError("Public discovery result shape exceeded bounds")
        urls: list[str] = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("url"), str):
                continue
            try:
                url = validate_public_url(row["url"])
            except ValueError:
                continue
            if url not in urls:
                urls.append(url)
        return urls
    finally:
        if client is None:
            http.close()


def _acquire_registered_direct(
    source_id: str, external_id: str, *, deadline: float, max_bytes: int
):
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        return acquire_registered_record(
            source_id, external_id, deadline=deadline, max_bytes=max_bytes, client=client
        )


def _discover_direct(query: str, *, api_key: str, deadline: float, limit: int):
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        return discover_urls(
            query,
            api_key=api_key,
            deadline=deadline,
            limit=limit,
            before_request=lambda _: None,
            client=client,
        )


class ExtractionUnavailable(ValueError):
    """Configured extraction is unavailable; no provider request was sent."""


def extract_public_document(
    url: str,
    *,
    api_key: str | None,
    deadline: float,
    before_request: Callable[[str], None],
    max_bytes: int = 750_000,
    client: httpx.Client | None = None,
):
    """One bounded markdown-only scrape after a confirmed public JavaScript shell.

    Contract: https://docs.firecrawl.dev/api-reference/endpoint/scrape
    Basic proxy only; no enhanced retry, actions, credentials, PDF/OCR, crawl,
    agent, or model extraction. Acquisition output still requires normal admission.
    """
    from gridlens.ingestion.adapters.buying_chain_public import (
        MAX_TEXT,
        PublicAccessRestricted,
        PublicDocument,
    )

    url = validate_public_url(url)
    if not api_key:
        raise ExtractionUnavailable("Firecrawl extraction is not configured")
    if not 1 <= max_bytes <= 750_000:
        raise ValueError("Extraction byte budget is outside research bounds")
    remaining = remaining_seconds(deadline)
    assert remaining is not None
    endpoint = "https://api.firecrawl.dev/v2/scrape"
    before_request(endpoint)
    if client is None:
        return run_isolated(
            "gridlens.ingestion.adapters.pursuit_acquisition:_extract_direct",
            (url,),
            {"api_key": api_key, "deadline": deadline, "max_bytes": max_bytes},
            deadline=deadline,
        )
    with client.stream(
        "POST",
        endpoint,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": False,
            "proxy": "basic",
            "skipTlsVerification": False,
            "parsers": [],
            "maxAge": 0,
            "storeInCache": False,
            "timeout": max(1000, int(min(20, remaining) * 1000)),
        },
        timeout=min(20, remaining),
        follow_redirects=False,
    ) as response:
        response.raise_for_status()
        if "json" not in response.headers.get("content-type", "").lower():
            raise SourceParseError("Extraction response was not JSON")
        declared = response.headers.get("content-length")
        if declared and (not declared.isdigit() or int(declared) > max_bytes):
            raise ResponseTooLarge("Extraction response exceeds declared byte bound")
        assert isinstance(response.stream, httpx.SyncByteStream)
        response.stream = _DeadlineStream(response.stream, deadline)
        chunks = []
        size = 0
        for chunk in response.iter_bytes():
            remaining_seconds(deadline)
            size += len(chunk)
            if size > max_bytes:
                raise ResponseTooLarge("Extraction response exceeds document byte bound")
            chunks.append(chunk)
        payload = json.loads(b"".join(chunks))
    remaining_seconds(deadline)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or payload.get("success") is not True:
        raise SourceParseError("Public extraction failed")
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        raise SourceParseError("Public extraction lacks source metadata")
    if metadata.get("statusCode") in {401, 403}:
        raise PublicAccessRestricted("Access restriction returned by public extraction")
    if metadata.get("statusCode") != 200 or metadata.get("error") or data.get("warning"):
        raise SourceParseError("Public extraction was incomplete or unsuccessful")
    returned_url = metadata.get("sourceURL")
    final_url = metadata.get("url", returned_url)
    if (
        not isinstance(returned_url, str)
        or not isinstance(final_url, str)
        or validate_public_url(returned_url) != url
        or validate_public_url(final_url) != url
    ):
        raise SourceParseError("Public extraction did not preserve the requested source URL")
    if metadata.get("contentType") and "html" not in metadata["contentType"].lower():
        raise SourceParseError("Extraction fallback only supports public HTML")
    markdown = data.get("markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        raise SourceParseError("Public extraction returned no document text")
    if len(markdown) > MAX_TEXT:
        raise ResponseTooLarge("Extracted document exceeds text bound; no truncation allowed")
    title = metadata.get("title")
    title = title if isinstance(title, str) else "Public project page"
    if len(title) > 500:
        raise ResponseTooLarge("Document title exceeds 500 characters")
    if re.search(
        r"captcha|access denied|access forbidden|login required|sign in to (?:view|access)|"
        r"log in to (?:view|access)|verify (?:you are|that you are) human",
        title + "\n" + markdown,
        re.I,
    ):
        raise PublicAccessRestricted("Extracted page is access restricted")
    published = metadata.get("article:published_time") or metadata.get("publishedTime")
    published_at = None
    if isinstance(published, str):
        try:
            parsed_date = datetime.fromisoformat(published.replace("Z", "+00:00")).date()
            if parsed_date <= datetime.now(UTC).date():
                published_at = parsed_date
        except ValueError:
            pass  # Missing or malformed publication dates remain unknown.
    return PublicDocument(
        url=url,
        title=title,
        text=markdown,
        published_at=published_at,
        extraction_location="Firecrawl public HTML markdown; complete bounded text",
    )


def _extract_direct(url: str, *, api_key: str, deadline: float, max_bytes: int):
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        return extract_public_document(
            url,
            api_key=api_key,
            deadline=deadline,
            max_bytes=max_bytes,
            before_request=lambda _: None,
            client=client,
        )


def retrieval_failure(exc: Exception) -> dict[str, Any]:
    """Stable diagnostics without exception text, request headers, or credentials."""
    from gridlens.ingestion.adapters.bounded_http import AcquisitionFailure
    from gridlens.ingestion.adapters.buying_chain_public import (
        PublicAccessRestricted,
        PublicExtractionUnavailable,
    )

    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    if isinstance(exc, AcquisitionFailure):
        match = re.fullmatch(r"http_status_(\d{3})", str(exc))
        status = int(match[1]) if match else None
    code = "retrieval_failed"
    retryable = False
    if status is not None:
        code = (
            "access_restricted"
            if status in {401, 403}
            else "not_found"
            if status in {404, 410}
            else "rate_limited"
            if status == 429
            else "http_error"
        )
        retryable = status == 429 or status >= 500
    elif isinstance(exc, PublicAccessRestricted):
        code = "access_restricted"
    elif isinstance(exc, ExtractionUnavailable):
        code = "extraction_not_configured"
    elif isinstance(exc, PublicExtractionUnavailable):
        code = "javascript_extraction_unavailable"
    elif isinstance(exc, TimeoutError | httpx.TimeoutException):
        code, retryable = "deadline_or_transport_timeout", True
    elif isinstance(exc, ResponseTooLarge):
        code = "document_budget_exceeded"
    elif isinstance(exc, httpx.RequestError) or (
        isinstance(exc, AcquisitionFailure) and str(exc) == "network_error"
    ):
        code, retryable = "network_error", True
    elif isinstance(exc, SourceParseError | json.JSONDecodeError):
        code = "unsupported_or_malformed_response"
    return {"failure_code": code, "http_status": status, "retryable": retryable, "reason": code}
