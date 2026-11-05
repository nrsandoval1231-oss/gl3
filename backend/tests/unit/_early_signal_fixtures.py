"""Small synthetic stand-ins for ERCOT RPG, TPIT and PUCT Interchange pages (no network, no files).

The sentences are short excerpts of the public documents read live on 2026-11-04 (ERCOT RPG
status update for 25RPG020 and 25RPG046; PUCT dockets 58015 and 59549), with names kept as stated
there. Everything else is invented structure.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections.abc import Callable
from datetime import datetime

import httpx
import openpyxl
from _permit_pdf import make_pdf

ERCOT = "www.ercot.com"
PUCT = "interchange.puc.texas.gov"
UA = "GridLens public source reader/1.0"

HUB = f"https://{ERCOT}/committees/other/rpg"
PLANNING = f"https://{ERCOT}/gridinfo/planning"
MEETING = f"https://{ERCOT}/calendar/07212026-RPG-Meeting"
STATUS_PDF = (
    f"https://{ERCOT}/files/docs/2026/07/17/"
    "6.-StatusUpdate_Combined_CPS-Energy-Large-Load-Additions-Project-and-STEC-Medina-County-"
    "Large-Load-Project_July2026_RPG.pdf"
)
OVERVIEW_PDF = f"https://{ERCOT}/files/docs/2026/07/17/16.-26RPG022-AEN-Dunlap-to-Decker-138-kV-Line-Project-Overview.pdf"
AGENDA_PDF = f"https://{ERCOT}/files/docs/2026/07/17/1.-Agenda.pdf"
TPIT_XLSX = f"https://{ERCOT}/files/docs/2022/03/02/ERCOT-October-TPIT-No-Cost-100126.xlsx"
SYSPLAN_PDF = (
    f"https://{ERCOT}/files/docs/2026/09/07/8-System-Planning-and-Weatherization-Update.pdf"
)


_FIXED = datetime(2026, 1, 1)


def _xlsx_bytes(wb: openpyxl.Workbook) -> bytes:
    """Byte-identical output for identical content.

    openpyxl stamps the document properties and every zip entry with the current time, so two
    builds of the same workbook in different seconds differ in bytes (and so in hash and ETag).
    """
    wb.properties.created = _FIXED
    wb.properties.modified = _FIXED
    raw = io.BytesIO()
    wb.save(raw)
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(raw.getvalue())) as source,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for info in source.infolist():
            clone = zipfile.ZipInfo(info.filename, date_time=(2026, 1, 1, 0, 0, 0))
            clone.compress_type = zipfile.ZIP_DEFLATED
            clone.external_attr = info.external_attr
            data = source.read(info.filename)
            if info.filename == "docProps/core.xml":
                # openpyxl resets "modified" to now on save, whatever the property says.
                data = re.sub(
                    rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:)",
                    rb"\g<1>2026-01-01T00:00:00Z\g<2>",
                    data,
                )
            target.writestr(clone, data)
    return out.getvalue()


def hub_html(*meetings: str) -> bytes:
    links = "".join(f'<li><a href="{m}">m</a></li>' for m in meetings)
    other = '<a href="/committees/other/rpg/2025">2025</a><a href="https://evil.example/calendar/01012026-RPG-Meeting">x</a>'
    return f"<html><body>{links}{other}</body></html>".encode()


def listed_file(url: str, title: str, listed: str, kind: str = "pdf", size: str = "3.8 MB") -> str:
    return (
        '<div class="row wrapper"><div class="col pl-2"><div class="row">'
        '<div class="col-12 col-md">'
        f'<a rel="noopener" target="_blank" href="{url}" title="{title}" class="d-block pb-2">'
        f'{title}</a><div class="row"><div $field="description_t" class="col"></div></div></div>'
        f'<div class="mb-2 caption col-12 col-md-2">'
        f'<span class="">{listed} - {kind} - {size}</span>'
        "</div></div></div></div>"
    )


def meeting_html(*docs: tuple[str, str, str]) -> bytes:
    return ("<html><body>" + "".join(listed_file(*d) for d in docs) + "</body></html>").encode()


def planning_html(*, tpit_listed: str = "Oct 23, 2026") -> bytes:
    return (
        "<html><body>"
        + listed_file(
            "https://www.ercot.com/files/docs/2021/10/22/Archived-Transmission-Project-and-Information-Tracking.zip",
            "Archived Transmission Project and Information Tracking",
            "Jul 17, 2026",
            "zip",
        )
        + listed_file(
            TPIT_XLSX,
            "Transmission Project and Information Tracking",
            tpit_listed,
            "xlsx",
            "566.8 KB",
        )
        + "</body></html>"
    ).encode()


STATUS_PAGES = [
    [
        "Combined CPS Energy Large Load",
        "Additions Project (25RPG020) and STEC Medina County Load Project (25RPG046)",
    ],
    [
        "Introduction",
        "PUBLIC",
        "CPS Energy submitted the Large Load Additions Project (25RPG020) for ERCOT",
        "Regional Planning Group (RPG) review in June 2025",
        "- This is a Tier 1 project with an estimated cost of approximately $333.7 million",
        "and will",
        "require a Certificate of Convenience and Necessity (CCN)",
        "- Estimated in-service date (ISD) is Summer Peak 2035",
        "- This project is needed to addresses post-contingency reliability in Bexar and Medina",
        "counties with the addition of approximately 2 GW Load by 2035",
    ],
    [
        "Introduction",
        "PUBLIC",
        "South Texas Electric Cooperative (STEC) submitted the Medina County Load",
        "Project (25RPG046)",
        "for ERCOT Regional Planning Group (RPG) review in December 2025",
        "- This is a Tier 1 project with an estimated cost of $492 million and will require a",
        "Certificate of Convenience and Necessity (CCN)",
        "- Estimated in-service date (ISD) is June 2031",
        "- Addresses post-contingency reliability concerns seen by STEC with the addition of",
        "approximately 1 GW Load",
    ],
    [
        "Study Assumption",
        "Load Updates",
        "- Approximately 980 MW of new STEC load was added in the study area",
    ],
]
# "-" bullets are rendered as a middle-dot bullet (Latin-1 safe for the minimal PDF writer).
STATUS_PAGES = [
    [ln.replace("- ", "· ", 1) if ln.startswith("- ") else ln for ln in p] for p in STATUS_PAGES
]


def status_pdf(pages: list[list[str]] | None = None) -> bytes:
    return make_pdf(pages or STATUS_PAGES)


OVERVIEW_PAGES = [
    [
        "26RPG022 AEN Dunlap to Decker 138-kV Line Project Overview",
        "AEN submitted the Dunlap to Decker 138-kV Line Project (26RPG022)",
        "for RPG review in May 2026",
        "· This is a Tier 2 project with an estimated cost of $41.2 million and will not require a",
        "Certificate of Convenience and Necessity (CCN)",
        "· The project is in Travis County and adds a new Whitetail 138-kV substation",
    ]
]


def workbook(sheets: dict[str, list[dict[str, str | None]]]) -> bytes:
    """A TPIT-shaped workbook: title row, header row, data rows (contact column included)."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    cost = wb.create_sheet("ImprovementCostSummary10232026")
    cost.append(["x"])
    headers = [
        "ERCOT Project Number",
        "Project Title (text, please start with l",
        "Project Description (text)",
        "Comments/Reasons for Delays/Changes/Spee",
        'Terminal "from" Location',
        'Terminal "to" Location',
        'Transmission Status "under construction,',
        "Transmission Owner (text)",
        "TSP/Company Contact",
        "Projected In-Service Date (Month/Yr)",
        "Actual In-Service Date (Month/Yr)",
        "Service Level kV",
        "Autotransformer Capacity (MVA)",
        "County Location for Substation or Starti",
        "County Location for Ending Point for a L",
        "Planning Charter Tier ",
        "RPG Number",
    ]
    keys = [
        "number",
        "title",
        "description",
        "comments",
        "from",
        "to",
        "status",
        "owner",
        "contact",
        "isd",
        "actual",
        "kv",
        "mva",
        "county",
        "county_end",
        "tier",
        "rpg",
    ]
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        ws.append(["OCTOBER BASE FOR TRANSMISSION OWNER SUBMISSIONS"])
        ws.append(headers)
        for row in rows:
            ws.append([row.get(k) for k in keys])
    return _xlsx_bytes(wb)


def tpit_row(number: str, **kw: str | None) -> dict[str, str | None]:
    base: dict[str, str | None] = {
        "number": number,
        "title": f"Project {number}",
        "description": "Expand station to connect a large load",
        "status": "Planned",
        "owner": "CTT",
        "contact": "Jane Doe jane.doe@example.com",
        "isd": "2027-01-31",
        "kv": "345",
        "county": "Hall",
        "tier": "Tier 4",
        "rpg": None,
    }
    base.update(kw)
    return base


SHEETS = {
    "FutureTPIT100126NoCost": [
        tpit_row("100305"),
        tpit_row(
            "90051",
            title="Riley: Construct New 345 kV Terminal",
            description="Interconnect the Sabey Data Center load",
            county="Wilbarger",
        ),
        tpit_row(
            "110828", title="STEC Mesquite Large Load Project Phase 1", tier="Tier 2", owner="STEC"
        ),
        tpit_row("99999", description="Replace breaker", title="Breaker", tier="Tier 4"),
    ],
    "PlannedTPIT100126NoCost": [
        tpit_row("73025", tier="Tier 1", rpg="22RPG005", description="New substation")
    ],
    "CompletedTPIT100126NoCost": [
        tpit_row("81726", status="In-Service", tier="Tier 3", description="Mobile substation")
    ],
    "CancelledTPIT100126NoCost": [
        tpit_row("81573", status="Conceptual", description="Interconnect the Alpha load")
    ],
}


# --------------------------------------------------------------------------- PUCT

CASE_59549 = (
    "APPLICATION OF CITY PUBLIC SERVICE BOARD (CPS ENERGY) TO AMEND ITS CERTIFICATE OF "
    "CONVENIENCE AND NECESSITY FOR THE PROPOSED LEGEND FALLS 138-KV TRANSMISSION LINE PROJECT "
    "IN MEDINA COUNTY"
)
CASE_58015 = (
    "APPLICATION OF AEP TEXAS INC. TO AMEND ITS CERTIFICATE OF CONVENIENCE AND NECESSITY FOR "
    "THE RIO BRAVO-TO-WORMSER ROAD 138-KV CUT-IN TO MANGANA HEIN SUBSTATION DOUBLE-CIRCUIT "
    "TRANSMISSION LINE IN WEBB COUNTY"
)
CASE_GEN = (
    "APPLICATION OF EL PASO ELECTRIC COMPANY TO AMEND ITS CERTIFICATE OF CONVENIENCE AND "
    "NECESSITY FOR A 366 MW NATURAL GAS GENERATION FACILITY"
)


def search_html(rows: list[tuple[str, str, str, str]]) -> bytes:
    body = "".join(
        f'<tr><td><a href="/Search/Filings?ControlNumber={c}">{c}</a></td>'
        f"<td>{f}</td><td>{u}</td><td>{d}</td></tr>"
        for c, f, u, d in rows
    )
    return f"<html><body>{len(rows)} record(s) found<table>{body}</table></body></html>".encode()


def export_xlsx(rows: list[tuple[str, str, str, str]]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Control #", "Filings", "Utility", "Description (Case Style)"])
    for c, f, u, d in rows:
        ws.append([c, f, u, d])
    return _xlsx_bytes(wb)


def filings_html(control: str, items: list[tuple[str, str, str, str, str]]) -> bytes:
    rows = "".join(
        f'<tr><td><strong><a href="/search/documents/?controlNumber={control}'
        f'&amp;itemNumber={i}">{i}</a>'
        f"</strong></td><td> {d} </td><td> {p} </td><td> {t} </td><td> {desc} </td></tr>"
        for i, d, p, t, desc in items
    )
    return f"<html><body><table><tr><th>Item</th></tr>{rows}</table></body></html>".encode()


def documents_html(control: str, item: str, doc_ids: list[tuple[str, str]]) -> bytes:
    links = "".join(
        f'<a href="https://{PUCT}/Documents/{control}_{item}_{i}.{ext}">{control}_{item}_{i}</a>'
        for i, ext in doc_ids
    )
    return f"<html><body>{links}</body></html>".encode()


APPLICATION_PAGES = [
    ["Description of Project"],
    [
        "The Proposed Project consists of constructing one new substation (the Legend Falls",
        "Substation) and two segments of a new double-circuit 138 kV transmission line",
        "located in far east Medina County, Texas.",
        "The total estimated cost for the Proposed Project ranges between $26.79 million to",
        "$31.15 million depending on the route.",
        "The Rio Medina Project was proposed to serve 129 MW of load at the proposed new",
        "Rio Medina 138 kV substation.",
    ],
]
ORDER_PAGES = [
    [
        "In addition to the general area load growth, a commercial customer has submitted",
        "a request",
        "for approximately 10 megawatts of load capacity to be served from the Sierra Vista",
        "substation transformer number 2. The estimated cost for the proposed single routing",
        "option is approximately $9.82 million.",
    ]
]


def pdf(pages: list[list[str]]) -> bytes:
    return make_pdf(pages)


# --------------------------------------------------------------------------- mock origin


class Origin:
    """Mock ERCOT and PUCT hosts: exact-URL routes, a request log, forced replies."""

    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, dict[str, str], bytes]] = {}
        self.log: list[tuple[str, str]] = []
        self.force: Callable[[str], httpx.Response | None] | None = None

    def put(
        self,
        url: str,
        body: bytes,
        *,
        ctype: str | None = None,
        status: int = 200,
        etag: str | None = "auto",
    ) -> None:
        if ctype is None:
            ctype = (
                "application/pdf"
                if url.lower().endswith(".pdf")
                else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                if ("xlsx" in url or "exportdockets" in url)
                else "text/html; charset=utf-8"
            )
        headers = {"content-type": ctype}
        if etag == "auto":
            etag = '"' + hashlib.sha256(body).hexdigest()[:12] + '"'
        if etag:
            headers["etag"] = etag
        self.routes[url] = (status, headers, body)

    def handler(self, request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        query = f"?{request.url.query.decode()}" if request.url.query else ""
        full = f"https://{host}{request.url.path}{query}"
        self.log.append((request.method, full))
        assert host in {ERCOT, PUCT}, host
        assert request.headers["user-agent"] == UA
        if self.force is not None and (forced := self.force(full)) is not None:
            return forced
        route = self.routes.get(full)
        if route is None:
            return httpx.Response(404, headers={"content-type": "text/html"}, content=b"<html>")
        status, headers, body = route
        if status != 200:
            return httpx.Response(status, headers={"location": "https://x.example/"})
        if request.headers.get("if-none-match") and request.headers["if-none-match"] == headers.get(
            "etag"
        ):
            return httpx.Response(304, headers={"etag": headers["etag"]})
        return httpx.Response(
            200, headers={**headers, "content-length": str(len(body))}, content=body
        )

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler), follow_redirects=False)

    def urls(self) -> list[str]:
        return [u for _, u in self.log]


def ercot_origin(status_body: bytes | None = None, tpit_body: bytes | None = None) -> Origin:
    o = Origin()
    o.put(HUB, hub_html(MEETING))
    o.put(
        MEETING,
        meeting_html(
            (STATUS_PDF, "6. StatusUpdate_Combined_CPS Energy Large Load", "Jul 17, 2026"),
            (
                OVERVIEW_PDF,
                "16. 26RPG022 AEN Dunlap to Decker 138-kV Line Project Overview",
                "Jul 17, 2026",
            ),
            (AGENDA_PDF, "1. Agenda", "Jul 17, 2026"),
        ),
    )
    o.put(PLANNING, planning_html())
    o.put(STATUS_PDF, status_body or status_pdf())
    o.put(OVERVIEW_PDF, pdf(OVERVIEW_PAGES))
    o.put(TPIT_XLSX, tpit_body or workbook(SHEETS))
    return o
