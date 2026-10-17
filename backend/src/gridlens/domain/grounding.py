"""Deterministic grounding checks for model-written newsletter claims.

A claim is accepted only when every number, month/date, and proper name it states
appears in the text of the evidence items it cites. This catches invented figures and
entities; it cannot prove a sentence is a faithful paraphrase, so output is always a
draft for human review.
"""

import re

MONTHS = (
    "january february march april may june july august september october november december"
).split()
_MONTH_FORMS = {m: {m, m[:3]} for m in MONTHS}
_NUMBER = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?")
_WORD = re.compile(r"[A-Za-z][A-Za-z&\-]*(?:['’]s)?")
_MONTH_DAY = re.compile(
    r"\b("
    + "|".join(m.capitalize() for m in MONTHS)
    + r"|"
    + "|".join(m[:3].capitalize() for m in MONTHS)
    + r")\.?\s+\d{1,2}\b"
)
_COMMON_OPENERS = {
    "regulators", "officials", "utilities", "utility", "developers", "developer", "operators",
    "operator", "companies", "company", "executives", "analysts", "state", "states", "federal",
    "local", "several", "some", "most", "many", "more", "other", "another", "one", "two",
    "three", "four", "five", "six", "seven", "eight", "nine", "ten", "both", "each", "all",
    "demand", "prices", "price", "power", "electricity", "energy", "grid", "data", "capacity",
    "generation", "load", "projects", "project", "plans", "plan", "requests", "report",
    "reports", "proposed", "approved", "planned", "recent", "latest", "total", "average",
    "wholesale", "natural", "solar", "wind", "nuclear", "battery", "storage", "transmission",
    "customers", "ratepayers", "consumers", "lawmakers", "agencies", "agency", "board",
    "commission", "committee", "council", "group", "groups", "market", "markets",
    "large", "major", "new", "no", "not", "there", "here", "when", "where", "why", "how",
    "what", "who", "which", "if", "so", "yet", "then", "now", "today", "yesterday",
    "tomorrow", "last", "next", "earlier", "later", "since", "during", "under", "over",
    "between", "across", "among", "about", "despite", "because", "although", "though",
    "year", "week", "month", "quarter", "summer", "winter", "fall", "spring", "peak",
}  # fmt: skip
_STOP = {
    "the", "a", "an", "in", "on", "at", "and", "but", "or", "of", "for", "to", "with", "by",
    "from", "as", "after", "before", "while", "according", "this", "that", "these", "those",
    "it", "its", "their", "his", "her", "meanwhile", "however", "separately", "also",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "new",
    "us", "u",
}  # fmt: skip


def normalize(text: str) -> str:
    return (
        text.replace("’", "'").replace("–", "-").replace("—", "-").replace("\u00a0", " ")
    ).casefold()


def numbers(text: str) -> set[str]:
    found = set()
    for token in _NUMBER.findall(text):
        value = token.lstrip("$").replace(",", "").rstrip(".")
        found.add(value)
    return found


def _word_set(text: str) -> set[str]:
    words = set()
    for raw in _WORD.findall(normalize(text)):
        word = re.sub(r"'s$", "", raw)
        words.add(word)
        words.update(part for part in word.split("-") if part)
    return words


def _names(text: str) -> tuple[set[str], set[str]]:
    """Capitalized names and acronyms, plus uncommon sentence openers checked leniently."""
    names: set[str] = set()
    openers: set[str] = set()
    for match in _WORD.finditer(text):
        raw = re.sub(r"['’]s$", "", match.group(0))
        if len(raw) < 2 or not raw[0].isupper():
            continue
        before = text[: match.start()].rstrip()
        sentence_start = not before or before[-1] in ".!?:;\"'“(" or before.endswith("\n")
        is_acronym = raw.isupper()
        lowered = normalize(raw)
        if lowered in _STOP:
            continue
        if sentence_start and not is_acronym:
            # A sentence opener is only a name if it is not an everyday word.
            if lowered in _COMMON_OPENERS:
                continue
            openers.add(lowered)
            continue
        names.add(lowered)
    return names, openers


def ungrounded(claim: str, cited_text: str) -> list[str]:
    """Return what the claim states that the cited text does not (empty = grounded)."""
    problems = []
    cited_numbers = numbers(cited_text)
    for number in sorted(numbers(claim) - cited_numbers):
        problems.append(f"number:{number}")
    cited_words = _word_set(cited_text)
    cited_normal = normalize(cited_text)
    for match in _MONTH_DAY.finditer(claim):
        month = normalize(match.group(1))
        forms = next(f for f in _MONTH_FORMS.values() if month in f)
        if not forms & cited_words:
            problems.append(f"date:{match.group(0)}")
    names, openers = _names(claim)
    for opener in sorted(openers):
        stem = opener[:-1] if opener.endswith("s") else opener
        if opener not in cited_words and stem not in cited_words:
            problems.append(f"name:{opener}")
    for name in sorted(names):
        parts = [p for p in name.split("-") if p]
        if name in cited_words or all(part in cited_words for part in parts):
            continue
        if name in _MONTH_FORMS and _MONTH_FORMS[name] & cited_words:
            continue
        if any(name in forms and forms & cited_words for forms in _MONTH_FORMS.values()):
            continue
        if name in cited_normal and len(name) > 3:  # e.g. "pg&e" inside punctuation
            continue
        problems.append(f"name:{name}")
    return problems
