"""Host-pinned, redirect-free, polite HTTP for the early-signal sources (ERCOT, PUCT Interchange).

Every request names a URL that the caller's policy function accepts (exact host and path shape),
connects to a public DNS answer pinned for that request, never follows a redirect, caps the body
by Content-Length and by running count, sends the declared generic user agent, and is paced by the
caller's ``pacer`` (at most one request per second). A status other than 200 or 304 is a typed
``DocumentFailure`` carrying ``Retry-After`` for 429/503. Nothing from the response body is put into
an exception or a failure code.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from gridlens.ingestion.adapters import tceq_application_documents as shared
from gridlens.ingestion.adapters import tceq_http
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.tceq_application_documents import DocumentFailure

USER_AGENT = shared.USER_AGENT
ERCOT_HOST = "www.ercot.com"
PUCT_HOST = "interchange.puc.texas.gov"
ALLOWED_HOSTS = frozenset({ERCOT_HOST, PUCT_HOST})
MAX_URL_CHARS = 600
_HTML = frozenset({"text/html", "application/xhtml+xml"})
_PDF = frozenset({"application/pdf", "application/x-pdf"})
_XLSX = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    }
)
HTML = _HTML
PDF = _PDF
XLSX = _XLSX


@dataclass(slots=True)
class Fetched:
    status: int  # 200, or 304 when the conditional request matched
    body: bytes = b""
    sha256: str | None = None
    media_type: str = ""
    validators: dict[str, Any] = field(default_factory=dict)


def check_url(url: str, policy: Callable[[str], bool]) -> str:
    """The exact https URL on an allowed host that the caller's policy accepts."""
    if not isinstance(url, str) or len(url) > MAX_URL_CHARS or not policy(url):
        raise SourceParseError("Early-signal URL is outside the reviewed host and path policy")
    host = httpx.URL(url).host
    if host not in ALLOWED_HOSTS:
        raise SourceParseError("Early-signal host is not allowed")
    return host


def _read_limited(response: httpx.Response, max_bytes: int) -> bytes:
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise DocumentFailure("oversize", declared)
    body = bytearray()
    for chunk in response.iter_bytes(64 * 1024):
        body += chunk
        if len(body) > max_bytes:
            raise DocumentFailure("oversize", str(len(body)))
    return bytes(body)


class EarlyFetcher:
    """One polite GET at a time. ``pacer`` is called before every request."""

    def __init__(
        self,
        client: httpx.Client,
        pacer: Callable[[], None],
        policy: Callable[[str], bool],
    ) -> None:
        if client.follow_redirects:
            raise SourceParseError("Early-signal client must not automatically follow redirects")
        self.client = client
        self.pacer = pacer
        self.policy = policy
        self.requests = 0

    def get(
        self,
        url: str,
        *,
        max_bytes: int,
        media_types: frozenset[str],
        known: dict[str, Any] | None = None,
        accept: str = "*/*",
    ) -> Fetched:
        def run() -> Fetched:
            host = check_url(url, self.policy)
            ip = tceq_http._public_ip(host)
            pinned = httpx.URL(url).copy_with(host=ip)
            headers = {"Host": host, "User-Agent": USER_AGENT, "Accept": accept}
            if known and known.get("etag"):
                headers["If-None-Match"] = str(known["etag"])
            elif known and known.get("last_modified"):
                headers["If-Modified-Since"] = str(known["last_modified"])
            self.pacer()
            self.requests += 1
            with self.client.stream(
                "GET", str(pinned), headers=headers, extensions={"sni_hostname": host}
            ) as response:
                if response.status_code == 304:
                    return Fetched(304, validators=shared._validators(response.headers))
                if 300 <= response.status_code < 400:
                    raise DocumentFailure("redirect_not_followed")
                if response.status_code != 200:
                    raise shared._status_failure(response)
                media = shared._media_type(response.headers)
                if media not in media_types:
                    if media in _HTML and not (media_types & _HTML):
                        raise DocumentFailure("js_shell", media)
                    raise DocumentFailure("wrong_content_type", media[:60])
                validators = shared._validators(response.headers)
                body = _read_limited(response, max_bytes)
                if not body:
                    raise DocumentFailure("empty_body")
                return Fetched(
                    200, body, hashlib.sha256(body).hexdigest(), media, validators=validators
                )

        value: Fetched = shared._guard_network(run)
        return value
