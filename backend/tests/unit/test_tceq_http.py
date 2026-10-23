from __future__ import annotations

import httpx
import pytest

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.tceq_http import (
    _MAX_REDIRECTS,
    HOST,
    NSR_LISTING,
    RECORDS_HOST,
    read_tceq_response,
)

RECORD_URL = (
    "https://records.tceq.texas.gov/cs/idcplg?"
    "IdcService=TCEQ_EXTERNAL_SEARCH_GET_FILE&Rendition=Web&dID=7474076"
)
PDF_URL = (
    "https://www.tceq.texas.gov/downloads/permitting/air/bilingual/"
    "pending-permit-notices/182126-pls-english.pdf"
)


def test_host_header_is_per_request_and_does_not_mutate_the_shared_client(monkeypatch):
    import threading

    import gridlens.ingestion.adapters.tceq_http as policy

    monkeypatch.setattr(policy, "_public_ip", lambda _host: "8.8.8.8")
    barrier = threading.Barrier(2)
    seen: list[tuple[str, str]] = []
    lock = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        barrier.wait(timeout=2)
        with lock:
            seen.append((str(request.url), request.headers["host"]))
        # The shared client header must stay untouched while both requests run.
        assert client.headers.get("Host") == "preserve.example"
        if request.headers["host"] == HOST:
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html/>")
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7")

    client = httpx.Client(
        headers={"Host": "preserve.example"},
        follow_redirects=False,
        transport=httpx.MockTransport(handler),
    )
    errors: list[BaseException] = []

    def run(url: str, route: str) -> None:
        try:
            read_tceq_response(client, url, 100, route=route)
        except BaseException as exc:
            errors.append(exc)

    listing = threading.Thread(target=run, args=(NSR_LISTING, "listing"))
    record = threading.Thread(target=run, args=(RECORD_URL, "record_pdf"))
    listing.start()
    record.start()
    listing.join()
    record.join()
    assert errors == []
    assert {host for _url, host in seen} == {HOST, RECORDS_HOST}
    assert client.headers["Host"] == "preserve.example"


def test_listing_request_pins_public_dns_and_restores_host_header(monkeypatch):
    import gridlens.ingestion.adapters.tceq_http as policy

    resolved = []
    monkeypatch.setattr(policy, "_public_ip", lambda host: resolved.append(host) or "8.8.8.8")
    observed = []

    def handler(request):
        observed.append(request)
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html/>")

    client = httpx.Client(
        headers={"Host": "preserve.example"},
        follow_redirects=False,
        transport=httpx.MockTransport(handler),
    )
    headers, body = read_tceq_response(client, NSR_LISTING, 100, route="listing")
    assert headers["content-type"] == "text/html" and body == b"<html/>"
    assert resolved == [HOST]
    assert observed[0].url.host == "8.8.8.8"
    assert observed[0].headers["host"] == HOST
    assert observed[0].extensions["sni_hostname"] == HOST
    assert client.headers["Host"] == "preserve.example"


def test_records_request_pins_records_host_and_accepts_pdf(monkeypatch):
    import gridlens.ingestion.adapters.tceq_http as policy

    resolved = []
    monkeypatch.setattr(policy, "_public_ip", lambda host: resolved.append(host) or "8.8.8.8")
    observed = []
    client = httpx.Client(
        follow_redirects=False,
        transport=httpx.MockTransport(
            lambda request: observed.append(request)
            or httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7")
        ),
    )
    _, body = read_tceq_response(client, RECORD_URL, 100, route="record_pdf")
    assert body == b"%PDF-1.7"
    assert resolved == [RECORDS_HOST]
    assert observed[0].url.host == "8.8.8.8"
    assert observed[0].headers["host"] == RECORDS_HOST
    assert observed[0].extensions["sni_hostname"] == RECORDS_HOST


def test_rejects_unapproved_routes_before_request():
    bad_urls = (
        "https://www.tceq.texas.gov.evil.example/assets/public/a.pdf",
        "https://user@www.tceq.texas.gov/assets/public/a.pdf",
        "https://www.tceq.texas.gov:444/assets/public/a.pdf",
        "https://127.0.0.1/assets/public/a.pdf",
        RECORD_URL + "&dID=7474077",
        RECORD_URL + "&extra=1",
        RECORD_URL.replace("Rendition=Web", "Rendition=Web\x00"),
        RECORD_URL.replace("/cs/idcplg", "/cs/../idcplg"),
        RECORD_URL + "%00",
    )
    calls = []
    client = httpx.Client(
        follow_redirects=False,
        transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200)),
    )
    for url in bad_urls:
        with pytest.raises(SourceParseError):
            read_tceq_response(client, url, 100, route="record_pdf")
    assert not calls


def test_rejects_private_dns_before_request(monkeypatch):
    import gridlens.ingestion.adapters.tceq_http as policy

    monkeypatch.setattr(
        policy.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    calls = []
    client = httpx.Client(
        follow_redirects=False,
        transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200)),
    )
    with pytest.raises(SourceParseError, match="non-public"):
        read_tceq_response(client, NSR_LISTING, 100, route="listing")
    assert not calls


def test_rejects_mixed_public_and_private_dns_answers(monkeypatch):
    import gridlens.ingestion.adapters.tceq_http as policy

    monkeypatch.setattr(
        policy.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (None, None, None, None, ("8.8.8.8", 443)),
            (None, None, None, None, ("10.0.0.2", 443)),
        ],
    )
    with pytest.raises(SourceParseError, match="non-public"):
        policy._public_ip(RECORDS_HOST)


def test_redirect_following_client_is_rejected_before_request(monkeypatch):
    import gridlens.ingestion.adapters.tceq_http as policy

    monkeypatch.setattr(policy, "_public_ip", lambda _host: "8.8.8.8")
    calls = []
    client = httpx.Client(
        follow_redirects=True,
        transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200)),
    )
    with pytest.raises(SourceParseError, match="automatically follow redirects"):
        read_tceq_response(client, NSR_LISTING, 100, route="listing")
    assert not calls


@pytest.mark.parametrize(
    "content_type,body,limit",
    [
        ("text/html", b"%PDF-1.7", 100),
        ("application/pdf", b"not pdf", 100),
        ("application/pdf", b"%PDF-" + b"x" * 50, 10),
    ],
)
def test_rejects_wrong_media_signature_and_oversize(content_type, body, limit, monkeypatch):
    import gridlens.ingestion.adapters.tceq_http as policy

    monkeypatch.setattr(policy, "_public_ip", lambda _host: "8.8.8.8")
    client = httpx.Client(
        follow_redirects=False,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, headers={"content-type": content_type}, content=body
            )
        ),
    )
    with pytest.raises((SourceParseError, ValueError)):
        read_tceq_response(client, RECORD_URL, limit, route="record_pdf")


def test_rejects_unapproved_redirect_and_caps_redirect_chain(monkeypatch):
    import gridlens.ingestion.adapters.tceq_http as policy

    monkeypatch.setattr(policy, "_public_ip", lambda _host: "8.8.8.8")
    calls = []
    evil = httpx.Client(
        follow_redirects=False,
        transport=httpx.MockTransport(
            lambda request: calls.append(request)
            or httpx.Response(302, headers={"location": "https://evil.example/a.pdf"})
        ),
    )
    with pytest.raises(SourceParseError):
        read_tceq_response(evil, RECORD_URL, 100, route="record_pdf")
    assert len(calls) == 1

    calls.clear()
    loop = httpx.Client(
        follow_redirects=False,
        transport=httpx.MockTransport(
            lambda request: calls.append(request)
            or httpx.Response(
                302,
                headers={
                    "location": "https://records.tceq.texas.gov/cs/idcplg?"
                    "IdcService=TCEQ_EXTERNAL_SEARCH_GET_FILE&Rendition=Web&dID=7474076"
                },
            )
        ),
    )
    with pytest.raises(httpx.HTTPStatusError):
        read_tceq_response(loop, RECORD_URL, 100, route="record_pdf")
    assert len(calls) == _MAX_REDIRECTS + 1
