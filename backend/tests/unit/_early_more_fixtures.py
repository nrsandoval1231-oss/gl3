"""Small stand-ins for the Comptroller, OCC, Haskell County and TCEQ water-rights pages and PDFs.

Names, labels, dates and sentences are short excerpts of the public pages and documents read live
on 2026-11-04 (Comptroller data-center lists; the OCC Notice of Intent Submissions list and the
Google/Tulsa County attestation form; the Haskell County Commissioners Court page and the agenda of
2026-05-12; the TCEQ pending-applications page and the Ingram Readymix notice). The agenda item 9
and the water notice "requests" sentence are invented to exercise the extractors and are marked.
Everything else is invented structure.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import httpx
from _permit_pdf import make_pdf

from gridlens.ingestion.adapters import tceq_application_documents as shared

UA = shared.USER_AGENT
COMPTROLLER = "comptroller.texas.gov"
OCC = "oklahoma.gov"
HASKELL = "www.haskellcountytx.gov"
TCEQ = "www.tceq.texas.gov"
HOSTS = {COMPTROLLER, OCC, HASKELL, TCEQ}

REGISTRY_URL = f"https://{COMPTROLLER}/taxes/data-centers/data-center-lists.php"
OCC_URL = (
    f"https://{OCC}/occ/divisions/public-utility/energy/electric-utility/"
    "data-center-customer-ratepayer-protection-act.html"
)
OCC_BASE = f"https://{OCC}/content/dam/ok/en/occ/documents/pu/data-center-act/notice-of-intent-submissions/"
OCC_GOOGLE = OCC_BASE + "2026-10-15-google-tulsa-county.pdf"
OCC_EMERALD = OCC_BASE + "2026-07-10-emerald-projectco-pittsburg-county-battles-112.pdf"
HASKELL_URL = f"https://{HASKELL}/page/haskell.Commissioners.Court"
HASKELL_AGENDA = f"https://{HASKELL}/upload/page/7690/docs/Agenda%205.12.26.pdf"
HASKELL_SCAN = f"https://{HASKELL}/upload/page/7690/docs/Agenda%206.23.26.pdf"
TCEQ_URL = f"https://{TCEQ}/permitting/water_rights/wr-permitting/view-wr-pend-apps"
TCEQ_NOTICE = (
    f"https://{TCEQ}/downloads/permitting/water-rights/pending/notice/"
    "ingram-readymix-no-87-llc-23-2653c-notice.pdf"
)

# --------------------------------------------------------------------------- Comptroller


def _cell(value: str | list[str]) -> str:
    if isinstance(value, list):
        return '<td><ul class="dc-list">' + "".join(f"<li>{v}</li>" for v in value) + "</ul></td>"
    return f"<td>{value}</td>"


def registry_row(
    name: str,
    effective: str,
    owner: str | list[str],
    owner_no: str | list[str],
    occupant: str | list[str],
    occupant_no: str | list[str],
    operator: str | list[str],
    operator_no: str | list[str],
    end: str | None = "",
) -> str:
    cells = [owner, owner_no, occupant, occupant_no, operator, operator_no]
    tail = "" if end is None else _cell(end)
    return (
        f'<tr><th scope="row">{name}</th>'
        + _cell(effective)
        + "".join(_cell(c) for c in cells)
        + tail
        + "</tr>"
    )


_HEADER = (
    '<thead><tr><th scope="col">Data Center</th><th scope="col">Effective Date</th>'
    '<th scope="col">Owner Name</th><th scope="col">Owner Registration Number</th>'
    '<th scope="col">Occupant Name</th><th scope="col">Occupant Registration Number</th>'
    '<th scope="col">Operator Name</th><th scope="col">Operator Registration Number</th>'
    '<th scope="col">Exemption End Date</th></tr></thead>'
)

DC_ROW = registry_row(
    "ALE60 Data Center",
    "01/01/2021",
    "COPT San Antonio LP",
    "DC046706-OW1",
    "Amazon Data Services Inc.",
    "DC046706-OC1",
    "Amazon Data Services Inc.",
    "DC046706-OP1",
)
DC_MULTI_ROW = registry_row(
    "3301 Hibbetts Road Data Center",
    "02/20/2024",
    "",
    "",
    "Coreweave, Inc.",
    "DC481494-OC1",
    ["Core Scientific, Inc.", "Coreweave Compute Acquisition Co. II. LLC"],
    ["DC481494-OP1", "DC481494-OP2"],
)
LD_ROW = registry_row(
    "Alpha Digital Campus",
    "10/19/2026",
    "Powerbridge LLC",
    "LD549949-OW1",
    "Powerbridge LLC",
    "LD549949-OC1",
    "Powerbridge LLC",
    "LD549949-OP1",
    "10/19/2036",
)
LD_SHORT_ROW = registry_row(
    "Pecos Ranch Data Center",
    "08/10/2026",
    "Amazon Data Services, Inc.",
    "LD547974-OW1",
    "Amazon Data Services, Inc.",
    "LD547974-OC1",
    "Amazon Data Services, Inc.",
    "LD547974-OP1",
    end=None,
)
NO_NUMBER_ROW = registry_row("Nameless Row", "01/01/2025", "X LLC", "", "X LLC", "", "X LLC", "")


def registry_html(dc_rows: list[str], ld_rows: list[str]) -> bytes:
    def table(rows: list[str]) -> str:
        return f'<table class="data-left scroll">{_HEADER}<tbody>{"".join(rows)}</tbody></table>'

    return (
        "<html><body><h1>Data Centers in Texas</h1>"
        + table(dc_rows)
        + "<!-- Registered Qualifying Large Data Center Projects -->"
        + table(ld_rows)
        + "</body></html>"
    ).encode()


# --------------------------------------------------------------------------- OCC

GOOGLE_LABEL = "Google, LLC - Tulsa County - October 15, 2026"
# The live page separates company, project and county with an en dash (U+2013).
EMERALD_LABEL = "Emerald Project Inc – Battles 112 – Pittsburg County - July 10, 2026"


def occ_html(links: list[tuple[str, str]]) -> bytes:
    items = "".join(f'<li><a href="{href}" target="_blank">{text}</a></li>' for href, text in links)
    return (
        '<html><body><div data-cmp-data-layer="{&#34;dc:title&#34;:&#34;Notice of Intent '
        'Submissions&#34;}" class="cmp-title"></div>'
        '<h2 class="cmp-title__text">Notice of Intent Submissions</h2>'
        f'<div class="cmp-text"><ul>{items}</ul></div>'
        '<a href="https://www.facebook.com/okcorpcomm">Facebook</a></body></html>'
    ).encode()


def occ_links() -> list[tuple[str, str]]:
    return [
        (
            "/content/dam/ok/en/occ/documents/pu/data-center-act/notice-of-intent-submissions/"
            "2026-10-15-google-tulsa-county.pdf",
            GOOGLE_LABEL,
        ),
        (
            "/content/dam/ok/en/occ/documents/pu/data-center-act/notice-of-intent-submissions/"
            "2026-07-10-emerald-projectco-pittsburg-county-battles-112.pdf",
            EMERALD_LABEL,
        ),
    ]


GOOGLE_FORM_PAGES = [
    [
        "Oklahoma Data Center Attestation",
        "Large Load Customer Company Name: Google LLC",
        "Land Purchase Date: 8/21/2026",
        "County(ies): Tulsa County_____________________________________",
        "Planned Utility Provider(s): Public Service Company of Oklahoma (PSO)",
        "Data Center Customer Ratepayer Protection Act of 2026",
        "Pursuant to the Oklahoma Data Center Customer Ratepayer Protection Act of 2026,",
        "17 O.S. 906,",
    ],
    [
        "I, Aaron McGarry [Title] Senior Director",
        "of Google LLC [Company Name], attest that the statements on this form are true.",
        "Adjacent owner: Jane Q. Landowner, 100 County Road 5",
    ],
]


def pdf(pages: list[list[str]]) -> bytes:
    return make_pdf(pages)


# --------------------------------------------------------------------------- Haskell County


def haskell_html(links: list[tuple[str, str]]) -> bytes:
    anchors = "".join(f'<li><a href="{href}">{text}</a></li>' for href, text in links)
    return (
        '<html><body><a href="/page/haskell.Abatement">Tax Abatement Information</a>'
        f"<ul>{anchors}</ul></body></html>"
    ).encode()


def haskell_links() -> list[tuple[str, str]]:
    return [
        ("/upload/page/7690/docs/Agenda 5.12.26.pdf", "May 12, 2026"),
        ("/upload/page/7690/docs/Agenda 6.23.26.pdf", "June 23, 2026"),
        ("/upload/page/7690/docs/Agenda 2.10.26.doc", "February 10, 2026"),
        ("/upload/page/7690/NOTICE OF CANCELLATION- 10.20.26.pdf", "NOTICE OF CANCELLATION"),
        ("/upload/page/9220/docs/Agenda 3.24.26.pdf", "Agenda 3.24.26"),
        ("https://evil.example/upload/page/7690/Agenda.pdf", "Elsewhere"),
    ]


AGENDA_PAGES = [
    [
        "COMMISSIONER'S COURT MEETING",
        "THE COMMISSIONERS' COURT OF HASKELL COUNTY, TEXAS will meet in a regular meeting.",
        "5. Reports, if any, by other Department Heads;",
        "6. Dee Clevenger to discuss selling fireworks for this Memorial Day season.",
        "7. Discuss and take possible action to consider a proposed tax abatement agreement with "
        "Crusoe Energy Systems, LLC, which may include discussion of procedural requirements and "
        "deadlines, proposed terms, and conditions for granting tax abatement, project updates, "
        "infrastructure, transportation planning, and other related matters.",
        "8. Discuss and take possible action on procedures for the abatement of neighborhood "
        "nuisances.",
        # Invented to exercise the field extractors.
        "9. Discuss a data center of 300 MW on 1,200 acres with an investment of $2.5 billion "
        "located near County Road 12.",
        "10. Adjourn",
    ]
]


# --------------------------------------------------------------------------- TCEQ water rights

_WATER_HEADER = (
    "<tr><th>Applicant</th><th>WR No.</th><th>County</th><th>Received by TCEQ</th>"
    "<th>Admin. Complete</th><th>Notice Issued</th><th>Public Meeting</th></tr>"
)
_PENDING = "/downloads/permitting/water-rights/pending"


def water_row(
    applicant: str,
    wr_no: str,
    county: str,
    received: str,
    admin: str = "",
    notice: tuple[str, str] | None = None,
) -> str:
    def link(kind: str, name: str, when: str) -> str:
        href = f"{_PENDING}/{kind}/{name}"
        return f'<td><a href="{href}" target="_blank"><svg><path d="M1"/></svg> {when}</a></td>'

    return (
        f"<tr><td>{applicant}</td><td>{wr_no}</td><td>{county}</td>"
        + link("application", f"{wr_no.lower()}-application.pdf", received)
        + (
            link("admin-complete", f"{wr_no.lower()}-adcpackage.pdf", admin)
            if admin
            else "<td></td>"
        )
        + (link("notice", notice[0], notice[1]) if notice else "<td></td>")
        + "<td></td></tr>"
    )


def tceq_html(*row_groups: list[str]) -> bytes:
    tables = "".join(f"<table>{_WATER_HEADER}{''.join(rows)}</table>" for rows in row_groups)
    return f'<html><body><div class="accordion-body">{tables}</div></body></html>'.encode()


WATER_ROWS = [
    water_row("Kimberlin On the Brazos, LLC", "12-4013D", "Palo Pinto", "9/25/2026"),
    water_row(
        "Ingram Readymix No. 87, L.L.C",
        "23-2653C",
        "Val Verde",
        "5/1/2026",
        "6/2/2026",
        ("ingram-readymix-no-87-llc-23-2653c-notice.pdf", "9/1/2026"),
    ),
]

NOTICE_PAGES = [
    [
        "NOTICE OF APPLICATION TO AMEND A CERTIFICATE OF ADJUDICATION APPLICATION NO. 23-2653C",
        "Ingram Readymix No. 87, L.L.C. (Owner/Applicant) seeks to amend a portion of Certificate "
        "of Adjudication No. 23-2653C to add mining use and a place of use for mining purposes in "
        "Val Verde County.",
        "A portion of Certificate of Adjudication No. 23-2653C (Certificate), as amended, "
        "authorizes Ingram Readymix No. 87, L.L.C to divert and use not to exceed 27.75 acre-feet "
        "of water per year from a point on Cienegas Creek and from a point on the Rio Grande, for "
        "agricultural purposes to irrigate 13.87 acres of land.",
        # Invented to exercise the role classifier.
        "Applicant requests 1,000 acre-feet of water per year for industrial use.",
    ]
]

# --------------------------------------------------------------------------- mock origin


class MoreOrigin:
    """Mock hosts: exact-URL routes, a request log, forced replies."""

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
                "application/pdf" if url.lower().endswith(".pdf") else "text/html; charset=utf-8"
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
        full = f"https://{host}{request.url.raw_path.decode().split('?')[0]}{query}"
        self.log.append((request.method, full))
        assert host in HOSTS, host
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


def occ_origin(form: bytes | None = None) -> MoreOrigin:
    origin = MoreOrigin()
    origin.put(OCC_URL, occ_html(occ_links()))
    origin.put(OCC_GOOGLE, form or pdf(GOOGLE_FORM_PAGES))
    origin.put(OCC_EMERALD, b"%PDF-1.4\n%%EOF")  # a scan: no text layer
    return origin


def haskell_origin(agenda: bytes | None = None) -> MoreOrigin:
    origin = MoreOrigin()
    origin.put(HASKELL_URL, haskell_html(haskell_links()))
    origin.put(HASKELL_AGENDA, agenda or pdf(AGENDA_PAGES))
    origin.put(HASKELL_SCAN, b"%PDF-1.4\n%%EOF")
    return origin


def tceq_origin(notice: bytes | None = None) -> MoreOrigin:
    origin = MoreOrigin()
    origin.put(TCEQ_URL, tceq_html(WATER_ROWS))
    origin.put(TCEQ_NOTICE, notice or pdf(NOTICE_PAGES))
    return origin


def registry_origin(dc_rows=None, ld_rows=None) -> MoreOrigin:
    origin = MoreOrigin()
    origin.put(
        REGISTRY_URL,
        registry_html(
            dc_rows if dc_rows is not None else [DC_ROW, DC_MULTI_ROW],
            ld_rows if ld_rows is not None else [LD_ROW, LD_SHORT_ROW, NO_NUMBER_ROW],
        ),
    )
    return origin
