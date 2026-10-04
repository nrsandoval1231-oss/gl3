"""Deterministic timing checks; no external network or shared database required."""

import gzip

import httpx
import pytest

from gridlens.ingestion.adapters import bounded_http, buying_chain_public
from gridlens.ingestion.adapters.bounded_http import ResponseTooLarge, read_bounded_response


class Clock:
    def __init__(self):
        self.now = 100.0

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(bounded_http.time, "monotonic", lambda: clock.now)
    return clock


class DripStream(httpx.SyncByteStream):
    def __init__(self, clock, chunks, delay=0.0):
        self.clock = clock
        self.chunks = chunks
        self.delay = delay
        self.consumed = 0
        self.closed = False

    def __iter__(self):
        for chunk in self.chunks:
            self.clock.advance(self.delay)
            self.consumed += 1
            yield chunk

    def close(self):
        self.closed = True


def test_expired_deadline_never_opens_request(clock):
    def respond(request):
        pytest.fail("Expired research must not open another request")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(TimeoutError, match="deadline exhausted"):
            read_bounded_response(client, "https://public.example", 100, deadline=clock.now)


def test_deadline_clamps_request_and_body_phase_without_mutating_extensions(clock):
    stream = DripStream(clock, [b"body"])
    observed = {}
    extensions = {"sni_hostname": "public.example", "timeout": {"connect": 1.0}}

    def respond(request):
        observed["request"] = request
        observed["initial_timeout"] = request.extensions["timeout"].copy()
        assert request.extensions["sni_hostname"] == "public.example"
        clock.advance(3.0)
        return httpx.Response(200, stream=stream)

    with httpx.Client(
        transport=httpx.MockTransport(respond), timeout=httpx.Timeout(7.0, pool=None)
    ) as client:
        _, body = read_bounded_response(
            client, "https://public.example", 100, extensions=extensions, deadline=105.0
        )

    assert body == b"body"
    assert observed["initial_timeout"] == {
        "connect": 1.0, "read": 5.0, "write": 5.0, "pool": 5.0
    }
    assert observed["request"].extensions["timeout"] == {
        "connect": 1.0, "read": 2.0, "write": 2.0, "pool": 2.0
    }
    assert extensions == {"sni_hostname": "public.example", "timeout": {"connect": 1.0}}
    assert stream.closed


def test_slow_drip_cannot_refresh_shared_deadline(clock):
    stream = DripStream(clock, [b"x"] * 100, delay=0.4)
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    ) as client:
        with pytest.raises(TimeoutError, match="deadline exhausted"):
            read_bounded_response(client, "https://public.example", 1000, deadline=101.0)

    assert stream.consumed == 3
    assert stream.closed


def test_compressed_raw_chunks_are_checked_before_decoder_yields_bytes(clock):
    compressed = gzip.compress(b"A public document with enough text to parse.")
    stream = DripStream(clock, [bytes([byte]) for byte in compressed], delay=0.4)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-encoding": "gzip"}, stream=stream
            )
        )
    ) as client:
        with pytest.raises(TimeoutError, match="deadline exhausted"):
            read_bounded_response(client, "https://public.example", 1000, deadline=101.0)

    # The first three bytes are gzip metadata, so iter_bytes alone would not check them.
    assert stream.consumed == 3
    assert stream.closed


def test_deadline_expired_in_headers_closes_response_without_reading_body(clock):
    stream = DripStream(clock, [b"body"])

    def respond(request):
        clock.advance(2.0)
        return httpx.Response(200, stream=stream)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(TimeoutError, match="deadline exhausted"):
            read_bounded_response(client, "https://public.example", 100, deadline=101.0)

    assert stream.consumed == 0
    assert stream.closed


def test_response_end_still_checks_deadline(clock):
    class LateEndStream(DripStream):
        def __iter__(self):
            yield b"body"
            self.clock.advance(2.0)

    stream = LateEndStream(clock, [])
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    ) as client:
        with pytest.raises(TimeoutError, match="deadline exhausted"):
            read_bounded_response(client, "https://public.example", 100, deadline=101.0)
    assert stream.closed


def test_no_deadline_preserves_existing_timeout_and_decompression(clock):
    content = b"unchanged adapter behavior"
    stream = DripStream(clock, [gzip.compress(content)], delay=100.0)

    def respond(request):
        assert request.extensions["timeout"] == {
            "connect": 7.0, "read": 7.0, "write": 7.0, "pool": 7.0
        }
        return httpx.Response(200, headers={"content-encoding": "gzip"}, stream=stream)

    with httpx.Client(transport=httpx.MockTransport(respond), timeout=7.0) as client:
        _, body = read_bounded_response(client, "https://public.example", 100)
    assert body == content
    assert stream.closed


def test_deadline_does_not_weaken_decoded_byte_bound(clock):
    stream = DripStream(clock, [gzip.compress(b"x" * 1000)])
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-encoding": "gzip"}, stream=stream
            )
        )
    ) as client:
        with pytest.raises(ResponseTooLarge, match="exceeds 100 bytes"):
            read_bounded_response(client, "https://public.example", 100, deadline=105.0)
    assert stream.closed


def test_direct_reader_checks_expiry_after_dns_before_connecting(clock, monkeypatch):
    def resolve(*args, **kwargs):
        clock.advance(6.0)
        return [(2, 1, 6, "", ("8.8.8.8", 443))]

    def unexpected_client(*args, **kwargs):
        pytest.fail("An expired DNS result must not start an HTTP connection")

    monkeypatch.setattr(buying_chain_public.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(buying_chain_public.httpx, "Client", unexpected_client)
    with pytest.raises(TimeoutError, match="deadline exhausted"):
        buying_chain_public._retrieve_direct("https://public.example", deadline=105.0)


@pytest.mark.parametrize("deadline", [None, 105.0])
def test_retrieve_preserves_ip_pinning_sni_and_security_settings(clock, monkeypatch, deadline):
    real_client = httpx.Client
    observed = {}

    def respond(request):
        observed["request"] = request
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"Public source with sufficient project information for parsing.",
        )

    def create_client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        assert "verify" not in kwargs  # TLS certificate verification keeps its default True.
        assert kwargs["timeout"].read == (7.0 if deadline is None else 5.0)
        return real_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(buying_chain_public, "_public_ip", lambda host: "8.8.8.8")
    monkeypatch.setattr(buying_chain_public.httpx, "Client", create_client)
    document = buying_chain_public._retrieve_direct(
        "https://public.example/project", deadline=deadline
    )

    request = observed["request"]
    assert str(request.url) == "https://8.8.8.8/project"
    assert request.headers["host"] == "public.example"
    assert request.extensions["sni_hostname"] == "public.example"
    assert document.url == "https://public.example/project"


def test_retrieve_does_not_accept_document_if_parsing_expires_budget(clock, monkeypatch):
    real_client = httpx.Client
    real_parser = buying_chain_public.parse_document

    def parse(*args):
        clock.advance(6.0)
        return real_parser(*args)

    def create_client(**kwargs):
        return real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    headers={"content-type": "text/plain"},
                    content=b"Public source with sufficient project information for parsing.",
                )
            ),
            **kwargs,
        )

    monkeypatch.setattr(buying_chain_public, "_public_ip", lambda host: "8.8.8.8")
    monkeypatch.setattr(buying_chain_public.httpx, "Client", create_client)
    monkeypatch.setattr(buying_chain_public, "parse_document", parse)
    with pytest.raises(TimeoutError, match="deadline exhausted"):
        buying_chain_public._retrieve_direct("https://public.example", deadline=105.0)
