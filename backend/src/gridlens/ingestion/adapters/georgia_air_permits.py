"""Bounded public Georgia EPD Draft Title V listing and narrative retrieval."""

from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from pypdf import PdfReader

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.parsers.generator_schedule import VERSION, extract_generator_facts

SOURCE_ID = "georgia-air-draft-title-v"
APP_ID = "5582edf87a0f92370d4ae1f9"
SCENE_KEY = "scene_1"
VIEW_KEY = "view_1"
APP_HOST = "api.knack.com"
EPD_HOST = "epd.georgia.gov"
LISTING_URL = "https://epd.georgia.gov/draft-title-v-permitsamendments-other-draft-permits"
APP_METADATA_URL = f"https://{APP_HOST}/v1/applications/{APP_ID}"
RECORDS_URL = f"https://{APP_HOST}/v1/scenes/{SCENE_KEY}/views/{VIEW_KEY}/records"
ROWS_PER_PAGE = 100
MAX_PAGES = 5
MAX_RECORDS = 500
MAX_RESPONSE_BYTES = 2_000_000
MAX_RUN_BYTES = 30_000_000
MAX_PDFS_PER_RUN = 50
MAX_PDF_BYTES = 4_000_000
MAX_PDF_PAGES = 200
MAX_PDF_PAGES_PER_RUN = 5_000
MAX_EXCERPT_CHARS = 4000
MAX_ADDITIONAL_PAGE_CHARS = 800
_PROSPECTIVE_SITE_ACTIVITY = re.compile(
    r"\bconstruction\s+of\s+(?:the|a|an)\s+(?:facility|site|plant|campus|quarry|"
    r"data\s+cent(?:er|re))\s+(?:is\s+)?(?:planned|expected|scheduled)\s+to\s+begin\b|"
    r"\b(?:proposes?|plans?)\s+to\s+(?:construct|build|develop)\b.{0,180}\b"
    r"(?:facility|plant|campus|quarry|data\s+cent(?:er|re))\b|"
    r"\b(?:proposed|planned)\s+(?:greenfield\s+)?(?:facility|plant|campus|quarry|"
    r"data\s+cent(?:er|re))\b.{0,140}\b(?:construct|build|develop|locate|consist)\b",
    re.I,
)
_SCOPE_HEADING = re.compile(
    r"\b(?:Updated\s+)?(?:Equipment\s+List|Emissions\s+Summary|"
    r"Regulatory\s+Applicability|Permit\s+Conditions|Existing\s+Permits|"
    r"Prior\s+Approvals|Background\s+Information)\b",
    re.I,
)
_DOC_PATH = re.compile(r"^/document/document/[A-Za-z0-9_-]+-(?:nar|draft|notice|pn)/download$")
_DOC_LABELS = {
    "field_4_raw": "application",
    "field_5_raw": "narrative",
    "field_6_raw": "draft permit",
    "field_7_raw": "public notice",
}
_FETCH_DOCUMENT_LABELS = {"narrative", "draft permit"}
_RELEVANT = re.compile(
    r"\b(?:data cent(?:er|re)|construction|greenfield|generator|generators|"
    r"expansion|addition|install(?:ation|ed)?|modification|emissions change|"
    r"equipment|proposed|facility description|source code)\b",
    re.IGNORECASE,
)
_LEGAL_SUFFIXES = {
    "llc",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "ltd",
    "limited",
    "co",
    "company",
}


def _identity_tokens(value: str) -> list[str]:
    # Agency PDFs and Knack rows vary in punctuation and corporate style. Fold
    # dotted initialisms (U.S. -> US), then remove legal suffixes while keeping
    # every remaining facility token in order for exact sequence matching.
    compact = re.sub(
        r"\b(?:[a-z]\.)+[a-z]?\.?", lambda match: match.group(0).replace(".", ""), value, flags=re.I
    )
    return [
        token
        for token in re.findall(r"[a-z0-9]+", compact.casefold())
        if token not in _LEGAL_SUFFIXES
    ]


def _bounded_get(
    client: httpx.Client,
    url: str,
    max_bytes: int,
    *,
    params: dict[str, str | int] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[httpx.Headers, bytes]:
    parts: list[bytes] = []
    size = 0
    with client.stream("GET", url, params=params, headers=headers) as response:
        response.raise_for_status()
        declared = response.headers.get("content-length")
        if declared:
            try:
                if int(declared) > max_bytes:
                    raise SourceParseError("Georgia source response exceeds its byte limit")
            except ValueError as exc:
                raise SourceParseError("Georgia source Content-Length is malformed") from exc
        for part in response.iter_bytes():
            size += len(part)
            if size > max_bytes:
                raise SourceParseError("Georgia source response exceeds its byte limit")
            parts.append(part)
        return response.headers, b"".join(parts)


def _record_value(record: dict[str, Any], key: str) -> str:
    raw = record.get(f"{key}_raw")
    value = raw.get("date") if key == "field_3" and isinstance(raw, dict) else record.get(key)
    if isinstance(raw, dict) and key != "field_3":
        value = raw.get("url") or record.get(key)
    return " ".join(str(value or "").split())


def _deadline(value: str) -> str | None:
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise SourceParseError("Georgia public-comment deadline is malformed")


def _source_date(value: str, error_message: str) -> str:
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise SourceParseError(error_message)


def _current_scope_excerpt(narrative_excerpt: str) -> str:
    pages = [
        section
        for section in re.split(r"(?=Page\s+\d+:)", narrative_excerpt)
        if re.match(r"Page\s+[1-3]:", section)
    ]
    opening_pages = "\n".join(pages)
    purpose = re.search(r"\bPurpose\s+of\s+(?:the\s+)?Application\b", opening_pages, re.I)
    current_purpose = ""
    background = opening_pages
    if purpose:
        following_heading = _SCOPE_HEADING.search(opening_pages, purpose.end())
        end = following_heading.start() if following_heading else len(opening_pages)
        purpose_text = opening_pages[purpose.start() : end]
        page_markers = list(re.finditer(r"Page\s+(\d+):", opening_pages[: purpose.start()]))
        purpose_page = page_markers[-1].group(1) if page_markers else "1"
        current_purpose = f"Page {purpose_page} current application purpose: {purpose_text}"
        background = opening_pages[: purpose.start()]

    # Existing-permit inventories and prior-approval tables are historical
    # context, even when they contain words like proposed, install, or construct.
    background = re.sub(
        r"\b(?:Existing\s+Permits|Prior\s+Approvals)\b.*?(?=\b(?:Purpose\s+of\s+"
        r"(?:the\s+)?Application|Background\s+Information|Equipment\s+List)\b|$)",
        " ",
        background,
        flags=re.I | re.S,
    )
    prospective: list[str] = []
    for page in pages:
        page_number = re.match(r"Page\s+(\d+):", page)
        if not page_number:
            continue
        text = page
        global_start = opening_pages.find(page)
        if purpose and global_start <= purpose.start() < global_start + len(page):
            text = page[: purpose.start() - global_start]
        text = re.sub(
            r"\b(?:Existing\s+Permits|Prior\s+Approvals)\b.*$", " ", text, flags=re.I | re.S
        )
        for match in _PROSPECTIVE_SITE_ACTIVITY.finditer(text):
            start = max(text.rfind(".", 0, match.start()), text.rfind("\n", 0, match.start())) + 1
            ends = [index for delim in (".", "\n") if (index := text.find(delim, match.end())) >= 0]
            end = min(ends) + 1 if ends else len(text)
            sentence = " ".join(text[start:end].split())
            if sentence:
                prospective.append(
                    f"Page {page_number.group(1)} background prospective activity: {sentence}"
                )
    return "\n".join(part for part in (current_purpose.strip(), *prospective) if part)


def _document_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != EPD_HOST
        or parsed.query
        or not _DOC_PATH.fullmatch(parsed.path)
    ):
        raise SourceParseError("Georgia document link is outside the approved EPD path")
    return value


def _extract_document(
    client: httpx.Client,
    url: str,
    label: str,
    run_state: dict[str, int],
    facility: str,
    application_number: str,
    location: str,
) -> dict[str, Any] | None:
    if not url:
        return None
    if run_state["pdf_count"] >= MAX_PDFS_PER_RUN:
        raise SourceParseError("Georgia document count exceeded the run bound")
    response_headers, content = _bounded_get(client, url, MAX_PDF_BYTES)
    run_state["bytes"] += len(content)
    run_state["pdf_count"] += 1
    if run_state["bytes"] > MAX_RUN_BYTES:
        raise SourceParseError("Georgia retrieval exceeded total run byte limit")
    content_type = response_headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type != "application/pdf" or not content.startswith(b"%PDF-"):
        raise SourceParseError("Georgia EPD document is not a PDF")
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        page_count = len(reader.pages)
        if reader.is_encrypted:
            raise SourceParseError("Georgia PDF is encrypted")
        if not page_count:
            raise SourceParseError("Georgia PDF is empty")
        if page_count > MAX_PDF_PAGES:
            raise SourceParseError(
                f"Georgia PDF page count {page_count} exceeds per-document limit {MAX_PDF_PAGES}"
            )
        run_state["pdf_pages"] = run_state.get("pdf_pages", 0) + page_count
        if run_state["pdf_pages"] > MAX_PDF_PAGES_PER_RUN:
            raise SourceParseError(
                f"Georgia PDFs exceed total run page limit {MAX_PDF_PAGES_PER_RUN}"
            )
        candidates: list[tuple[int, int, str]] = []
        nonempty_pages: list[tuple[int, str]] = []
        full_text: list[str] = []
        for page_number, page in enumerate(reader.pages, 1):
            text = " ".join((page.extract_text() or "").split())
            if not text:
                continue
            full_text.append(text)
            nonempty_pages.append((page_number, text))
            score = len(_RELEVANT.findall(text))
            # Front matter often includes the facility, address, and filed date;
            # later equipment schedules can carry stronger power evidence.
            if page_number <= 2:
                score += 1
            if score:
                candidates.append((score, page_number, text[:MAX_EXCERPT_CHARS]))
        combined = " ".join(full_text).casefold()
        normalized_text = " ".join(_identity_tokens(combined))
        facility_key = " ".join(_identity_tokens(facility))
        # Location corroboration is required even when the application number is
        # present. The first source location component is the listing's city/site.
        site_label = location.split(",", 1)[0].strip()
        site_key = " ".join(_identity_tokens(site_label))
        app_digits = "".join(re.findall(r"\d", application_number))
        padded_text = f" {normalized_text} "
        site_matches = len(site_key) >= 3 and f" {site_key} " in padded_text
        facility_matches = len(facility_key) >= 5 and f" {facility_key} " in padded_text
        application_matches = bool(
            app_digits
            and re.search(
                rf"\b(?:application|permit)(?:\s+(?:number|no\.?|#))?\s*[:#-]?\s*"
                rf"(?:[a-z]{{1,8}}[- ]?)?{re.escape(app_digits)}\b|"
                rf"\bsip[- ]?{re.escape(app_digits)}\b",
                combined,
                re.IGNORECASE,
            )
        )
        if not site_matches or not (facility_matches or application_matches):
            raise SourceParseError(
                "Georgia PDF does not bind the listed facility/application to its site location"
            )
        if not nonempty_pages:
            raise SourceParseError("Georgia PDF has no extractable source page text")
        opening = [(MAX_EXCERPT_CHARS, page, text) for page, text in nonempty_pages if page <= 3]
        opening_page_numbers = {page for _, page, _ in opening}
        additional = [item for item in candidates if item[1] not in opening_page_numbers]
        chosen = opening + sorted(additional, key=lambda item: (-item[0], item[1]))[:5]
        chosen.sort(key=lambda item: item[1])
        excerpts: list[str] = []
        total_chars = 0
        for _, cited_page, page_excerpt in chosen:
            page_limit = MAX_EXCERPT_CHARS if cited_page <= 3 else MAX_ADDITIONAL_PAGE_CHARS
            excerpt = page_excerpt[:page_limit]
            excerpt = excerpt[: max(0, 16_000 - total_chars)]
            if excerpt:
                excerpts.append(f"Page {cited_page}: {excerpt}")
                total_chars += len(excerpt)
            if total_chars >= 16_000:
                break
        scope_abstract = "\n".join(excerpts)
        schedule = extract_generator_facts(nonempty_pages, url)
        excerpts.extend(
            f"Page {fact['page']} generator schedule context: {fact['quote']}"
            for fact in schedule["facts"]
        )
        page_text = "\n".join(excerpts)
        pdf_hash = hashlib.sha256(content).hexdigest()
        return {
            "content_hash": hashlib.sha256(f"{pdf_hash}:{VERSION}".encode()).hexdigest(),
            "pdf_hash": pdf_hash,
            "generator_schedule": schedule,
            "scope_abstract": scope_abstract,
            "title": f"Georgia EPD {label}",
            "abstract": page_text,
            "url": url,
            "extraction_location": "PDF pages "
            + ", ".join(
                str(page)
                for page in sorted(
                    {page for _, page, _ in chosen} | {f["page"] for f in schedule["facts"]}
                )
            ),
        }
    except SourceParseError:
        raise
    except Exception as exc:
        raise SourceParseError(f"Georgia PDF extraction failed: {type(exc).__name__}") from exc


def retrieve(source: dict[str, Any], client: httpx.Client | None = None) -> list[dict[str, Any]]:
    if source.get("id") != SOURCE_ID or source.get("endpoint") != LISTING_URL:
        raise SourceParseError("Georgia air source ID or listing endpoint is not configured")
    query = source.get("query", {})
    if (
        query.get("rows_per_page") != ROWS_PER_PAGE
        or not 1 <= query.get("max_pages", 0) <= MAX_PAGES
        or not 1 <= query.get("max_records", 0) <= MAX_RECORDS
        or query.get("max_response_bytes") != MAX_RESPONSE_BYTES
        or query.get("max_run_bytes") != MAX_RUN_BYTES
        or query.get("max_pdf_pages") != MAX_PDF_PAGES
        or query.get("max_pdf_total_pages") != MAX_PDF_PAGES_PER_RUN
    ):
        raise SourceParseError("Georgia air source bounds are invalid")
    own_client = client is None
    http = client or httpx.Client(timeout=25, follow_redirects=False)
    api_headers = {
        "X-Knack-Application-Id": APP_ID,
        "X-Knack-REST-API-Key": "knack",
        "Accept": "application/json",
    }
    state = {"bytes": 0, "pdf_count": 0, "pdf_pages": 0}
    try:
        metadata_headers, metadata_body = _bounded_get(
            http, APP_METADATA_URL, MAX_RESPONSE_BYTES, headers=api_headers
        )
        state["bytes"] += len(metadata_body)
        if "json" not in metadata_headers.get("content-type", "").lower():
            raise SourceParseError("Georgia Knack metadata is not JSON")
        try:
            metadata = json.loads(metadata_body)["application"]
            objects = metadata["objects"]
            fields = {field["key"]: field["name"] for field in objects[0]["fields"]}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise SourceParseError("Georgia Knack application schema is malformed") from exc
        expected_fields = {
            "field_1": "Facility Name",
            "field_2": "Location",
            "field_3": "Public Comment Deadline",
            "field_4": "Application Link",
            "field_8": "Application Number",
            "field_5": "Narrative",
            "field_6": "Draft Permit",
            "field_7": "Public Notice",
        }
        if metadata.get("id") != APP_ID or metadata.get("home_scene", {}).get("key") != SCENE_KEY:
            raise SourceParseError("Georgia Knack app identity changed")
        if any(fields.get(key) != name for key, name in expected_fields.items()):
            raise SourceParseError("Georgia Knack source field map changed")

        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        expected_count: int | None = None
        expected_pages: int | None = None
        for page in range(1, int(query["max_pages"]) + 1):
            headers, body = _bounded_get(
                http,
                RECORDS_URL,
                MAX_RESPONSE_BYTES,
                params={"rows_per_page": ROWS_PER_PAGE, "page": page},
                headers=api_headers,
            )
            state["bytes"] += len(body)
            if (
                state["bytes"] > MAX_RUN_BYTES
                or "json" not in headers.get("content-type", "").lower()
            ):
                raise SourceParseError("Georgia listing exceeded bounds or returned non-JSON")
            try:
                payload = json.loads(body)
                rows = payload["records"]
                count = int(payload["total_records"])
                pages = int(payload["total_pages"])
            except (ValueError, KeyError, TypeError) as exc:
                raise SourceParseError("Georgia listing response is malformed") from exc
            if not isinstance(rows, list) or count < 1 or count > int(query["max_records"]):
                raise SourceParseError("Georgia listing is empty or exceeds its record bound")
            if pages < 1 or pages > int(query["max_pages"]):
                raise SourceParseError("Georgia listing exceeds its page bound")
            if expected_count is None:
                expected_count, expected_pages = count, pages
            elif (count, pages) != (expected_count, expected_pages):
                raise SourceParseError("Georgia listing changed during pagination")
            if page > pages:
                break
            if not rows:
                raise SourceParseError("Georgia listing ended before its declared page count")
            for row in rows:
                if not isinstance(row, dict):
                    raise SourceParseError("Georgia listing row has invalid shape")
                record_id = " ".join(str(row.get("id") or "").split())
                facility = _record_value(row, "field_1")
                location = _record_value(row, "field_2")
                application_number = _record_value(row, "field_8")
                if (
                    not record_id
                    or record_id in seen
                    or not facility
                    or not location
                    or not application_number
                ):
                    raise SourceParseError(
                        "Georgia listing row lacks stable identity or site fields"
                    )
                seen.add(record_id)
                deadline = _deadline(_record_value(row, "field_3"))
                links: dict[str, str] = {}
                for key, label in _DOC_LABELS.items():
                    value = row.get(key)
                    raw_url = str(value.get("url") or "").strip() if isinstance(value, dict) else ""
                    if raw_url:
                        links[label] = _document_url(raw_url)
                if not links.get("narrative") or not links.get("draft permit"):
                    raise SourceParseError(
                        "Georgia listing row lacks a required narrative or draft permit"
                    )
                documents = [
                    document
                    for label, url in links.items()
                    if label in _FETCH_DOCUMENT_LABELS
                    and (
                        document := _extract_document(
                            http, url, label, state, facility, application_number, location
                        )
                    )
                    is not None
                ]
                narrative = next(
                    (document for document in documents if "narrative" in document["title"]), None
                )
                narrative_text = narrative["abstract"] if narrative else ""
                opening_text = "\n".join(
                    section
                    for section in re.split(r"(?=Page\s+\d+:)", narrative_text)
                    if re.match(r"Page\s+[1-3]:", section)
                )
                current_scope_text = _current_scope_excerpt(
                    narrative["scope_abstract"] if narrative else ""
                )
                current_scope_pages = sorted(
                    {int(value) for value in re.findall(r"\bPage\s+(\d+):", current_scope_text)}
                )
                received_date = None
                application_date = None
                received = re.search(
                    (
                        r"(?:Date\s+(?:Title V\s+)?Application Received|"
                        r"Application\s+(?:Received|Submitted)\s+Date)\s*:\s*"
                        r"([A-Z][a-z]+\s+\d{1,2},\s+20\d{2})"
                    ),
                    opening_text,
                    re.IGNORECASE,
                )
                if received:
                    received_date = _source_date(
                        received.group(1), "Georgia application-received date is malformed"
                    )
                application_date_match = re.search(
                    r"\bDate\s+of\s+Application\s*:\s*"
                    r"([A-Z][a-z]+\s+\d{1,2},\s+20\d{2})",
                    opening_text,
                    re.IGNORECASE,
                )
                if application_date_match:
                    application_date = _source_date(
                        application_date_match.group(1), "Georgia application date is malformed"
                    )
                unextracted_links = {
                    label: url
                    for label, url in links.items()
                    if label not in _FETCH_DOCUMENT_LABELS
                }
                document_facts = "; ".join(
                    f"{label} URL (retained reference, not fetched): {url}"
                    if label in unextracted_links
                    else f"{label} URL: {url}"
                    for label, url in sorted(links.items())
                )
                draft = next((d for d in documents if d["url"] == links.get("draft permit")), None)
                # Front-page identity, bounded independently from technical excerpts.
                # Keep the exact excerpt and PDF reference in the accepted parent
                # version so enrichment does not need to refetch a PDF as HTML.
                draft_identity = ""
                if draft:
                    front = draft["scope_abstract"].split("\nPage 2:", 1)[0]
                    match = re.search(
                        r"Facility Name: .{1,200}? Facility Address: .{1,500}? "
                        r"(?:Mailing Address: .{1,500}? )?Facility AIRS Number: .{1,100}? "
                        r"is issued a Permit for the following: .{1,800}?(?= This Permit)",
                        front,
                    )
                    if match and front.startswith("Page 1: "):
                        draft_identity = match.group(0)
                abstract = "\n".join(
                    part
                    for part in (
                        f"Facility: {facility}",
                        f"Location: {location}, Georgia",
                        f"Application number: {application_number}",
                        f"Application received date: {received_date}" if received_date else "",
                        f"Application date: {application_date}" if application_date else "",
                        f"Public comment deadline: {deadline}" if deadline else "",
                        f"Official narrative excerpt: {narrative_text}" if narrative_text else "",
                        f"Draft identity (page 1): {draft_identity}" if draft_identity else "",
                        document_facts,
                    )
                    if part
                )
                semantic = {
                    "permit_identity_version": "ga-permit-identity-v1",
                    "draft_identity": draft_identity,
                    "record_id": record_id,
                    "facility": facility,
                    "location": location,
                    "application_number": application_number,
                    "public_comment_deadline": deadline,
                    "application_received_date": received_date,
                    "application_date": application_date,
                    "current_scope": current_scope_text,
                    "document_links": links,
                    "document_hashes": {d["url"]: d["pdf_hash"] for d in documents},
                    "generator_facts": [
                        f for d in documents for f in d["generator_schedule"]["facts"]
                    ],
                    "generator_excerpts_omitted": sum(
                        d["generator_schedule"]["omitted"] for d in documents
                    ),
                    "application_document_available": "application" in links,
                    "documents": [
                        {
                            key: document[key]
                            for key in ("url", "content_hash", "extraction_location")
                        }
                        for document in documents
                    ],
                }
                source_hash = hashlib.sha256(
                    json.dumps(
                        semantic, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                    ).encode()
                ).hexdigest()
                source_fields = {
                    "facility": "field_1",
                    "location": "field_2",
                    "public_comment_deadline": "field_3",
                    "application_number": "field_8",
                }
                output.append(
                    {
                        "document_number": record_id,
                        "title": facility,
                        "abstract": abstract,
                        "publication_date": None,
                        "html_url": LISTING_URL,
                        "extraction_location": (
                            "Georgia EPD listing; narrative PDF pages; draft identity PDF page 1"
                        ),
                        "event_date": received_date or application_date or deadline,
                        "event_date_label": (
                            "Application received date (source-stated)"
                            if received_date
                            else "Application date (source-stated)"
                            if application_date
                            else "Public comment deadline (source-stated)"
                        ),
                        "companions": documents,
                        "source_hash": source_hash,
                        "permit": {
                            "source_type": "georgia-air-draft-title-v",
                            "city": location,
                            "state": "GA",
                            "address": location,
                            "class": "Draft air permit listing (Title V/SIP/synthetic minor)",
                            "work": "air permit application or modification",
                            "type": "Draft air permit; category requires document review",
                            "status": (
                                "Listed in current Georgia EPD draft air permits view; "
                                "project status unconfirmed"
                            ),
                            "description": (
                                f"{facility}. {location}, Georgia. "
                                f"Current application-purpose excerpt: {current_scope_text}"
                            ),
                            "current_scope": current_scope_text,
                            "current_scope_pages": current_scope_pages,
                            "row_id": application_number,
                            "record_id": record_id,
                            "application_number": application_number,
                            "public_comment_deadline": deadline,
                            "application_received_date": received_date,
                            "application_date": application_date,
                            "document_links": links,
                            "document_hashes": {d["url"]: d["pdf_hash"] for d in documents},
                            "generator_facts": [
                                f for d in documents for f in d["generator_schedule"]["facts"]
                            ],
                            "generator_excerpts_omitted": sum(
                                d["generator_schedule"]["omitted"] for d in documents
                            ),
                            "application_document_available": "application" in links,
                            "unextracted_document_links": unextracted_links,
                            "source_fields": source_fields,
                            "reported_values": {},
                        },
                    }
                )
            if len(output) >= expected_count:
                if len(output) != expected_count or page != expected_pages:
                    raise SourceParseError(
                        "Georgia pagination does not match the declared complete row count"
                    )
                return output
        raise SourceParseError("Georgia listing exceeded pagination bound or was incomplete")
    except httpx.HTTPError as exc:
        raise SourceParseError(f"Georgia source request failed: {type(exc).__name__}") from exc
    finally:
        if own_client:
            http.close()
