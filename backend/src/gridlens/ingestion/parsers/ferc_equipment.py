"""Bounded extraction for the Federal Register FERC environmental-assessment layout.

This parser records source assertions. It does not infer electrical input or turn
station work such as uprates and re-wheels into new equipment demand.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from hashlib import sha256

VERSION = "ferc-compressor-station-notice-v2"
MAX_INPUT_CHARS = 128_000
MAX_SITES = 16
MAX_ACTIVITIES = 64
MAX_DOCKET_REFERENCES = 16


@dataclass(frozen=True, slots=True)
class NativeEquipmentClaim:
    """One explicit new compressor assertion with source-bound fields."""

    claim_key: str
    equipment_type: str
    drive: str
    lifecycle_status: str
    count: int | None
    rating: Decimal | None
    rating_unit: str | None
    rating_basis: str
    source_equipment_id: str | None
    id_basis: str
    role: str
    quote: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class UnsupportedActivity:
    """Explicit facility work that this extractor cannot model as equipment demand."""

    activity: str
    quote: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class NativeEquipmentSite:
    facility: str
    location: str
    heading_quote: str
    heading_start: int
    heading_end: int
    claims: tuple[NativeEquipmentClaim, ...] = ()
    unsupported_activities: tuple[UnsupportedActivity, ...] = ()


@dataclass(slots=True)
class NativeEquipmentExtraction:
    title: str
    source_party_name: str | None = None
    source_project_name: str | None = None
    source_party_quote: str | None = None
    source_party_start: int | None = None
    source_party_end: int | None = None
    source_party_span_source: str = "title"
    body_applicant_name: str | None = None
    body_applicant_quote: str | None = None
    body_applicant_start: int | None = None
    body_applicant_end: int | None = None
    sites: list[NativeEquipmentSite] = field(default_factory=list)
    notice_kind: str | None = None
    docket_references: list[dict[str, object]] = field(default_factory=list)
    docket_issues: list[str] = field(default_factory=list)
    project_activities: list[UnsupportedActivity] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    attribution_issues: list[str] = field(default_factory=list)
    truncated: bool = False
    extractor_version: str = VERSION


def _normalized_with_offsets(text: str) -> tuple[str, list[int]]:
    """Collapse whitespace while retaining a map back to original character offsets."""
    chars: list[str] = []
    offsets: list[int] = []
    in_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if chars and not in_space:
                chars.append(" ")
                offsets.append(index)
            in_space = True
        else:
            chars.append(char)
            offsets.append(index)
            in_space = False
    if chars and chars[-1] == " ":
        chars.pop()
        offsets.pop()
    return "".join(chars), offsets


def _raw_span(offsets: list[int], start: int, end: int, text_length: int) -> tuple[int, int]:
    return offsets[start], offsets[end - 1] + 1 if end < len(offsets) else text_length


def _layout_gap_is_ignorable(value: str) -> bool:
    """Only whitespace and GovInfo page labels may sit between structural elements."""
    without_page_labels = re.sub(r"\[GovInfo PDF page \d+\]", "", value)
    return not without_page_labels.strip()


_TITLE = re.compile(
    r"(?P<party>[^;]{1,240});\s*Notice of Availability of the "
    r"Environmental Assessment for the Proposed "
    r"(?P<project>[A-Za-z0-9][A-Za-z0-9 ,&()'./-]{1,220} Project)",
    re.I,
)
_SCHEDULE_TITLE = re.compile(
    r"(?P<party>[^;]{1,240});\s*Notice of Schedule for the Preparation of an "
    r"Environmental Assessment for the (?P<project>[A-Za-z0-9][A-Za-z0-9 ,&()'./-]{1,220} Project)",
    re.I,
)
_STATE = (
    r"Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|"
    r"Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|"
    r"Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|"
    r"Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|"
    r"North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|"
    r"South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|"
    r"Wisconsin|Wyoming|[A-Z]{2}"
)
_HEADING_PREFIX = r"(?:Modifications and Installations|Modification) at Compressor Station"
_HEADING = re.compile(
    rf"(?P<heading>{_HEADING_PREFIX} (?P<number>\d+) in "
    rf"(?P<county>[A-Za-z -]+) County, (?P<state>{_STATE})):",
    re.I,
)
_BULLET = re.compile(
    r"•\s*(?P<body>.*?)(?=(?:\s+•\s+)|"
    rf"(?:\s+{_HEADING_PREFIX}\s+\d+\s+in\s+)|\Z)",
    re.I,
)
_STATION_MENTION = re.compile(r"\bCompressor Station\b", re.I)
_INSTALL_CLAUSE = re.compile(
    r"Install (?P<count>one|1|two|2|three|3|four|4|five|5|[0-9]{1,3}) new "
    r"(?P<drive>electric motor driven(?:\s+\(EMD\))?|gas engine driven|"
    r"diesel engine driven|steam turbine driven) compressor units? with a rating of "
    r"(?P<rating>(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?) "
    r"(?P<unit>hp|kW|MW|kVA)[.;]",
    re.I,
)


def parse_ferc_notice_title(title: str) -> tuple[str, str, str] | None:
    """Return the supported title identity and notice family, if recognized."""
    value = title.strip()
    match = _TITLE.fullmatch(value)
    kind = "environmental_assessment_availability"
    if match is None:
        match = _SCHEDULE_TITLE.fullmatch(value)
        kind = "environmental_review_schedule"
    if match is None:
        return None
    return match.group("party").strip(), match.group("project").strip(), kind


_DOCKET = re.compile(
    r"\bCP\s*(?P<year>\d{2})\s*[‐‑‒–—-]\s*(?P<number>\d{1,5})"
    r"(?:\s*[‐‑‒–—-]\s*(?P<suffix>\d{3}))?(?![\w‐‑‒–—-])",
    re.I,
)
_DOCKET_LIKE = re.compile(
    r"\bCP\s*\d+\s*[‐‑‒–—-]\s*\w+(?:\s*[‐‑‒–—-]\s*\w+)*",
    re.I,
)


def _docket_references(text: str) -> tuple[list[dict[str, object]], list[str]]:
    references: list[dict[str, object]] = []
    issues: list[str] = []
    for position, candidate in enumerate(_DOCKET_LIKE.finditer(text)):
        if position >= MAX_DOCKET_REFERENCES:
            issues.append("Docket reference bound exceeded; docket identity is unresolved.")
            break
        raw = candidate.group(0)
        match = _DOCKET.fullmatch(raw)
        if match is None:
            issues.append(
                f"Malformed docket reference retained at offset {candidate.start()}; "
                "docket identity is unresolved."
            )
            continue
        year = match.group("year")
        number = match.group("number")
        suffix = match.group("suffix")
        full = f"CP{year}-{number}-{suffix}" if suffix else None
        root = f"CP{year}-{number}"
        references.append(
            {
                "normalized_full": full,
                "normalized_root": root,
                "quote": raw,
                "start": candidate.start(),
                "end": candidate.end(),
            }
        )
    full_values = {item["normalized_full"] for item in references if item["normalized_full"]}
    root_values = {item["normalized_root"] for item in references}
    if len(full_values) > 1 or len(root_values) > 1:
        issues.append("Docket references conflict; docket identity is unresolved.")
    elif not references:
        issues.append("No supported docket reference was found; docket identity is unresolved.")
    return references, issues


_COUNT_WORDS = {
    "one": 1,
    "1": 1,
    "two": 2,
    "2": 2,
    "three": 3,
    "3": 3,
    "four": 4,
    "4": 4,
    "five": 5,
    "5": 5,
}
_CONTRADICTION = re.compile(
    r"(?:(?:project|installation|compressor|compressor station|facilities)"
    r"[^.]{0,160}(?:cancelled|canceled|withdrawn|will not proceed|"
    r"will not be installed|will not be constructed)|"
    r"(?:cancelled|canceled|withdrawn)[^.]{0,160}"
    r"(?:project|installation|compressor|compressor station|facilities))",
    re.I,
)


def extract_ferc_equipment(text: str, *, title: str) -> NativeEquipmentExtraction:
    """Parse only the supported FERC environmental-assessment notice layout.

    Offsets and quotes address ``text`` exactly. A caller must keep that text
    bound to the original evidence artifact; this function does not authenticate it.
    """
    result = NativeEquipmentExtraction(title=title)
    if len(text) > MAX_INPUT_CHARS:
        result.truncated = True
        result.issues.append(
            f"Input exceeds {MAX_INPUT_CHARS} character parser bound; extraction abstained."
        )
        return result
    parsed_title = parse_ferc_notice_title(title)
    if parsed_title is None:
        result.issues.append(
            "Title does not match the supported FERC environmental-assessment notice layout."
        )
        return result
    result.source_party_name, result.source_project_name, result.notice_kind = parsed_title
    is_schedule = result.notice_kind == "environmental_review_schedule"
    title_value = title.strip()
    title_offset = title.find(title_value)
    title_match = (_SCHEDULE_TITLE if is_schedule else _TITLE).fullmatch(title_value)
    assert title_match is not None
    result.source_party_quote = result.source_party_name
    result.source_party_start = title_offset + title_match.start("party")
    result.source_party_end = result.source_party_start + len(result.source_party_name)
    result.docket_references, result.docket_issues = _docket_references(text)

    normalized, offsets = _normalized_with_offsets(text)
    for contradiction in _CONTRADICTION.finditer(normalized):
        start, end = _raw_span(offsets, contradiction.start(), contradiction.end(), len(text))
        quote = text[start:end]
        result.issues.append(f"Contradiction statement retained at offset {start}: {quote}")
    scope_pattern = re.compile(
        r"The Project would consist of the following facilities and activities:"
        if is_schedule
        else rf"The proposed {re.escape(result.source_project_name)} includes the "
        r"following facilities and activities:",
        re.I,
    )
    scopes = list(scope_pattern.finditer(normalized))
    if len(scopes) != 1:
        result.issues.append(
            "Facilities-and-activities section is missing or ambiguous; extraction abstained."
        )
        return result
    scope = scopes[0]
    tail = normalized[scope.end() :]
    tail_offset = scope.end()
    if is_schedule:
        appurtenant = re.search(
            r"In addition, Natural has identified in its application certain appurtenant "
            r"facilities that it intends to construct/\s*install under section 2\.55\(a\) "
            r"of the Commission['’]s regulations\.",
            tail,
            re.I,
        )
        if appurtenant is None:
            result.issues.append(
                "Appurtenant-facilities boundary is missing; extraction abstained."
            )
            return result
        a_start, a_end = _raw_span(
            offsets,
            tail_offset + appurtenant.start(),
            tail_offset + appurtenant.end(),
            len(text),
        )
        result.project_activities.append(
            UnsupportedActivity(
                "unscoped_appurtenant_facilities", text[a_start:a_end], a_start, a_end
            )
        )
        tail = tail[: appurtenant.start()]
    applicants = list(
        re.finditer(r"proposed by (?P<party>[^()]+?)\s*\((?P<alias>[^)]+)\)", normalized, re.I)
    )
    if len(applicants) == 1:
        applicant = applicants[0]
        party_start = applicant.start("party")
        party_end = applicant.end("party")
        raw_start, raw_end = _raw_span(offsets, party_start, party_end, len(text))
        result.body_applicant_name = applicant.group("party").strip()
        result.body_applicant_start = raw_start
        result.body_applicant_end = raw_end
        result.body_applicant_quote = text[raw_start:raw_end]
    if (
        result.body_applicant_name
        and result.body_applicant_name.casefold() != result.source_party_name.casefold()
    ):
        result.attribution_issues.append(
            "Resolve the body applicant name against the different party name "
            "in the official title."
        )
    elif len(applicants) > 1:
        result.attribution_issues.append(
            "Multiple body applicant names are ambiguous; retain attribution as unresolved."
        )
    heading_pattern = (
        re.compile(
            rf"(?P<heading>{_HEADING_PREFIX} (?P<number>\d+)"
            rf"(?:\s+\(CS\s*(?P<alias>\d+)\))? in "
            rf"(?P<county>[A-Za-z -]+) County, (?P<state>{_STATE})):?",
            re.I,
        )
        if is_schedule
        else _HEADING
    )
    headings = list(heading_pattern.finditer(tail))
    if not headings:
        result.issues.append(
            "No supported compressor-station headings were found; extraction abstained."
        )
        return result
    if len(headings) > MAX_SITES:
        result.truncated = True
        result.issues.append(f"Input exceeds {MAX_SITES} station bound; extraction abstained.")
        return result
    identities = [
        (
            heading.group("number").casefold(),
            heading.group("county").casefold(),
            heading.group("state").casefold(),
        )
        for heading in headings
    ]
    if len(set(identities)) != len(identities):
        result.issues.append("Duplicate station headings are ambiguous; extraction abstained.")
        return result
    if is_schedule and any(
        heading.group("alias") and heading.group("alias") != heading.group("number")
        for heading in headings
    ):
        result.issues.append(
            "Station heading alias does not match its number; extraction abstained."
        )
        return result
    if not _layout_gap_is_ignorable(tail[: headings[0].start()]):
        result.issues.append(
            "Unexpected text precedes the first station heading; extraction abstained."
        )
        return result
    # Unsupported numbers, aliases or locations still delimit a possible site.
    # Never absorb such a heading into the preceding station's activity text.
    all_station_mentions = list(_STATION_MENTION.finditer(tail))
    if len(all_station_mentions) != len(headings) or any(
        mention.start() != tail.lower().find("compressor station", heading.start())
        for mention, heading in zip(all_station_mentions, headings, strict=True)
    ):
        result.issues.append(
            "Station heading layout is ambiguous or unsupported; extraction abstained."
        )
        return result

    for position, heading in enumerate(headings):
        section_end = headings[position + 1].start() if position + 1 < len(headings) else len(tail)
        end_of_facility_list = re.search(
            r"\s+The Commission mailed a copy of the Notice of Availability",
            tail[heading.end() : section_end],
            re.I,
        )
        if end_of_facility_list:
            section_end = heading.end() + end_of_facility_list.start()
        section = tail[heading.end() : section_end]
        if len(re.findall(r"•", section)) > MAX_ACTIVITIES:
            result.truncated = True
            result.issues.append(
                f"Station exceeds {MAX_ACTIVITIES} activity bound; extraction abstained."
            )
            result.sites.clear()
            return result
        bullet_matches = list(_BULLET.finditer(section))
        if not bullet_matches or not _layout_gap_is_ignorable(_BULLET.sub("", section)):
            result.issues.append(
                f"Station activity section has unrecognized text at offset "
                f"{tail_offset + heading.end()}; extraction abstained."
            )
            result.sites.clear()
            return result
        site_claims: list[NativeEquipmentClaim] = []
        unsupported: list[UnsupportedActivity] = []
        seen_claim_keys: set[str] = set()
        facility = f"Compressor Station {heading.group('number')}"
        location = f"{heading.group('county')} County, {heading.group('state')}"
        site_digest = sha256(
            json.dumps(
                [result.source_party_name.casefold(), facility.casefold(), location.casefold()],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        for bullet in _BULLET.finditer(section):
            body = bullet.group("body")
            body_start = tail_offset + heading.end() + bullet.start("body")
            body_end = tail_offset + heading.end() + bullet.end("body")
            raw_start, raw_end = _raw_span(offsets, body_start, body_end, len(text))
            leading_trim = len(text[raw_start:raw_end]) - len(text[raw_start:raw_end].lstrip())
            trailing_trim = len(text[raw_start:raw_end].rstrip())
            raw_start += leading_trim
            raw_end = raw_start + trailing_trim - leading_trim
            quote = text[raw_start:raw_end]
            lowered = body.casefold()
            if re.search(
                r"\b(?:do not|does not|will not|not)\s+install\b|\bno\s+new\b", body, re.I
            ):
                result.issues.append(
                    f"Negated installation statement at offset {raw_start}; no claim extracted."
                )
                unsupported.append(
                    UnsupportedActivity("negated_activity", quote, raw_start, raw_end)
                )
            elif "uprate" in lowered or "increase" in lowered:
                if re.search(r"\b(?:install|add|new)\b", body, re.I):
                    result.issues.append(
                        f"Mixed uprate and installation activity at offset {raw_start}; abstained."
                    )
                    unsupported.append(
                        UnsupportedActivity("mixed_activity", quote, raw_start, raw_end)
                    )
                else:
                    unsupported.append(UnsupportedActivity("uprate", quote, raw_start, raw_end))
            elif "re-wheel" in lowered or "rewheel" in lowered:
                if re.search(r"\b(?:install|add|new)\b", body, re.I):
                    result.issues.append(
                        f"Mixed re-wheel and installation activity at offset "
                        f"{raw_start}; abstained."
                    )
                    unsupported.append(
                        UnsupportedActivity("mixed_activity", quote, raw_start, raw_end)
                    )
                else:
                    unsupported.append(UnsupportedActivity("rewheel", quote, raw_start, raw_end))
            elif (install_match := _INSTALL_CLAUSE.fullmatch(body.strip())) is not None:
                count = _COUNT_WORDS.get(install_match.group("count").casefold())
                if count is None:
                    result.issues.append(
                        f"Installation count exceeds supported bound at offset {raw_start}."
                    )
                    unsupported.append(
                        UnsupportedActivity("unresolved_installation", quote, raw_start, raw_end)
                    )
                    continue
                drive_value = install_match.group("drive").casefold()
                drive = {
                    "electric motor driven": "electric",
                    "electric motor driven (emd)": "electric",
                    "gas engine driven": "gas_engine",
                    "diesel engine driven": "diesel_engine",
                    "steam turbine driven": "steam",
                }[drive_value]
                rating_text = install_match.group("rating")
                rating = Decimal(rating_text.replace(",", ""))
                exponent = rating.as_tuple().exponent
                if (
                    len(rating_text) > 100
                    or len(rating.as_tuple().digits) > 64
                    or not isinstance(exponent, int)
                    or exponent < -100
                    or exponent > 100
                    or not rating.is_finite()
                    or rating <= 0
                ):
                    result.issues.append(f"Invalid installation rating at offset {raw_start}.")
                    unsupported.append(
                        UnsupportedActivity("unresolved_installation", quote, raw_start, raw_end)
                    )
                    continue
                unit = install_match.group("unit").casefold()
                unit = {"hp": "hp", "kw": "kW", "mw": "MW", "kva": "kVA"}[unit]
                claim_values = [
                    "compressor",
                    drive,
                    "proposed",
                    count,
                    str(rating),
                    unit,
                    "unknown",
                ]
                semantic_digest = sha256(
                    json.dumps([site_digest, *claim_values], separators=(",", ":")).encode()
                ).hexdigest()
                claim_key = f"claim:{semantic_digest}"
                if claim_key in seen_claim_keys:
                    result.issues.append(
                        f"Repeated unidentified installation assertion at offset "
                        f"{raw_start}; equipment identity is ambiguous."
                    )
                    unsupported.append(
                        UnsupportedActivity(
                            "duplicate_unidentified_installation", quote, raw_start, raw_end
                        )
                    )
                    continue
                seen_claim_keys.add(claim_key)
                site_claims.append(
                    NativeEquipmentClaim(
                        equipment_type="compressor",
                        claim_key=claim_key,
                        drive=drive,
                        lifecycle_status="proposed",
                        count=count,
                        rating=rating,
                        rating_unit=unit,
                        rating_basis="unknown",
                        source_equipment_id=None,
                        id_basis="derived_semantic_key",
                        role="unknown",
                        quote=quote,
                        start=raw_start,
                        end=raw_end,
                    )
                )
            else:
                result.issues.append(
                    f"Unresolved activity at offset {raw_start}; retained as source evidence."
                )
                unsupported.append(
                    UnsupportedActivity("unresolved_activity", quote, raw_start, raw_end)
                )
        h_start, h_end = _raw_span(
            offsets,
            tail_offset + heading.start("heading"),
            tail_offset + heading.end("heading"),
            len(text),
        )
        result.sites.append(
            NativeEquipmentSite(
                facility=facility,
                location=location,
                heading_quote=text[h_start:h_end],
                heading_start=h_start,
                heading_end=h_end,
                claims=tuple(site_claims),
                unsupported_activities=tuple(unsupported),
            )
        )
    if not result.sites:
        result.issues.append("No station records were extracted.")
    return result
