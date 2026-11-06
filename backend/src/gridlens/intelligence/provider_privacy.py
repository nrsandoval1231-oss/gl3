"""Fail-closed privacy checks for evidence sent to external providers.

Evidence is retained as immutable source material. If an evidence item contains
contact or ambiguous personal data, callers should omit that complete item rather
than redact quoted text or alter citation offsets.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import date, datetime
from html import unescape
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit
from uuid import UUID

MAX_STRUCTURE_DEPTH = 16
MAX_STRUCTURE_NODES = 10_000
MAX_TEXT_LENGTH = 250_000

_EMAIL = re.compile(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_PHONE_SPAN = re.compile(r"\+?\d[\d(). \t-]{5,}\d")
_NANP_PHONE = re.compile(
    r"(?<!\d)(?:\+?1[ \t.-]?)?(?:\(\d{3}\)|\d{3})[ \t.-]\d{3}[ \t.-]\d{4}(?!\d)"
)
_PHONE_CONTEXT = re.compile(r"\b(?:phone|telephone|tel|fax|mobile|cell|contact|call)\b", re.I)
_CONTACT_KIND = re.compile(
    r"\b(phone|telephone|tel|fax|mobile|cell|email|contact|person|profile)\b", re.I
)
_EMAIL_CONTEXT = re.compile(r"\b(?:e-?mail|email address)\b", re.I)
_PERSONAL_DATA_CONTEXT = re.compile(
    r"\b(?:date of birth|dob|social security|ssn|driver'?s license|"
    r"residential address|home address|mailing address|personal address)\b",
    re.I,
)
_PERSON_CONTEXT = re.compile(
    r"\b(?:contact(?: person)?|point of contact|prepared by|submitted by|"
    r"signed by|signatory|representative|attorney|agent|applicant|owner|landowner)\b",
    re.I,
)
_LABELED_PERSON = re.compile(
    r"(?i:(?:\b(?:contact(?: person)?|point of contact|signatory|representative|"
    r"attorney|agent|applicant|owner|landowner)(?:\s+(?:name|is))?\s*[:=\-]|"
    r"\b(?:submitted by|prepared by|signed by)\b\s*))([^\n;]+)"
)
_ORG_INDICATOR = re.compile(
    r"\b(?:inc(?:orporated)?|corp(?:oration)?|llc|l\.l\.c\.|ltd|limited|"
    r"lp|l\.p\.|llp|company|co\.?|city|county|department|district|authority|"
    r"commission|university|school|municipal|energy|resources|gas|oil|power|"
    r"infrastructure|industrial|holdings|partners|services|systems|development)\b",
    re.I,
)
_NAME_SEQUENCE = re.compile(r"\b[A-Za-z][A-Za-z'’.-]{1,}(?:\s+[A-Za-z][A-Za-z'’.-]{1,}){1,3}\b")
_PERCENT_ESCAPE = re.compile(r"%[0-9a-f]{2}", re.I)
_SENSITIVE_KEYS = frozenset(
    {
        "contact",
        "contacts",
        "contact_info",
        "contact_details",
        "contact_name",
        "contact_person",
        "point_of_contact",
        "poc",
        "phone",
        "phone_number",
        "telephone",
        "telephone_number",
        "tel",
        "fax",
        "mobile",
        "mobile_number",
        "cell",
        "cell_phone",
        "email",
        "email_address",
        "e_mail",
        "public_contacts",
        "reported_contacts",
        "first_name",
        "last_name",
        "full_name",
        "person_name",
        "individual_name",
        "applicant_name",
        "owner_name",
        "landowner_name",
        "agent_name",
        "representative_name",
        "submitter_name",
        "prepared_by",
        "submitted_by",
        "signatory",
        "signature",
        "date_of_birth",
        "birth_date",
        "dob",
        "social_security_number",
        "ssn",
        "personal_address",
        "residential_address",
        "home_address",
        "mailing_address",
        "private_address",
    }
)
_SENSITIVE_KEY_PARTS = frozenset(
    {
        "contact",
        "phone",
        "telephone",
        "fax",
        "mobile",
        "cell",
        "email",
        "person_name",
        "individual_name",
        "first_name",
        "last_name",
        "full_name",
        "applicant_name",
        "owner_name",
        "landowner_name",
        "agent_name",
        "representative_name",
        "submitter_name",
        "personal_address",
        "residential_address",
        "home_address",
        "mailing_address",
        "private_address",
        "date_of_birth",
        "birth_date",
        "ssn",
        "social_security_number",
        "signature",
        "signatory",
    }
)


class ProviderPrivacyError(ValueError):
    """A provider-bound structure is not demonstrably free of contact data."""


def _decode_bounded(value: str) -> tuple[str, bool]:
    decoded = value
    for _ in range(3):
        next_value = unescape(unquote(decoded))
        if next_value == decoded:
            return decoded, False
        decoded = next_value
    return decoded, bool(_PERCENT_ESCAPE.search(decoded))


def _nonempty(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping | list | tuple | set | frozenset):
        return bool(value)
    return True


def _normalize_text_labels(value: str) -> str:
    """Expose snake, kebab, and camel field labels to context-word checks."""
    spaced_case = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return re.sub(r"[_-]+", " ", spaced_case)


def _sensitive_key(key: object) -> bool:
    if not isinstance(key, str):
        return True
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    normalized = re.sub(r"[^a-z0-9]+", "_", camel_split.casefold()).strip("_")
    if normalized in _SENSITIVE_KEYS:
        return True
    parts = set(normalized.split("_"))
    if parts & {"phone", "telephone", "tel", "fax", "mobile", "cell", "email"}:
        return True
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _sensitive_text(value: str, key: str) -> bool:
    if len(value) > MAX_TEXT_LENGTH:
        return True
    decoded, undecoded_escape = _decode_bounded(value)
    if undecoded_escape:
        return True
    if _EMAIL.search(value) or _EMAIL.search(decoded) or re.search(r"\bmailto\s*:", decoded, re.I):
        return True
    if _EMAIL_CONTEXT.search(key) and value.strip():
        return True
    if _PERSONAL_DATA_CONTEXT.search(value):
        return True
    if re.search(r"\b(?:mailto|tel)\s*:", value, re.I):
        return True

    phone_text = re.sub(r"https?://[^\s<>\"']+", " ", decoded, flags=re.I)
    key_has_phone_context = bool(_PHONE_CONTEXT.search(_normalize_text_labels(key)))
    if key_has_phone_context and any(
        7 <= len(number) <= 15 for number in re.findall(r"\d+", phone_text)
    ):
        return True
    for match in _PHONE_SPAN.finditer(phone_text):
        number = match.group()
        digits = re.sub(r"\D", "", number)
        prefix = _normalize_text_labels(phone_text[max(0, match.start() - 40) : match.start()])
        has_phone_context = key_has_phone_context or bool(_PHONE_CONTEXT.search(prefix))
        if has_phone_context and any(
            7 <= len(run) <= 15 for run in re.findall(r"(?<!\d)\d+(?!\d)", number)
        ):
            return True
        explicit_format = (
            number.startswith("+")
            or "(" in number
            or bool(_NANP_PHONE.search(number))
            or bool(re.search(r"(?<!\d)\d{3}[-. ]\d{4}(?!\d)", number))
        )
        if 7 <= len(digits) <= 15 and (has_phone_context or explicit_format):
            return True
    if _PERSON_CONTEXT.search(phone_text):
        for match in _LABELED_PERSON.finditer(phone_text):
            # A legal entity can appear beside a person in the same permit quote;
            # reject any non-organization name sequence independently.
            for name in _NAME_SEQUENCE.finditer(match.group(1)):
                if not _ORG_INDICATOR.search(name.group()):
                    return True
    return False


def _sensitive_url(value: str) -> bool:
    for match in re.finditer(r"https?://[^\s<>\"']+", value, re.I):
        raw_url, undecoded_escape = _decode_bounded(match.group())
        if undecoded_escape:
            return True
        try:
            parsed = urlsplit(raw_url)
            if parsed.username is not None or parsed.password is not None:
                return True
            if _EMAIL.search(unquote(parsed.path)) or _EMAIL.search(unquote(parsed.fragment)):
                return True
            path_parts = [part for part in parsed.path.split("/") if part]
            for index, name in enumerate(path_parts[:-1]):
                if _sensitive_key(name) and path_parts[index + 1].strip():
                    return True
            params = parse_qsl(parsed.query, keep_blank_values=True)
            params.extend(parse_qsl(parsed.fragment.lstrip("?&"), keep_blank_values=True))
            for name, content in params:
                if _sensitive_key(name) and content.strip():
                    return True
                if _sensitive_text(content, name):
                    return True
        except (ValueError, UnicodeError):
            return True
    return False


def _contains_sensitive_contact(
    value: Any, *, key: str = "", depth: int = 0, budget: list[int] | None = None
) -> bool:
    if budget is None:
        budget = [MAX_STRUCTURE_NODES]
    budget[0] -= 1
    if budget[0] < 0 or depth > MAX_STRUCTURE_DEPTH:
        return True
    if isinstance(value, str):
        return _sensitive_url(value) or _sensitive_text(value, key)
    if value is None or isinstance(value, bool | int):
        return False
    if isinstance(value, date | datetime | UUID):
        return False
    if isinstance(value, float):
        return not (value == value and abs(value) != float("inf"))
    if isinstance(value, Mapping):
        kind = value.get("kind") or value.get("type") or ""
        label = value.get("label") or ""
        contact_context = bool(isinstance(kind, str) and _CONTACT_KIND.search(kind)) or bool(
            isinstance(label, str) and _CONTACT_KIND.search(label)
        )
        if contact_context and any(
            _nonempty(value.get(field)) for field in ("value", "href", "url", "number")
        ):
            return True
        for child_key, child in value.items():
            if not isinstance(child_key, str):
                return True
            if _sensitive_text(child_key, ""):
                return True
            if _sensitive_key(child_key) and _nonempty(child):
                return True
            if _contains_sensitive_contact(
                child, key=str(child_key), depth=depth + 1, budget=budget
            ):
                return True
        return False
    if isinstance(value, list | tuple):
        return any(
            _contains_sensitive_contact(child, key=key, depth=depth + 1, budget=budget)
            for child in value
        )
    # Unsupported values cannot be safely inspected or serialized for a provider.
    return True


def contains_sensitive_contact(value: object) -> bool:
    """Return true if a JSON-like structure contains contact or ambiguous personal data.

    Malformed, oversized, deeply nested, or unsupported values fail closed. This
    function never includes inspected values in an exception or log message.
    """
    try:
        return _contains_sensitive_contact(value)
    except Exception:
        # Provider-bound privacy checks should fail closed even for hostile custom
        # Mapping implementations; callers receive only a boolean decision.
        return True


def require_contact_free(value: object) -> None:
    """Reject provider-bound data unless its inspected structure is contact-free."""
    if contains_sensitive_contact(value):
        raise ProviderPrivacyError("provider input contains sensitive or ambiguous personal data")


def contact_free_evidence(
    items: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Deep-copy safe evidence records, dropping each unsafe record as a whole.

    Quotes, source text and citation offsets are never rewritten. Invalid entries
    and records that exceed inspection bounds are omitted without revealing why.
    """
    safe: list[dict[str, object]] = []
    try:
        for item in items:
            if not isinstance(item, Mapping) or contains_sensitive_contact(item):
                continue
            try:
                cloned = deepcopy(item)
            except Exception:
                continue
            if isinstance(cloned, dict) and not contains_sensitive_contact(cloned):
                safe.append(cloned)
    except Exception:
        # If collection iteration itself fails, do not return a partial evidence
        # set whose privacy status may depend on inaccessible remaining items.
        return []
    return safe
