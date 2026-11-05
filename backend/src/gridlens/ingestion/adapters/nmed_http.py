"""Host-pinned, redirect-free, polite HTTP for the two New Mexico Environment Department hosts.

Shared by the air-facilities layer reader and the application-document stage. Each request names
one exact host; the public DNS answer is pinned for the connection (the same helper the TCEQ and
OK DEQ stages use), redirects are never followed (the caller sees the 3xx), and the caller's
``before_request`` paces every hop. Typed failures come from the shared TCEQ stage module.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from urllib.parse import urlsplit

import httpx

from gridlens.ingestion.adapters import tceq_application_documents as shared
from gridlens.ingestion.adapters import tceq_http
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.tceq_application_documents import DocumentFailure

USER_AGENT = shared.USER_AGENT
ARCGIS_HOST = "mercator.env.nm.gov"
SITE_HOST = "www.env.nm.gov"
ALLOWED_HOSTS = frozenset({ARCGIS_HOST, SITE_HOST})


def check_host(url: str, host: str) -> None:
    """The URL must be https on exactly ``host``: no userinfo, port, or fragment tricks."""
    if host not in ALLOWED_HOSTS:
        raise SourceParseError("New Mexico host is not allowed")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise SourceParseError("New Mexico URL is invalid") from exc
    if (
        parts.scheme != "https"
        or parts.hostname != host
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or parts.fragment
        or len(url) > 1000
    ):
        raise SourceParseError("New Mexico URL is outside the reviewed host policy")


@contextmanager
def open_pinned(
    client: httpx.Client,
    url: str,
    host: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    before_request: Callable[[], None] | None = None,
) -> Iterator[httpx.Response]:
    if method not in {"GET", "HEAD"}:
        raise SourceParseError("New Mexico request method is unsupported")
    if client.follow_redirects:
        raise SourceParseError("New Mexico client must not automatically follow redirects")
    check_host(url, host)
    ip = tceq_http._public_ip(host)
    pinned = httpx.URL(url).copy_with(host=ip)
    if before_request is not None:
        before_request()
    with client.stream(
        method,
        str(pinned),
        headers={"Host": host, "User-Agent": USER_AGENT, **(headers or {})},
        extensions={"sni_hostname": host},
    ) as response:
        yield response


def check_status(response: httpx.Response) -> None:
    if 300 <= response.status_code < 400:
        raise DocumentFailure("redirect_not_followed")
    if response.status_code != 200:
        raise shared._status_failure(response)


def read_limited(response: httpx.Response, max_bytes: int) -> bytes:
    """The body, refusing by Content-Length first and by running count while streaming."""
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise DocumentFailure("oversize", declared)
    body = bytearray()
    for chunk in response.iter_bytes(64 * 1024):
        body += chunk
        if len(body) > max_bytes:
            raise DocumentFailure("oversize", str(len(body)))
    return bytes(body)
