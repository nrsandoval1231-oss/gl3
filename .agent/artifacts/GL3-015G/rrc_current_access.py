"""Bounded public RRC index/JSF access helpers used by the GL3-015G probe."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from bs4 import BeautifulSoup

INDEX_URL = "https://www.rrc.texas.gov/resource-center/research/data-sets-available-for-download/"
GO_DRIVE = "https://mft.rrc.texas.gov/webclient/godrive/PublicGoDrive.xhtml"
FOLDER_GUID = "5f07cc72-2e79-4df8-ade1-9aeb792e03fc"
FOLDER_URL = f"https://mft.rrc.texas.gov/link/{FOLDER_GUID}"
MAX_RESPONSE_BYTES = 5_000_000
MAX_RUN_BYTES = 12_000_000
TIMEOUT_SECONDS = 20


class AccessError(ValueError):
    pass


@dataclass(frozen=True)
class ListingSelection:
    row_key: str
    view_state: str
    modified: str
    advertised_size: str
    filename: str = "daf420.dat"


def allowlisted(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    if parsed.hostname == "www.rrc.texas.gov":
        return parsed.path == urlparse(INDEX_URL).path and not parsed.query and not parsed.fragment
    if parsed.hostname == "mft.rrc.texas.gov":
        if parsed.path == f"/link/{FOLDER_GUID}":
            return not parsed.query and not parsed.fragment
        if parsed.path == urlparse(GO_DRIVE).path:
            return not parsed.query and not parsed.fragment
    return False


def validate_response(
    *, status: int, headers: dict[str, str], url: str, body: bytes, max_bytes: int
) -> None:
    if not allowlisted(url):
        raise AccessError("response URL is outside the RRC allowlist")
    if 300 <= status < 400:
        raise AccessError(f"redirect rejected (HTTP {status})")
    if status != 200:
        raise AccessError(f"unexpected HTTP status {status}")
    if len(body) > max_bytes:
        raise AccessError(f"response exceeded {max_bytes} byte limit")


def parse_index(content: bytes) -> str:
    soup = BeautifulSoup(content, "html.parser")
    matches = []
    for link in soup.select("a[href]"):
        href = str(link.get("href", ""))
        text = link.get_text(" ", strip=True)
        if href == FOLDER_URL and text == "ASCII Format":
            row = link.find_parent("tr")
            if row is not None and "Daily File" in row.get_text(" ", strip=True):
                matches.append(link)
    if len(matches) != 1:
        raise AccessError(f"official index has {len(matches)} matching daily-folder links")
    return FOLDER_URL


def parse_listing(content: bytes) -> ListingSelection:
    if b"<html" not in content.lower() or b"<title" not in content.lower():
        raise AccessError("GoDrive response is not an HTML listing")
    soup = BeautifulSoup(content, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if title != "RRC Web Client - GoDrive":
        raise AccessError("GoDrive listing title is missing or unexpected")
    if soup.select_one("form#user-login-form, form[action*='Login']"):
        raise AccessError("GoDrive returned a login page")
    hits = [a for a in soup.select("a[href]") if a.get_text(" ", strip=True) == "daf420.dat"]
    if len(hits) != 1:
        raise AccessError(f"GoDrive listing has {len(hits)} exact daf420.dat rows")
    row = hits[0].find_parent("tr")
    if row is None or row.get("data-ri") != "0" or not row.get("data-rk"):
        raise AccessError("daf420.dat is not the unique published row 0")
    form = soup.select_one("form#fileList")
    state = form.select_one('input[name="javax.faces.ViewState"]') if form else None
    if state is None or not state.get("value"):
        raise AccessError("same-session JSF ViewState is missing")
    if form.select_one('input[name="fileTable_selection"]') is None:
        raise AccessError("PrimeFaces row selection field is missing")
    button_forms = []
    for candidate in soup.select("form"):
        buttons = candidate.select("button")
        if any(button.get_text(" ", strip=True) == "Download" for button in buttons):
            button_forms.append(candidate)
    if len(button_forms) != 1:
        raise AccessError("GoDrive download form is missing or ambiguous")
    if button_forms[0].get("action") != "/webclient/godrive/PublicGoDrive.xhtml":
        raise AccessError("GoDrive download form action is outside the allowlist")
    modified = row.select_one("td.ModifiedOnColumn")
    advertised_size = row.select_one("td.SizeColumn")
    if modified is None or advertised_size is None:
        raise AccessError("GoDrive listing lacks modified time or advertised size")
    return ListingSelection(
        row_key=str(row["data-rk"]),
        view_state=str(state["value"]),
        modified=modified.get_text(" ", strip=True),
        advertised_size=advertised_size.get_text(" ", strip=True),
    )


def selection_post(selection: ListingSelection) -> dict[str, str]:
    return {
        "javax.faces.partial.ajax": "true",
        "javax.faces.source": "fileTable",
        "javax.faces.partial.execute": "fileTable",
        "javax.faces.partial.render": "multiRowButtons",
        "javax.faces.behavior.event": "rowSelect",
        "javax.faces.partial.event": "rowSelect",
        "fileTable": "fileTable",
        "fileTable_selection": selection.row_key,
        "fileList_SUBMIT": "1",
        "javax.faces.ViewState": selection.view_state,
    }


def selected_view_state(partial_response: bytes, fallback: str) -> str:
    if b"<partial-response" not in partial_response.lower() or b"<error" in partial_response.lower():
        raise AccessError("JSF row selection did not return a valid partial response")
    matches = re.findall(
        rb'<update\b[^>]*id=["\'][^"\']*javax\.faces\.ViewState[^"\']*["\'][^>]*>'
        rb"(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</update>",
        partial_response,
        re.I | re.S,
    )
    if len(matches) > 1:
        raise AccessError("JSF selection returned ambiguous ViewState updates")
    if not matches:
        return fallback
    value = matches[0].decode("utf-8", errors="strict").strip()
    if not value or "<" in value:
        raise AccessError("JSF selection returned malformed ViewState")
    return value


def validate_jsf_partial(status: int, headers: dict[str, str], url: str, body: bytes) -> None:
    if not allowlisted(url):
        raise AccessError("JSF response URL is outside the RRC allowlist")
    if 300 <= status < 400:
        raise AccessError(f"JSF redirect rejected (HTTP {status})")
    if status != 200:
        raise AccessError(f"JSF selection returned HTTP {status}")
    if len(body) > MAX_RESPONSE_BYTES:
        raise AccessError(f"JSF response exceeded {MAX_RESPONSE_BYTES} byte limit")
    if "html" in headers.get("content-type", "").casefold():
        raise AccessError("JSF selection returned HTML instead of a partial response")
    if b"<partial-response" not in body.lower() or b"<error" in body.lower():
        raise AccessError("JSF selection returned malformed or error partial XML")


def download_post(listing: bytes, view_state: str) -> dict[str, str]:
    soup = BeautifulSoup(listing, "html.parser")
    forms = []
    for form in soup.select("form"):
        if any(button.get_text(" ", strip=True) == "Download" for button in form.select("button")):
            forms.append(form)
    if len(forms) != 1:
        raise AccessError("download form changed or is ambiguous")
    form = forms[0]
    data: dict[str, str] = {}
    for field in form.select('input[type="hidden"][name]'):
        data[str(field["name"])] = str(field.get("value", ""))
    state_field = next((key for key in data if key == "javax.faces.ViewState"), None)
    if state_field is None:
        raise AccessError("download form has no JSF state field")
    data[state_field] = view_state
    button = next(
        button
        for button in form.select("button")
        if button.get_text(" ", strip=True) == "Download"
    )
    button_name = button.get("name")
    if not button_name:
        raise AccessError("download button has no JSF command name")
    data[str(button_name)] = str(button.get("value") or button_name)
    return data


def validate_attachment(status: int, headers: dict[str, str], url: str, body: bytes) -> None:
    if not allowlisted(url):
        raise AccessError("download response URL is outside the RRC allowlist")
    if 300 <= status < 400:
        raise AccessError(f"download redirect rejected (HTTP {status})")
    if status != 200:
        raise AccessError(f"download returned HTTP {status}")
    content_type = headers.get("content-type", "").casefold()
    if (
        "text/html" in content_type
        or "xml" in content_type
        or body.lstrip().lower().startswith((b"<html", b"<?xml"))
    ):
        raise AccessError("JSF/HTML/XML/error body masquerades as permit attachment")
    disposition = headers.get("content-disposition", "").casefold()
    if "attachment" not in disposition and "force-download" not in content_type:
        raise AccessError("response is not an advertised file attachment")
    if not body:
        raise AccessError("permit attachment is empty")
