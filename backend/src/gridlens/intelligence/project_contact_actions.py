"""Safe project-card contact actions derived only from its contact projection."""

from __future__ import annotations

import re
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.orm import Session

from gridlens.intelligence.contact_suppressions import (
    _ledger_states,
    company_suppression_key,
    global_method_suppression_key,
    global_person_suppression_key,
    method_suppression_key,
    person_suppression_key,
)


def _safe_href(value: object, kind: str) -> str | None:
    href = str(value or "").strip()
    if not href or any(ord(char) < 32 for char in href):
        return None
    parsed = urlsplit(href)
    if kind == "email" and parsed.scheme.lower() == "mailto":
        address = parsed.path
        if re.fullmatch(
            r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}", address
        ):
            return href
    if kind == "call" and parsed.scheme.lower() == "tel":
        number = parsed.path
        if re.fullmatch(r"\+?[0-9]{7,15}", number):
            return href
    if kind == "contact" and parsed.scheme.lower() in {"http", "https"} and parsed.hostname:
        if parsed.username is None and parsed.password is None:
            return href
    return None


def _suppression_method_kind(kind: str) -> str:
    """Map presentation controls to the canonical privacy-ledger method kind."""
    return "phone" if kind == "call" else kind


def project_contact_actions(compact: dict) -> list[dict]:
    """Return source-verified actions from current projected contact claims.

    Expected input is a compact project card containing ``contacts`` or an
    ``intelligence_card.contacts`` array. Callers must build this from a fresh,
    suppression-filtered projection; this pure formatter cannot query the
    suppression ledger or revalidate retained evidence itself.
    """
    card = compact.get("intelligence_card") or {}
    contacts = compact.get("contacts") or card.get("contacts") or []
    result: list[dict] = []
    seen: set[tuple] = set()
    for contact in contacts:
        if not isinstance(contact, dict) or any(
            contact.get(flag) for flag in ("suppressed", "stale", "retracted", "withheld")
        ):
            continue
        responsibility = str(contact.get("responsibility") or "")
        if responsibility not in {
            "General company contact path",
            "Verified project responsibility",
            "Verified organizational responsibility",
            "Inferred likely role",
        }:
            continue
        company = str(contact.get("company") or "").strip()
        if not company:
            continue
        person = str(contact.get("name") or "").strip() or None
        title = str(contact.get("title") or "").strip() or None
        role = str(contact.get("role") or "unknown").strip()
        # Existing contact_projection is the source/evidence gate. Require a
        # current source citation as a defense against incomplete cached cards.
        sources = contact.get("sources") or []
        if not any(
            isinstance(source, dict)
            and source.get("verification_status") == "Current retained support"
            for source in sources
        ):
            continue
        methods = contact.get("methods") or []
        for method in methods:
            if not isinstance(method, dict):
                continue
            original_kind = str(method.get("kind") or "").lower()
            kind = (
                "email"
                if original_kind == "email"
                else "call"
                if original_kind in {"phone", "telephone", "call"}
                else None
            )
            if kind is None:
                continue
            href = _safe_href(method.get("href"), kind)
            if not href:
                continue
            key = (contact.get("claim_id"), kind, href)
            if key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "kind": kind,
                    "href": href,
                    "company": company,
                    "name": person,
                    "title": title,
                    "role": role,
                    "responsibility": responsibility,
                    "purchasing_authority": contact.get("purchasing_authority")
                    or "Requires confirmation for this power package",
                    "source_url": method.get("source_url")
                    or next(
                        (s.get("url") for s in sources if isinstance(s, dict) and s.get("url")),
                        None,
                    ),
                    "claim_id": contact.get("claim_id"),
                    "company_identity_id": contact.get("company_identity_id"),
                    "person_identity_id": contact.get("person_identity_id"),
                }
            )
        if responsibility == "General company contact path":
            for source in sources:
                if not isinstance(source, dict):
                    continue
                source_url = str(source.get("url") or "")
                path = urlsplit(source_url).path.casefold()
                # A source citation alone is not an invitation to contact.
                # Only expose an explicitly labeled public contact route.
                title = str(source.get("title") or "").casefold()
                if not (
                    re.search(r"(?:^|/)(?:contact|contacts|inquiry|inquiries)(?:/|$)", path)
                    or "contact" in title
                ):
                    continue
                href = _safe_href(source_url, "contact")
                if not href:
                    continue
                key = (contact.get("claim_id"), "contact", href)
                if key in seen:
                    continue
                seen.add(key)
                result.append(
                    {
                        "kind": "contact",
                        "href": href,
                        "company": company,
                        "name": None,
                        "title": None,
                        "role": role,
                        "responsibility": responsibility,
                        "purchasing_authority": "No buyer authority established",
                        "source_url": source.get("url"),
                        "claim_id": contact.get("claim_id"),
                        "company_identity_id": contact.get("company_identity_id"),
                        "person_identity_id": contact.get("person_identity_id"),
                    }
                )
    return result


def project_contact_people(compact: dict) -> list[dict]:
    """Return source-supported named roles even when no method is known."""
    card = compact.get("intelligence_card") or {}
    contacts = compact.get("contacts") or card.get("contacts") or []
    people = []
    for contact in contacts:
        if not isinstance(contact, dict) or any(
            contact.get(flag) for flag in ("suppressed", "stale", "retracted", "withheld")
        ):
            continue
        if not contact.get("name") or not contact.get("company"):
            continue
        if contact.get("methods"):
            continue
        responsibility = str(contact.get("responsibility") or "")
        if responsibility not in {
            "Verified project responsibility",
            "Verified organizational responsibility",
            "Inferred likely role",
        }:
            continue
        if not any(
            isinstance(source, dict)
            and source.get("verification_status") == "Current retained support"
            for source in contact.get("sources") or []
        ):
            continue
        people.append(
            {
                "record_type": "contact_person",
                "claim_id": contact.get("claim_id"),
                "company_identity_id": contact.get("company_identity_id"),
                "person_identity_id": contact.get("person_identity_id"),
                "company": contact.get("company"),
                "name": contact.get("name"),
                "title": contact.get("title"),
                "role": contact.get("role"),
                "responsibility": responsibility,
                "purchasing_authority": contact.get("purchasing_authority")
                or "Requires confirmation for this power package",
                "source_url": next(
                    (
                        s.get("url")
                        for s in contact.get("sources") or []
                        if isinstance(s, dict) and s.get("url")
                    ),
                    None,
                ),
            }
        )
    return people


def filter_project_contact_records(session: Session, records: list[dict]) -> list[dict]:
    """Recheck cached action/person records against current privacy suppressions.

    One batched ledger lookup covers all records in a page, including actions
    nested under needs. Caller must flatten those records before invoking.
    """
    keys: set[tuple[str, str]] = set()
    parsed: list[tuple[dict, UUID, UUID | None]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            company_id = UUID(str(record.get("company_identity_id")))
        except (ValueError, TypeError, AttributeError):
            # Missing canonical identity means the record cannot be safely
            # published from a cached projection.
            continue
        try:
            person_id = (
                UUID(str(record.get("person_identity_id")))
                if record.get("person_identity_id")
                else None
            )
        except (ValueError, TypeError, AttributeError):
            person_id = None
        parsed.append((record, company_id, person_id))
        keys.add(("company", company_suppression_key(company_id)))
        name = str(record.get("name") or "").strip()
        if name:
            keys.add(("person", person_suppression_key(company_id, name)))
        if person_id:
            keys.add(("person", global_person_suppression_key(person_id)))
        kind = _suppression_method_kind(str(record.get("kind") or ""))
        href = str(record.get("href") or "")
        if kind and href:
            keys.add(("method", method_suppression_key(company_id, name or None, kind, href)))
            keys.add(("method", global_method_suppression_key(kind, href)))
    states = _ledger_states(session, keys)
    kept = []
    for record, company_id, person_id in parsed:
        if states.get(("company", company_suppression_key(company_id))) == "suppress":
            continue
        name = str(record.get("name") or "").strip()
        if name and states.get(("person", person_suppression_key(company_id, name))) == "suppress":
            continue
        if (
            person_id
            and states.get(("person", global_person_suppression_key(person_id))) == "suppress"
        ):
            continue
        kind = _suppression_method_kind(str(record.get("kind") or ""))
        href = str(record.get("href") or "")
        if (
            kind
            and href
            and (
                states.get(("method", method_suppression_key(company_id, name or None, kind, href)))
                == "suppress"
                or states.get(("method", global_method_suppression_key(kind, href))) == "suppress"
            )
        ):
            continue
        kept.append(record)
    return kept


def filter_project_contact_actions(session: Session, actions: list[dict]) -> list[dict]:
    """Backward-compatible action-only spelling for page-time revalidation."""
    return [
        record for record in filter_project_contact_records(session, actions) if record.get("kind")
    ]
