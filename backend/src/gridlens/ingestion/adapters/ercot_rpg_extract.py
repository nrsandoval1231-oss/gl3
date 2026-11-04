"""Evidence-bound extraction from ERCOT Regional Planning Group (RPG) documents.

Pure functions over page text (plus one PDF entry point that reads the text layer in the killable
child). Every value is stated in the document; each carries its basis, page, verbatim quote and the
quote's span inside the normalised page text. A value is dropped unless the same field pattern,
run again on the quote alone, returns the same value. Nothing is inferred:

* ``documented``  the value is stated as-is (a tier, an in-service date, a county, a MW figure);
* ``calculated``  deterministic unit scaling of a stated value (GW to MW, million to dollars);
* ``unknown``     not stated, or stated twice with conflicting values (both quotes are kept).

A project field is attributed to a project ID only when the statement names that one ID, or follows
such a statement on the same page before another ID appears, or the whole document names exactly
one ID. Anything else stays unknown. MW is never taken from a study-assumption sentence, only from
the "addition of approximately N MW/GW load" shape of a project statement.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from gridlens.ingestion.adapters.tceq_application_documents import DocumentFailure

VERSION = "ercot-rpg-extract-v1"
MAX_PROJECTS = 60
MAX_LIST = 20
MAX_QUOTE = 300
MAX_PDF_BYTES = 40 * 1024 * 1024
MAX_PAGES = 400

PROJECT_ID = re.compile(r"\b(\d{2}RPG\d{3})\b")
_BOUNDARY = re.compile(r"(?m)^(?=[ \t]*[•◦▪‣·])")
_PUBLIC_LINE = re.compile(r"(?:CONFIDENTIAL)?PUBLIC\b")
_DIGITS_LINE = re.compile(r"\s*\d{1,3}\s*")
_WORD = r"[A-Z][A-Za-z.'’-]*"
_COUNTY = rf"{_WORD}(?: {_WORD})?"

_UTILITY = re.compile(
    r"^(?:[•◦▪‣·]\s*)?"
    r"(?P<u>[A-Z][A-Za-z&.'’-]*(?: [A-Za-z&.'’()-]+){0,6}?) submitted (?:the )?[^()]{3,160}?"
    r"\((?P<id>\d{2}RPG\d{3})\)"
)
_TIER = re.compile(r"\bTier\s+(?P<t>[1-4])\b")
_COST = re.compile(
    r"\bcost of (?:approximately )?\$\s?(?P<n>\d[\d,]*(?:\.\d+)?)\s*(?P<u>million|billion)\b",
    re.I,
)
_ISD = re.compile(r"in-service date(?: \(ISD\))? is (?P<d>(?:[A-Z][a-z]+ ){1,2}\d{4})\b")
_CCN = re.compile(
    r"\bwill (?P<neg>not )?require a Certificate of Convenience and Necessity\b", re.I
)
_LOAD = re.compile(
    r"\baddition of (?:approximately )?(?P<n>\d[\d,]*(?:\.\d+)?)\s*(?P<u>GW|MW)\s+"
    r"(?:of )?(?:new )?(?:large )?load\b",
    re.I,
)
_COUNTIES = re.compile(
    rf"\b(?:in|within|across)\s+(?P<c>{_COUNTY}(?:(?:, and |, | and ){_COUNTY})*)"
    r"\s+[Cc]ount(?:y|ies)\b"
)
_SUBSTATION = re.compile(
    rf"\bNew (?P<n>{_WORD}(?: {_WORD}){{0,3}}) (?:\d{{2,3}}(?:/\d{{2,3}})?-?\s?kV )"
    r"(?:switching )?(?:station|substation)\b"
)
_NEW_SUBSTATION = re.compile(
    rf"\b(?:new|proposed|future) (?P<n>{_WORD}(?: {_WORD}){{0,3}})"
    r"(?: \d{2,3}(?:/\d{2,3})?-?\s?kV)? [Ss]ubstation\b"
)
_LOAD_STATIONS = re.compile(r"\bNew Load (?:Stations?|Substations?)\b")
# A list dash is a dash after whitespace or at the start ("- Alpha"), never the hyphen of
# "In-Service".
_LIST_ITEM = re.compile(
    rf"(?<!\w)[–—-]\s+(?P<n>{_WORD}(?: {_WORD}){{0,3}})(?=,|;|\s+tapped|\s+connected|\s+[–—-]\s|$)"
)
_SENTENCE_END = re.compile(r"\.\s|\s[•◦▪‣·]\s")
_ASSUMPTION = re.compile(r"assum|study area|\bmodeled\b|\bwas added\b|\bwere added\b", re.I)

_SCALAR_FIELDS = ("utility", "tier", "cost", "in_service", "ccn", "load")
_STOP_NAMES = frozenset({"New", "Existing", "The", "This", "Proposed", "Load", "Loads"})


def normalise(text: str) -> str:
    return " ".join(text.split())


def _exact(value: Decimal) -> int | str:
    """An exact figure: an int when whole, else its exact decimal text (never truncated)."""
    if value == value.to_integral_value():
        return int(value)
    return format(value.normalize(), "f")


def _money(number: str, unit: str) -> tuple[int | str, str]:
    value = Decimal(number.replace(",", "")) * (
        Decimal(1_000_000) if unit.casefold() == "million" else Decimal(1_000_000_000)
    )
    return _exact(value), "calculated"


def _field_utility(text: str) -> Any:
    found = _UTILITY.search(text)
    return (found["u"].strip(), "documented", found["id"]) if found else None


def _field_tier(text: str) -> Any:
    found = _TIER.search(text)
    return (f"Tier {found['t']}", "documented") if found else None


def _field_cost(text: str) -> Any:
    found = _COST.search(text)
    if not found:
        return None
    try:
        value, basis = _money(found["n"], found["u"])
    except (InvalidOperation, ValueError):
        return None
    return (value, basis)


def _field_in_service(text: str) -> Any:
    found = _ISD.search(text)
    return (found["d"], "documented") if found else None


def _field_ccn(text: str) -> Any:
    found = _CCN.search(text)
    return (found["neg"] is None, "documented") if found else None


def _field_load(text: str) -> Any:
    found = _LOAD.search(text)
    if not found:
        return None
    try:
        number = Decimal(found["n"].replace(",", ""))
    except InvalidOperation:
        return None
    if found["u"].upper() == "GW":
        return (_exact(number * 1000), "calculated")
    return (_exact(number), "documented")


_EXTRACTORS = {
    "utility": _field_utility,
    "tier": _field_tier,
    "cost": _field_cost,
    "in_service": _field_in_service,
    "ccn": _field_ccn,
    "load": _field_load,
}
_MATCHERS = {
    "utility": _UTILITY,
    "tier": _TIER,
    "cost": _COST,
    "in_service": _ISD,
    "ccn": _CCN,
    "load": _LOAD,
}


def _quote_around(segment: str, start: int, end: int) -> str:
    """The match plus bounded context, cut at word edges, inside the normalised segment."""
    lo = max(0, start - 90)
    hi = min(len(segment), end + 90)
    while lo > 0 and segment[lo - 1] != " ":
        lo -= 1
    while hi < len(segment) and segment[hi] != " ":
        hi += 1
    quote = segment[lo:hi].strip()
    if len(quote) > MAX_QUOTE:
        quote = segment[max(0, start - 20) : min(len(segment), end + 20)].strip()[:MAX_QUOTE]
    return quote


def _locate(page_text: str, quote: str) -> list[int] | None:
    at = page_text.find(quote)
    return [at, at + len(quote)] if at >= 0 else None


def _evidence(
    value: Any, basis: str, page: int, quote: str, page_norm: str, **extra: Any
) -> dict[str, Any] | None:
    span = _locate(page_norm, quote)
    if span is None:
        return None
    return {
        "value": value,
        "basis": basis,
        "page": page,
        "quote": quote,
        "span": span,
        **extra,
    }


def _strip_slide_header(page_text: str) -> str:
    """Drop the slide-header lines ("PUBLIC Title" or "Title" then "PUBLIC", then a number)."""
    lines = page_text.split("\n")
    drop = 0
    if lines and _PUBLIC_LINE.match(lines[0].strip()):
        drop = 1
    elif len(lines) > 1 and _PUBLIC_LINE.fullmatch(lines[1].strip()) and len(lines[0]) <= 80:
        drop = 2
    if drop and len(lines) > drop and _DIGITS_LINE.fullmatch(lines[drop]):
        drop += 1
    return "\n".join(lines[drop:])


def _segments(page_text: str) -> list[str]:
    raw = _strip_slide_header(page_text)
    return [normalise(part) for part in _BOUNDARY.split(raw) if part.strip()]


class _Project:
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self.values: dict[str, list[dict[str, Any]]] = {name: [] for name in _SCALAR_FIELDS}
        self.counties: list[dict[str, Any]] = []
        self.substations: list[dict[str, Any]] = []
        self.pages: set[int] = set()

    def add_scalar(self, name: str, evidence: dict[str, Any]) -> None:
        self.values[name].append(evidence)

    def add_list(self, target: list[dict[str, Any]], evidence: dict[str, Any]) -> None:
        if len(target) < MAX_LIST and all(
            e["value"].casefold() != evidence["value"].casefold() for e in target
        ):
            target.append(evidence)

    def render_places(self) -> dict[str, Any]:
        return {"counties": self.counties, "substations": self.substations}

    def render(self) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        for name in _SCALAR_FIELDS:
            found = self.values[name]
            distinct = {repr(e["value"]) for e in found}
            if not found:
                fields[name] = {"value": None, "basis": "unknown", "reason": "not_stated"}
            elif len(distinct) > 1:
                fields[name] = {
                    "value": None,
                    "basis": "unknown",
                    "reason": "conflicting_statements",
                    "candidates": found[:4],
                }
            else:
                fields[name] = found[0]
        fields["counties"] = self.counties or {
            "value": None,
            "basis": "unknown",
            "reason": "not_stated",
        }
        fields["substations"] = self.substations or {
            "value": None,
            "basis": "unknown",
            "reason": "not_stated",
        }
        return {"project_id": self.project_id, "pages": sorted(self.pages), "fields": fields}


def _counties_from(text: str) -> list[str]:
    found = _COUNTIES.search(text)
    if not found:
        return []
    parts = re.split(r", and |, | and ", found["c"])
    return [p.strip() for p in parts if p.strip() and p.split()[0] not in _STOP_NAMES]


def _substations_from(text: str) -> list[str]:
    names: list[str] = []
    for pattern in (_SUBSTATION, _NEW_SUBSTATION):
        for found in pattern.finditer(text):
            names.append(found["n"].strip())
    heading = _LOAD_STATIONS.search(text)
    if heading:
        tail = text[heading.end() :]
        stop = _SENTENCE_END.search(tail)
        if stop:
            tail = tail[: stop.start()]
        for item in _LIST_ITEM.finditer(tail):
            names.append(item["n"].strip())
    return [n for n in dict.fromkeys(names) if n.split()[0] not in _STOP_NAMES]


def extract_projects(pages: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Per-project documented fields and the unattributed places, from per-page text.

    Page numbers are 1-based. Places named where no single project ID applies are returned
    apart and never attached to a project.
    """
    all_ids = {i for text in pages for i in PROJECT_ID.findall(text)}
    sole = next(iter(all_ids)) if len(all_ids) == 1 else None
    projects: dict[str, _Project] = {}
    loose = _Project("unattributed")
    for number, page_text in enumerate(pages, start=1):
        page_norm = normalise(page_text)
        current: str | None = sole
        for position, segment in enumerate(_segments(page_text)):
            ids = set(PROJECT_ID.findall(segment))
            if len(ids) == 1:
                only = next(iter(ids))
                # Only a project-defining statement (the slide title, or "X submitted ... (ID)")
                # switches the project. A segment that merely mentions a different ID ("this
                # project supersedes 24RPG010") ends attribution instead of taking it over.
                defining = position == 0 or _UTILITY.match(segment) is not None
                if only == current:
                    pass
                elif defining:
                    current = only
                else:
                    current = None
            elif len(ids) > 1:
                current = None
            if current is None:
                # Named places on a page or statement with no single project ID are kept apart
                # and never attached to a project.
                _collect_places(loose, segment, number, page_norm)
                continue
            if current not in projects:
                if len(projects) >= MAX_PROJECTS:
                    continue
                projects[current] = _Project(current)
            project = projects[current]
            project.pages.add(number)
            _collect(project, segment, number, page_norm)
    return [projects[key].render() for key in sorted(projects)], loose.render_places()


def _collect(project: _Project, segment: str, page: int, page_norm: str) -> None:
    for name, matcher in _MATCHERS.items():
        found = matcher.search(segment)
        if not found:
            continue
        if name == "load" and (
            _ASSUMPTION.search(page_norm) or project.project_id not in page_norm
        ):
            continue
        quote = _quote_around(segment, found.start(), found.end())
        rerun = _EXTRACTORS[name](quote)
        if rerun is None or rerun != _EXTRACTORS[name](segment):
            continue
        if name == "utility":
            if rerun[2] != project.project_id:
                continue
            evidence = _evidence(rerun[0], rerun[1], page, quote, page_norm)
        else:
            evidence = _evidence(rerun[0], rerun[1], page, quote, page_norm)
            if evidence is not None and name in {"cost", "load"}:
                evidence["unit"] = "USD" if name == "cost" else "MW"
        if evidence is not None:
            project.add_scalar(name, evidence)
    _collect_places(project, segment, page, page_norm)


def _reverified_substation(name: str, quote: str) -> bool:
    """The name must be found again by a substation pattern or list item inside its own quote."""
    if name in _substations_from(quote):
        return True
    item = re.compile(
        rf"(?<!\w)[–—-]\s+{re.escape(name)}(?=,|;|\s+tapped|\s+connected|\s+[–—-]\s|$)"
    )
    return item.search(quote) is not None


def _collect_places(project: _Project, segment: str, page: int, page_norm: str) -> None:
    counties = _counties_from(segment)
    if counties:
        found = _COUNTIES.search(segment)
        assert found is not None
        quote = _quote_around(segment, found.start(), found.end())
        if _counties_from(quote) == counties:
            for county in counties:
                evidence = _evidence(county, "documented", page, quote, page_norm)
                if evidence is not None:
                    project.add_list(project.counties, evidence)
    names = _substations_from(segment)
    for name in names:
        anchor = segment.find(name)
        quote = _quote_around(segment, anchor, anchor + len(name))
        if _reverified_substation(name, quote):
            evidence = _evidence(name, "documented", page, quote, page_norm)
            if evidence is not None:
                project.add_list(project.substations, evidence)


def summary_lines(projects: list[dict[str, Any]]) -> list[str]:
    """Plain structured lines for the evidence text; values only, never quotes."""
    lines: list[str] = []
    for project in projects:
        fields = project["fields"]

        def one(name: str, fields: dict[str, Any] = fields) -> str:
            entry = fields[name]
            return "unknown" if entry.get("basis") == "unknown" else str(entry["value"])

        def many(name: str, fields: dict[str, Any] = fields) -> str:
            entry = fields[name]
            if isinstance(entry, dict):
                return "unknown"
            return ", ".join(e["value"] for e in entry)

        load = fields["load"]
        load_text = (
            "unknown" if load.get("basis") == "unknown" else f"{load['value']} MW ({load['basis']})"
        )
        cost = fields["cost"]
        cost_text = (
            "unknown"
            if cost.get("basis") == "unknown"
            else f"USD {cost['value']} ({cost['basis']})"
        )
        ccn = fields["ccn"]
        ccn_text = "unknown" if ccn.get("basis") == "unknown" else ("yes" if ccn["value"] else "no")
        lines.append(
            f"RPG project {project['project_id']}: utility {one('utility')}; "
            f"tier {one('tier')}; cost {cost_text}; in-service {one('in_service')}; "
            f"CCN required {ccn_text}; stated load {load_text}; counties {many('counties')}; "
            f"new substations {many('substations')}"
        )
    return lines


def count_fields(projects: list[dict[str, Any]]) -> int:
    total = 0
    for project in projects:
        for entry in project["fields"].values():
            if isinstance(entry, list) or entry.get("basis") != "unknown":
                total += 1
    return total


# --------------------------------------------------------------------------- PDF entry points


def read_pdf_pages(
    body: bytes, budget: float, isolate: bool, first_pages: int | None = None
) -> tuple[list[str], list[int]]:
    from gridlens.ingestion.parsers.permit_docs.text_layer import (
        TextLayerFailure,
        TextLayerLimits,
        build_canonical_text,
    )

    if not body.startswith(b"%PDF-"):
        raise DocumentFailure("not_pdf_signature")
    limits = TextLayerLimits(
        max_bytes=MAX_PDF_BYTES,
        max_pages=MAX_PAGES,
        max_seconds=budget,
        max_seconds_per_page=60.0,
        first_pages=first_pages,
    )
    canon = build_canonical_text(body, limits, isolate=isolate)
    if isinstance(canon, TextLayerFailure):
        raise DocumentFailure(f"text_layer_{canon.code}")
    if canon.pages and len(canon.scanned_pages) >= len(canon.pages):
        raise DocumentFailure("empty_text_layer")
    return [page.text for page in canon.pages], list(canon.scanned_pages)[:200]


def rpg_project_extraction(pages: list[str], scanned: list[int]) -> dict[str, Any]:
    projects, unattributed = extract_projects(pages)
    return {
        "extractor": VERSION,
        "pages": len(pages),
        "scanned_pages": scanned,
        "projects": projects,
        "unattributed": unattributed,
        "summary_lines": summary_lines(projects),
        "fields_found": count_fields(projects),
        "abstain": None
        if projects
        else {
            "reason": "no project ID with stated fields",
            "note": "Abstention, not zero: unknown is not zero.",
        },
    }


# --------------------------------------------------------------------------- System Planning update

_AGGREGATES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "rpg_projects_under_review_usd",
        re.compile(r"\bOf the \$(?P<n>\d[\d,]*(?:\.\d+)?)\s*billion of RPG Projects", re.I),
        "billion",
    ),
    (
        "large_load_dependent_usd",
        re.compile(r"\$(?P<n>\d[\d,]*(?:\.\d+)?)\s*billion is Large Load-\s*dependent", re.I),
        "billion",
    ),
    (
        "non_large_load_dependent_usd",
        re.compile(
            r"\$(?P<n>\d[\d,]*(?:\.\d+)?)\s*billion is Non-\s*Large Load-\s*dependent", re.I
        ),
        "billion",
    ),
    (
        "endorsed_transmission_total_usd",
        re.compile(
            r"endorsed transmission projects totaling \$(?P<n>\d[\d,]*(?:\.\d+)?)\s*billion", re.I
        ),
        "billion",
    ),
)
_YTD_PROJECTS = re.compile(
    r"\bYear to date (?P<y>20\d{2}),\s*(?P<n>\d[\d,]*)\s*new\s*projects", re.I
)
_AS_OF = re.compile(r"\bAs of (?P<d>[A-Z][a-z]+ \d{1,2}, \d{4})")


def system_planning_extraction(pages: list[str], scanned: list[int]) -> dict[str, Any]:
    """Stated aggregate totals only. These are ERCOT-wide figures, never a project or site."""
    values: dict[str, Any] = {}
    for number, text in enumerate(pages, start=1):
        norm = normalise(text)
        for name, pattern, _unit in _AGGREGATES:
            found = pattern.search(norm)
            if found and name not in values:
                quote = _quote_around(norm, found.start(), found.end())
                again = pattern.search(quote)
                if again is None or again["n"] != found["n"]:
                    continue
                dollars, basis = _money(found["n"], "billion")
                ev = _evidence(dollars, basis, number, quote, norm, unit="USD")
                if ev is not None:
                    values[name] = ev
        ytd = _YTD_PROJECTS.search(norm)
        if ytd and "new_planning_model_projects_ytd" not in values:
            quote = _quote_around(norm, ytd.start(), ytd.end())
            ev = _evidence(
                int(ytd["n"].replace(",", "")),
                "documented",
                number,
                quote,
                norm,
                year=int(ytd["y"]),
            )
            if ev is not None:
                values["new_planning_model_projects_ytd"] = ev
        as_of = _AS_OF.search(norm)
        if as_of and "as_of" not in values:
            quote = _quote_around(norm, as_of.start(), as_of.end())
            ev = _evidence(as_of["d"], "documented", number, quote, norm)
            if ev is not None:
                values["as_of"] = ev
    lines = [
        f"System Planning aggregate {name}: {entry['value']} ({entry['basis']})"
        for name, entry in sorted(values.items())
    ]
    return {
        "extractor": VERSION,
        "pages": len(pages),
        "scanned_pages": scanned,
        "aggregates": values,
        "summary_lines": lines,
        "fields_found": len(values),
        "note": "ERCOT-wide totals; no project, utility, county or site.",
    }
