"""Evidence-bound fields from PUCT certificate (CCN) dockets: case style and filing text.

Pure functions. A value is kept only if the same pattern, run again on its own quote, returns the
same value. Every value carries its basis, page, verbatim quote and where it came from: a value
read from a filing PDF is stamped with that PDF's role, item, SHA-256 and URL; a value read from
the case style has no document hash (``document_sha256`` is None) and carries the docket record's
own ``record_source_hash`` and the filings URL instead. Two kinds of MW are kept apart and never
mixed with an ERCOT project total:

* ``customer_request_mw``  only the sentence shape "a customer ... has submitted a request for
  approximately N megawatts" (verbatim quote kept); wording about generation, solar, wind,
  storage, injection or interconnection is rejected, and two different requests make the value
  unknown (both quotes kept);
* ``stated_load_mw``       any other "N MW of load" statement by the applicant (documented as
  stated, not attributed to a customer, and never the same span as a customer request).

Cost is a stated dollar figure or range; units M, B, K, million, billion and thousand are read, an
unreadable unit or a range with low above high is unknown, and nothing is truncated. Nothing is
inferred.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from gridlens.ingestion.adapters.ercot_rpg_extract import (
    MAX_LIST,
    MAX_QUOTE,
    PROJECT_ID,
    _exact,
    normalise,
)

VERSION = "puct-ccn-extract-v2"
MIN_PLAUSIBLE_USD = 1000

_CCN_STYLE = re.compile(r"CERTIFICATES? OF CONVENIENCE AND NECESSITY", re.I)
_LINE_OR_SUB = re.compile(r"TRANSMISSION LINES?|SUBSTATION", re.I)
_KV_STYLE = re.compile(r"\b(\d{2,3}(?:/\d{2,3})?)\s?-?\s?KV\b", re.I)
_COUNTY_WORD = r"[A-Z][A-Z.'-]*(?: [A-Z][A-Z.'-]*){0,2}"
_STYLE_COUNTIES = re.compile(
    rf"\bIN ({_COUNTY_WORD}(?:(?:, AND | AND |, ){_COUNTY_WORD})*) COUNT(?:Y|IES)\b"
)
_STYLE_NEW_SUB = re.compile(
    r"\b(?:NEW|PROPOSED) ([A-Z][A-Z0-9.'-]*(?: [A-Z][A-Z0-9.'-]*){0,3}?)"
    r"(?: \d{2,3}(?:/\d{2,3})?-?\s?KV)? SUBSTATION\b"
)

# Only the project's own line: "a new double circuit 138 kilovolt", "operated at 138-kV". A kV
# merely mentioned (an existing line, a rule threshold) is not the project voltage.
_KV_TEXT = re.compile(
    r"(?:\b(?:new|proposed)\s+(?:(?:double|single)[- ]circuit\s+)?|\boperated at\s+)"
    r"(\d{2,3}(?:/\d{2,3})?)[\s-]*(?:kV|kilovolt)\b",
    re.I,
)
_AMOUNT = (
    r"\$\s?(?P<{a}>\d[\d,]*(?:\.\d+)?)\s?"
    r"(?P<{u}>million|billion|thousand|(?-i:[MBK]))?(?![A-Za-z])"
)
_COST = re.compile(
    r"\bestimated cost\b[^$]{0,120}?"
    + _AMOUNT.format(a="a", u="ua")
    + r"(?:\s*(?:to|-|–)\s*(?:a\s+high\s+of\s+)?"
    + _AMOUNT.format(a="b", u="ub")
    + r")?",
    re.I,
)
_SCALE = {
    "million": Decimal(10**6),
    "m": Decimal(10**6),
    "billion": Decimal(10**9),
    "b": Decimal(10**9),
    "thousand": Decimal(10**3),
    "k": Decimal(10**3),
}
_REQUEST = re.compile(
    r"\bcustomer\b[^.]{0,80}?\b(?:submitted a request|has requested|have requested)\b\s+"
    r"(?:(?:for|of)\s+)?(?:approximately\s+|about\s+)?(?P<n>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<u>megawatts?|MW|gigawatts?|GW)\b",
    re.I,
)
_NOT_A_LOAD_REQUEST = re.compile(
    r"generat|solar|\bwind\b|storage|battery|injection|interconnect", re.I
)
_STATED_LOAD = re.compile(
    r"\b(?P<n>\d[\d,]*(?:\.\d+)?)\s*(?P<u>MW|megawatts?)\s+of\s+(?:new\s+|additional\s+)?load\b",
    re.I,
)
_TEXT_SUB = re.compile(
    r"\b(?:new|proposed|future) substation \((?:the )?(?P<n>[A-Z][\w.'-]*(?: [A-Z][\w.'-]*){0,3})"
    r" Substation\)"
    r"|\b(?:new|proposed|future) (?P<m>[A-Z][\w.'-]*(?: [A-Z][\w.'-]*){0,3}?)"
    r"(?: \d{2,3}(?:/\d{2,3})?-?\s?kV)? [Ss]ubstation\b"
)
# A substation counts only in a sentence that describes the project itself.
_PROJECT_SENTENCE = re.compile(
    r"\b(?:proposed project|this application|the applicant|applicant's|the project|"
    r"consists of|will begin|will be constructed)\b",
    re.I,
)
# A cited RPG project ID counts only in a sentence that says it is this project's own review.
_ID_OWN = re.compile(r"\b(?:this project|the proposed project|rpg review|rpg project)\b", re.I)
_ID_OTHER = re.compile(
    r"\b(?:unlike|supersed|replac|other than|instead of|previous|prior|different|another)", re.I
)

_STOP = frozenset({"New", "Existing", "The", "This", "Proposed", "Project", "Applicant"})


def _titlecase(name: str) -> str:
    return " ".join(w.capitalize() for w in name.split())


def style_is_relevant(description: str) -> bool:
    return bool(_CCN_STYLE.search(description) and _LINE_OR_SUB.search(description))


def case_style_fields(
    description: str, record_source_hash: str | None = None, url: str | None = None
) -> dict[str, Any]:
    """County, voltage and any named new substation, all quoted from the case style itself.

    These values have no filing document: ``document_sha256`` is None and the docket record's own
    hash and the filings URL identify where they came from.
    """
    text = normalise(description)
    base = {
        "basis": "documented",
        "page": None,
        "quote": text[:MAX_QUOTE],
        "location": "PUCT docket case style",
        "document_sha256": None,
        "record_source_hash": record_source_hash,
        "url": url,
    }
    fields: dict[str, Any] = {}
    counties: list[dict[str, Any]] = []
    found = _STYLE_COUNTIES.findall(text)
    if found:
        for name in re.split(r", AND | AND |, ", found[-1]):
            value = _titlecase(name.strip())
            if value and value.split()[0] not in _STOP and len(counties) < MAX_LIST:
                counties.append({"value": value, **base})
    fields["counties"] = counties
    volts: list[dict[str, Any]] = []
    seen_kv: list[int] = []
    for group in _KV_STYLE.findall(text):
        for part in group.split("/"):
            if int(part) not in seen_kv:
                seen_kv.append(int(part))
                volts.append({"value": int(part), "unit": "kV", **base})
    fields["voltage_kv"] = volts[:MAX_LIST]
    fields["substations"] = [
        {"value": _titlecase(m), **base} for m in dict.fromkeys(_STYLE_NEW_SUB.findall(text))
    ][:MAX_LIST]
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


def _sentence(norm: str, start: int, end: int) -> str:
    """The sentence around a match, cut at a period followed by a space."""
    lo = norm.rfind(". ", 0, start)
    hi = norm.find(". ", end)
    return norm[(lo + 2 if lo >= 0 else 0) : (hi if hi >= 0 else len(norm))]


def _mw(number: str, unit: str) -> tuple[int | str, str] | None:
    try:
        value = Decimal(number.replace(",", ""))
    except InvalidOperation:
        return None
    if unit.lower().startswith("g"):
        return _exact(value * 1000), "calculated"
    return _exact(value), "documented"


def _money(a: str, ua: str | None, b: str | None, ub: str | None) -> dict[str, Any] | None:
    """A stated figure or range in dollars, exact; None when unreadable or implausible."""
    try:
        unit_a = (ua or ub or "").lower()
        low = Decimal(a.replace(",", "")) * _SCALE.get(unit_a, Decimal(1))
        high = (
            Decimal(b.replace(",", "")) * _SCALE.get((ub or ua or "").lower(), Decimal(1))
            if b
            else None
        )
    except InvalidOperation:
        return None
    top = high if high is not None else low
    if low < MIN_PLAUSIBLE_USD or top < low:
        return None
    return {
        "low_usd": _exact(low),
        "high_usd": _exact(top),
        "range": high is not None,
        "basis": "calculated" if (ua or ub) else "documented",
    }


def _again(pattern: re.Pattern[str], quote: str, found: re.Match[str]) -> re.Match[str] | None:
    """The same match, found again inside the quote (not merely some other match in it)."""
    for candidate in pattern.finditer(quote):
        if candidate.group(0) == found.group(0):
            return candidate
    return None


def _verified(
    fields: dict[str, Any], key: str, evidence: dict[str, Any], *, multi: bool = False
) -> None:
    if multi:
        target = fields.setdefault(key, [])
        if len(target) < MAX_LIST and all(e["value"] != evidence["value"] for e in target):
            target.append(evidence)
    elif key not in fields:
        fields[key] = evidence


def text_fields(pages: list[str], origin: dict[str, Any] | None = None) -> dict[str, Any]:
    """Voltage, cost, customer request, stated load, new substations and RPG IDs from page text.

    ``origin`` (role, item, document_sha256, url of the PDF) is stamped on every value.
    """
    stamp = dict(origin or {})
    fields: dict[str, Any] = {}
    requests: list[dict[str, Any]] = []
    for number, raw in enumerate(pages, start=1):
        norm = normalise(raw)

        def evidence(
            value: Any, basis: str, quote: str, number: int = number, **extra: Any
        ) -> dict[str, Any]:
            return {
                "value": value,
                "basis": basis,
                "page": number,
                "quote": quote,
                **extra,
                **stamp,
            }

        for found in _KV_TEXT.finditer(norm):
            quote = _context(norm, found.start(), found.end())
            if quote in norm and _again(_KV_TEXT, quote, found):
                for part in found[1].split("/"):
                    _verified(
                        fields,
                        "voltage_kv",
                        evidence(int(part), "documented", quote, unit="kV"),
                        multi=True,
                    )
        cost = _COST.search(norm)
        if cost and "cost" not in fields:
            quote = _context(norm, cost.start(), cost.end())
            again = _again(_COST, quote, cost)
            money = _money(cost["a"], cost["ua"], cost["b"], cost["ub"])
            if again and money and quote in norm:
                redo = _money(again["a"], again["ua"], again["b"], again["ub"])
                if redo == money:
                    fields["cost"] = {
                        **money,
                        "value": money["low_usd"],
                        "unit": "USD",
                        "page": number,
                        "quote": quote,
                        **stamp,
                    }
        request_spans: list[tuple[int, int]] = []
        for request in _REQUEST.finditer(norm):
            request_spans.append((request.start(), request.end()))
            sentence = _sentence(norm, request.start(), request.end())
            if _NOT_A_LOAD_REQUEST.search(sentence):
                continue
            quote = _context(norm, request.start(), request.end())
            again = _again(_REQUEST, quote, request)
            converted = _mw(request["n"], request["u"])
            if (
                again
                and converted
                and quote in norm
                and _mw(again["n"], again["u"]) == converted
                and not _NOT_A_LOAD_REQUEST.search(_sentence(quote, again.start(), again.end()))
            ):
                requests.append(evidence(converted[0], converted[1], quote, unit="MW"))
        for found in _STATED_LOAD.finditer(norm):
            if any(found.start() < end and found.end() > start for start, end in request_spans):
                continue  # the same words as a customer request: kept there, not twice
            quote = _context(norm, found.start(), found.end())
            again = _again(_STATED_LOAD, quote, found)
            converted = _mw(found["n"], found["u"])
            if again and converted and quote in norm and _mw(again["n"], again["u"]) == converted:
                _verified(
                    fields,
                    "stated_load_mw",
                    evidence(converted[0], converted[1], quote, unit="MW"),
                    multi=True,
                )
        for found in _TEXT_SUB.finditer(norm):
            name = (found["n"] or found["m"] or "").strip()
            if not name or name.split()[0] in _STOP:
                continue
            if not _PROJECT_SENTENCE.search(_sentence(norm, found.start(), found.end())):
                continue
            quote = _context(norm, found.start(), found.end())
            again = _again(_TEXT_SUB, quote, found)
            if quote in norm and again and (again["n"] or again["m"] or "").strip() == name:
                _verified(fields, "substations", evidence(name, "documented", quote), multi=True)
        for project_id in dict.fromkeys(PROJECT_ID.findall(norm)):
            at = norm.find(project_id)
            sentence = _sentence(norm, at, at + len(project_id))
            if not _ID_OWN.search(sentence) or _ID_OTHER.search(sentence):
                continue
            quote = _context(norm, at, at + len(project_id))
            _verified(fields, "rpg_ids", evidence(project_id, "documented", quote), multi=True)
    if requests:
        distinct = {str(e["value"]) for e in requests}
        if len(distinct) > 1:
            fields["customer_request_mw"] = {
                "value": None,
                "basis": "unknown",
                "reason": "conflicting_statements",
                "candidates": requests[:4],
            }
        else:
            fields["customer_request_mw"] = requests[0]
    return fields


def merge_fields(*parts: dict[str, Any]) -> dict[str, Any]:
    """Union list fields (deduplicated by value) and keep the first scalar; unknown otherwise.

    Two documents that state different customer requests make the value unknown.
    """
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
                continue
            current = merged.get(key)
            if current is None or (
                current.get("basis") == "unknown"
                and current.get("reason") != "conflicting_statements"
            ):
                merged[key] = value
            elif (
                key == "customer_request_mw"
                and current.get("basis") != "unknown"
                and value.get("basis") != "unknown"
                and str(value.get("value")) != str(current.get("value"))
            ):
                merged[key] = {
                    "value": None,
                    "basis": "unknown",
                    "reason": "conflicting_statements",
                    "candidates": [current, value],
                }
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
        f"PUCT docket {control} fields: counties {many('counties')};"
        f" voltage kV {many('voltage_kv')};"
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
