"""Registered JETI acquisition uses runtime transport without relaxing URL policy."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import pytest

from gridlens.ingestion.adapters import jeti_applications
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.jeti_applications import API_URL, retrieve
from gridlens.ingestion.registry import load_registry


def _source():
    return next(row for row in load_registry() if row["id"] == "texas-jeti-applications")


def test_default_jeti_transport_reaches_configured_runtime_proxy(monkeypatch):
    targets = []

    class Proxy(BaseHTTPRequestHandler):
        def do_CONNECT(self):
            targets.append(self.path)
            self.send_error(502, "Local test proxy deliberately refuses the tunnel")

        def log_message(self, *_args):
            pass

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    thread = Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    # Environment variable names are case-insensitive on Windows, so clear
    # lowercase variants before setting uppercase values.
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{proxy.server_port}")
    monkeypatch.setenv("NO_PROXY", "")
    # Keep this transport regression entirely on loopback, including its
    # destination, so the suite's external-network prohibition still applies.
    local_url = "https://127.0.0.2/open-data/v1/tables/jeti"
    monkeypatch.setattr(jeti_applications, "API_URL", local_url)
    monkeypatch.setattr(jeti_applications, "ALLOWED_HOSTS", frozenset({"127.0.0.2"}))
    source = {**_source(), "endpoint": local_url}
    try:
        # The deliberate CONNECT rejection proves a real request used the
        # configured proxy, without contacting the external API or skipping TLS.
        with pytest.raises(httpx.ProxyError):
            retrieve(source)
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=2)
    assert targets == ["127.0.0.2:443"] * 3


def test_runtime_proxy_support_does_not_allow_reconfigured_source_url():
    source = {**_source(), "endpoint": "https://127.0.0.1/internal"}

    def unexpected(_request):
        pytest.fail("an unregistered endpoint must not be requested")

    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        with pytest.raises(SourceParseError, match="not configured"):
            retrieve(source, client)


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (
            httpx.Response(302, headers={"location": "https://evil.invalid/jeti"}),
            "redirect host is not allowed",
        ),
        (
            httpx.Response(302, headers={"location": API_URL}),
            "redirects are not followed",
        ),
        (
            httpx.Response(
                200,
                headers={"content-type": "application/json", "content-length": "2000001"},
                content=b"{}",
            ),
            "exceeds its byte limit",
        ),
    ],
)
def test_runtime_proxy_support_keeps_redirect_and_byte_guards(response, reason):
    requests = []

    def handle(request):
        requests.append(str(request.url))
        return response

    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=False) as client:
        with pytest.raises(SourceParseError, match=reason):
            retrieve(_source(), client)
    assert requests == [API_URL]
