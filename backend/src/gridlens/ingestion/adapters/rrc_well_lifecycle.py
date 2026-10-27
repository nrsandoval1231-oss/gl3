"""Identity-bound lifecycle fields from the official RRC W-1 detail page."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup, Tag

from gridlens.ingestion.adapters.bounded_http import remaining_seconds
from gridlens.ingestion.adapters.federal_register import SourceParseError

MAX_DETAIL_BYTES = 1_000_000
SEARCH_FORM_URL = (
    "https://webapps2.rrc.texas.gov/EWA/drillingPermitsQueryAction.do"
    "?methodToCall=search&pager.offset=0&pager.pageSize=10"
)
_DATE = re.compile(r"\d{2}/\d{2}/\d{4}\Z")
_API = re.compile(r"\d{8}\Z")
_PERMIT = re.compile(r"\d{7}\Z")
_OPERATOR = re.compile(r"\d{6}\Z")


@dataclass(frozen=True)
class WellIdentity:
    api_number: str | None
    permit_number: str
    operator_number: str
    lease: str
    well_number: str
    county_code: str
    county: str | None = None
    operator_name: str | None = None


class _Inputs(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "input":
            return
        row = dict(attrs)
        name, value = row.get("name"), row.get("value")
        if name and value is not None:
            self.values.setdefault(name, []).append(value.strip())


def _one(values: dict[str, list[str]], name: str) -> str:
    rows = values.get(name, [])
    if len(rows) != 1:
        raise SourceParseError("RRC W-1 detail has missing or duplicate identity field")
    return rows[0]


def _norm(value: str) -> str:
    return " ".join(value.split()).casefold()


def _api8(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return digits[2:] if len(digits) == 10 and digits.startswith("42") else digits


def _canonical_api(value: str) -> str:
    digits = _api8(value)
    return f"42{digits}" if re.fullmatch(r"\d{8}", digits) else ""


def _date(value: str) -> str | None:
    if not value:
        return None
    if not _DATE.fullmatch(value):
        raise SourceParseError("RRC W-1 lifecycle date has unexpected format")
    try:
        return datetime.strptime(value, "%m/%d/%Y").date().isoformat()
    except ValueError as exc:
        raise SourceParseError("RRC W-1 lifecycle date is invalid") from exc


def parse_w1_detail(
    body: bytes, expected: WellIdentity, *, evidence_ref: str | None = None
) -> dict[str, Any]:
    """Parse only exact official hidden fields after matching the full well identity.

    The current W-1 detail may have blank spud/completion dates. Blank is unknown.
    Permit issue/effective dates are never used as drilling lifecycle events.
    """
    if not isinstance(body, bytes) or not body or len(body) > MAX_DETAIL_BYTES:
        raise SourceParseError("RRC W-1 detail is empty or exceeds its byte bound")
    text = body.decode("latin-1")
    if "Drilling Permit (W-1) Query" not in text:
        raise SourceParseError("RRC page is not a W-1 detail record")
    parser = _Inputs()
    parser.feed(text)
    values = parser.values
    actual = {
        "permit": _one(values, "detailRecord.statusNoHndlr.inputValue"),
        "api": _one(values, "detailRecord.apiNoHndlr.inputValue"),
        "operator": _one(values, "detailRecord.operatorNoHndlr.inputValue"),
        "operator_name": _one(values, "detailRecord.operatorNameHndlr.inputValue"),
        "lease": _one(values, "detailRecord.leaseNameHndlr.inputValue"),
        "well": _one(values, "detailRecord.wellNoHndlr.inputValue"),
        "county_code": _one(values, "detailRecord.countyCodeHndlr.inputValue"),
        "county": _one(values, "detailRecord.countyNameHndlr.inputValue"),
    }
    if not (
        (expected.api_number is None or _API.fullmatch(_api8(expected.api_number)))
        and _PERMIT.fullmatch(expected.permit_number)
        and _OPERATOR.fullmatch(expected.operator_number)
        and expected.county_code.isdigit()
        and _API.fullmatch(actual["api"])
        and (expected.api_number is None or _api8(actual["api"]) == _api8(expected.api_number))
        and actual["permit"].zfill(7) == expected.permit_number
        and actual["operator"] == expected.operator_number
        and (
            expected.operator_name is None
            or _norm(actual["operator_name"]) == _norm(expected.operator_name)
        )
        and _norm(actual["lease"]) == _norm(expected.lease)
        and _norm(actual["well"]) == _norm(expected.well_number)
        and actual["county_code"] == expected.county_code
        and (expected.county is None or _norm(actual["county"]) == _norm(expected.county))
    ):
        raise SourceParseError("RRC W-1 detail identity does not match the expected well")

    spud = _date(_one(values, "detailRecord.spudDtHndlr.inputValue"))
    completion = _date(_one(values, "detailRecord.completionDtHndlr.inputValue"))
    events = []
    if spud:
        events.append(
            {
                "kind": "spud",
                "label": "Drilling started",
                "date": spud,
                "source": "texas-rrc-w1-detail",
                "evidence_refs": [evidence_ref] if evidence_ref else [],
            }
        )
    if completion:
        events.append(
            {
                "kind": "rrc_w1_completion_date",
                "label": "RRC W-1 completion date",
                "date": completion,
                "source": "texas-rrc-w1-detail",
                "evidence_refs": [evidence_ref] if evidence_ref else [],
            }
        )
    identity = {
        "api": actual["api"],
        "api_number": _canonical_api(actual["api"]),
        "permit": actual["permit"],
        "permit_number": expected.permit_number,
        "operator": actual["operator_name"],
        "operator_number": actual["operator"],
        "lease": actual["lease"],
        "well": actual["well"],
        "well_number": actual["well"],
        "county_code": actual["county_code"],
        "county": actual["county"],
    }
    return {
        "source": "texas-rrc-w1-detail",
        "identity_validated": True,
        "identity": identity,
        "asset_identity": {
            "kind": "us_well_api",
            "value": _canonical_api(actual["api"]),
            "source": "texas-rrc-w1-detail",
            "evidence_refs": [evidence_ref] if evidence_ref else [],
        },
        "spud_date": spud,
        "rrc_w1_completion_date": completion,
        "events": events,
    }


def _packet_fields(body: bytes) -> dict[str, str]:
    if not isinstance(body, bytes) or not body or len(body) > MAX_DETAIL_BYTES:
        raise SourceParseError("RRC completion packet is empty or exceeds its byte bound")
    text = body.decode("latin-1")
    if "Packet Summary Data" not in text:
        raise SourceParseError("RRC page is not a completion packet detail")
    soup = BeautifulSoup(text, "html.parser")
    labels = (
        "Tracking No.",
        "Status:",
        "Operator Name:",
        "Type Of Completion:",
        "Completion or Recompletion Date:",
        "Lease Name:",
        "County:",
        "Well No.",
        "API No.:",
        "Drilling Permit No:",
    )
    fields: dict[str, str] = {}
    for cell_element in soup.find_all("td"):
        if not isinstance(cell_element, Tag):
            continue
        cell = cell_element
        value = " ".join(cell.get_text(" ", strip=True).split())
        for label in labels:
            if value.startswith(label):
                remainder = value[len(label) :].strip()
                strong = cell.find("strong")
                if isinstance(strong, Tag):
                    remainder = " ".join(strong.get_text(" ", strip=True).split())
                if remainder:
                    fields[label.rstrip(":")] = remainder
    return fields


def parse_completion_packet(
    body: bytes,
    expected: WellIdentity,
    *,
    evidence_ref: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    """Join an official W-2 completion packet to a well by API and full identity.

    Recompletion dates retain their historical meaning. The packet's approval date
    is not promoted to a completion date, and its prior permit remains separately named.
    """
    fields = _packet_fields(body)
    safe_source_url = (
        _sanitized_source_url(source_url, allowed_path="/CMPL/") if source_url else None
    )
    operator_match = re.fullmatch(r"(.+?)\s*\((\d{6})\)", fields.get("Operator Name", ""))
    api_digits = _api8(fields.get("API No.", ""))
    permit = re.sub(r"\D", "", fields.get("Drilling Permit No", ""))
    packet = fields.get("Tracking No.", "")
    if not (
        re.fullmatch(r"\d{6,7}", packet)
        and re.fullmatch(r"\d{8}", api_digits)
        and (expected.api_number is None or api_digits == _api8(expected.api_number))
        and operator_match
        and operator_match.group(2) == expected.operator_number
        and _norm(fields.get("Lease Name", "")) == _norm(expected.lease)
        and re.sub(r"\s+", "", fields.get("Well No.", "")).casefold()
        == re.sub(r"\s+", "", expected.well_number).casefold()
        and (expected.county is None or _norm(fields.get("County", "")) == _norm(expected.county))
        and re.fullmatch(r"Approved\s*\(\d{2}/\d{2}/\d{4}\)", fields.get("Status", ""))
    ):
        raise SourceParseError("RRC completion packet identity does not match the expected well")
    completion_date = _date(fields.get("Completion or Recompletion Date", ""))
    completion_type = fields.get("Type Of Completion", "")
    if not completion_date or not completion_type:
        raise SourceParseError("RRC completion packet lacks a typed completion date")
    is_recompletion = "recompletion" in completion_type.casefold()
    is_initial_completion = (
        "initial" in completion_type.casefold() and "completion" in completion_type.casefold()
    ) or completion_type.casefold() == "new well"
    if not is_recompletion and not is_initial_completion:
        raise SourceParseError("RRC completion packet type has no supported lifecycle meaning")
    event = {
        "kind": "historical_recompletion" if is_recompletion else "historical_completion",
        "label": "Recompletion reported (historical)"
        if is_recompletion
        else "Completion reported (historical)",
        "date": completion_date,
        "source": "texas-rrc-completion-packet",
        "evidence_refs": [evidence_ref] if evidence_ref else [],
    }
    return {
        "source": "texas-rrc-completion-packet",
        "identity_validated": True,
        "packet_number": packet,
        "identity": {
            "api": api_digits,
            "api_number": _canonical_api(api_digits),
            "operator_number": operator_match.group(2),
            "operator": operator_match.group(1).strip(),
            "lease": fields["Lease Name"],
            "well": fields["Well No."].strip(),
            "well_number": fields["Well No."].strip(),
            "county": fields.get("County"),
        },
        "asset_identity": {
            "kind": "us_well_api",
            "value": _canonical_api(api_digits),
            "source": "texas-rrc-completion-packet",
            "evidence_refs": [evidence_ref] if evidence_ref else [],
        },
        "related_drilling_permit": permit or None,
        "completion_type": completion_type,
        "completion_date": completion_date,
        "content_hash": hashlib.sha256(body).hexdigest(),
        "source_url": safe_source_url,
        "events": [event],
    }


def _official_url(base: str, action: str) -> str:
    url = urljoin(base, action)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "webapps2.rrc.texas.gov"
        or not parsed.path.startswith("/EWA/")
    ):
        raise SourceParseError("RRC detail form left the reviewed official host or path")
    return url


def _sanitized_source_url(url: str, *, allowed_path: str) -> str:
    """Retain a stable official citation without transient RRC session state."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc
        != {"/EWA/": "webapps2.rrc.texas.gov", "/CMPL/": "webapps.rrc.texas.gov"}.get(allowed_path)
        or not parsed.path.startswith(allowed_path)
    ):
        raise SourceParseError("RRC source URL is outside the reviewed official host")
    path = re.sub(r";(?:j?sessionid)=[^/;?]+", "", parsed.path, flags=re.I)
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in {"rrcactionman", "jsessionid", "sessionid"}
        ]
    )
    return urlunsplit(("https", parsed.netloc, path, query, ""))


def _bounded_request(
    client: httpx.Client,
    method: str,
    url: str,
    deadline: float,
    *,
    data: dict[str, str] | None = None,
    budget: list[int],
) -> tuple[str, bytes]:
    response_url = url
    for _ in range(2):
        if budget[0] <= 0:
            raise SourceParseError("RRC request count exceeds its bound")
        budget[0] -= 1
        remaining = remaining_seconds(deadline)
        with client.stream(
            method,
            response_url,
            data=data,
            follow_redirects=False,
            timeout=min(20, remaining or 20),
        ) as response:
            if response.status_code in {302, 303}:
                location = response.headers.get("location")
                if not location:
                    raise SourceParseError("RRC detail redirect lacks a target")
                response_url = _official_url(response_url, location)
                method, data = "GET", None
                continue
            response.raise_for_status()
            content: list[bytes] = []
            size = 0
            for part in response.iter_bytes():
                remaining_seconds(deadline)
                size += len(part)
                if size > MAX_DETAIL_BYTES:
                    raise SourceParseError("RRC detail response exceeds its byte bound")
                content.append(part)
            return str(response.url), b"".join(content)
    raise SourceParseError("RRC detail redirect count exceeds its bound")


def _form_data(form) -> dict[str, str]:
    data: dict[str, str] = {}
    for control in form.find_all("input"):
        name = control.get("name")
        if name and control.get("type", "text").casefold() in {"hidden", "text"}:
            data[name] = control.get("value", "")
    for control in form.find_all("select"):
        name = control.get("name")
        selected = control.find_all("option", selected=True)
        if name and selected:
            data[name] = selected[0].get("value", selected[0].get_text(strip=True))
    return data


def retrieve_w1_detail(
    record: dict[str, Any], *, deadline: float, client: httpx.Client | None = None
) -> dict[str, Any]:
    """Fetch a W-1 detail only through the official observed search/detail forms."""
    permit = record.get("permit") if isinstance(record, dict) else None
    if not isinstance(permit, dict):
        raise SourceParseError("RRC permit record is missing typed permit fields")
    number = str(permit.get("permit_number") or permit.get("project") or "")
    operator = str(permit.get("operator_number") or "")
    lease, well, county_code = (
        str(permit.get(key) or "") for key in ("lease", "well", "county_code")
    )
    if not (
        re.fullmatch(r"\d{7}", number)
        and re.fullmatch(r"\d{6}", operator)
        and lease.strip()
        and well.strip()
        and county_code.isdigit()
    ):
        raise SourceParseError("RRC permit record lacks exact well-join identifiers")
    owned_client = client is None
    http = client or httpx.Client(follow_redirects=False, timeout=20)
    request_budget = [4]
    try:
        form_url, search_page = _bounded_request(
            http, "GET", SEARCH_FORM_URL, deadline, budget=request_budget
        )
        soup = BeautifulSoup(search_page, "html.parser")
        forms: list[Tag] = []
        for form_element in soup.find_all("form"):
            if (
                isinstance(form_element, Tag)
                and form_element.get("name") == "drillingPermitsQueryActionForm"
            ):
                forms.append(form_element)
        if len(forms) != 1:
            raise SourceParseError("RRC search page lacks one reviewed permit form")
        form = forms[0]
        form_action = form.get("action")
        if not isinstance(form_action, str):
            raise SourceParseError("RRC search form lacks a usable action URL")
        action = _official_url(form_url, form_action)
        data = _form_data(form)
        permit_field = "searchArgs.permitStatusNoHndlr.inputValue"
        operator_field = "searchArgs.operatorNoHndlr.inputValue"
        if permit_field not in data or operator_field not in data:
            raise SourceParseError("RRC search form fields differ from the reviewed form")
        data[permit_field] = str(int(number))
        data[operator_field] = operator
        county_field = "searchArgs.countyCodeHndlr.selectedCodes"
        county_options = soup.find("select", attrs={"name": county_field})
        county_name = None
        if isinstance(county_options, Tag):
            for option_element in county_options.find_all("option"):
                if not isinstance(option_element, Tag):
                    continue
                option = option_element
                if option.get("value") == county_code:
                    county_name = " ".join(option.get_text(" ", strip=True).split())
                    break
        if not county_name:
            raise SourceParseError("RRC search form lacks the retained county code")
        data[county_field] = county_code
        results_url, results_body = _bounded_request(
            http, "POST", action, deadline, data=data, budget=request_budget
        )
        result_soup = BeautifulSoup(results_body, "html.parser")
        data_table = result_soup.find("table", class_="DataGrid")
        if not isinstance(data_table, Tag):
            raise SourceParseError("RRC permit query returned no result grid")
        headers = [
            " ".join(cell.get_text(" ", strip=True).casefold().split())
            for cell in data_table.find_all("th")
        ]
        matching = []
        for row_element in data_table.find_all("tr"):
            if not isinstance(row_element, Tag):
                continue
            row = row_element
            link_element = row.find(
                "a",
                href=lambda href: bool(
                    href
                    and "drillingPermitDetailAction.do" in href
                    and "searchByUniversalDocNo" in href
                    and "universalDocNo=" in href
                ),
            )
            if not isinstance(link_element, Tag):
                continue
            link = link_element
            cell_elements = row.find_all("td", recursive=False)
            if not all(isinstance(cell, Tag) for cell in cell_elements):
                continue
            cells = [cell for cell in cell_elements if isinstance(cell, Tag)]
            if len(cells) != len(headers):
                continue
            values = [" ".join(cell.get_text(" ", strip=True).split()) for cell in cells]
            columns = dict(zip(headers, values, strict=True))
            status_number = columns.get("status number", "")
            operator_match = re.search(r"\((\d{6})\)\s*$", columns.get("permitted operator", ""))
            if (
                status_number.zfill(7) != number
                or not operator_match
                or operator_match.group(1) != operator
            ):
                continue
            if _norm(columns.get("lease", "")) != _norm(lease):
                continue
            if _norm(columns.get("well number", "")) != _norm(well):
                continue
            if _norm(columns.get("county", "")) != _norm(county_name):
                continue
            matching.append(link)
        if len(matching) != 1:
            raise SourceParseError("RRC permit query returned zero or conflicting exact well rows")
        detail_href = matching[0].get("href")
        if not isinstance(detail_href, str):
            raise SourceParseError("RRC detail row lacks a usable href")
        detail_url = _official_url(results_url, detail_href)
        official_url, detail_body = _bounded_request(
            http,
            "GET",
            detail_url,
            deadline,
            budget=request_budget,
        )
        expected = WellIdentity(
            api_number=None,
            permit_number=number,
            operator_number=operator,
            lease=lease,
            well_number=well,
            county_code=county_code,
            county=county_name,
            operator_name=str(permit.get("operator") or "") or None,
        )
        parsed = parse_w1_detail(detail_body, expected)
        identity = parsed["identity"]
        source_text = "\n".join(
            [
                "Official RRC W-1 detail",
                f"API number: {parsed['asset_identity']['value']}",
                f"Permit/status number: {identity['permit']}",
                f"Operator: {identity['operator']}",
                f"Operator number: {identity['operator_number']}",
                f"Lease: {identity['lease']}",
                f"Well: {identity['well']}",
                f"County: {identity['county']}",
                f"Spud date: {parsed['spud_date'] or 'Unknown'}",
                f"RRC W-1 completion date: {parsed['rrc_w1_completion_date'] or 'Unknown'}",
            ]
        )
        return {
            **parsed,
            "source_url": _sanitized_source_url(official_url, allowed_path="/EWA/"),
            "content_hash": hashlib.sha256(detail_body).hexdigest(),
            "native_content_hash": str(record.get("source_hash") or ""),
            "source_text": source_text,
        }
    finally:
        if owned_client:
            http.close()
