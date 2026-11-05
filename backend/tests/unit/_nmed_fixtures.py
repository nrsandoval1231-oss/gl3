"""Synthetic NMED application PDFs and a mock www.env.nm.gov origin (no network, no real files)."""

from __future__ import annotations

import httpx
from _permit_pdf import make_pdf

HOST = "www.env.nm.gov"
BASE = f"https://{HOST}/air-quality/wp-content/uploads/sites/2/"
LISTING = f"https://{HOST}/public-notices/"


def url(month: str = "2025/01", name: str = "A-1092-Jal3-Full-Application") -> str:
    return f"{BASE}{month}/{name}.pdf"


ELECTRIC_PROSE = (
    "The applicant proposes to install three (3) 2,500-hp Siemens electric compressor motors "
    "and the three (3) associated Ariel KBZ compressors at the station."
)
SUPPLY_PROSE = (
    "The station also has one (1) 1,000-kW natural gas-fired generator and "
    "two 5,200-hp Ariel compressors in service."
)
GENERATOR_ONLY = "The project will install four (4) 2,000-kW natural gas-fired generators."


def application_pdf(*pages: str) -> bytes:
    head = ["NEW MEXICO ENVIRONMENT DEPARTMENT", "AIR QUALITY BUREAU", "PERMIT APPLICATION"]
    body = list(pages) if pages else [ELECTRIC_PROSE, SUPPLY_PROSE]
    return make_pdf([head, *[[text] for text in body]])


def listing_html(*hrefs: str) -> bytes:
    links = "".join(f'<li><a href="{h}">link</a></li>' for h in hrefs)
    return f"<html><body><ul>{links}</ul></body></html>".encode()


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class Origin:
    """Mock www.env.nm.gov: per-path body and validators, a request log, forced replies."""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}
        self.log: list[tuple[str, str]] = []
        self.listing: tuple[int, dict, bytes] = (
            200,
            {"content-type": "text/html; charset=UTF-8"},
            listing_html(),
        )
        self.head_status: int | None = None
        self.get_status: int | None = None

    def put(
        self,
        path_url: str,
        body: bytes,
        *,
        etag: str = '"e1"',
        ctype: str = "application/pdf",
        status: int = 200,
    ) -> None:
        self.docs[path_url] = {
            "body": body,
            "etag": etag,
            "ctype": ctype,
            "status": status,
            "last_modified": "Fri, 26 Jan 2024 18:32:10 GMT",
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        full = f"https://{host}{request.url.path}"
        self.log.append((request.method, full))
        assert host == HOST, host
        assert request.headers["user-agent"] == "GridLens public source reader/1.0"
        if request.url.path == "/public-notices/":
            status, headers, content = self.listing
            return httpx.Response(status, headers=headers, content=content)
        if request.method == "HEAD" and self.head_status is not None:
            return httpx.Response(self.head_status, headers={"retry-after": "120"})
        if request.method == "GET" and self.get_status is not None:
            return httpx.Response(self.get_status, headers={"retry-after": "90"})
        entry = self.docs.get(full)
        if entry is None:
            return httpx.Response(404, headers={"content-type": "text/html"}, content=b"<html>")
        if entry["status"] != 200:
            return httpx.Response(entry["status"], headers={"location": "https://x.example/"})
        headers = {
            "content-type": entry["ctype"],
            "etag": entry["etag"],
            "last-modified": entry["last_modified"],
            "content-length": str(len(entry["body"])),
        }
        if request.method == "HEAD":
            return httpx.Response(200, headers=headers)
        return httpx.Response(200, headers=headers, content=entry["body"])

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler), follow_redirects=False)

    def methods(self) -> list[str]:
        return [method for method, _ in self.log]
