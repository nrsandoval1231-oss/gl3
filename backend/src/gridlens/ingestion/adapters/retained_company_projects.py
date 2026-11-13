"""Offline adapter for the retained company/project public-source cohort.

The adapter reads only the bounded retained excerpt files. It derives source
records from each document's own text and metadata; reference customer/project
labels are never an input. Ambiguous or under-specified physical sites are
reported as HOLD and never sent to ingestion.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from gridlens.domain.project_activity_binding import activity_is_bound_to_project

SOURCE_ID = "retained-company-project-evaluation"
FAMILY = "retained-public-document"
RETRIEVAL_METHOD = "retained-company-projects"
SCHEMA_VERSION = "retained-company-project-v2"

_DATA_CENTER = re.compile(r"\b(?:data\s*cent(?:er|re)|hyperscale campus)\b", re.I)
_PROJECT_NOUN = re.compile(r"\b(?:campus|data\s*cent(?:er|re)|project|facility)\b", re.I)
_RELATION_LOCATION = re.compile(
    r"\b(?:in|at|near|within|inside)\s+(?:(?:its|the|a|an)\s+)?"
    r"(?P<place>[A-Z][A-Za-z.'’\-]*(?:\s+[A-Z][A-Za-z.'’\-]*){0,4}"
    r"(?:\s+County)?)\s*,\s*"
    r"(?P<state>Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|"
    r"Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|"
    r"Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|"
    r"Montana|Nebraska|Nevada|New\s+Hampshire|New\s+Jersey|New\s+Mexico|New\s+York|"
    r"North\s+Carolina|North\s+Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode\s+Island|"
    r"South\s+Carolina|South\s+Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|"
    r"West\s+Virginia|Wisconsin|Wyoming|AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|"
    r"IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|"
    r"SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b"
)
_REVERSE_SITE = re.compile(
    r"\b(?P<place>[A-Z][A-Za-z.'’\-]*(?:\s+[A-Z][A-Za-z.'’\-]*){0,3}),\s*"
    r"(?P<state>North\s+Dakota|South\s+Dakota|[A-Z]{2})\s+"
    r"(?P<subject>(?:(?:data\s*cent(?:er|re)|AI|hyperscale)\s+){1,4}"
    r"(?:campus|facility|site|project))\b"
)
_COUNTY_SUBJECT = re.compile(
    r"\b(?P<subject>(?:(?:new|mega-scale|hyperscale|AI|data\s*cent(?:er|re)|"
    r"campus|facility|site|project|development)\s+){1,7})"
    r"(?P<place>[A-Z][A-Za-z.'’\-]*(?:\s+[A-Z][A-Za-z.'’\-]*){0,3}\s+County)",
    re.I,
)
_CITY_SUBJECT = re.compile(
    r"\b(?P<subject>(?:(?:new|mega-scale|hyperscale|AI|data\s*cent(?:er|re)|"
    r"campus|facility|site|project|development)\s+){1,7})"
    r"(?P<place>[A-Z][A-Za-z.'’\-]*(?:\s+[A-Z][A-Za-z.'’\-]*){0,2})"
    r"\s*,\s*(?P<state>Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|"
    r"Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|"
    r"Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|"
    r"Montana|Nebraska|Nevada|New\s+Hampshire|New\s+Jersey|New\s+Mexico|New\s+York|"
    r"North\s+Carolina|North\s+Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode\s+Island|"
    r"South\s+Carolina|South\s+Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|"
    r"West\s+Virginia|Wisconsin|Wyoming|[A-Z]{2})\b"
)
_DEVELOP_SUBJECT = re.compile(
    r"\bto\s+(?:develop|build|construct)\s+(?:a\s+|an\s+|the\s+)?"
    r"(?P<subject>(?:[A-Za-z0-9'’&.\-]+\s+){0,6}"
    r"(?:data\s*cent(?:er|re)\s+campus|AI\s+campus|data\s*cent(?:er|re)|campus))\s+"
    r"(?:in|at|near|within|inside)\s+(?P<place>[A-Z][A-Za-z.'’\-]*(?:\s+[A-Z][A-Za-z.'’\-]*){0,3})"
    r"(?:,\s*(?P<state>[A-Z]{2}|Texas|California|Oregon|Ohio|Louisiana|North\s+Dakota|"
    r"South\s+Dakota|Wyoming|Mississippi|Arizona))?",
    re.I,
)
_ADVERSE_STATUS = re.compile(
    r"\b(?:cancelled|canceled|abandoned|withdrawn|suspended|terminated|"
    r"on\s+hold|not\s+proceeding|stopped)\b",
    re.I,
)
_ILLUSTRATIVE = re.compile(r"\b(?:for example|for instance|hypothetical(?:ly)?|e\.g\.)\b", re.I)
_OTHER_SITE_CLAUSE = re.compile(
    r"\b(?:while|whereas|but|although|and)\s+"
    r"(?:(?:a|an|the|another|separate|different|new)\s+)?"
    r"(?:[A-Z][A-Za-z0-9'’.-]*\s+){0,3}"
    r"(?:data\s*cent(?:er|re)|campus|facility|site|building)\b",
    re.I,
)
_BUILDING_RELATION = re.compile(
    r"\b(?P<subject>(?:its|the|a|an|first|second|third|fourth|new|additional|initial)\s+"
    r".{0,35}?(?:data\s*cent(?:er|re)|building|facility|campus))\s+"
    r"(?:is|are|was|were|currently|already|has|have)?\s*"
    r"(?:under construction|currently under construction|being built|construction\s+"
    r"(?:has\s+)?(?:begun|started|commenced))",
    re.I,
)
_ADJACENT_DC = re.compile(
    r"\b(?P<subject>new\s+data\s*cent(?:er|re)\s+adjacent\s+to\s+the\s+"
    r"[A-Z][A-Za-z'’.-]*(?:\s+[A-Z][A-Za-z'’.-]*){0,4}\s+Energy\s+Center)\b",
    re.I,
)
_PARK_SITE = re.compile(
    r"\b(?P<subject>(?:new\s+)?(?:data\s*cent(?:er|re)\s+)?campus)\s+"
    r"(?:inside|within|at)\s+(?:the\s+)?"
    r"(?P<place>[A-Z][A-Za-z'’.-]*(?:\s+[A-Z][A-Za-z'’.-]*){0,4}\s+"
    r"(?:Industrial Park|Technology Park|Business Park))\b"
)
_ACTIVITY = re.compile(
    r"\b(?:construction\s+(?:has\s+)?(?:begun|commenced|started)|"
    r"broke\s+ground|groundbreaking|commence(?:s|d)?\s+construction|"
    r"(?:is|are|currently)\s+under\s+construction|"
    r"construction\s+on\s+(?:the|its|a|this)\s+.{1,60}?\s+"
    r"(?:has\s+)?(?:already\s+)?(?:begun|commenced|started)|"
    r"(?:planned|plans?\s+to|will)\s+(?:develop|build|construct)|"
    r"\bto\s+(?:develop|build|construct)\b|"
    r"\b(?:is|are|was|were)\s+building\b|"
    r"(?:has\s+)?(?:commenced|begun|started)\s+development\s+of|"
    r"(?:commenced|begun|started)\s+(?:construction|development)\s+of|"
    r"development\s+of|expan(?:d|ds|ded|sion)\s+(?:the|its|a|this)?\s*"
    r"(?:new\s+)?(?:data\s*cent(?:er|re)|campus|site)|"
    r"(?:new|planned)\s+development\s+of\s+(?:a\s+)?(?:data\s*cent(?:er|re)|campus))\b",
    re.I,
)
_CONSTRUCTION = re.compile(
    r"\b(?:construction\s+(?:.{0,40}\s+)?(?:has\s+)?(?:begun|commenced|started)|"
    r"(?:is|are|currently)\s+under\s+construction|"
    r"construction\s+on\s+(?:the|its|a|this)\s+.{1,60}?\s+"
    r"(?:has\s+)?(?:already\s+)?(?:begun|commenced|started)|"
    r"broke\s+ground|groundbreaking|commence(?:s|d)?\s+construction|"
    r"construction\s+(?:will\s+)?(?:begin|start|commence))\b",
    re.I,
)
_QUOTED_PROJECT = re.compile(
    r"[\"“]([A-Z0-9][A-Za-z0-9'’&.\- ]{1,70})[\"”]"
    r"\s*(?:,?\s*(?:campus|data\s*cent(?:er|re)|project|facility)\b)?",
)
_NAMED_PROJECT = re.compile(
    r"\b((?:[A-Z][A-Za-z0-9'’&.\-]*\s+){0,4}"
    r"[A-Z][A-Za-z0-9'’&.\-]*)\s+"
    r"(?:data\s*cent(?:er|re)\s+campus|AI\s+campus|campus|data\s*cent(?:er|re))\b"
)
_PLACE = re.compile(
    r"\b(?:in|near|at|within)\s+(?:(?:its|the|a|an)\s+)?"
    r"(?P<place>[A-Z][A-Za-z.'’\-]*(?:\s+[A-Z][A-Za-z.'’\-]*){0,4}"
    r"(?:\s+County)?)\s*,\s*"
    r"(?P<state>Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|"
    r"Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|"
    r"Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|"
    r"Montana|Nebraska|Nevada|New\s+Hampshire|New\s+Jersey|New\s+Mexico|New\s+York|"
    r"North\s+Carolina|North\s+Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode\s+Island|"
    r"South\s+Carolina|South\s+Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|"
    r"West\s+Virginia|Wisconsin|Wyoming|AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|"
    r"IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|"
    r"SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b"
)
_COUNTY_LOCATION = re.compile(
    r"\b(?P<place>[A-Z][A-Za-z.'’\-]*(?:\s+[A-Z][A-Za-z.'’\-]*){0,3}\s+County)"
    r"\s*,\s*(?P<state>AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|"
    r"ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|"
    r"TN|TX|UT|VT|VA|WA|WV|WI|WY)\b",
    re.I,
)
_STATE_CODES = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}
_DATE_PATTERNS = (
    re.compile(
        r"\b(?:published\s*:\s*)?(January|February|March|April|May|June|July|"
        r"August|September|October|November|December)\s+(\d{1,2}),\s*(\d{4})\b",
        re.I,
    ),
    re.compile(
        r"\b(?:published\s*:\s*)?(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+"
        r"(\d{1,2}),\s*(\d{4})\b",
        re.I,
    ),
)


@dataclass(frozen=True)
class SiteCandidate:
    state: str
    project_name: str | None
    location: str | None
    activity_key: str | None
    rationale: str | None
    activity_quote: str | None
    location_quote: str | None
    reason: str
    project_quote: str | None = None
    phase: str | None = None
    source_spans: dict[str, Any] | None = None
    building_id: str | None = None


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def retained_record_hash(record: dict[str, Any]) -> str:
    """Stable native document version hash, separate from semantic identity."""
    fields = {
        "url": record.get("html_url"),
        "title": record.get("title"),
        "abstract": record.get("abstract"),
        "publication_date": record.get("publication_date"),
        "publication_date_precision": record.get("publication_date_precision"),
    }
    raw = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _digest(raw.encode("utf-8"))


def _normal_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _as_date(value: str | None, text: str) -> date | None:
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    # Publication metadata is limited to an exact day in a source header.
    # Dates later in the excerpt may be event/delivery targets and are not
    # publication dates. Month/year-only labels stay unknown.
    header = text[:320]
    for pattern, fmt in (
        (_DATE_PATTERNS[0], "%B %d, %Y"),
        (_DATE_PATTERNS[1], "%b %d, %Y"),
    ):
        match = pattern.search(header)
        if match:
            try:
                month, day, year = match.groups()
                return datetime.strptime(f"{month} {day}, {year}", fmt).date()
            except ValueError:
                continue
    return None


def _activity(text: str) -> tuple[str | None, str | None, str | None, tuple[int, int] | None]:
    match = _ACTIVITY.search(text)
    if match is None:
        return None, None, None, None
    activity_start, matched_end = match.span()
    activity_end = matched_end
    prefix = text[max(0, activity_start - 180) : activity_start]
    if _ILLUSTRATIVE.search(prefix) or re.search(
        r"\b(?:not|never|no\s+longer|cannot|can't)\s+"
        r"(?:(?:yet|currently|now|at\s+this\s+time)\s+)*$",
        prefix,
        re.I,
    ):
        return None, None, None, None
    # A construction predicate belongs to a site only when its own clause
    # names that site as subject/object. Do not borrow a predicate from an
    # unrelated facility introduced in a following prepositional phrase.
    predicate_clause = text[max(0, activity_start - 120) : activity_end]
    if re.search(
        r"\b(?:from|by|at|inside|within)\s+(?:the\s+)?"
        r"[A-Z][A-Za-z0-9'’&.\- ]{0,55}\b(?:facility|campus|site|data\s*cent(?:er|re))\b"
        r"\s*,?\s*(?:which\s+)?(?:is\s+|has\s+been\s+)?$",
        predicate_clause,
        re.I,
    ):
        return None, None, None, None
    if match.group(0).casefold() in {"development of", "develop", "to develop"}:
        tail = text[activity_end : activity_end + 100]
        object_match = re.match(r"\s+(?:its|the|a|an|this|new)?\s*[^,.;]{1,80}", tail, re.I)
        if object_match:
            activity_end += object_match.end()
    quote = _normal_text(text[activity_start:activity_end])
    if _CONSTRUCTION.search(quote):
        return (
            "construction",
            quote,
            "Source reports construction activity at a named site.",
            (activity_start, activity_end),
        )
    return (
        "facility-expansion",
        quote,
        "Source reports planned or active site development.",
        (activity_start, activity_end),
    )


def _sentences(text: str) -> list[tuple[int, int, str]]:
    """Split on punctuation outside markdown links and decimal numbers."""
    result = []
    starts = [0]
    in_link_target = False
    i = 0
    while i < len(text):
        if text.startswith("](", i):
            in_link_target = True
            i += 2
            continue
        if in_link_target and text[i] == ")":
            in_link_target = False
            i += 1
            continue
        char = text[i]
        if char in ".!?" and not in_link_target:
            if char == "." and i + 1 < len(text) and not text[i + 1].isspace():
                i += 1
                continue
            decimal = (
                char == "."
                and i > 0
                and i + 1 < len(text)
                and text[i - 1].isdigit()
                and text[i + 1].isdigit()
            )
            if not decimal:
                j = i + 1
                while j < len(text) and text[j].isspace():
                    j += 1
                # Do not break a markdown anchor's visible text from its
                # linked destination; relation parsing sees the visible text.
                if j < len(text) and (text[j].isupper() or text[j] in '#*[-"“'):
                    starts.append(j)
        i += 1
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        left = start + len(text[start:end]) - len(text[start:end].lstrip())
        right = start + len(text[start:end].rstrip())
        sentence = text[left:right]
        if sentence:
            result.append((left, right, sentence))
    return result


def _source_name(
    sentence: str,
    sentence_offset: int,
    subject_start: int,
    subject_end: int,
    subject_quote: str,
    place: str,
    following: list[tuple[int, str]],
) -> tuple[str, str, tuple[int, int]]:
    """Keep the physical subject; aliases require their separate source proof."""
    return (
        _normal_text(subject_quote),
        subject_quote,
        (sentence_offset + subject_start, sentence_offset + subject_end),
    )


def _relation_candidates(sections: list[str]) -> list[SiteCandidate]:
    candidates: list[SiteCandidate] = []
    for section_index, section in enumerate(sections):
        sentences = _sentences(section)
        for index, (start, _end, sentence) in enumerate(sentences):
            relations = []
            adjacent = _ADJACENT_DC.search(sentence)
            for location in _RELATION_LOCATION.finditer(sentence):
                if adjacent and location.start() > adjacent.end():
                    continue
                nouns = [
                    noun
                    for noun in _PROJECT_NOUN.finditer(sentence[: location.start()])
                    if location.start() - noun.end() <= 180
                ]
                if not nouns:
                    continue
                noun = nouns[-1]
                subject_window = sentence[max(0, noun.start() - 120) : location.start() + 1]
                if not _DATA_CENTER.search(subject_window):
                    continue
                prefix = sentence[: noun.end()]
                typed_subject = re.search(
                    r"\b(?:(?:new|planned|proposed|largest|mega-scale|AI|hyperscale|"
                    r"\d+(?:\.\d+)?\s*(?:MW|megawatts?)?)\s+){0,5}"
                    r"(?:data\s*cent(?:er|re)\s+)?(?:campus|facility|site|project)\b$",
                    prefix,
                    re.I,
                )
                if not typed_subject:
                    continue
                subject = _normal_text(typed_subject.group(0))
                subject_start, subject_end = typed_subject.span()
                relations.append((subject, subject_start, subject_end, location, "state"))
            if adjacent:
                for location in _RELATION_LOCATION.finditer(sentence):
                    if (
                        location.start() > adjacent.end()
                        and location.start() - adjacent.end() < 100
                    ):
                        relations.append(
                            (
                                adjacent.group("subject"),
                                adjacent.start("subject"),
                                adjacent.end("subject"),
                                location,
                                "state",
                            )
                        )
                        break
            # A named campus may be the physical subject of an explicit
            # construction-at or construction-in relation.
            for match in re.finditer(
                r"\b(?P<verb>construction\s+(?:has\s+)?(?:begun|started|commenced))\s+"
                r"(?:at|on)\s+(?:the\s+)?(?P<site>[A-Z][A-Za-z0-9'’&.\- ]{1,55}?)\s+"
                r"in\s+(?P<place>[A-Z][A-Za-z.'’\-]*(?:\s+[A-Z][A-Za-z.'’\-]*){0,2}),\s*"
                r"(?P<state>North\s+Dakota|South\s+Dakota|Texas|California|Oregon|Ohio|"
                r"Louisiana|Wyoming|Mississippi|Arizona|Alabama|Arkansas|Colorado|Florida|"
                r"Georgia|Illinois|Indiana|Iowa|Kansas|Kentucky|Michigan|Minnesota|Missouri|"
                r"Nevada|New\s+York|North\s+Carolina|Oklahoma|Pennsylvania|Tennessee|Utah|"
                r"Virginia|Washington|Wisconsin|[A-Z]{2})(?![A-Za-z])",
                sentence,
                re.I,
            ):
                site = match.group("site").strip()
                if re.search(r"\b(?:campus|data\s*cent(?:er|re)|facility|site)\b", site, re.I):
                    relations.append(
                        (site, match.start("site"), match.end("site"), match, "direct")
                    )
            for location in _REVERSE_SITE.finditer(sentence):
                if not _DATA_CENTER.search(location.group("subject")):
                    continue
                relations.append(
                    (
                        location.group("subject"),
                        location.start("subject"),
                        location.end("subject"),
                        location,
                        "state",
                    )
                )
            for site in _PARK_SITE.finditer(sentence):
                if not _DATA_CENTER.search(site.group("subject")):
                    continue
                relations.append(
                    (
                        site.group("subject"),
                        site.start("subject"),
                        site.end("subject"),
                        site,
                        "park",
                    )
                )
            # County or explicit city-state descriptions can bind a subject
            # only when the facility noun precedes that locality in the same
            # sentence. Location-first appositives/datelines are excluded.
            for location in _COUNTY_SUBJECT.finditer(sentence):
                subject = _normal_text(location.group("subject"))
                if _DATA_CENTER.search(subject) and _PROJECT_NOUN.search(subject):
                    relations.append(
                        (
                            subject,
                            location.start("subject"),
                            location.end("subject"),
                            location,
                            "county",
                        )
                    )
            for location in _CITY_SUBJECT.finditer(sentence):
                subject = _normal_text(location.group("subject"))
                if _DATA_CENTER.search(subject) and _PROJECT_NOUN.search(subject):
                    relations.append(
                        (
                            subject,
                            location.start("subject"),
                            location.end("subject"),
                            location,
                            "city",
                        )
                    )
            for location in _DEVELOP_SUBJECT.finditer(sentence):
                subject = _normal_text(location.group("subject"))
                if not _DATA_CENTER.search(subject):
                    continue
                relations.append(
                    (
                        subject,
                        location.start("subject"),
                        location.end("subject"),
                        location,
                        "develop",
                    )
                )
            # A relation clause must name one physical subject and one location.
            unique_relations = {}
            for relation in relations:
                unique_relations[(relation[0].casefold(), relation[3].group(0).casefold())] = (
                    relation
                )
            if len(unique_relations) != 1:
                continue
            subject, subject_start, subject_end, location_relation, location_kind = next(
                iter(unique_relations.values())
            )
            if location_kind == "park":
                project_location = _normal_text(location_relation.group("place"))
                location_quote = location_relation.group(0)
            elif location_kind == "county":
                project_location = _normal_text(location_relation.group("place"))
                location_quote = location_relation.group("place")
            elif location_kind == "direct":
                place = _normal_text(location_relation.group("place"))
                state_raw = location_relation.group("state")
                state = _STATE_CODES.get(state_raw.casefold(), state_raw.upper())
                project_location = f"{place}, {state}"
                location_quote = f"{place}, {state_raw}"
            elif location_kind == "develop":
                place = _normal_text(location_relation.group("place"))
                state_raw = location_relation.group("state")
                state = (
                    _STATE_CODES.get(state_raw.casefold(), state_raw.upper()) if state_raw else None
                )
                project_location = f"{place}, {state}" if state else place
                location_quote = location_relation.group("place") + (
                    f", {state_raw}" if state_raw else ""
                )
            elif location_kind == "city":
                place = _normal_text(location_relation.group("place"))
                state_raw = location_relation.group("state")
                state = _STATE_CODES.get(state_raw.casefold(), state_raw.upper())
                project_location = f"{place}, {state}"
                location_quote = location_relation.group("place") + ", " + state_raw
            else:
                place = _normal_text(location_relation.group("place"))
                state_raw = location_relation.group("state")
                state = _STATE_CODES.get(state_raw.casefold(), state_raw.upper())
                project_location = f"{place}, {state}"
                location_quote = location_relation.group(0)
            following = [
                (next_start, next_sentence)
                for next_start, _next_end, next_sentence in sentences[index + 1 : index + 3]
            ]
            name, project_quote, name_span = _source_name(
                sentence,
                start,
                subject_start,
                subject_end,
                subject,
                project_location,
                following,
            )
            if not name:
                candidates.append(
                    SiteCandidate(
                        "HOLD",
                        None,
                        project_location,
                        None,
                        None,
                        None,
                        location_quote,
                        "Multiple source-native project names share one site clause",
                        subject,
                        source_spans={
                            "project": [start + subject_start, start + subject_end],
                            "location": [
                                start + location_relation.start(),
                                start + location_relation.end(),
                            ],
                        },
                    )
                )
                continue
            activity_sentence = sentence
            relation_end = max(location_relation.end(), subject_end)
            other_clause = _OTHER_SITE_CLAUSE.search(sentence[relation_end:])
            if other_clause:
                activity_sentence = sentence[: relation_end + other_clause.start()]
            activity, activity_quote, rationale, activity_span = _activity(activity_sentence)
            if activity is not None and activity_span is not None:
                primitive = _ACTIVITY.search(activity_sentence)
                activity_owns_site = activity_is_bound_to_project(
                    activity_sentence,
                    subject_span=(subject_start, subject_end),
                    activity_span=primitive.span() if primitive else activity_span,
                    site_span=(location_relation.start(), location_relation.end()),
                )
                if not activity_owns_site:
                    activity = activity_quote = rationale = None
                    activity_span = None
            if location_kind == "park":
                project_label = f"{project_location} data center campus"
                project_quote = subject
                project_span = (start + subject_start, start + subject_end)
            elif adjacent and subject.casefold() == adjacent.group("subject").casefold():
                project_label = _normal_text(adjacent.group("subject"))
                project_quote = adjacent.group("subject")
                project_span = (
                    start + adjacent.start("subject"),
                    start + adjacent.end("subject"),
                )
            elif location_kind in {"state", "city"} and re.match(
                r"^(?:development|develop|to develop|serve|its|the|a|an|new|planned)\b",
                name,
                re.I,
            ):
                place = _normal_text(location_relation.group("place"))
                project_label = f"{place} data center campus"
                project_quote = subject
                project_span = (start + subject_start, start + subject_end)
            elif name.casefold() in {
                "new data center campus",
                "new campus",
                "data center campus",
            } or re.fullmatch(
                r"\d+(?:\.\d+)?\s*(?:MW|megawatts?)\s+(?:data\s*cent(?:er|re)\s+)?campus",
                name,
                re.I,
            ):
                project_label = f"{project_location} data center campus"
                project_quote = subject
                project_span = (start + subject_start, start + subject_end)
            else:
                project_label = name
                project_span = name_span
            building_match = _BUILDING_RELATION.search(activity_sentence)
            if activity is None and building_match and _PROJECT_NOUN.search(subject):
                building_subject = building_match.span("subject")
                building_phrase = re.search(r"under construction", building_match.group(0), re.I)
                building_activity_span = (
                    (
                        building_match.start("subject") + building_phrase.start(),
                        building_match.start("subject") + building_phrase.end(),
                    )
                    if building_phrase
                    else None
                )
                building_bound = bool(
                    building_activity_span
                    and activity_is_bound_to_project(
                        activity_sentence,
                        subject_span=building_subject,
                        activity_span=building_activity_span,
                        site_span=(location_relation.start(), location_relation.end()),
                    )
                )
                if building_bound:
                    activity = "construction"
                    activity_quote = _normal_text(building_match.group(0))
                    rationale = "Source reports construction of a building within the named site."
                    activity_span = building_activity_span
            phase = None
            building_id = None
            activity_offset = start
            if activity is None:
                for next_start, next_sentence in following:
                    phase_match = re.search(
                        r"\b(first|second|third|fourth)\s+building\b", next_sentence, re.I
                    )
                    anaphor = re.match(
                        r"^\s*(?:the|this|its)\s+(?:same\s+)?"
                        r"(?:campus|data\s*cent(?:er|re)|site|project|facility)\b",
                        next_sentence,
                        re.I,
                    )
                    competing_site = bool(
                        re.search(
                            r"\b(?:another|different|other|north|south|east|west)\s+"
                            r"(?:campus|data\s*cent(?:er|re)|site|facility)\b",
                            next_sentence,
                            re.I,
                        )
                    )
                    if competing_site:
                        continue
                    deal_support = bool(
                        adjacent
                        and re.match(r"^\s*The deal\b", next_sentence, re.I)
                        and re.search(
                            r"\bto support a new .{0,45}?facility\b.{0,45}?"
                            r"(?:currently\s+)?under construction",
                            next_sentence,
                            re.I,
                        )
                    )
                    if not (anaphor or deal_support):
                        continue
                    activity, activity_quote, rationale, activity_span = _activity(next_sentence)
                    if activity is not None:
                        if deal_support:
                            facility = re.search(
                                r"\b(?:a|the|new)\s+(?:state\s+of\s+the\s+art\s+)?"
                                r"facility\b",
                                next_sentence,
                                re.I,
                            )
                            subject_span = facility.span() if facility else None
                        else:
                            subject_span = anaphor.span() if anaphor else None
                        activity_bound = bool(
                            subject_span
                            and activity_span
                            and activity_is_bound_to_project(
                                next_sentence,
                                subject_span=subject_span,
                                activity_span=activity_span,
                                site_span=subject_span,
                            )
                        )
                        if activity_bound:
                            activity_offset = next_start
                            if phase_match:
                                building_id = {
                                    "first": "1",
                                    "second": "2",
                                    "third": "3",
                                    "fourth": "4",
                                }[phase_match.group(1).casefold()]
                            break
                        activity = activity_quote = rationale = None
                        activity_span = None
            if activity is None or activity_span is None:
                continue
            activity_abs = (
                [activity_offset + activity_span[0], activity_offset + activity_span[1]]
                if activity_span
                else None
            )
            project_rel = project_span[0]
            location_rel = [start + location_relation.start(), start + location_relation.end()]
            candidates.append(
                SiteCandidate(
                    "CANDIDATE",
                    project_label,
                    project_location,
                    activity,
                    rationale,
                    activity_quote,
                    location_quote,
                    "Explicit source project/location relation and activity",
                    project_quote,
                    phase,
                    {
                        "project": [project_rel, project_span[1]],
                        "location": location_rel,
                        "activity": activity_abs,
                        "section": [section_index, section_index],
                    },
                    building_id,
                )
            )
    return candidates


def _candidate(sections: list[str]) -> SiteCandidate:
    found = _relation_candidates(sections)
    candidates = [item for item in found if item.state == "CANDIDATE"]
    holds = [item for item in found if item.state == "HOLD"]
    if holds:
        return holds[0]
    if len(candidates) == 1:
        candidate = candidates[0]
        if _adverse_status_for_candidate(sections, candidate):
            return SiteCandidate(
                "HOLD",
                None,
                candidate.location,
                None,
                None,
                None,
                candidate.location_quote,
                "Adverse or contradictory status is reported near the selected site",
            )
        return candidate
    if len(candidates) > 1:
        unique_sites = {
            (item.project_name.casefold(), item.location.casefold())
            for item in candidates
            if item.project_name and item.location
        }
        if len(unique_sites) == 1:
            candidate = candidates[0]
            if _adverse_status_for_candidate(sections, candidate):
                return SiteCandidate(
                    "HOLD",
                    None,
                    candidate.location,
                    None,
                    None,
                    None,
                    candidate.location_quote,
                    "Adverse or contradictory status is reported near the selected site",
                )
            return candidate
        return SiteCandidate(
            "HOLD",
            None,
            None,
            None,
            None,
            None,
            None,
            "Multiple source-bound project/site relations in one retained document",
        )
    # A locality repeated across source excerpts does not prove that the
    # building activity belongs to this campus. Keep cross-section phase
    # candidates out until the source establishes an explicit native parent
    # relation within the same bounded clause.
    return SiteCandidate(
        "HOLD",
        None,
        None,
        None,
        None,
        None,
        None,
        "No complete source-bound project/location/activity relation",
    )


def _adverse_status_for_candidate(sections: list[str], candidate: SiteCandidate) -> bool:
    if not candidate.location:
        return False
    locality = candidate.location.split(",", 1)[0].casefold()
    selected_name = (candidate.project_quote or candidate.project_name or "").casefold()
    for section in sections:
        selected_site_context = False
        for _start, _end, sentence in _sentences(section):
            text = sentence.casefold()
            if locality in text or (selected_name and selected_name in text):
                selected_site_context = True
            if not _ADVERSE_STATUS.search(sentence):
                if re.search(
                    r"\b(?:another|separate|different|competing)\s+"
                    r"(?:data\s*cent(?:er|re)|campus|site|facility)\b",
                    sentence,
                    re.I,
                ):
                    selected_site_context = False
                continue
            anaphoric_status = bool(
                selected_site_context
                and re.search(r"\b(?:the|this|its)\s+(?:campus|site|facility|project)\b", text)
            )
            if locality in text or (selected_name and selected_name in text) or anaphoric_status:
                return True
            selected_site_context = False
    return False


def _source_project_aliases(
    sections: list[str], candidate: SiteCandidate, *, title: str = ""
) -> dict[str, Any]:
    """Extract explicit source-native site names linked by a named locality."""
    if not candidate.location:
        return {"project_aliases": [], "alias_spans": {}, "alias_quotes": {}}
    locality = candidate.location.split(",", 1)[0].strip()
    title_market = re.search(
        r"\b(?P<market>[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2})\s+Data Campus\b",
        title,
        re.I,
    )
    if title_market is None:
        return {"project_aliases": [], "alias_spans": {}, "alias_quotes": {}}
    market = _normal_text(title_market.group("market"))
    selected_spans = candidate.source_spans or {}
    selected_section = selected_spans.get("section", [None])[0]
    selected_relation_index: int | None = None
    selected_relation_sentence: tuple[int, int, str] | None = None
    if isinstance(selected_section, int) and 0 <= selected_section < len(sections):
        relation_spans = [selected_spans.get(key) for key in ("project", "location", "activity")]
        valid_spans: list[tuple[int, int]] = []
        for span in relation_spans:
            if (
                not isinstance(span, list)
                or len(span) != 2
                or not all(isinstance(value, int) for value in span)
            ):
                valid_spans = []
                break
            valid_spans.append((span[0], span[1]))
        if len(valid_spans) == 3:
            for sentence_index, row in enumerate(_sentences(sections[selected_section])):
                if all(row[0] <= span[0] and span[1] <= row[1] for span in valid_spans):
                    selected_relation_index = sentence_index
                    selected_relation_sentence = row
                    break
    if selected_relation_sentence is None or selected_relation_index is None:
        return {"project_aliases": [], "alias_spans": {}, "alias_quotes": {}}
    aliases: dict[str, tuple[int, int, str]] = {}
    cursor = 0
    for section_index, section in enumerate(sections):
        sentence_rows = _sentences(section)
        for index, (sentence_start, _sentence_end, sentence) in enumerate(sentence_rows):
            for match in _QUOTED_PROJECT.finditer(sentence):
                alias = _normal_text(match.group(1)).strip(" .,-")
                left = sentence[max(0, match.start() - 90) : match.start()]
                locality_alias = bool(
                    re.fullmatch(
                        re.escape(locality) + r"(?:\s+(?:data\s+center\s+)?campus)?",
                        alias,
                        re.I,
                    )
                )
                in_same_excerpt_next_sentence = (
                    section_index == selected_section and index == selected_relation_index + 1
                )
                in_next_excerpt_first_sentence = (
                    section_index == selected_section + 1
                    and index == 0
                    and selected_relation_index == len(_sentences(sections[selected_section])) - 1
                )
                selected_location_precedes = (
                    (in_same_excerpt_next_sentence or in_next_excerpt_first_sentence)
                    and candidate.location.casefold() in selected_relation_sentence[2].casefold()
                    and re.search(r"\bland\b", selected_relation_sentence[2], re.I) is not None
                )
                explicit_land_naming = bool(
                    re.fullmatch(
                        rf"\s*The\s+{re.escape(market)}\s+land\s+will\s+become\s+"
                        r"home\s+to\s+the\s+new\s*",
                        left,
                        re.I,
                    )
                ) and bool(_PROJECT_NOUN.search(alias))
                competing_site = bool(
                    re.search(
                        r"\b(?:another|separate|different|other|north|south|east|west)\s+"
                        r"(?:data\s*cent(?:er|re)|campus|site|facility)\b",
                        sentence,
                        re.I,
                    )
                )
                if (
                    not selected_location_precedes
                    or not explicit_land_naming
                    or competing_site
                    or not locality_alias
                ):
                    continue
                start = cursor + sentence_start + match.start()
                end = cursor + sentence_start + match.end()
                aliases[alias] = (start, end, match.group(0))
        cursor += len(section) + 2
    if len(aliases) != 1:
        return {"project_aliases": [], "alias_spans": {}, "alias_quotes": {}}
    alias, (start, end, quote) = next(iter(aliases.items()))
    return {
        "project_aliases": [alias],
        "alias_spans": {alias: [start, end]},
        "alias_quotes": {alias: quote},
    }


def retained_records(corpus: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return native ingestion rows and explicit HOLD receipts from retained files."""
    manifest = json.loads((corpus / "source-hashes.json").read_text())
    manifest_by_file = {item["file"]: item for item in manifest}
    records: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    documents: dict[str, dict[str, Any]] = {}
    for path in sorted((corpus / "sources").glob("*.json")):
        relative = path.relative_to(corpus).as_posix()
        expected = manifest_by_file.get(relative)
        artifact_bytes = path.read_bytes()
        if expected is None or _digest(artifact_bytes) != expected["sha256"]:
            raise ValueError(f"Retained source hash mismatch: {relative}")
        source = json.loads(artifact_bytes)
        if not isinstance(source.get("url"), str) or not source["url"].startswith("https://"):
            held.append({"source_file": relative, "state": "HOLD", "reason": "Invalid source URL"})
            continue
        excerpts = source.get("excerpts")
        if (
            not isinstance(excerpts, list)
            or not excerpts
            or any(not isinstance(x, str) for x in excerpts)
        ):
            held.append({"source_file": relative, "state": "HOLD", "reason": "No retained text"})
            continue
        body = "\n\n".join(excerpts)
        if _digest(body.encode()) != expected["excerpt_sha256"]:
            raise ValueError(f"Retained excerpt hash mismatch: {relative}")
        document = documents.setdefault(
            source["url"],
            {
                "title": str(source.get("title") or ""),
                "excerpts": [],
                "excerpt_source_files": {},
                "artifacts": [],
                "publication_date_metadata": [],
                "observation_dates": [],
            },
        )
        if isinstance(source.get("observation_date"), str):
            document["observation_dates"].append(source["observation_date"])
        if source.get("publication_date_metadata"):
            document["publication_date_metadata"].append(source["publication_date_metadata"])
        document["artifacts"].append(
            {
                "source_file": relative,
                "source_artifact_hash": expected["sha256"],
                "source_excerpt_hash": expected["excerpt_sha256"],
            }
        )
        for excerpt in excerpts:
            if excerpt not in document["excerpts"]:
                document["excerpts"].append(excerpt)
                document["excerpt_source_files"][excerpt] = [relative]
            elif relative not in document["excerpt_source_files"][excerpt]:
                document["excerpt_source_files"][excerpt].append(relative)

    for url, document in sorted(documents.items()):
        source_title = document["title"] or "Retained public project document"
        body = "\n\n".join(document["excerpts"])
        artifacts = document["artifacts"]
        relative = ", ".join(item["source_file"] for item in artifacts)
        body_hash = _digest(body.encode())
        source = {"url": url}
        sections = list(document["excerpts"])
        candidate = _candidate(sections)
        title_adverse = bool(
            re.search(r"\b(?:cancelled|canceled|abandoned|withdrawn)\b", source_title, re.I)
        )
        if candidate.state == "CANDIDATE" and title_adverse:
            candidate = SiteCandidate(
                "HOLD",
                None,
                candidate.location,
                None,
                None,
                None,
                candidate.location_quote,
                "Title signals a potentially adverse project status; native status review required",
            )
        if candidate.state != "CANDIDATE":
            held.append(
                {
                    "source_files": [item["source_file"] for item in artifacts],
                    "source_url": url,
                    "content_hash": body_hash,
                    **asdict(candidate),
                }
            )
            if title_adverse or "Adverse or contradictory status" in str(candidate.reason):
                publication_date = _as_date(
                    document["publication_date_metadata"][0]
                    if len(set(document["publication_date_metadata"])) == 1
                    and document["publication_date_metadata"]
                    else None,
                    body,
                )
                status_quote = (
                    source_title
                    if title_adverse
                    else next(
                        (
                            sentence
                            for section in sections
                            for _start, _end, sentence in _sentences(section)
                            if _ADVERSE_STATUS.search(sentence)
                            and (
                                not candidate.location
                                or candidate.location.split(",", 1)[0].casefold()
                                in sentence.casefold()
                            )
                        ),
                        "",
                    )
                )
                host = urlsplit(url).hostname or ""
                status_record = {
                    "document_number": hashlib.sha256(url.encode()).hexdigest(),
                    "title": source_title,
                    "abstract": body,
                    "html_url": url,
                    "publication_date": publication_date.isoformat() if publication_date else None,
                    "observation_date": max(document["observation_dates"])
                    if document["observation_dates"]
                    else None,
                    "publication_date_precision": "day" if publication_date else "unknown",
                    "source_body_hash": body_hash,
                    "source_hash": "",
                    "extraction_location": "retained excerpt text",
                    "retained_company_project": {
                        "schema_version": SCHEMA_VERSION,
                        "source_id": SOURCE_ID,
                        "publisher_host": host,
                        "source_files": [item["source_file"] for item in artifacts],
                        "source_artifacts": artifacts,
                        "source_url": url,
                        "body_hash": body_hash,
                        "status": "adverse_status_review",
                        "status_reason": candidate.reason,
                        "status_quote": status_quote,
                        "publication_date": publication_date.isoformat()
                        if publication_date
                        else None,
                        "publication_date_precision": "day" if publication_date else "unknown",
                    },
                }
                status_record["source_hash"] = retained_record_hash(status_record)
                status_context = status_record.get("retained_company_project")
                if isinstance(status_context, dict):
                    status_context["content_hash"] = status_record["source_hash"]
                records.append(status_record)
            continue
        source_aliases = _source_project_aliases(sections, candidate, title=source_title)
        metadata_dates = document["publication_date_metadata"]
        publication_date = _as_date(
            metadata_dates[0] if len(set(metadata_dates)) == 1 and metadata_dates else None,
            "\n".join(sections),
        )
        if publication_date is None:
            held.append(
                {
                    "source_files": [item["source_file"] for item in artifacts],
                    "source_url": url,
                    "content_hash": body_hash,
                    **asdict(candidate),
                    "state": "HOLD",
                    "reason": "No exact source publication date; undated activity not admitted",
                }
            )
            continue
        host = urlsplit(url).hostname or ""
        source_id = SOURCE_ID
        external_id = hashlib.sha256(url.encode()).hexdigest()
        section_ranges: list[dict[str, Any]] = []
        cursor = 0
        for index, excerpt in enumerate(sections):
            if index:
                cursor += 2
            start = cursor
            end = start + len(excerpt)
            section_ranges.append(
                {
                    "start": start,
                    "end": end,
                    "sha256": _digest(excerpt.encode()),
                    "source_files": document["excerpt_source_files"][excerpt],
                }
            )
            cursor = end
        candidate_spans = dict(candidate.source_spans or {})
        section_indexes = candidate_spans.get("section_indexes", {})
        for key in ("project", "location", "activity"):
            span = candidate_spans.get(key)
            if isinstance(span, list) and len(span) == 2:
                section_index = section_indexes.get(key, candidate_spans.get("section", [0])[0])
                section_start = section_ranges[section_index]["start"]
                candidate_spans[key] = [span[0] + section_start, span[1] + section_start]
        candidate_spans["section_indexes"] = section_indexes
        record = {
            "document_number": external_id,
            "title": source_title,
            "abstract": body,
            "html_url": url,
            "publication_date": publication_date.isoformat(),
            "observation_date": max(document["observation_dates"])
            if document["observation_dates"]
            else None,
            "event_date": None,
            "event_date_label": None,
            "extraction_location": "retained excerpt text",
            "source_body_hash": body_hash,
            "publication_date_precision": "day",
            "source_hash": "",
            "retained_company_project": {
                "schema_version": SCHEMA_VERSION,
                "source_id": source_id,
                "publisher_host": host,
                "source_files": [item["source_file"] for item in artifacts],
                "source_artifacts": artifacts,
                "source_url": url,
                "content_hash": "",
                "body_hash": body_hash,
                "project_name": candidate.project_name,
                "project_location": candidate.location,
                "activity_key": candidate.activity_key,
                "rationale": candidate.rationale,
                "activity_quote": candidate.activity_quote,
                "location_quote": candidate.location_quote,
                "project_quote": candidate.project_quote,
                "phase": candidate.phase,
                "building_id": candidate.building_id,
                "source_spans": candidate_spans,
                "section_ranges": section_ranges,
                **source_aliases,
                "publication_date": publication_date.isoformat(),
                "publication_date_precision": "day",
            },
        }
        record["source_hash"] = retained_record_hash(record)
        retained_context = record.get("retained_company_project")
        if isinstance(retained_context, dict):
            retained_context["content_hash"] = record["source_hash"]
        records.append(record)
    return records, held


def interpret_retained_company_project(record: dict[str, Any]) -> dict[str, str] | None:
    """Reparse exact retained text and verify every claimed source relation."""
    context = record.get("retained_company_project")
    if not isinstance(context, dict) or context.get("schema_version") != SCHEMA_VERSION:
        return None
    if context.get("status") == "adverse_status_review":
        return None
    if re.search(
        r"\b(?:cancelled|canceled|abandoned|withdrawn)\b",
        str(record.get("title") or ""),
        re.I,
    ):
        return None
    body = record.get("abstract")
    if not isinstance(body, str) or _digest(body.encode()) != record.get("source_body_hash"):
        return None
    if record.get("source_hash") != retained_record_hash(record):
        return None
    if _digest((record.get("html_url") or "").encode()) != record.get("document_number"):
        return None
    ranges = context.get("section_ranges")
    if not isinstance(ranges, list) or not ranges:
        return None
    sections: list[str] = []
    previous_end = 0
    for item in ranges:
        if not isinstance(item, dict):
            return None
        start, end = item.get("start"), item.get("end")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or start < previous_end
            or end <= start
            or end > len(body)
        ):
            return None
        section = body[start:end]
        if _digest(section.encode()) != item.get("sha256"):
            return None
        sections.append(section)
        previous_end = end
    if "\n\n".join(sections) != body:
        return None
    candidate = _candidate(sections)
    if candidate.state != "CANDIDATE":
        return None
    source_aliases = _source_project_aliases(
        sections, candidate, title=str(record.get("title") or "")
    )
    if (
        context.get("project_aliases") != source_aliases["project_aliases"]
        or context.get("alias_spans") != source_aliases["alias_spans"]
        or context.get("alias_quotes") != source_aliases["alias_quotes"]
    ):
        return None
    for alias, span in source_aliases["alias_spans"].items():
        if body[span[0] : span[1]] != source_aliases["alias_quotes"][alias]:
            return None
    spans = context.get("source_spans")
    if not isinstance(spans, dict):
        return None
    section_indexes = (candidate.source_spans or {}).get("section_indexes", {})
    for key in ("project", "location", "activity"):
        expected = (candidate.source_spans or {}).get(key)
        actual = spans.get(key)
        if not isinstance(expected, list) or not isinstance(actual, list) or len(actual) != 2:
            return None
        section_index = section_indexes.get(
            key, (candidate.source_spans or {}).get("section", [0])[0]
        )
        if not isinstance(section_index, int) or section_index >= len(ranges):
            return None
        base = ranges[section_index]["start"]
        if actual != [expected[0] + base, expected[1] + base]:
            return None
        quote = context.get(f"{key}_quote")
        if not isinstance(quote, str) or body[actual[0] : actual[1]] != quote:
            return None
    if (
        context.get("source_url") != record.get("html_url")
        or context.get("content_hash") != record.get("source_hash")
        or context.get("body_hash") != record.get("source_body_hash")
        or context.get("activity_key") not in {"construction", "facility-expansion"}
        or context.get("project_name") != candidate.project_name
        or context.get("project_location") != candidate.location
        or context.get("activity_key") != candidate.activity_key
        or context.get("activity_quote") != candidate.activity_quote
        or context.get("project_quote") != candidate.project_quote
        or context.get("location_quote") != candidate.location_quote
        or context.get("phase") != candidate.phase
        or context.get("building_id") != candidate.building_id
        or context.get("publication_date") != record.get("publication_date")
        or context.get("publication_date_precision") != record.get("publication_date_precision")
        or record.get("publication_date_precision") != "day"
        or context.get("rationale") != candidate.rationale
        or _as_date(record.get("publication_date"), body) is None
    ):
        return None
    observed = record.get("observation_date")
    if isinstance(observed, str):
        try:
            observed_date = date.fromisoformat(observed[:10])
            published_date = date.fromisoformat(record["publication_date"])
        except (TypeError, ValueError):
            return None
        if published_date > observed_date:
            return None
    if candidate.rationale is None:
        return None
    return {
        "name": context["project_name"],
        "activity_key": context["activity_key"],
        "rationale": candidate.rationale,
        "location": context["project_location"],
    }
