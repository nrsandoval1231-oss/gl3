"""Internal privacy controls for hiding stable contact subjects and methods."""

from __future__ import annotations

import hashlib
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gridlens.persistence.suppression_models import ContactSuppression


class SuppressionConflict(ValueError):
    """The requested expected version is stale or the ledger is conflicted."""


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().casefold())


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
    return _key("method", str(company_id), _norm(name), _norm(kind), _norm(value))


def global_method_suppression_key(kind: str, value: str) -> str:
    return _key("method", "global", _norm(kind), _norm(value))


def _ledger_state(session: Session, scope: str, subject_key: str) -> tuple[str, int]:
    rows = session.scalars(
        select(ContactSuppression)
        .where(ContactSuppression.scope == scope, ContactSuppression.subject_key == subject_key)
        .order_by(ContactSuppression.version)
    ).all()
    state, version = "active", 0
    for row in rows:
        if row.expected_version != version or row.version != version + 1:
            # A fork means privacy intent is unresolved. Fail closed.
            return "suppressed", version
        state, version = row.action, row.version
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
    if not subject_key or len(subject_key) != 64:
        raise ValueError("subject_key must be a stable SHA-256 hex digest")
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
        if existing.action != action or existing.expected_version != expected_version:
            raise SuppressionConflict("idempotency key was already used for a different event")
        return existing
    current, version = _ledger_state(session, scope, subject_key)
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
    company_key = company_suppression_key(company_id)
    if _ledger_state(session, "company", company_key)[0] == "suppress":
        return []
    filtered = []
    for contact in contacts:
        name = getattr(contact, "name", None)
        person_id = getattr(contact, "person_identity_id", None)
        if name and (
            _ledger_state(session, "person", person_suppression_key(company_id, name))[0]
            == "suppress"
            or (
                person_id
                and _ledger_state(session, "person", global_person_suppression_key(person_id))[0]
                == "suppress"
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
                _ledger_state(session, "method", key)[0] != "suppress"
                and _ledger_state(session, "method", global_key)[0] != "suppress"
            ):
                methods.append(method)
        if hasattr(contact, "model_copy"):
            contact = contact.model_copy(update={"methods": methods})
        else:
            contact.methods = methods
        filtered.append(contact)
    return filtered
