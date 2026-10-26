"""Internal privacy controls for hiding stable contact subjects and methods."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gridlens.persistence.suppression_models import ContactSuppression


class SuppressionConflict(ValueError):
    """The requested expected version is stale or the ledger is conflicted."""


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().casefold())


def _method_parts(kind: str, value: str) -> tuple[str, str]:
    """Canonicalize extractor values and presentation hrefs to the same key."""
    kind = _norm(kind)
    value = value.strip()
    if kind in {"telephone", "tel"}:
        kind = "phone"
    if kind == "email":
        if value.casefold().startswith("mailto:"):
            value = value[7:].split("?", 1)[0]
        return kind, _norm(value)
    if kind == "phone":
        if value.casefold().startswith("tel:"):
            value = value[4:].split(";", 1)[0]
        digits = re.sub(r"\D", "", value)
        return kind, ("+" if value.lstrip().startswith("+") else "") + digits
    if kind in {"profile", "website", "url"}:
        parsed = urlsplit(value if "://" in value else "//" + value)
        host = (parsed.hostname or "").casefold().removeprefix("www.")
        path = (parsed.path or "").rstrip("/")
        return "profile" if kind == "url" else kind, host + path
    return kind, _norm(value)


def _key(scope: str, *parts: str) -> str:
    raw = "\x1f".join((scope, *parts))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def company_suppression_key(company_id: UUID) -> str:
    return _key("company", str(company_id))


def person_suppression_key(company_id: UUID, name: str) -> str:
    return _key("person", str(company_id), _norm(name))


def global_person_suppression_key(person_id: UUID) -> str:
    return _key("person", "global", str(person_id))


def method_suppression_key(company_id: UUID, name: str | None, kind: str, value: str) -> str:
    kind, value = _method_parts(kind, value)
    # A method is scoped to its canonical company, not a transient claim/person
    # label, so name corrections or refreshed claims cannot revive the method.
    return _key("method", str(company_id), kind, value)


def global_method_suppression_key(kind: str, value: str) -> str:
    kind, value = _method_parts(kind, value)
    return _key("method", "global", kind, value)


def _ledger_states(session: Session, keys: set[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """Load one request/cohort snapshot; corrupt chains remain suppressed."""
    if not keys:
        return {}
    rows = session.scalars(
        select(ContactSuppression)
        .where(tuple_(ContactSuppression.scope, ContactSuppression.subject_key).in_(keys))
        .order_by(
            ContactSuppression.scope, ContactSuppression.subject_key, ContactSuppression.version
        )
    ).all()
    grouped: dict[tuple[str, str], list[ContactSuppression]] = {}
    for row in rows:
        key = (row.scope, row.subject_key)
        if key in keys:
            grouped.setdefault(key, []).append(row)
    states: dict[tuple[str, str], str] = {}
    for key in keys:
        state, version = "active", 0
        for row in grouped.get(key, []):
            if row.expected_version != version or row.version != version + 1:
                state = "suppress"
                version = -1
                break
            state, version = row.action, row.version
        states[key] = state
    return states


def _ledger_state(session: Session, scope: str, subject_key: str) -> tuple[str, int]:
    state = _ledger_states(session, {(scope, subject_key)}).get((scope, subject_key), "active")
    rows = session.scalars(
        select(ContactSuppression)
        .where(ContactSuppression.scope == scope, ContactSuppression.subject_key == subject_key)
        .order_by(ContactSuppression.version)
    ).all()
    version = 0
    for row in rows:
        if row.expected_version != version or row.version != version + 1:
            return "suppress", -1
        version = row.version
    return state, version


def record_contact_suppression(
    session: Session,
    *,
    scope: str,
    subject_key: str,
    action: str,
    expected_version: int,
    reason: str,
    actor: str,
    idempotency_key: str,
) -> ContactSuppression:
    """Append an audited internal suppression/reinstatement event."""
    if scope not in {"company", "person", "method"} or action not in {"suppress", "reinstate"}:
        raise ValueError("Unsupported contact suppression scope or action")
    if (
        not subject_key
        or len(subject_key) != 64
        or any(c not in "0123456789abcdef" for c in subject_key)
    ):
        raise ValueError("subject_key must be a stable SHA-256 hex digest")
    if any(not isinstance(value, str) for value in (reason, actor, idempotency_key)):
        raise ValueError("reason, actor, and idempotency_key must be strings")
    if not reason.strip() or not actor.strip() or not idempotency_key.strip():
        raise ValueError("reason, actor, and idempotency_key are required")
    existing = session.scalar(
        select(ContactSuppression).where(
            ContactSuppression.scope == scope,
            ContactSuppression.subject_key == subject_key,
            ContactSuppression.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.action != action
            or existing.expected_version != expected_version
            or existing.reason != reason.strip()
            or existing.actor != actor.strip()
        ):
            raise SuppressionConflict("idempotency key was already used for a different event")
        return existing
    current, version = _ledger_state(session, scope, subject_key)
    if version < 0:
        raise SuppressionConflict("suppression history is conflicted; explicit review is required")
    if version != expected_version:
        raise SuppressionConflict(
            f"expected version {expected_version}; current version is {version}"
        )
    if (action == "suppress" and current == "suppress") or (
        action == "reinstate" and current != "suppress"
    ):
        raise SuppressionConflict("requested action does not match current suppression state")
    row = ContactSuppression(
        scope=scope,
        subject_key=subject_key,
        expected_version=expected_version,
        version=expected_version + 1,
        action=action,
        reason=reason.strip(),
        actor=actor.strip(),
        idempotency_key=idempotency_key.strip(),
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        raise SuppressionConflict("concurrent suppression event; reload history and retry") from exc
    return row


def apply_contact_suppressions(session: Session, company_id: UUID, contacts: list):
    """Filter suppressed companies, people, or methods; retain empty role assertions."""
    key_set = {("company", company_suppression_key(company_id))}
    for contact in contacts:
        name = getattr(contact, "name", None)
        person_id = getattr(contact, "person_identity_id", None)
        if name:
            key_set.add(("person", person_suppression_key(company_id, name)))
        if person_id:
            key_set.add(("person", global_person_suppression_key(person_id)))
        for method in getattr(contact, "methods", []):
            kind = method.get("kind") if isinstance(method, dict) else getattr(method, "kind", "")
            value = method.get("href") if isinstance(method, dict) else getattr(method, "href", "")
            key_set.add(
                (
                    "method",
                    method_suppression_key(company_id, name, str(kind or ""), str(value or "")),
                )
            )
            key_set.add(
                ("method", global_method_suppression_key(str(kind or ""), str(value or "")))
            )
    states = _ledger_states(session, key_set)
    company_key = company_suppression_key(company_id)
    if states.get(("company", company_key)) == "suppress":
        return []
    filtered = []
    for contact in contacts:
        name = getattr(contact, "name", None)
        person_id = getattr(contact, "person_identity_id", None)
        if name and (
            states.get(("person", person_suppression_key(company_id, name))) == "suppress"
            or (
                person_id
                and states.get(("person", global_person_suppression_key(person_id))) == "suppress"
            )
        ):
            continue
        methods = []
        for method in getattr(contact, "methods", []):
            kind = method.get("kind") if isinstance(method, dict) else getattr(method, "kind", "")
            value = method.get("href") if isinstance(method, dict) else getattr(method, "href", "")
            key = method_suppression_key(company_id, name, str(kind or ""), str(value or ""))
            global_key = global_method_suppression_key(str(kind or ""), str(value or ""))
            if (
                states.get(("method", key)) != "suppress"
                and states.get(("method", global_key)) != "suppress"
            ):
                methods.append(method)
        if hasattr(contact, "model_copy"):
            contact = contact.model_copy(update={"methods": methods})
        else:
            contact.methods = methods
        filtered.append(contact)
    return filtered
