"""TCEQ TXR150000 construction stormwater NOIs whose site name matches a data center.

The Water Quality General Permits search posts to www2.tceq.texas.gov/wq_dpa.
This adapter keeps active construction Notices of Intent whose site name contains
"data center" or "datacenter". It does not download every construction NOI in Texas.
The result table has no authorization date, so none is invented. Driving directions
stay in the description and are not the classified place.
"""

from __future__ import annotations

import hashlib
import json
import re
from html import unescape
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

import httpx

from gridlens.domain.air_permit_hours import classify_operating_hours
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.power_signals import power_signal_tags
from gridlens.ingestion.adapters.public_source_http import read_public_response

SOURCE_ID = "texas-tceq-construction-noi"
START_URL = "https://www2.tceq.texas.gov/wq_dpa/"
SEARCH_URL = "https://www2.tceq.texas.gov/wq_dpa/index.cfm"
PERMIT_TYPE = "SWC|Construction Notice of Intent (TXR15)"
SITE_TERMS = ("data center", "datacenter")
MAX_RESPONSE_BYTES = 2_000_000
MAX_RECORDS = 200
_COLUMNS = (
    "auth",
    "site_name",
    "permittee",
    "sic",
    "segment",
    "county",
    "region",
    "city",
    "site_location",
)
_DATA_CENTER = re.compile(r"data\s*cent(?:er|re)|hyperscale", re.IGNORECASE)
_AUTH = re.compile(r"^TXR[0-9A-Z]+$")


def _plain(value: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", value)).split())


def _summary_url(href: str, auth: str) -> str:
    absolute = urljoin(SEARCH_URL, unescape(href))
    parts = urlsplit(absolute)
    if (
        parts.scheme != "https"
        or parts.hostname != "www2.tceq.texas.gov"
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
        or parts.path != "/wq_dpa/index.cfm"
        or parts.fragment
    ):
        raise SourceParseError("TCEQ NOI link is outside the official search host")
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if query.get("fuseaction") != "home.permit_summary" or query.get("lgl_ident_txt") != auth:
        raise SourceParseError("TCEQ NOI link is not that authorization's summary")
    return absolute


def parse_results(body: bytes) -> list[dict[str, str]]:
    text = body.decode("utf-8", errors="replace")
    declared = re.search(r"Your search returned (\d+) records", text)
    if not declared:
        raise SourceParseError("TCEQ NOI search did not state a record count")
    expected = int(declared.group(1))
    if expected == 0:
        if re.search(r"<table", text, re.IGNORECASE):
            raise SourceParseError("TCEQ NOI search says it is empty and contains a table")
        return []
    paging = re.search(r"(\d+)\s*-\s*(\d+)\s+of\s+(\d+)\s+Records", text)
    if not paging or tuple(int(part) for part in paging.groups()) != (1, expected, expected):
        raise SourceParseError("TCEQ NOI search is paginated or its count disagrees")
    table = re.search(r"<table[^>]*>([\s\S]*?)</table>", text, re.IGNORECASE)
    if not table:
        raise SourceParseError("TCEQ NOI search has no result table")
    rows: list[dict[str, str]] = []
    for raw in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", table.group(1), re.IGNORECASE):
        cells = re.findall(r"<td[^>]*>([\s\S]*?)</td>", raw, re.IGNORECASE)
        if not cells:
            continue
        if len(cells) != 9:
            raise SourceParseError("TCEQ NOI result row has an unexpected column count")
        href = re.search(r'href="([^"]+)"', cells[0], re.IGNORECASE)
        auth = _plain(cells[0])
        if not href or not _AUTH.fullmatch(auth):
            raise SourceParseError("TCEQ NOI result row lacks an authorization link")
        values = [_plain(cell) for cell in cells]
        values[0] = auth
        row = dict(zip(_COLUMNS, values, strict=True))
        row["summary_url"] = _summary_url(href.group(1), auth)
        if not row["site_name"] or not row["permittee"] or not row["county"] or not row["city"]:
            raise SourceParseError("TCEQ NOI result row lacks site, permittee, county, or city")
        rows.append(row)
    if len(rows) != expected:
        raise SourceParseError("TCEQ NOI search count does not match its rows")
    return rows


def _record(row: dict[str, str]) -> dict[str, Any]:
    text = f"{row['site_name']} {row['permittee']} {row['site_location']}"
    tags = power_signal_tags(text)
    hours = classify_operating_hours(text)
    place = f"{row['city']}, {row['county']} County, TX"
    row_id = f"TXR150000-{row['auth']}"
    semantic = {**row, "power_signals": tags, "operating_hours": hours}
    return {
        "document_number": row_id,
        "title": f"{row['site_name']} — {row['auth']}",
        "abstract": "\n".join(
            [
                f"Authorization: {row['auth']}",
                f"Site name: {row['site_name']}",
                f"Permittee: {row['permittee']}",
                f"City: {row['city']}",
                f"County: {row['county']}",
                f"Site location: {row['site_location'] or 'not stated'}",
                "Authorization date: not stated on the search result",
                f"Operating-hour rule {hours['rule_id']}: "
                f"{hours['classification'] or 'unclassified'}",
                f"Power signal tags: {', '.join(tags) or 'none'}",
            ]
        ),
        "publication_date": None,
        "event_date": None,
        "event_date_label": None,
        "html_url": row["summary_url"],
        "extraction_location": "TCEQ water-quality general permit search, TXR150000 NOI",
        "source_hash": hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "permit": {
            "source_type": SOURCE_ID,
            "row_id": row_id,
            "applicant": row["permittee"],
            "facility": row["site_name"],
            "permit_numbers": [row["auth"]],
            "permit_type": "TXR150000 construction stormwater NOI",
            "status": "ACTIVE",
            "description": f"{row['site_name']} {row['site_location']}".strip(),
            "location": place,
            "county": row["county"],
            "state": "TX",
            "data_center": bool(_DATA_CENTER.search(text)),
            "power_signals": tags,
            "operating_hours": hours,
            "document_links": {"TCEQ NOI summary": row["summary_url"]},
            "source_fields": {
                "applicant": "Permittee",
                "facility": "Site Name",
                "location": "City and County; site directions are kept in the description",
                "event_date": "not present on the search result",
            },
        },
    }


def _open_advanced() -> bytes:
    return urlencode(
        [
            ("_fuseaction=home.permit_info_search.x", "1"),
            ("_fuseaction=home.permit_info_search.y", "1"),
        ]
    ).encode()


def _search(site_name: str) -> bytes:
    return urlencode(
        [
            ("newsearch", "yes"),
            ("permit_type", PERMIT_TYPE),
            ("permit_status", "ACTIVE"),
            ("start_date", ""),
            ("end_date", ""),
            ("princ_name", ""),
            ("phys_name", site_name),
            ("street_name", ""),
            ("city_name", ""),
            ("goto", "search"),
            ("permitStatusList", "ACTIVE"),
            ("_fuseaction=home.validate_search_crit.x", "1"),
            ("_fuseaction=home.validate_search_crit.y", "1"),
        ]
    ).encode()


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != START_URL:
        raise SourceParseError("TCEQ NOI source ID or endpoint is not configured")
    query = source.get("query", {})
    if (
        query.get("max_response_bytes") != MAX_RESPONSE_BYTES
        or query.get("max_records") != MAX_RECORDS
        or tuple(query.get("site_terms") or ()) != SITE_TERMS
    ):
        raise SourceParseError("TCEQ NOI query bounds are invalid")
    http = client or httpx.Client(timeout=60, follow_redirects=False, trust_env=False)
    try:
        _, start = read_public_response(
            http,
            START_URL,
            max_bytes=MAX_RESPONSE_BYTES,
            allowed_media_types={"text/html"},
        )
        if b"TXR150000" not in start:
            raise SourceParseError("TCEQ water-quality search is not the expected page")
        _, advanced = read_public_response(
            http,
            SEARCH_URL,
            max_bytes=MAX_RESPONSE_BYTES,
            allowed_media_types={"text/html"},
            method="POST",
            content=_open_advanced(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if b"validate_search_crit" not in advanced:
            raise SourceParseError("TCEQ NOI advanced search form did not open")
        kept: dict[str, dict[str, str]] = {}
        for term in SITE_TERMS:
            _, body = read_public_response(
                http,
                SEARCH_URL,
                max_bytes=MAX_RESPONSE_BYTES,
                allowed_media_types={"text/html"},
                method="POST",
                content=_search(term),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            for row in parse_results(body):
                prior = kept.get(row["auth"])
                if prior is not None and prior != row:
                    raise SourceParseError("TCEQ NOI authorization was returned with a conflict")
                kept.setdefault(row["auth"], row)
        if len(kept) > MAX_RECORDS:
            raise SourceParseError("TCEQ NOI count exceeds its bound")
        return [_record(kept[auth]) for auth in sorted(kept)]
    finally:
        if client is None:
            http.close()
