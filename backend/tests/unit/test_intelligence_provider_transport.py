"""Loopback-only transport tests; no provider is contacted."""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from gridlens.integrations import intelligence_provider


class _Server:
    def __init__(self, behavior):
        self.posts = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                outer.posts += 1
                self.rfile.read(int(self.headers.get("content-length", "0")))
                behavior(self)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/v1"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def serve():
    servers = []

    def start(behavior):
        server = _Server(behavior)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


def _reply(handler, body: bytes, *, request_id="req-loopback", status=200, length=True):
    handler.send_response(status)
    if request_id:
        handler.send_header("x-request-id", request_id)
    if length:
        handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _post(server, timeout_seconds):
    return intelligence_provider._post_json(
        server.url, headers={}, payload={"probe": 1}, timeout_seconds=timeout_seconds
    )


def test_immediate_success_returns_body_and_request_id(serve):
    server = serve(lambda h: _reply(h, b'{"id":"resp-1","ok":true}'))
    data, request_id, _latency = _post(server, 5)
    assert data["ok"] is True
    assert request_id == "req-loopback"
    assert server.posts == 1


def test_delayed_response_inside_total_budget_succeeds(serve, monkeypatch):
    # Regression for #93: a single phase limit shorter than the total budget
    # used to fail a valid response that arrived before the total deadline.
    monkeypatch.setattr(intelligence_provider, "CONNECT_PHASE_TIMEOUT_SECONDS", 0.5)

    def delayed(handler):
        time.sleep(1.5)
        _reply(handler, b'{"ok":true}')

    server = serve(delayed)
    data, request_id, latency_ms = _post(server, 4)
    assert data == {"ok": True}
    assert request_id == "req-loopback"
    assert latency_ms >= 1400
    assert server.posts == 1


def test_true_total_deadline_expiry_is_inconclusive_and_bounded(serve):
    def stalled(handler):
        time.sleep(3)
        _reply(handler, b"{}")

    server = serve(stalled)
    started = time.monotonic()
    with pytest.raises(intelligence_provider.ProviderResponseError) as raised:
        _post(server, 1)
    assert time.monotonic() - started < 2
    error = raised.value
    assert error.conclusive is False
    assert error.response_received is False
    assert error.cause == "total_deadline_exceeded"
    assert server.posts == 1


def test_partial_body_stall_is_bounded_by_total_deadline(serve):
    def dribble(handler):
        handler.send_response(200)
        handler.send_header("x-request-id", "req-partial")
        handler.send_header("content-length", "100")
        handler.end_headers()
        handler.wfile.write(b'{"partial":')
        handler.wfile.flush()
        time.sleep(3)

    server = serve(dribble)
    started = time.monotonic()
    with pytest.raises(intelligence_provider.ProviderResponseError) as raised:
        _post(server, 1)
    assert time.monotonic() - started < 2.5
    error = raised.value
    assert error.conclusive is False
    assert error.response_received is True
    assert error.request_id == "req-partial"
    assert error.cause == "total_deadline_exceeded"
    assert server.posts == 1


def test_slow_drip_cannot_extend_past_total_deadline(serve):
    def drip(handler):
        handler.send_response(200)
        handler.send_header("content-length", "40")
        handler.end_headers()
        for _ in range(40):
            handler.wfile.write(b" ")
            handler.wfile.flush()
            time.sleep(0.1)

    server = serve(drip)
    started = time.monotonic()
    with pytest.raises(intelligence_provider.ProviderResponseError) as raised:
        _post(server, 1)
    assert time.monotonic() - started < 2
    assert raised.value.cause == "total_deadline_exceeded"


def test_connection_failure_is_inconclusive_with_sanitized_cause():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with pytest.raises(intelligence_provider.ProviderResponseError) as raised:
        intelligence_provider._post_json(
            f"http://127.0.0.1:{port}/", headers={}, payload={}, timeout_seconds=2
        )
    assert raised.value.conclusive is False
    assert raised.value.response_received is False
    assert raised.value.cause == "connect_error"


def test_invalid_json_is_conclusive(serve):
    server = serve(lambda h: _reply(h, b"not json"))
    with pytest.raises(intelligence_provider.ProviderResponseError) as raised:
        _post(server, 5)
    assert raised.value.conclusive is True
    assert raised.value.cause == "invalid_response"
    assert server.posts == 1


def test_missing_provider_response_id_falls_back_to_body_id_or_none(serve):
    server = serve(lambda h: _reply(h, json.dumps({"id": "resp-body"}).encode(), request_id=None))
    _data, request_id, _ = _post(server, 5)
    assert request_id == "resp-body"
    server = serve(lambda h: _reply(h, b'{"ok":true}', request_id=None))
    _data, request_id, _ = _post(server, 5)
    assert request_id is None


def test_server_error_is_inconclusive_and_never_redispatched(serve):
    server = serve(lambda h: _reply(h, b"{}", status=503))
    with pytest.raises(intelligence_provider.ProviderResponseError) as raised:
        _post(server, 5)
    assert raised.value.conclusive is False
    assert raised.value.status_code == 503
    assert raised.value.cause == "http_status"
    assert server.posts == 1


def test_oversized_body_is_rejected(serve):
    big = b'{"x":"' + b"a" * (intelligence_provider.MAX_RESPONSE_BYTES + 10) + b'"}'
    server = serve(lambda h: _reply(h, big, length=False))
    with pytest.raises(intelligence_provider.ProviderResponseError) as raised:
        _post(server, 5)
    assert raised.value.cause == "response_too_large"
