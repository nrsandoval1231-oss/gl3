"""Classify air-permit power role from permitted operating hours.

The thresholds live in config/sources/air-permit-hours.v1.json. A record keeps
the matched evidence and the rule id. Conflicting clauses stay unclassified.

A single annual figure is backup at 500 hours per year or less, bridge/temporary
from 2,000 through 6,000, and behind-the-meter only at exactly 8,760 when the
same clause says "onsite use only". The clause is the sentence. A semicolon does
not end it, and neither does an abbreviation period such as "U.S."

A hyphen, en dash, em dash, or the word "to" between two of those figures is one
range. Both endpoints are kept, in the order written, and a decimal stays on the
endpoint it follows, so "1.5-2.5 hours per year" is 1.5 and 2.5 rather than 5 or
2.5 alone. The range is not replaced by its right-hand number. It takes a class
only when both endpoints fall in the same band, using the same onsite test. A
range that crosses bands, or that has an endpoint in no band, stays unclassified.
"12-500 hours per year" is backup because both ends are at or under 500.
"12-2,000 hours per year" crosses bands and stays unclassified. "2,000-6,000
hours per year" is bridge/temporary. "up to 500 hours per year" is a single cap
of 500, not a range.

Portable or trailer-mounted wording, and an expiring or temporary permit, are
bridge/temporary only when that same clause names power generation. A generator,
genset, gen-set, generator set, turbine, or the phrase electric generation or
power generation is that context. The bare word generator counts, so a portable
generator, portable generator engines, temporary generators, a propane
generator, and a gas-fired generator all count. The word engine by itself,
including an engine-driven crusher or pump, does not.

The exclusion list is the filter for reviewed non-electric compounds: hazardous
waste generator, steam generator, waste generator, small quantity generator,
gas generator, and the ozone, nitrogen, oxygen, hydrogen, vapor, signal, smoke,
and aerosol forms. Those phrases do not count even when a fuel or duty word is
stacked in front of them. Process-gas "gas generator" is on that list. A
gas-fired generator is not, and neither is a natural gas generator.

A negation governs only the noun phrase it attaches to. The cue (no, not,
without, never) has to sit before that phrase, after the last comma, semicolon,
or and/or/but before the phrase, and no more than six words away. "No."
followed by a number is a label, not a negation. A comma or semicolon ends the
cue's reach. It does not end the sentence used for hours and "onsite use only".
A negated phrase does not suppress a different affirmative generator, so
"no turbines; portable diesel generators" and "portable diesel generators, not
turbines" still tag. The next sentence is a new clause and can still tag.

Negation does not change an hours band. Backup, bridge, and behind-the-meter
still come from the hours figure. "8,760 hours per year for onsite use only"
stays behind-the-meter when the same sentence says the units do not generate
electricity for the grid, or that no power generation is exported. "Does not
generate electricity" negates that phrase for a portable or temporary tag.
Affirmative "generate electricity", without a generator or the other power
words above, is not power context.

Only a TCEQ New Source Review plain-language summary carries summary text into
this rule. Construction NOI and electric-generating-unit rows classify the
fields on the row itself and do not fetch a summary.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

_CONFIG_PATH = (
    Path(__file__).resolve().parents[4] / "config" / "sources" / "air-permit-hours.v1.json"
)
# Number, optional decimal, optional range, then the unit and the year.
# The left guard stops "1.5 hours" from being read as 5. A range consumes both
# endpoints so the right-hand number is not classified by itself. "of operation"
# may sit between the unit and the year.
_NUMBER = r"(?:\d{1,3}(?:,\d{3})*|\d+)"
_HOURS = re.compile(
    r"(?<![\d.,])"
    rf"(?P<hours>{_NUMBER})"
    r"(?P<fraction>\.\d+)?"
    r"(?:"
    r"(?P<range_sep>\s*(?:-|\u2010|\u2011|\u2013|\u2014|\u2212)\s*|\s+to\s+)"
    rf"(?P<high>{_NUMBER})"
    r"(?P<high_fraction>\.\d+)?"
    r")?"
    r"\s*(?:hours?|hrs?|h)(?:\s+of\s+operation)?"
    r"\s*(?:(?:/|per)\s*(?:year|yr)|annually)\b",
    re.IGNORECASE,
)
_ONSITE = re.compile(r"on-?site use only", re.IGNORECASE)
_BLANK_LINE = re.compile(r"\n\s*\n")
# A period after one of these words is an abbreviation, not a sentence end.
_ABBREVIATIONS = frozenset(
    {"approx", "co", "corp", "dr", "etc", "fig", "inc", "ltd", "mr", "mrs", "ms", "no", "st", "vs"}
)
_TOKEN = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
_CUE = frozenset({"no", "not", "without", "never"})
_BREAK = frozenset({"but", "however", "except", "although", "and", "or"})
_DO = frozenset({"do", "does", "did"})
# The cue may sit up to this many words before the power phrase.
_CUE_DISTANCE = 6
_POWER_SAMPLES = (
    "generator",
    "generators",
    "portable generator",
    "portable generator engines",
    "engine-driven generator",
    "gas-fired generator",
    "propane generator",
    "diesel generator",
    "emergency generator",
    "standby generator",
    "electric generator",
    "power generator",
    "natural gas generator",
    "natural-gas generator",
    "natural gas-fired generator",
    "natural-gas-fired generator",
    "diesel engine generator",
    "diesel engine-driven generator",
    "emergency diesel generator",
    "standby natural gas generator",
    "genset",
    "gen-set",
    "generator set",
    "turbine",
    "electric generation",
    "power generation",
)
_NOT_POWER = (
    "engine",
    "engines",
    "engine-driven crusher",
    "engine-driven pump",
)
_STILL_AFFIRMATIVE = (
    "no backup boilers; 2 portable diesel generators",
    "no turbines; portable diesel generators",
    "portable diesel generators, not turbines",
    "portable emergency generator but no power generation",
)
_EXCLUDED_SAMPLES = (
    "hazardous waste generator",
    "steam generator",
    "waste generator",
    "small quantity generator",
    "gas generator",
    "process gas generator",
    "ozone generator",
    "nitrogen generator",
    "oxygen generator",
    "hydrogen generator",
)
_NEGATED_CLAUSES = (
    "no power generation",
    "not used for power generation",
    "does not generate electricity",
    "without generators",
    "without a diesel generator",
    "portable unit; no generators",
    "temporary permit; no power generation equipment",
)
_OPEN_CLAUSES = (
    "diesel generator",
    "temporary permit for the emergency generator",
    "limited to 500 hours per year",
    "will generate electricity at the site",
    "no backup boilers; 2 portable diesel generators",
)


@lru_cache(maxsize=1)
def load_hours_rule() -> dict[str, Any]:
    rule = json.loads(_CONFIG_PATH.read_text())
    required = {
        "rule_id",
        "backup_max_hours_per_year",
        "bridge_min_hours_per_year",
        "bridge_max_hours_per_year",
        "btm_hours_per_year",
        "btm_phrase",
        "bridge_unit_pattern",
        "bridge_permit_pattern",
        "power_generation_pattern",
        "power_generation_exclusion_pattern",
        "power_negation_target_pattern",
    }
    if set(rule) != required or rule["btm_phrase"].casefold() != "onsite use only":
        raise ValueError("Air-permit hours rule config is not the reviewed rule")
    if not (
        0
        <= rule["backup_max_hours_per_year"]
        < rule["bridge_min_hours_per_year"]
        <= rule["bridge_max_hours_per_year"]
        < rule["btm_hours_per_year"]
    ):
        raise ValueError("Air-permit hours thresholds are out of order")
    re.compile(rule["bridge_unit_pattern"])
    re.compile(rule["bridge_permit_pattern"])
    power = _compiled(rule["power_generation_pattern"])
    excluded = _compiled(rule["power_generation_exclusion_pattern"])
    if any(power.search(sample) is None for sample in _POWER_SAMPLES) or any(
        power.search(sample) for sample in _NOT_POWER
    ):
        raise ValueError("Air-permit power-generation pattern does not match the reviewed context")
    if any(excluded.search(sample) is None for sample in _EXCLUDED_SAMPLES) or any(
        excluded.search(sample) for sample in _POWER_SAMPLES
    ):
        raise ValueError("Air-permit power exclusion does not match the reviewed phrases")
    if any(not _clause_negates_power(rule, sample) for sample in _NEGATED_CLAUSES) or any(
        _clause_negates_power(rule, sample) for sample in _OPEN_CLAUSES
    ):
        raise ValueError("Air-permit power negation does not match the reviewed clauses")
    if any(not _affirmative_power(rule, sample) for sample in _POWER_SAMPLES):
        raise ValueError("Air-permit power-generation pattern does not match the reviewed context")
    if any(not _affirmative_power(rule, sample) for sample in _STILL_AFFIRMATIVE):
        raise ValueError("Air-permit negation reached past the noun phrase it governs")
    if any(_affirmative_power(rule, sample) for sample in _EXCLUDED_SAMPLES):
        raise ValueError("Air-permit power exclusion does not match the reviewed phrases")
    return rule


@lru_cache(maxsize=8)
def _compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


def _tokens(text: str) -> list[tuple[str, int, int]]:
    return [(match.group(0), match.start(), match.end()) for match in _TOKEN.finditer(text)]


def _cue_word(clause: str, word: str, end: int) -> bool:
    if word.casefold() not in _CUE:
        return False
    # "No. 5" is a label. It does not negate the words that follow.
    return not (word.casefold() == "no" and end < len(clause) and clause[end] == ".")


def _list_boundary(clause: str, index: int) -> bool:
    """Comma and semicolon bound a negation. A thousands separator does not."""
    char = clause[index]
    if char == ";":
        return True
    if char != ",":
        return False
    previous = clause[index - 1] if index else ""
    following = clause[index + 1] if index + 1 < len(clause) else ""
    return not (previous.isdigit() and following.isdigit())


def _negated_span(clause: str, match_start: int, match_end: int) -> tuple[int, int] | None:
    """Cue-to-phrase span when a negation governs this match. None otherwise.

    The cue has to sit before this noun phrase. A comma, semicolon, or
    coordinating word ends the cue's reach, so it does not cross into another
    phrase in the same sentence.
    """
    region = 0
    for index in range(match_start):
        if _list_boundary(clause, index):
            region = index + 1
    before = [token for token in _tokens(clause) if region <= token[1] and token[2] <= match_start]
    cut = 0
    for index, (word, _start, _end) in enumerate(before):
        if word.casefold() in _BREAK:
            cut = index + 1
    window = before[cut:]
    for offset, (word, start, end) in enumerate(reversed(window)):
        if offset > _CUE_DISTANCE:
            break
        if not _cue_word(clause, word, end):
            continue
        index = len(window) - 1 - offset
        if word.casefold() == "not" and index > 0 and window[index - 1][0].casefold() in _DO:
            start = window[index - 1][1]
        return start, match_end
    return None


def _overlaps(left: re.Match[str], right: re.Match[str]) -> bool:
    return left.start() < right.end() and right.start() < left.end()


def _excluded(rule: dict[str, Any], clause: str, match: re.Match[str]) -> bool:
    exclusion = _compiled(rule["power_generation_exclusion_pattern"])
    return any(_overlaps(match, other) for other in exclusion.finditer(clause))


def _affirmative_power(rule: dict[str, Any], clause: str) -> bool:
    """True when the clause has a power phrase that is not excluded or negated."""
    for match in _compiled(rule["power_generation_pattern"]).finditer(clause):
        if _excluded(rule, clause, match):
            continue
        if _negated_span(clause, match.start(), match.end()):
            continue
        return True
    return False


def _negated_power_quote(rule: dict[str, Any], clause: str) -> str:
    target = _compiled(rule["power_negation_target_pattern"])
    for match in target.finditer(clause):
        span = _negated_span(clause, match.start(), match.end())
        if span:
            return " ".join(clause[span[0] : span[1]].split())
    return ""


def _clause_negates_power(rule: dict[str, Any], clause: str) -> bool:
    """True when this sentence denies power generation. Other sentences are separate."""
    return _negated_power_quote(rule, clause) != ""


def _sentence_period(text: str, index: int) -> bool:
    """True when the period at index ends a sentence."""
    previous = text[index - 1] if index else ""
    following = text[index + 1] if index + 1 < len(text) else ""
    if previous.isdigit() and following.isdigit():
        return False
    # "U.S." and "e.g." are single-letter abbreviations.
    if previous.isalpha() and (index < 2 or not text[index - 2].isalpha()):
        return False
    letters: list[str] = []
    cursor = index - 1
    while cursor >= 0 and text[cursor].isalpha():
        letters.append(text[cursor])
        cursor -= 1
    return "".join(reversed(letters)).casefold() not in _ABBREVIATIONS


def _boundaries(text: str):
    """Sentence ends and blank lines. A semicolon or a line wrap is not an end."""
    index = 0
    while index < len(text):
        if text[index] in "!?" or (text[index] == "." and _sentence_period(text, index)):
            yield index, index + 1
            index += 1
            continue
        blank = _BLANK_LINE.match(text, index)
        if blank:
            yield blank.start(), blank.end()
            index = blank.end()
            continue
        index += 1


def _clause(text: str, start: int, end: int) -> str:
    """Return the sentence that contains the match. A semicolon stays inside it."""
    previous = 0
    stop = len(text)
    for begin, finish in _boundaries(text):
        if finish <= start:
            previous = finish
        elif begin >= end:
            stop = begin
            break
    return text[previous:stop]


def _decimal(whole: str, fraction: str | None) -> Decimal:
    return Decimal(whole.replace(",", "") + (fraction or ""))


def _public_hours(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _band(
    value: Decimal,
    *,
    onsite: bool,
    backup_max: Decimal,
    bridge_min: Decimal,
    bridge_max: Decimal,
    btm_hours: Decimal,
) -> str:
    if value <= backup_max:
        return "backup"
    if bridge_min <= value <= bridge_max:
        return "bridge_temporary"
    if value == btm_hours and onsite:
        return "btm"
    return ""


def classify_operating_hours(text: str) -> dict[str, Any]:
    """Apply the configured hours rule and keep every matched quote."""
    rule = load_hours_rule()
    classes: list[str] = []
    evidence: list[dict[str, str]] = []
    hours: list[int | float] = []
    backup_max = Decimal(rule["backup_max_hours_per_year"])
    bridge_min = Decimal(rule["bridge_min_hours_per_year"])
    bridge_max = Decimal(rule["bridge_max_hours_per_year"])
    btm_hours = Decimal(rule["btm_hours_per_year"])
    noted: set[str] = set()

    def note_negation(clause: str) -> None:
        if clause in noted:
            return
        noted.add(clause)
        quote = _negated_power_quote(rule, clause)
        if quote:
            evidence.append({"clause": "negated_power", "quote": quote})

    for match in _HOURS.finditer(text):
        value = _decimal(match.group("hours"), match.group("fraction"))
        high_whole = match.group("high")
        clause = _clause(text, match.start(), match.end())
        onsite = _ONSITE.search(clause)
        hours.append(_public_hours(value))
        high = None
        if high_whole is not None:
            high = _decimal(high_whole, match.group("high_fraction"))
            hours.append(_public_hours(high))
        if high is None:
            kind = _band(
                value,
                onsite=bool(onsite),
                backup_max=backup_max,
                bridge_min=bridge_min,
                bridge_max=bridge_max,
                btm_hours=btm_hours,
            )
        else:
            low_band = _band(
                value,
                onsite=bool(onsite),
                backup_max=backup_max,
                bridge_min=bridge_min,
                bridge_max=bridge_max,
                btm_hours=btm_hours,
            )
            high_band = _band(
                high,
                onsite=bool(onsite),
                backup_max=backup_max,
                bridge_min=bridge_min,
                bridge_max=bridge_max,
                btm_hours=btm_hours,
            )
            kind = low_band if low_band and low_band == high_band else ""
        if kind:
            classes.append(kind)
        evidence.append({"clause": kind or "unclassified_hours", "quote": match.group(0)})
        if kind == "btm" and onsite:
            evidence.append({"clause": "onsite_use_only", "quote": onsite.group(0)})
    for pattern, label in (
        ("bridge_unit_pattern", "portable_or_trailer_mounted"),
        ("bridge_permit_pattern", "expiring_or_temporary_permit"),
    ):
        for match in re.finditer(rule[pattern], text, re.IGNORECASE):
            clause = _clause(text, match.start(), match.end())
            if _affirmative_power(rule, clause):
                classes.append("bridge_temporary")
                evidence.append({"clause": label, "quote": match.group(0)})
                break
            note_negation(clause)
    unique = list(dict.fromkeys(classes))
    conflict = len(unique) > 1
    return {
        "rule_id": rule["rule_id"],
        "classification": None if conflict or not unique else unique[0],
        "conflict": conflict,
        "hours_per_year": hours,
        "evidence": evidence,
    }
