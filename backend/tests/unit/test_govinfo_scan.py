import base64
import hashlib
from datetime import UTC, datetime

import httpx
import pytest

from gridlens.ingestion.adapters import govinfo_scan

URL = "https://www.govinfo.gov/content/pkg/FR-2026-09-14/pdf/2026-18765.pdf"
HASH = "a" * 64


def test_capture_rejects_nonexact_govinfo_urls_before_network():
    for url in (
        URL.replace("www.govinfo.gov", "evil.example"),
        URL + "?download=1",
        URL.replace("https://", "http://"),
    ):
        with pytest.raises(ValueError):
            govinfo_scan._checked_url(url)


def test_capture_checks_pinned_public_host_mime_magic_hash_and_pages(monkeypatch):
    body = b"%PDF-test"
    monkeypatch.setattr(
        govinfo_scan.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("8.8.8.8", 443))],
    )

    class Page:
        def extract_text(self):
            return ""

    class Reader:
        def __init__(self, _stream, strict):
            assert strict
            self.is_encrypted = False
            self.pages = [Page(), Page()]

    monkeypatch.setattr(govinfo_scan, "PdfReader", Reader)

    original_client = httpx.Client

    class MockClient:
        def __init__(self, **kwargs):
            self.client = original_client(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200,
                        content=body,
                        headers={"content-type": "application/pdf"},
                    )
                ),
                **kwargs,
            )

        def __enter__(self):
            return self.client

        def __exit__(self, *args):
            self.client.close()

    monkeypatch.setattr(govinfo_scan.httpx, "Client", MockClient)
    result = govinfo_scan._capture_worker(
        URL, __import__("hashlib").sha256(body).hexdigest(), govinfo_scan.time.monotonic() + 10
    )
    assert result["page_count"] == 2
    assert result["scanned_pages"] == [1, 2]
    assert result["source_url"] == URL

    with pytest.raises(ValueError, match="changed"):
        govinfo_scan._capture_worker(URL, HASH, govinfo_scan.time.monotonic() + 10)


def test_capture_rejects_private_dns_and_never_follows_redirects(monkeypatch):
    monkeypatch.setattr(
        govinfo_scan.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    with pytest.raises(ValueError, match="public addresses"):
        govinfo_scan._capture_worker(URL, HASH, govinfo_scan.time.monotonic() + 10)


def test_capture_retention_and_write_once_merge():
    raw_pdf = b"%PDF-stub"
    digest = hashlib.sha256(raw_pdf).hexdigest()
    capture = {
        "document_id": "2026-18765",
        "content_hash": digest,
        "page_count": 2,
        "scanned_pages": [1],
        "data_base64": base64.b64encode(raw_pdf).decode("ascii"),
        "source_url": URL,
    }
    with pytest.raises(ValueError, match="explicitly allowed"):
        govinfo_scan.merge_write_once_capture(
            {}, capture, source_allowed=False, retention_allowed=True, retention_reference="test"
        )
    retained = govinfo_scan.merge_write_once_capture(
        {"raw_source_links": {"pdf": [URL]}},
        capture,
        source_allowed=True,
        retention_allowed=True,
        retention_reference="permit:test-source",
        retrieved_at=datetime(2026, 10, 18, tzinfo=UTC),
    )
    assert retained["raw_source_links"]["pdf"] == [URL]
    assert retained[govinfo_scan.CAPTURE_KEY]["source_url"] == URL
    assert retained[govinfo_scan.CAPTURE_KEY]["retention_reference"] == "permit:test-source"
    same = govinfo_scan.merge_write_once_capture(
        retained,
        capture,
        source_allowed=True,
        retention_allowed=True,
        retention_reference="permit:test-source",
    )
    assert same == retained
    changed_pdf = b"%PDF-other"
    changed = {
        **capture,
        "content_hash": hashlib.sha256(changed_pdf).hexdigest(),
        "data_base64": base64.b64encode(changed_pdf).decode("ascii"),
    }
    with pytest.raises(ValueError, match="immutable"):
        govinfo_scan.merge_write_once_capture(
            retained,
            changed,
            source_allowed=True,
            retention_allowed=True,
            retention_reference="permit:test-source",
        )
