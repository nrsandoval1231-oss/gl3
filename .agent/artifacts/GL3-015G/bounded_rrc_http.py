from __future__ import annotations

from typing import Any

import httpx

from rrc_current_access import MAX_RESPONSE_BYTES, MAX_RUN_BYTES, AccessError, allowlisted


def bounded_request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    data: dict[str, str] | None = None,
    run_bytes: dict[str, int] | None = None,
) -> tuple[int, dict[str, str], bytes, dict[str, Any]]:
    """Read at most one response limit plus a sentinel byte; redirects stay disabled."""
    if not allowlisted(url):
        raise AccessError("request URL is outside the RRC allowlist")
    accounting = run_bytes if run_bytes is not None else {"bytes": 0}
    headers = {"User-Agent": "GridLens bounded public data compatibility probe/1.0"}
    with client.stream(
        method,
        url,
        data=data,
        headers=headers,
        follow_redirects=False,
        timeout=20.0,
    ) as response:
        parts: list[bytes] = []
        size = 0
        for chunk in response.iter_bytes():
            remaining = MAX_RESPONSE_BYTES + 1 - size
            if remaining <= 0:
                break
            part = chunk[:remaining]
            parts.append(part)
            size += len(part)
            accounting["bytes"] = accounting.get("bytes", 0) + len(part)
            if size > MAX_RESPONSE_BYTES or accounting["bytes"] > MAX_RUN_BYTES:
                break
        body = b"".join(parts)
        metadata = {
            "status": response.status_code,
            "url": str(response.url),
            "content_type": response.headers.get("content-type"),
            "content_length_header": response.headers.get("content-length"),
            "content_disposition": response.headers.get("content-disposition"),
            "location": response.headers.get("location"),
            "body_bytes_read": len(body),
            "run_bytes_read": accounting["bytes"],
        }
        return response.status_code, dict(response.headers), body, metadata
