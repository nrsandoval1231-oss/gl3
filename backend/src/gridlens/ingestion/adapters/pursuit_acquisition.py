"""Exact registered-record retrieval and optional URL-only public discovery.

Search snippets never enter evidence admission. Each outbound attempt is debited
by the caller before issuing it; neither adapter retries or follows redirects.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import httpx

from gridlens.ingestion.adapters.bounded_http import (
    ResponseTooLarge,
    _DeadlineStream,
    read_bounded_response,
    remaining_seconds,
)
from gridlens.ingestion.adapters.buying_chain_public import validate_public_url
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.socrata_permits import MAPS, SYSTEM_FIELD_SELECTS, render_record
from gridlens.ingestion.registry import load_registry

SUPPORTED_SOURCES = frozenset({"austin-building-permits", "chicago-building-permits"})


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
        raise ValueError("Invalid stable permit identifier")
    if not 1 <= max_bytes <= 750_000:
        raise ValueError("Document byte budget is outside research bounds")
    source = next(s for s in load_registry() if s["id"] == source_id)
    params: dict[str, str | int] = {
        "$where": f"{MAPS[source_id]['row']}='{external_id}'",
        "$limit": 2,
    }
    if source_id in SYSTEM_FIELD_SELECTS:
        params["$select"] = SYSTEM_FIELD_SELECTS[source_id]
    http = client or httpx.Client(timeout=20, follow_redirects=False)
    try:
        remaining_seconds(deadline)
        url = str(httpx.URL(source["endpoint"], params=params))
        if before_request is not None:
            before_request(url)
        headers, body = read_bounded_response(
            http, source["endpoint"], max_bytes, params, deadline=deadline
        )
        if "json" not in headers.get("content-type", "").lower():
            raise SourceParseError("Exact permit response was not JSON")
        rows = json.loads(body)
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise SourceParseError("Exact permit response must contain exactly one record")
        if str(rows[0].get(MAPS[source_id]["row"])) != external_id:
            raise SourceParseError("Exact permit response escaped its stable identifier")
        return source, render_record(source, rows[0])
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
    http = client or httpx.Client(timeout=min(20, remaining), follow_redirects=False)
    try:
        before_request(endpoint)
        with http.stream(
            "POST",
            endpoint,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "query": query,
                "limit": limit,
                "sources": ["web"],
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
