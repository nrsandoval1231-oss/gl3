"""Synthetic Oklahoma DEQ evaluation memoranda and a mock origin (no network, no real files)."""

from __future__ import annotations

import httpx
from _permit_pdf import make_pdf

from gridlens.ingestion.adapters.ok_deq_public_review import _record

HOST = "applications.deq.ok.gov"
BASE = f"https://{HOST}/permitspublic/storedpermits/"

# West Edmond (permit 2017-0987-C M-2): prose says three 2,500-hp electric motors; the EUG-17
# table lists the driven Ariel compressors at 5,200 rated hp with no driver column.
WEST_EDMOND_PROSE = (
    "OGS requests authorization to add three (3) 2,500-hp Siemens electric compressor motors "
    "and the three (3) associated Ariel KBZ compressors, one (1) 2,500-hp Waukesha 9394 GSI "
    "emergency generator, and associated fugitive components."
)
WEST_EDMOND_TABLE = [
    "EUG-17: Affected Compressors",
    "Operating Rated Manufacture Serial",
    "Emission Unit Description",
    "Speed Horsepower Date Number",
    "C-0701, Ariel Model KBZ 1,000 RPM 5,200 2022 F66626",
    "C-0801, Ariel Model KBZ 1,000 RPM 5,200 2022 F66698",
    "C-0901, Ariel Model KBZ 1,000 RPM 5,200 2022 F66773",
]
GENERATORS = "The project will install four (4) 2,000-kW natural gas-fired generators."


def memo_pdf(
    *,
    permit: str | None = "2017-0987-C (M-2)",
    company: str = "ONEOK Gas Storage, L.L.C.",
    facility: str = "West Edmond Compressor Station",
    date: str = "March 9, 2023",
    body: list[list[str]] | None = None,
) -> bytes:
    header = ["DRAFT/PROPOSED", "OKLAHOMA DEPARTMENT OF ENVIRONMENTAL QUALITY"]
    header += ["AIR QUALITY DIVISION", f"MEMORANDUM {date}", "TO: Phillip Fielder, P.E."]
    if permit is not None:
        header += [f"SUBJECT:  Evaluation of Permit Application No. {permit}"]
    else:
        header += ["SUBJECT:  Evaluation of a permit application"]
    header += [f"   {company}", f"   {facility} (Facility ID: 1226)", "   Logan County, Oklahoma"]
    header += ["SECTION I.  INTRODUCTION"]
    pages = body if body is not None else [[WEST_EDMOND_PROSE], WEST_EDMOND_TABLE]
    return make_pdf([header, *pages])


def listing_record(
    permit_no: str = "2017-0987-C M-2",
    company: str = "ONEOK Gas Storage, L.L.C.",
    facility: str = "West Edmond Compressor Station",
) -> dict:
    row = {
        "permit_no": permit_no,
        "division": "AQD",
        "county": "LOGAN",
        "company": company,
        "facility": facility,
        "tier": "Tier I",
        "permit_type": "Minor Source Construction Permit",
        "step": "Technical Review",
        "status": "Under DEQ Review",
        "location": "Logan County, OK",
        "event_date": None,
        "html_url": "https://applications.deq.ok.gov/PermitsPublicReview/permitinformation.aspx?id=1",
        "tags": [],
    }
    return _record(row)


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
    """Mock applications.deq.ok.gov: per-key body and validators, request log."""

    def __init__(self) -> None:
        self.docs: dict[int, dict] = {}
        self.log: list[tuple[str, str]] = []
        self.times: list[float] = []
        self.fake = FakeClock()
        self.head_status: int | None = None  # force every HEAD to this status
        self.other: dict[str, tuple[int, dict, bytes]] = {}

    def put(
        self,
        key: int,
        body: bytes,
        *,
        etag: str = '"e1"',
        ctype: str = "application/pdf",
        status: int = 200,
    ) -> None:
        self.docs[key] = {
            "body": body,
            "etag": etag,
            "ctype": ctype,
            "status": status,
            "last_modified": "Mon, 02 Nov 2026 10:00:00 GMT",
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.times.append(self.fake.now)
        host = request.headers["host"]
        self.log.append((request.method, f"https://{host}{request.url.path}"))
        if host != HOST:
            status, headers, content = self.other.get(
                f"https://{host}{request.url.path}", (404, {}, b"")
            )
            return httpx.Response(status, headers=headers, content=content)
        if request.method == "HEAD" and self.head_status is not None:
            return httpx.Response(self.head_status, headers={"retry-after": "120"})
        key = int(request.url.path.rsplit("/", 1)[-1].removesuffix(".pdf"))
        entry = self.docs.get(key)
        if entry is None:
            return httpx.Response(404, headers={"content-type": "text/html"}, content=b"<html>")
        if entry["status"] != 200:
            return httpx.Response(entry["status"], headers={"retry-after": "30"})
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

    def count(self, method: str) -> int:
        return sum(1 for item in self.log if item[0] == method)
