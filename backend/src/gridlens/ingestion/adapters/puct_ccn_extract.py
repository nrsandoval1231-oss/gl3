"""Evidence-bound fields from PUCT certificate (CCN) dockets: case style and filing text.

Pure functions. A value is kept only if the same pattern, run again on its own quote, returns the
same value. Two kinds of MW are kept apart and never mixed with an ERCOT project total:

* ``customer_request_mw``  only the sentence shape "a customer ... has submitted a request for
  approximately N megawatts" (verbatim quote kept);
* ``stated_load_mw``       any other "N MW of load" statement by the applicant (documented as
  stated, not attributed to a customer).

Cost is a stated dollar figure or range; a range keeps both ends. Nothing is inferred.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from gridlens.ingestion.adapters.ercot_rpg_extract import (
    MAX_LIST,
    MAX_QUOTE,
    PROJECT_ID,
    normalise,
)

VERSION = "puct-ccn-extract-v1"

_CCN_STYLE = re.compile(r"CERTIFICATES? OF CONVENIENCE AND NECESSITY", re.I)
_LINE_OR_SUB = re.compile(r"TRANSMISSION LINES?|SUBSTATION", re.I)
_KV_STYLE = re.compile(r"\b(\d{2,3})\s?-?\s?KV\b", re.I)
_COUNTY_WORD = r"[A-Z][A-Z.'-]*(?: [A-Z][A-Z.'-]*){0,2}"
_STYLE_COUNTIES = re.compile(
    rf"\bIN ({_COUNTY_WORD}(?:(?:, AND | AND |, ){_COUNTY_WORD})*) COUNT(?:Y|IES)\b"
)
_STYLE_NEW_SUB = re.compile(
    r"\b(?:NEW|PROPOSED) ([A-Z][A-Z0-9.'-]*(?: [A-Z][A-Z0-9.'-]*){0,3}) SUBSTATION\b"
)

_KV_TEXT = re.compile(r"\b(\d{2,3})[\s-]*(?:kV|kilovolt)\b", re.I)
_COST = re.compile(
    r"\bestimated cost\b[^$]{0,120}?\$\s?(?P<a>\d[\d,]*(?:\.\d+)?)\s*(?P<ua>million|billion)?"
    r"(?:\s*(?:to|-|–|and)\s*\$\s?(?P<b>\d[\d,]*(?:\.\d+)?)\s*(?P<ub>million|billion)?)?",
    re.I,
)
_REQUEST = re.compile(
    r"\b(?:customer|developer|entity|facility|company)\b[^.]{0,80}?"
    r"(?:submitted a request|has requested|requested|request)\s+(?:for|of)\s+"
    r"(?:approximately|about)?\s*(?P<n>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<u>megawatts?|MW|gigawatts?|GW)\b",
    re.I,
)
_STATED_LOAD = re.compile(
    r"\b(?P<n>\d[\d,]*(?:\.\d+)?)\s*(?P<u>MW|megawatts?)\s+of\s+(?:new\s+|additional\s+)?load\b",
    re.I,
)
_TEXT_SUB = re.compile(
    r"\b(?:new|proposed|future) substation \((?:the )?(?P<n>[A-Z][\w.'-]*(?: [A-Z][\w.'-]*){0,3})"
    r" Substation\)|\b(?:new|proposed|future) (?P<m>[A-Z][\w.'-]*(?: [A-Z][\w.'-]*){0,3})"
    r" [Ss]ubstation\b"
)

_STOP = frozenset({"New", "Existing", "The", "This", "Proposed", "Project", "Applicant"})


def _titlecase(name: str) -> str:
    return " ".join(w.capitalize() for w in name.split())


def style_is_relevant(description: str) -> bool:
    return bool(_CCN_STYLE.search(description) and _LINE_OR_SUB.search(description))


def case_style_fields(description: str) -> dict[str, Any]:
    """County, voltage and any named new substation, all quoted from the case style itself."""
    text = normalise(description)
    fields: dict[str, Any] = {}
    counties: list[dict[str, Any]] = []
    found = _STYLE_COUNTIES.findall(text)
    if found:
        for name in re.split(r", AND | AND |, ", found[-1]):
            value = _titlecase(name.strip())
            if value and value.split()[0] not in _STOP and len(counties) < MAX_LIST:
                counties.append(
                    {
                        "value": value,
                        "basis": "documented",
                        "page": None,
                        "quote": text[:MAX_QUOTE],
                        "location": "PUCT docket case style",
                    }
                )
    fields["counties"] = counties
    volts: list[dict[str, Any]] = []
    for kv in dict.fromkeys(_KV_STYLE.findall(text)):
        volts.append(
            {
                "value": int(kv),
                "unit": "kV",
                "basis": "documented",
                "page": None,
                "quote": text[:MAX_QUOTE],
                "location": "PUCT docket case style",
            }
        )
    fields["voltage_kv"] = volts[:MAX_LIST]
    subs = [
        {
            "value": _titlecase(m),
            "basis": "documented",
            "page": None,
            "quote": text[:MAX_QUOTE],
            "location": "PUCT docket case style",
        }
        for m in dict.fromkeys(_STYLE_NEW_SUB.findall(text))
    ]
    fields["substations"] = subs[:MAX_LIST]
    return fields


def _context(norm: str, start: int, end: int) -> str:
    lo = max(0, start - 100)
    hi = min(len(norm), end + 100)
    while lo > 0 and norm[lo - 1] != " ":
        lo -= 1
    while hi < len(norm) and norm[hi] != " ":
        hi += 1
    quote = norm[lo:hi].strip()
    return quote if len(quote) <= MAX_QUOTE else norm[max(0, start - 20) : end + 20][:MAX_QUOTE]


def _mw(number: str, unit: str) -> tuple[int, str] | None:
    try:
        value = Decimal(number.replace(",", ""))
    except InvalidOperation:
        return None
    if unit.lower().startswith("g"):
        return int(value * 1000), "calculated"
    return int(value), "documented"


def _money(a: str, ua: str | None, b: str | None, ub: str | None) -> dict[str, Any] | None:
    scale = {"million": Decimal(10**6), "billion": Decimal(10**9)}
    try:
        unit_a = (ua or ub or "").lower()
        low = Decimal(a.replace(",", "")) * scale.get(unit_a, Decimal(1))
        high = (
            Decimal(b.replace(",", "")) * scale.get((ub or ua or "").lower(), Decimal(1))
            if b
            else None
        )
    except InvalidOperation:
        return None
    return {
        "low_usd": int(low),
        "high_usd": int(high) if high is not None else int(low),
        "range": high is not None,
        "basis": "calculated" if (ua or ub) else "documented",
    }


def _verified(
    fields: dict[str, Any], key: str, evidence: dict[str, Any], *, multi: bool = False
) -> None:
    if multi:
        target = fields.setdefault(key, [])
        if len(target) < MAX_LIST and all(e["value"] != evidence["value"] for e in target):
            target.append(evidence)
    elif key not in fields:
        fields[key] = evidence


def text_fields(pages: list[str]) -> dict[str, Any]:
    """Voltage, cost, customer request, stated load, new substations and RPG IDs from page text."""
    fields: dict[str, Any] = {}
    for number, raw in enumerate(pages, start=1):
        norm = normalise(raw)
        for found in _KV_TEXT.finditer(norm):
            quote = _context(norm, found.start(), found.end())
            again = _KV_TEXT.search(quote)
            if again and again[1] == found[1] and quote in norm:
                _verified(
                    fields,
                    "voltage_kv",
                    {
                        "value": int(found[1]),
                        "unit": "kV",
                        "basis": "documented",
                        "page": number,
                        "quote": quote,
                    },
                    multi=True,
                )
        cost = _COST.search(norm)
        if cost and "cost" not in fields:
            quote = _context(norm, cost.start(), cost.end())
            again = _COST.search(quote)
            money = _money(cost["a"], cost["ua"], cost["b"], cost["ub"])
            if again and money and quote in norm:
                redo = _money(again["a"], again["ua"], again["b"], again["ub"])
                if redo == money:
                    fields["cost"] = {**money, "value": money["low_usd"], "unit": "USD",
                                      "page": number, "quote": quote}
        request = _REQUEST.search(norm)
        if request and "customer_request_mw" not in fields:
            quote = _context(norm, request.start(), request.end())
            again = _REQUEST.search(quote)
            converted = _mw(request["n"], request["u"])
            if again and converted and quote in norm and _mw(again["n"], again["u"]) == converted:
                fields["customer_request_mw"] = {
                    "value": converted[0],
                    "unit": "MW",
                    "basis": converted[1],
                    "page": number,
                    "quote": quote,
                }
        for found in _STATED_LOAD.finditer(norm):
            quote = _context(norm, found.start(), found.end())
            again = _STATED_LOAD.search(quote)
            converted = _mw(found["n"], found["u"])
            if again and converted and quote in norm and _mw(again["n"], again["u"]) == converted:
                _verified(
                    fields,
                    "stated_load_mw",
                    {
                        "value": converted[0],
                        "unit": "MW",
                        "basis": converted[1],
                        "page": number,
                        "quote": quote,
                    },
                    multi=True,
                )
        for found in _TEXT_SUB.finditer(norm):
            name = (found["n"] or found["m"] or "").strip()
            if not name or name.split()[0] in _STOP:
                continue
            quote = _context(norm, found.start(), found.end())
            if quote in norm and name in quote:
                _verified(
                    fields,
                    "substations",
                    {"value": name, "basis": "documented", "page": number, "quote": quote},
                    multi=True,
                )
        for project_id in dict.fromkeys(PROJECT_ID.findall(norm)):
            at = norm.find(project_id)
            quote = _context(norm, at, at + len(project_id))
            _verified(
                fields,
                "rpg_ids",
                {"value": project_id, "basis": "documented", "page": number, "quote": quote},
                multi=True,
            )
    return fields


def merge_fields(*parts: dict[str, Any]) -> dict[str, Any]:
    """Union list fields (deduplicated by value) and keep the first scalar; unknown otherwise."""
    merged: dict[str, Any] = {}
    for part in parts:
        for key, value in part.items():
            if isinstance(value, list):
                target = merged.setdefault(key, [])
                for evidence in value:
                    if len(target) < MAX_LIST and all(
                        str(e["value"]).casefold() != str(evidence["value"]).casefold()
                        for e in target
                    ):
                        target.append(evidence)
            else:
                current = merged.get(key)
                if current is None or current.get("basis") == "unknown":
                    merged[key] = value
    for key in ("cost", "customer_request_mw"):
        merged.setdefault(key, {"value": None, "basis": "unknown", "reason": "not_stated"})
    for key in ("counties", "voltage_kv", "substations", "stated_load_mw", "rpg_ids"):
        merged.setdefault(key, [])
    return merged


def summary_lines(control: str, fields: dict[str, Any]) -> list[str]:
    def many(name: str) -> str:
        items = fields.get(name) or []
        return ", ".join(str(e["value"]) for e in items) if items else "unknown"

    def one(name: str, fmt: str) -> str:
        entry = fields.get(name) or {}
        if entry.get("basis") == "unknown" or entry.get("value") is None:
            return "unknown"
        return fmt.format(**entry)

    cost = fields.get("cost") or {}
    if cost.get("basis") == "unknown" or "low_usd" not in cost:
        cost_text = "unknown"
    elif cost.get("range"):
        cost_text = f"USD {cost['low_usd']} to {cost['high_usd']} ({cost['basis']})"
    else:
        cost_text = f"USD {cost['low_usd']} ({cost['basis']})"
    return [
        f"PUCT docket {control} fields: counties {many('counties')}; voltage kV {many('voltage_kv')};"
        f" cost {cost_text}",
        f"Customer-requested load: {one('customer_request_mw', '{value} MW ({basis})')};"
        f" other stated load: {many('stated_load_mw')} MW",
        f"Named new substations: {many('substations')}; RPG IDs cited: {many('rpg_ids')}",
    ]


def count_fields(fields: dict[str, Any]) -> int:
    total = 0
    for value in fields.values():
        if isinstance(value, list):
            total += 1 if value else 0
        elif value.get("basis") != "unknown":
            total += 1
    return total
