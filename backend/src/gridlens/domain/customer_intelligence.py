"""Conservative source-bound customer facts and deterministic account projections.

This module never resolves company/project identities and never converts activity
or rental demand into facility capacity. Bounds on imprecise dates are for ordering;
``display_label``, ``qualifier`` and ``precision`` are the presentation authority.
For deadlines, earliest is unknown; start/end only bound the source's date label.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Literal, TypedDict

FACTS_VERSION = "customer-facts-v1"
VERSION = "customer-intelligence-v1"
PRIORITY_VERSION = "customer-commercial-priority-v1"
MAX_TEXT = 200_000
MAX_CLAIMS = 200
CAPACITY_BASES = {"campus_development", "it_load", "utility_service", "generation"}
CAPACITY_TYPES = CAPACITY_BASES | {"individual_phase"}


def apply_priority_context(
    priority: dict,
    *,
    recent_material_change: bool = False,
    verified_contact_available: bool = False,
    geographic_fit: bool | None = None,
) -> dict:
    """Add retained, independently authorized commercial context without boosting confidence.

    Caller supplies a material-event existence check and current native contact
    availability at generation publication. Unknown geography contributes nothing.
    Reapplication replaces these components, making snapshot rebuilds idempotent.
    """
    result = deepcopy(priority)
    components = result.setdefault("components", {})
    context_keys = ("material_changes", "verified_contacts", "geographic_fit")
    base = result.get("potential", 0) - sum(components.get(key, 0) for key in context_keys)
    components.update(
        {
            "material_changes": 10 if recent_material_change else 0,
            "verified_contacts": 5 if verified_contact_available else 0,
            "geographic_fit": 5 if geographic_fit is True else 0,
        }
    )
    result["potential"] = min(100, max(0, base + sum(components[key] for key in context_keys)))
    result["score"] = result["potential"] * result.get("confidence", 0) // 100
    return result


EVENT_TYPES = {
    "announced_construction_start",
    "actual_construction_start",
    "expected_first_energization",
    "phase_energization",
    "full_operational_target",
    "operational_target",
    "ready_for_service",
}


class SourceReference(TypedDict, total=False):
    url: str
    evidence_id: str
    content_hash: str
    published_at: str | None
    observed_at: str | None
    authority: Literal["primary", "regulatory", "secondary", "unknown"]
    verification_status: Literal["verified", "reported", "unverified"]


class CapacityClaim(TypedDict):
    fact_id: str
    project_id: str
    value_mw: str
    capacity_type: str
    basis: str
    scope_id: str
    phase_id: str | None
    includes_scope_ids: list[str]
    disjoint_scope_ids: list[str]
    qualifier: str
    quote: str
    source: dict[str, Any]
    status: str
    explicit_revision: bool
    extraction_method: str


_MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
_MONTH_PATTERN = "(?:" + "|".join(calendar.month_name[1:]) + ")"
_QUARTERS = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_DATE_PATTERN = (
    rf"(?:\d{{4}}-\d{{2}}-\d{{2}}|{_MONTH_PATTERN}\s+\d{{1,2}},?\s+\d{{4}}|"
    rf"Q[1-4][\s-]+\d{{4}}|(?:first|second|third|fourth)\s+quarter\s+of\s+"
    rf"(?:calendar\s+)?\d{{4}}|(?:first|second)\s+half\s+of\s+\d{{4}}|"
    rf"{_MONTH_PATTERN}\s+\d{{4}}|(?:early|mid|late)[\s-]+\d{{4}}|\d{{4}})"
)
_NUMBER = r"(?P<amount>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_UNIT = r"(?P<unit>gigawatts?|megawatts?|kilowatts?|GW|MW|kW)(?:\s*\((?:GW|MW|kW)\))?"
_QUALIFIER = r"(?P<qualifier>approximately|about|up\s+to|around|more\s+than|at\s+least|over)?"
_CAPACITY_LABELS = {
    "campus_development": (
        r"campus(?:\s+development)?\s+capacity|development\s+capacity|"
        r"(?:total|gross)\s+power\s+capacity|(?:GPU\s+)?compute\s+capacity"
    ),
    "it_load": r"(?:critical\s+)?IT\s+(?:load|capacity|power)",
    "utility_service": (
        r"utility\s+(?:service\s+)?capacity|(?:utility|electrical)\s+service\s+capacity"
    ),
    "generation": r"generation\s+capacity|generating\s+capacity",
}
_CAPACITY_PATTERNS = [
    (
        basis,
        re.compile(
            rf"\b(?:{label})\s*(?:is|of|:|=|will\s+be|will\s+have|totals?|reaches?)?\s*"
            rf"{_QUALIFIER}\s*{_NUMBER}[\s-]*{_UNIT}\b",
            re.I,
        ),
    )
    for basis, label in _CAPACITY_LABELS.items()
] + [
    (
        basis,
        re.compile(
            rf"\b{_QUALIFIER}\s*{_NUMBER}[\s-]*{_UNIT}"
            rf"\s+(?:of\s+)?(?:{label})\b",
            re.I,
        ),
    )
    for basis, label in _CAPACITY_LABELS.items()
]
_CAPACITY_PATTERNS.extend(
    [
        (
            "campus_development",
            re.compile(
                rf"\b{_QUALIFIER}\s*{_NUMBER}[\s-]*{_UNIT}\s+"
                r"(?:data\s+center\s+|hyperscale\s+|technology\s+)?campus\b",
                re.I,
            ),
        ),
        (
            "utility_service",
            re.compile(
                rf"\b(?:will\s+supply|will\s+provide|supplies)\s+{_QUALIFIER}\s*{_NUMBER}"
                rf"[\s-]*{_UNIT}\s+of\s+power\s+to\s+(?:the\s+)?(?:facility|campus|site)\b",
                re.I,
            ),
        ),
        (
            "utility_service",
            re.compile(rf"\b{_QUALIFIER}\s*{_NUMBER}[\s-]*{_UNIT}\s+sub[\s-]?station\b", re.I),
        ),
        (
            "generation",
            re.compile(
                rf"\b{_QUALIFIER}\s*{_NUMBER}[\s-]*{_UNIT}\s+"
                r"(?:sodium-cooled\s+fast\s+|nuclear\s+)?reactor\b",
                re.I,
            ),
        ),
        (
            "generation",
            re.compile(
                rf"\b{_QUALIFIER}\s*{_NUMBER}[\s-]*{_UNIT}\s+project\s+will\s+"
                r"provide\s+(?:zero-carbon|renewable|clean)\s+energy\b",
                re.I,
            ),
        ),
    ]
)
_CAPACITY_PATTERNS.extend(
    [
        (
            "utility_service",
            re.compile(
                rf"\b{_QUALIFIER}\s*{_NUMBER}[\s-]*{_UNIT}\s+agreement\b"
                r"[^.!?]{1,250}?\bto\s+serve\s+a\s+new\s+data\s+center\b",
                re.I,
            ),
        ),
        (
            "it_load",
            re.compile(
                rf"\bcritical\s+IT\s+(?:power|load)[^.!?]{{1,150}}?\bfor\s+a\s+total\s+of\s+"
                rf"{_QUALIFIER}\s*{_NUMBER}[\s-]*{_UNIT}\s+across\s+all\b",
                re.I,
            ),
        ),
    ]
)
_TIMELINE_PATTERNS = [
    (
        "actual_construction_start",
        re.compile(
            rf"\bconstruction\s+(?:began|started|commenced)\s+(?:on|in)\s+(?P<label>{_DATE_PATTERN})\b",
            re.I,
        ),
    ),
    (
        "announced_construction_start",
        re.compile(
            rf"\bconstruction\s+(?:(?:is|was|will)\s+)?(?:(?:expected|scheduled|planned|targeted)\s+to\s+)?"
            rf"(?:start|begin|commence|begins|starts)\s+(?:on|in)\s+(?P<label>{_DATE_PATTERN})\b",
            re.I,
        ),
    ),
    (
        "expected_first_energization",
        re.compile(
            rf"\b(?:first\s+energization|energization)\s+(?:(?:is|was)\s+)?"
            rf"(?:(?:expected|scheduled|planned|targeted)\s+)?(?:on|in|for)\s+(?P<label>{_DATE_PATTERN})\b",
            re.I,
        ),
    ),
    (
        "full_operational_target",
        re.compile(
            rf"\b(?:full\s+operations|full\s+operational\s+(?:target|date)|full\s+operation)\s+"
            rf"(?:(?:is|are)\s+)?(?:(?:expected|scheduled|planned|targeted)\s+)?"
            rf"(?:on|in|for)\s+(?P<label>{_DATE_PATTERN})\b",
            re.I,
        ),
    ),
]
_TIMELINE_PATTERNS.extend(
    [
        (
            "actual_construction_start",
            re.compile(
                rf"\bbegan\s+constructing\s+[^.!?]{{1,150}}?\s+in\s+(?P<label>{_DATE_PATTERN})\b",
                re.I,
            ),
        ),
        (
            "expected_first_energization",
            re.compile(
                rf"\bexpected\s+to\s+be\s+energized\s+in\s+(?:the\s+)?"
                rf"(?P<label>{_DATE_PATTERN})\b",
                re.I,
            ),
        ),
    ]
)
_TIMELINE_PATTERNS.extend(
    [
        (
            "ready_for_service",
            re.compile(
                rf"\bready\s+for\s+service\s+(?:date\s+of\s+|in\s+(?:the\s+)?)"
                rf"(?P<label>{_DATE_PATTERN})\b",
                re.I,
            ),
        ),
        (
            "operational_target",
            re.compile(
                rf"\bexpected\s+to\s+be\s+operational\s+(?:by|in)\s+(?:the\s+)?"
                rf"(?P<label>{_DATE_PATTERN})\b",
                re.I,
            ),
        ),
    ]
)
_NEGATION = re.compile(
    r"\b(?:not|never|denied|cancelled|canceled|hypothetical|could|might|may)\b", re.I
)
_REVISION = re.compile(
    r"\b(?:revised|updated|increased|reduced|rescheduled|delayed|postponed)\b", re.I
)
_PHASE = re.compile(r"\bphase\s+([0-9]{1,3}|[IVX]{1,6})\b", re.I)
_ALTERNATIVE_AMOUNT = re.compile(
    r"\b(?:gigawatts?|megawatts?|kilowatts?|GW|MW|kW)\b"
    r"(?:\s*\((?:GW|MW|kW)\))?\s*(?:or|to|through|and|[-–—])\s*\d"
    r"|\b(?:at least|between)\b",
    re.I,
)
_RANGE_PREFIX = re.compile(r"\d\s*(?:to|through|[-–—])\s*$", re.I)
_DATE_ALTERNATIVE = re.compile(r"^\s*(?:or|to|through|[-–—])\s*(?:\d{4}|Q[1-4])\b", re.I)
_ALLOCATION = re.compile(
    r"\b(?:lease|leases|option|offtake|fleet|portfolio|pipeline|footprint|follows|acquisition)\b",
    re.I,
)


def _key(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _format(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, str | int | Decimal):
        return None
    if len(str(value)) > 80:
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() and 0 < parsed <= Decimal("10000000") else None


def _date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _date_bounds(label: str) -> tuple[str, str, str] | None:
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", label):
            day = date.fromisoformat(label)
            return "day", day.isoformat(), day.isoformat()
        quarter = re.fullmatch(r"Q([1-4])[\s-]+(\d{4})", label, re.I)
        if quarter:
            year, month = int(quarter[2]), (int(quarter[1]) - 1) * 3 + 1
            return (
                "quarter",
                date(year, month, 1).isoformat(),
                date(year, month + 2, calendar.monthrange(year, month + 2)[1]).isoformat(),
            )
        if re.fullmatch(r"\d{4}", label):
            return "year", date(int(label), 1, 1).isoformat(), date(int(label), 12, 31).isoformat()
        words = re.fullmatch(
            r"(first|second|third|fourth)\s+quarter\s+of\s+(?:calendar\s+)?(\d{4})",
            label,
            re.I,
        )
        half = re.fullmatch(r"(first|second)\s+half\s+of\s+(\d{4})", label, re.I)
        if words or half:
            period = words or half
            assert period is not None
            year = int(period[2])
            month = (
                (_QUARTERS[period[1].lower()] - 1) * 3 + 1
                if words
                else (1 if period[1].lower() == "first" else 7)
            )
            last_month = month + (2 if words else 5)
            return (
                "quarter" if words else "half_year",
                date(year, month, 1).isoformat(),
                date(year, last_month, calendar.monthrange(year, last_month)[1]).isoformat(),
            )
        approximate = re.fullmatch(r"(?:early|mid|late)[\s-]+(\d{4})", label, re.I)
        if approximate:
            year = int(approximate[1])
            return "approximate_year", date(year, 1, 1).isoformat(), date(year, 12, 31).isoformat()
        human = re.fullmatch(rf"({_MONTH_PATTERN})\s+(?:(\d{{1,2}}),?\s+)?(\d{{4}})", label, re.I)
        if human:
            month, year = _MONTHS[human[1].lower()], int(human[3])
            if human[2]:
                day_label = date(year, month, int(human[2])).isoformat()
                return "day", day_label, day_label
            return (
                "month",
                date(year, month, 1).isoformat(),
                date(year, month, calendar.monthrange(year, month)[1]).isoformat(),
            )
    except ValueError:
        pass
    return None


def _source_copy(source: dict) -> dict:
    return {
        str(key): value.isoformat() if isinstance(value, date) else deepcopy(value)
        for key, value in source.items()
    }


def _scope_at(clause: str, position: int, project_id: str) -> tuple[str, str | None]:
    phases = list(_PHASE.finditer(clause[:position]))
    named = list(
        re.finditer(r"\b(initial|first|second|third|fourth)\s+phase\b", clause[:position], re.I)
    )
    phases.extend(named)
    phases.sort(key=lambda phase: phase.start())
    phase_id = phases[-1][1].lower() if phases else None
    return (
        (f"{project_id}:phase:{phase_id}", phase_id) if phase_id else (f"{project_id}:site", None)
    )


def extract_customer_facts(text: str, *, project_id: str, source: dict) -> dict:
    """Extract only explicitly typed, bounded source clauses; no engineering inference.

    The caller owns immutable source/project binding. This function returns exact
    source quotes and deterministic fact IDs; it does not certify verification.
    """
    result: dict[str, Any] = {
        "version": FACTS_VERSION,
        "project_id": project_id,
        "capacity_claims": [],
        "timeline_claims": [],
        "commissioning_inputs": [],
    }
    if not isinstance(text, str) or not project_id or not isinstance(source, dict):
        return result
    if len(text) > MAX_TEXT:
        result.update(overflow=True, limitations=["Source text exceeds bounded extraction length."])
        return result
    source_ref = _source_copy(source)
    clauses = re.split(r"(?<=[.!?])\s+|[\n;]+", text)
    if len(clauses) > 1000:
        result.update(overflow=True, limitations=["Source exceeds bounded extraction clauses."])
        return result
    for clause in clauses:
        if len(clause) > 2500 or _NEGATION.search(clause):
            continue
        revision = bool(_REVISION.search(clause))
        seen = set()
        for basis, pattern in _CAPACITY_PATTERNS:
            if _ALTERNATIVE_AMOUNT.search(clause) or _ALLOCATION.search(clause):
                continue
            for match in pattern.finditer(clause):
                raw = match["amount"].replace(",", "")
                amount = _decimal(raw)
                # A preceding sign/range means the positive point is not explicit.
                if amount is None or (match.start() and clause[match.start() - 1] in "-+–—"):
                    continue
                if _RANGE_PREFIX.search(clause[max(0, match.start() - 30) : match.start()]):
                    continue
                scope, phase_id = _scope_at(clause, match.start(), project_id)
                includes = []
                if re.search(r"for\s+a\s+total\s+of", match[0], re.I) and re.search(
                    r"across\s+all", match[0], re.I
                ):
                    scope, phase_id = f"{project_id}:site", None
                    includes = sorted(
                        {f"{project_id}:phase:{p[1].lower()}" for p in _PHASE.finditer(clause)}
                    )
                with localcontext() as context:
                    context.prec = 40
                    unit = match["unit"].lower()
                    factor = (
                        Decimal(1000)
                        if unit.startswith("g")
                        else Decimal("0.001")
                        if unit.startswith("k")
                        else Decimal(1)
                    )
                    amount *= factor
                if (basis, _format(amount)) in seen:
                    continue
                seen.add((basis, _format(amount)))
                qualifier = (match["qualifier"] or "").lower()
                qualifier = (
                    "more than" if clause[match.end() : match.end() + 1] == "+" else qualifier
                )
                normalized_qualifier = (
                    "up_to"
                    if qualifier == "up to"
                    else "more_than"
                    if qualifier in {"more than", "over"}
                    else "at_least"
                    if qualifier == "at least"
                    else "approximate"
                    if qualifier
                    else "exact"
                )
                fact: CapacityClaim = {
                    "fact_id": "cf_"
                    + _key([project_id, source_ref, clause, basis, scope, _format(amount)])[:32],
                    "project_id": project_id,
                    "value_mw": _format(amount),
                    "capacity_type": "individual_phase" if phase_id else basis,
                    "basis": basis,
                    "scope_id": scope,
                    "phase_id": phase_id,
                    "includes_scope_ids": includes,
                    "disjoint_scope_ids": [],
                    "qualifier": normalized_qualifier,
                    "quote": clause,
                    "source": deepcopy(source_ref),
                    "status": "reported",
                    "explicit_revision": revision,
                    "extraction_method": FACTS_VERSION,
                }
                result["capacity_claims"].append(fact)
        matches = []
        for event_type, pattern in _TIMELINE_PATTERNS:
            for match in pattern.finditer(clause):
                matches.append((match.start(), event_type, match))
        for _, event_type, match in sorted(matches, key=lambda row: row[0]):
            if _DATE_ALTERNATIVE.search(clause[match.end() :]):
                continue
            scope, phase_id = _scope_at(clause, match.start(), project_id)
            bounds = _date_bounds(match["label"])
            if bounds is None:
                continue
            if event_type == "expected_first_energization" and phase_id:
                event_type = "phase_energization"
            precision, start, end = bounds
            deadline = bool(re.search(r"\bby\s+(?:the\s+)?$", clause[: match.start("label")], re.I))
            result["timeline_claims"].append(
                {
                    "fact_id": "tf_"
                    + _key([project_id, source_ref, clause, event_type, scope, match["label"]])[
                        :32
                    ],
                    "project_id": project_id,
                    "event_type": event_type,
                    "label": match["label"],
                    "display_label": f"by {match['label']}" if deadline else match["label"],
                    "qualifier": "deadline" if deadline else "within",
                    "precision": precision,
                    "start": start,
                    "end": end,
                    "earliest": None if deadline else start,
                    "latest": end,
                    "scope_id": scope,
                    "quote": clause,
                    "source": deepcopy(source_ref),
                    "status": "actual" if event_type == "actual_construction_start" else "expected",
                    "explicit_revision": revision,
                    "extraction_method": FACTS_VERSION,
                }
            )
        if len(result["capacity_claims"]) + len(result["timeline_claims"]) >= MAX_CLAIMS:
            result.update(overflow=True, limitations=["Source exceeds bounded extraction claims."])
            break
    return result


def _source_valid(claim: dict, as_of: date) -> bool:
    source = claim.get("source")
    if not isinstance(source, dict) or source.get("current") is False:
        return False
    if claim.get("status") in {"withdrawn", "superseded", "retracted", "rejected"}:
        return False
    if not (source.get("url") or source.get("document_reference")):
        return False
    if not (source.get("evidence_id") or source.get("id")) or not source.get("content_hash"):
        return False
    published = _date(source.get("published_at"))
    return published is None or published <= as_of


def _strength(claim: dict) -> tuple[int, int]:
    source = claim["source"]
    verification = {"verified": 2, "reported": 1, "unverified": 0}.get(
        source.get("verification_status"), 0
    )
    authority = {"regulatory": 3, "primary": 3, "secondary": 1}.get(source.get("authority"), 0)
    return authority, verification


def _select(claims: list[dict], value_key: str) -> tuple[dict | None, list[str], list[str]]:
    """Authority first. A differing later value requires an explicit revision marker."""
    strongest = max(_strength(claim) for claim in claims)
    best = sorted((c for c in claims if _strength(c) == strongest), key=lambda c: c["fact_id"])
    weaker = [c["fact_id"] for c in claims if _strength(c) < strongest]
    values = {
        _key([c[value_key], c.get("qualifier", "exact" if value_key == "value_mw" else "within")])
        for c in best
    }
    if len(values) == 1:
        return best[0], sorted(weaker), []
    revisions = [
        c
        for c in best
        if c.get("explicit_revision") is True and _date(c["source"].get("published_at"))
    ]
    if revisions:
        revision_dates = [
            published
            for c in revisions
            if (published := _date(c["source"]["published_at"])) is not None
        ]
        newest = max(revision_dates)
        current = [c for c in best if _date(c["source"].get("published_at")) == newest]
        older = [c for c in best if c not in current]
        if len(
            {
                _key(
                    [
                        c[value_key],
                        c.get("qualifier", "exact" if value_key == "value_mw" else "within"),
                    ]
                )
                for c in current
            }
        ) == 1 and all(
            (published := _date(c["source"].get("published_at"))) is not None and published < newest
            for c in older
        ):
            return current[0], sorted(weaker + [c["fact_id"] for c in older]), []
    return None, sorted(weaker), sorted(c["fact_id"] for c in best)


def _capacity(claims: list[dict], project_count: int) -> dict:
    by_scope: dict[tuple[str, str], list[dict]] = {}
    for claim in claims:
        by_scope.setdefault((claim["basis"], claim["scope_id"]), []).append(claim)
    selected = []
    superseded: list[str] = []
    conflicts = []
    for (basis, scope), scoped in sorted(by_scope.items()):
        chosen, old, conflicting = _select(scoped, "value_mw")
        superseded.extend(old)
        if chosen:
            selected.append(chosen)
        if conflicting:
            conflicts.append(
                {
                    "basis": basis,
                    "scope_id": scope,
                    "claim_ids": conflicting,
                    "reason": "Equal-authority capacity claims disagree.",
                }
            )
    totals = []
    excluded: list[str] = []
    for basis in sorted({c["basis"] for c in claims}):
        current = [c for c in selected if c["basis"] == basis]
        included = {scope for claim in current for scope in claim.get("includes_scope_ids", [])}
        roots = [c for c in current if c["scope_id"] not in included]
        excluded.extend(c["fact_id"] for c in current if c["scope_id"] in included)
        conflict = any(c["basis"] == basis for c in conflicts)
        impossible_inclusion = any(
            Decimal(child["value_mw"]) > Decimal(parent["value_mw"])
            for parent in current
            for child in current
            if child["scope_id"] in parent.get("includes_scope_ids", [])
        )
        cycle = bool(current) and not roots
        overlap = any(
            right["scope_id"] not in left.get("disjoint_scope_ids", [])
            and left["scope_id"] not in right.get("disjoint_scope_ids", [])
            for i, left in enumerate(roots)
            for right in roots[i + 1 :]
        )
        status = (
            "conflict"
            if conflict or cycle or impossible_inclusion
            else "unknown_overlap"
            if overlap
            else "supported"
        )
        if status == "supported":
            upper = any(c.get("qualifier") == "up_to" for c in roots)
            lower = any(c.get("qualifier") in {"at_least", "more_than"} for c in roots)
            if upper and lower:
                status = "mixed_bounds"
            elif upper:
                status = "upper_bound"
            elif lower:
                status = "lower_bound"
        amount = None
        if status in {"supported", "upper_bound", "lower_bound"} and roots:
            with localcontext() as context:
                context.prec = 40
                amount = _format(sum((Decimal(c["value_mw"]) for c in roots), Decimal(0)))
        totals.append(
            {
                "basis": basis,
                "value_mw": amount,
                "status": status,
                "claim_ids": sorted(c["fact_id"] for c in roots),
                "qualifier": "unknown"
                if status == "mixed_bounds"
                else "approximate"
                if any(c.get("qualifier") == "approximate" for c in roots)
                else "up_to"
                if status == "upper_bound"
                else "more_than"
                if status == "lower_bound" and any(c.get("qualifier") == "more_than" for c in roots)
                else "at_least"
                if status == "lower_bound"
                else "exact",
                "complete": len(
                    {
                        c["project_id"]
                        for c in roots
                        if c.get("capacity_type") != "individual_phase"
                        and ":phase:" not in c["scope_id"]
                    }
                )
                == project_count
                and status in {"supported", "upper_bound", "lower_bound"},
            }
        )
    status = (
        "insufficient_data"
        if not totals
        else "conflict"
        if conflicts or any(t["status"] == "conflict" for t in totals)
        else "unknown_overlap"
        if any(t["status"] == "unknown_overlap" for t in totals)
        else "mixed_bounds"
        if any(t["status"] == "mixed_bounds" for t in totals)
        else "supported"
    )
    total = (
        totals[0]["value_mw"]
        if len(totals) == 1 and totals[0]["status"] == "supported" and totals[0]["complete"]
        else None
    )
    return {
        "status": status,
        "total_mw": total,
        "totals": totals,
        "claims": claims,
        "selected_claim_ids": sorted(c["fact_id"] for c in selected),
        "superseded_claim_ids": sorted(set(superseded)),
        "excluded_claim_ids": sorted(set(excluded)),
        "conflicts": conflicts,
        "coverage": {
            "projects_with_capacity": len({c["project_id"] for c in claims}),
            "projects_total": project_count,
        },
        "limitations": [
            "Different electrical bases are never added together.",
            "Partial supported amounts are not a complete company total.",
            "Mixed upper and lower bounds cannot establish an aggregate bound.",
        ],
    }


def _timelines(claims: list[dict]) -> dict:
    groups: dict[tuple[str, str], list[dict]] = {}
    for claim in claims:
        groups.setdefault((claim["event_type"], claim["scope_id"]), []).append(claim)
    selected, conflicts, superseded = [], [], []
    for (event, scope), rows in sorted(groups.items()):
        chosen, old, conflicting = _select(rows, "label")
        superseded.extend(old)
        if chosen:
            selected.append(chosen)
        if conflicting:
            conflicts.append({"event_type": event, "scope_id": scope, "claim_ids": conflicting})
    construction = [c for c in selected if c["event_type"] == "actual_construction_start"] or [
        c for c in selected if c["event_type"] == "announced_construction_start"
    ]
    energization = [
        c
        for c in selected
        if c["event_type"] in {"expected_first_energization", "phase_energization"}
    ]
    return {
        "construction_start": min(construction, key=lambda c: (c["start"], c["fact_id"]))
        if construction
        else None,
        "expected_energization": min(energization, key=lambda c: (c["start"], c["fact_id"]))
        if energization
        else None,
        "claims": claims,
        "selected_claim_ids": sorted(c["fact_id"] for c in selected),
        "superseded_claim_ids": sorted(set(superseded)),
        "conflicts": conflicts,
    }


def _priority(capacity: dict, timelines: dict, *, as_of: date) -> dict:
    selected = set(capacity["selected_claim_ids"]) | set(timelines["selected_claim_ids"])
    claims = [c for c in capacity["claims"] + timelines["claims"] if c["fact_id"] in selected]
    strengths = [min(100, _strength(c)[0] * 20 + _strength(c)[1] * 20) for c in claims]
    confidence = sum(strengths) // len(strengths) if strengths else 0
    if capacity["conflicts"] or timelines["conflicts"]:
        confidence = min(confidence, 40)
    amounts = [
        Decimal(t["value_mw"])
        for t in capacity["totals"]
        if t["value_mw"] and t["status"] == "supported"
    ]
    amount = max(amounts, default=Decimal(0))
    scale = (
        25
        if amount >= 500
        else 20
        if amount >= 100
        else 15
        if amount >= 20
        else 10
        if amount > 0
        else 0
    )
    construction = timelines["construction_start"]
    event = timelines["expected_energization"] or construction
    event_date = _date(event["start"]) if event else None
    delta = (event_date - as_of).days if event_date else None
    timing = (
        30
        if delta is not None and 0 <= delta <= 365
        else 15
        if delta is not None and -180 <= delta < 0
        else 10
        if delta is not None and 365 < delta <= 730
        else 0
    )
    dated = [_date(c["source"].get("published_at")) for c in claims]
    ages = [(as_of - d).days for d in dated if d is not None]
    freshness = 15 if ages and min(ages) <= 90 else 5 if ages and min(ages) <= 365 else 0
    phase = (
        15
        if construction and construction["event_type"] == "actual_construction_start"
        else 5
        if construction
        else 0
    )
    potential = scale + timing + freshness + phase
    components = {
        "capacity": scale,
        "timing": timing,
        "phase": phase,
        "freshness": freshness,
        "material_changes": 0,
        "geographic_fit": 0,
        "verified_contacts": 0,
    }
    return {
        "version": PRIORITY_VERSION,
        "potential": potential,
        "confidence": confidence,
        "score": potential * confidence // 100,
        "components": components,
        "limitations": [
            "Geographic fit and contact availability require separately verified account context.",
            "Facility capacity indicates project scale, not rental demand.",
        ],
    }


def _commissioning(plans: dict[str, dict[str, dict]], project_ids: set[str]) -> dict:
    from gridlens.domain.commissioning import estimate_commissioning

    by_project = [
        {"project_id": project, **estimate_commissioning(list(plans.get(project, {}).values()))}
        for project in sorted(project_ids)
    ]
    if len(by_project) == 1:
        result = by_project[0]
    else:
        result = estimate_commissioning([])
        result["projects"] = by_project
        if len(by_project) > 1:
            result["limitations"].append(
                "Project commissioning peaks are not additive without a supported shared schedule."
            )
    result["version"] = result["calculation_version"]
    return result


def resolve_customer_intelligence(projects: list[dict], *, as_of: date) -> dict:
    """Aggregate existing canonical project facts; never invent disjointness or identity.

    Caller must load the complete canonical account cohort, and validate retained
    evidence bindings before passing payloads. Distinct project IDs alone do not
    prove nonoverlapping capacity. This function does not mutate its inputs.
    """
    capacity_claims: dict[str, dict] = {}
    timeline_claims: dict[str, dict] = {}
    commissioning_plans: dict[str, dict[str, dict]] = {}
    overflow_limitations: set[str] = set()
    project_ids = {
        p["project_id"]
        for p in projects
        if isinstance(p, dict) and isinstance(p.get("project_id"), str)
    }
    for project in projects:
        if not isinstance(project, dict):
            continue
        project_id = project.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            continue
        for package in project.get("facts", []) if isinstance(project.get("facts"), list) else []:
            if (
                not isinstance(package, dict)
                or package.get("version") != FACTS_VERSION
                or package.get("project_id") != project_id
            ):
                continue
            if package.get("overflow") is True:
                overflow_limitations.add("Source coverage exceeds bounded commercial processing.")
                for limitation in package.get("limitations", []):
                    if isinstance(limitation, str):
                        overflow_limitations.add(limitation)
                continue
            inputs = package.get("commissioning_inputs", [])
            if isinstance(inputs, list):
                for block in inputs[:MAX_CLAIMS]:
                    if isinstance(block, dict) and block.get("project_id") == project_id:
                        commissioning_plans.setdefault(project_id, {})[_key(block)] = deepcopy(
                            block
                        )
            for field, destination in (
                ("capacity_claims", capacity_claims),
                ("timeline_claims", timeline_claims),
            ):
                rows = package.get(field)
                if not isinstance(rows, list):
                    continue
                for raw in rows[:MAX_CLAIMS]:
                    if (
                        not isinstance(raw, dict)
                        or raw.get("project_id") != project_id
                        or not _source_valid(raw, as_of)
                    ):
                        continue
                    if not all(
                        isinstance(raw.get(key), str) and raw[key]
                        for key in ("fact_id", "scope_id", "quote")
                    ):
                        continue
                    claim = deepcopy(raw)
                    if field == "capacity_claims":
                        amount = _decimal(claim.get("value_mw"))
                        if (
                            amount is None
                            or claim.get("basis") not in CAPACITY_BASES
                            or claim.get("capacity_type") not in CAPACITY_TYPES
                        ):
                            continue
                        if claim.get("qualifier", "exact") not in {
                            "exact",
                            "approximate",
                            "up_to",
                            "at_least",
                            "more_than",
                        }:
                            continue
                        claim["value_mw"] = _format(amount)
                        for key in ("includes_scope_ids", "disjoint_scope_ids"):
                            links = claim.get(key, [])
                            claim[key] = (
                                sorted(
                                    {
                                        link
                                        for link in links
                                        if isinstance(link, str)
                                        and link
                                        and link != claim["scope_id"]
                                    }
                                )
                                if isinstance(links, list)
                                else []
                            )
                    else:
                        if claim.get("event_type") not in EVENT_TYPES or not isinstance(
                            claim.get("label"), str
                        ):
                            continue
                        bounds = _date_bounds(claim["label"])
                        if (
                            bounds is None
                            or (claim.get("precision"), claim.get("start"), claim.get("end"))
                            != bounds
                        ):
                            continue
                        if (
                            claim.get("event_type") == "actual_construction_start"
                            and date.fromisoformat(claim["start"]) > as_of
                        ):
                            continue
                    destination[_key(claim)] = claim
    capacity = _capacity(
        sorted(capacity_claims.values(), key=lambda c: (c["basis"], c["scope_id"], c["fact_id"])),
        len(project_ids),
    )
    timelines = _timelines(
        sorted(timeline_claims.values(), key=lambda c: (c["start"], c["event_type"], c["fact_id"]))
    )
    commissioning = _commissioning(commissioning_plans, project_ids)
    if overflow_limitations:
        capacity.update(status="insufficient_data", total_mw=None)
        for total in capacity["totals"]:
            total.update(value_mw=None, status="insufficient_data", complete=False)
        capacity["selected_claim_ids"] = []
        timelines.update(construction_start=None, expected_energization=None, selected_claim_ids=[])
        commissioning = _commissioning({}, project_ids)
        commissioning["limitations"].extend(sorted(overflow_limitations))
    priority = _priority(capacity, timelines, as_of=as_of)
    if capacity["conflicts"] or timelines["conflicts"]:
        action = "Research conflicting project facts using primary sources before outreach."
    elif timelines["construction_start"] or timelines["expected_energization"]:
        action = (
            "Identify the verified electrical or commissioning lead and confirm "
            "the project test sequence and timing."
        )
    else:
        action = (
            "Research construction and energization timing, then identify a verified "
            "project decision-maker."
        )
    all_claims = capacity["claims"] + timelines["claims"]
    sources = {_key(c["source"]): c["source"] for c in all_claims}
    return {
        "version": VERSION,
        "as_of": as_of.isoformat(),
        "capacity": capacity,
        "timelines": timelines,
        "commissioning": commissioning,
        "recent_developments": [],
        "priority": priority,
        "recommended_next_action": action,
        "sources": [sources[key] for key in sorted(sources)],
        "limitations": [
            "Engineering scenarios are not verified customer demand.",
            "Only explicit supported source facts are included; missing values remain unknown.",
        ]
        + sorted(overflow_limitations),
    }
