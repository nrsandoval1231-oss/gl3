"""Read-time privacy projection over immutable saved commercial history."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from copy import deepcopy
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.intelligence.contact_suppressions import (
    _ledger_states,
    _method_parts,
    company_suppression_key,
    global_method_suppression_key,
    global_person_suppression_key,
    method_suppression_key,
    person_suppression_key,
)
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainCorrection,
    BuyingChainIdentityLink,
)

MAX_HISTORY_PROJECTS = 64
MAX_HISTORY_CLAIMS = 256
MAX_HISTORY_LINKS = 512
MAX_HISTORY_METHODS = 128
MAX_HISTORY_KEYS = 2048
_EMAIL = re.compile(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_PHONE = re.compile(r"\+?\d[\d(). \t-]{5,}\d")
_NANP = re.compile(r"(?<!\d)(?:\+?1[ \t.-]?)?(?:\(\d{3}\)|\d{3})[ \t.-]?\d{3}[ \t.-]?\d{4}(?!\d)")
_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
# Preserve machine semantics and audit pointers, including required enum fields.
_META = frozenset(
    {
        "id",
        "claim_id",
        "project_id",
        "related_project_ids",
        "need_id",
        "related_need_ids",
        "pursuit_id",
        "company_identity_id",
        "person_identity_id",
        "fingerprint",
        "input_hash",
        "input_fingerprint",
        "evidence_id",
        "evidence_ids",
        "content_hash",
        "hash",
        "reference",
        "source_version_hash",
        "version",
        "correction_version",
        "policy_version",
        "source_id",
        "retained_evidence_id",
        "observed_at",
        "published_at",
        "created_at",
        "updated_at",
        "verified_at",
        "evaluated_at",
        "evaluated_on",
        "date",
        "source_date",
        "assessed_at",
        "last_intelligence_update",
        "snapshot_status",
        "live_status",
        "disposition",
        "tier",
        "qualification",
        "status",
        "stage",
        "activity",
        "industry",
        "category",
        "organization_relationship",
        "person_organization_relationship",
        "person_project_relationship",
        "evidence_strength",
        "responsibility",
        "field_status",
        "section",
        "key",
        "kind",
        "type",
        "action",
        "supports",
        "conflict_state",
        "required_mw",
        "start_window",
        "duration",
    }
)
_CONTACT_LISTS = frozenset({"contacts", "candidates", "public_contacts", "reported_contacts"})
_EVIDENCE_LISTS = frozenset({"sources", "evidence", "facts", "correction_history"})


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _strings(value: Any, key: str = ""):
    if isinstance(value, str):
        if key not in _META:
            yield value
    elif isinstance(value, dict):
        for child_key, child in value.items():
            yield from _strings(child, str(child_key))
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child, key)


def _methods(value: Any) -> set[tuple[str, str]]:
    """Collect bounded literal spellings, including international phone numbers."""
    methods: set[tuple[str, str]] = set()
    for text in _strings(value):
        for pattern, kind in ((_EMAIL, "email"), (_URL, "profile")):
            for match in pattern.finditer(text):
                methods.add((kind, match.group().rstrip(".,;:)")))
                if len(methods) > MAX_HISTORY_METHODS:
                    return methods
        # Never join separate passages into a telephone number.
        for line in text.splitlines():
            for pattern in (_NANP, _PHONE):
                for match in pattern.finditer(line):
                    part = match.group()
                    if 7 <= len(re.sub(r"\D", "", part)) <= 15:
                        methods.add(("phone", part.strip(" .,:;")))
                        if len(methods) > MAX_HISTORY_METHODS:
                            return methods

    def structured_methods(part: Any) -> None:
        if len(methods) > MAX_HISTORY_METHODS:
            return
        if isinstance(part, dict):
            kind = part.get("kind") or part.get("type")
            method = part.get("href") or part.get("value")
            if kind and isinstance(method, str) and method.strip():
                methods.add((str(kind), method.strip()))
            for child in part.values():
                structured_methods(child)
        elif isinstance(part, list):
            for child in part:
                structured_methods(child)

    structured_methods(value)
    return methods


def _explicit_profiles(value: Any):
    """Yield explicitly typed contact URLs, excluding citation provenance URLs."""
    if isinstance(value, dict):
        kind = str(value.get("kind") or value.get("type") or "").casefold()
        method = value.get("href") or value.get("value")
        if kind in {"profile", "website", "url"} and isinstance(method, str):
            yield _method_parts(kind, method)
        for child in value.values():
            yield from _explicit_profiles(child)
    elif isinstance(value, list):
        for child in value:
            yield from _explicit_profiles(child)


def _redact_all_contact_tokens(value: Any, key: str = "", contact_context: bool = False) -> Any:
    """Stream overflow redaction without storing an unbounded token inventory.

    Preserve citation URLs and unformatted engineering identifiers. Explicit
    contact methods and formatted telephone numbers remain unavailable.
    """
    if isinstance(value, str):
        if key in _META:
            return value
        value = _EMAIL.sub("[redacted]", value)
        contact_context = contact_context or bool(
            re.search(r"\b(call|phone|telephone|tel)\b", value, re.I)
        )

        def phone(match):
            part = match.group()
            digits = re.sub(r"\D", "", part)
            formatted = (
                part.startswith("+")
                or "(" in part
                or bool(re.search(r"\d{3}[-. ]\d{3}[-. ]\d{4}", part))
                or bool(re.search(r"\d{3}[-. ]\d{4}$", part))
            )
            if 7 <= len(digits) <= 15 and (contact_context or formatted):
                return "[redacted]"
            return part

        return _PHONE.sub(phone, value)
    if isinstance(value, list):
        return [_redact_all_contact_tokens(child, key, contact_context) for child in value]
    if isinstance(value, dict):
        kind = str(value.get("kind") or value.get("type") or "").casefold()
        label = str(value.get("label") or "")
        contact_context = (
            contact_context
            or kind in {"phone", "tel", "telephone"}
            or bool(re.search(r"\b(phone|telephone|contact)\b", label, re.I))
        )
        result = {}
        for child_key, child in value.items():
            if (
                kind in {"profile", "website", "url"}
                and child_key in {"href", "value"}
                and isinstance(child, str)
            ):
                result[child_key] = "[redacted]"
            else:
                result[child_key] = _redact_all_contact_tokens(
                    child, str(child_key), contact_context
                )
        return result
    return value


def _project_ids(value: dict[str, Any]) -> set[UUID]:
    related = value.get("related_project_ids") or []
    return {
        parsed for raw in [value.get("project_id"), *related] if (parsed := _uuid(raw)) is not None
    }


def _redact(
    value: Any,
    hidden: set[str],
    hidden_claims: set[UUID],
    hidden_methods: set[tuple[str, str]],
    *,
    key: str = "",
    fail_closed: bool = False,
    hidden_records: set[int] | None = None,
) -> Any:
    if isinstance(value, str):
        if key in _META:
            return value
        if fail_closed:
            return "[redacted]" if value.strip() else value
        for term in sorted((term for term in hidden if term), key=len, reverse=True):
            pattern = (r"(?<!\w)" if term[:1].isalnum() else "") + re.escape(term)
            pattern += r"(?!\w)" if term[-1:].isalnum() else ""
            value = re.sub(pattern, "[redacted]", value, flags=re.I)
        return value
    if isinstance(value, list):
        if fail_closed and key in _CONTACT_LISTS | _EVIDENCE_LISTS:
            return []
        visible = []
        for child in value:
            if hidden_records and id(child) in hidden_records:
                continue
            if isinstance(child, dict) and key in _CONTACT_LISTS | {"methods"}:
                claim_id = _uuid(child.get("claim_id") or child.get("id"))
                if claim_id is not None and claim_id in hidden_claims:
                    continue
                kind = child.get("kind") or child.get("type")
                method = child.get("href") or child.get("value")
                if (
                    kind
                    and isinstance(method, str)
                    and _method_parts(str(kind), method) in hidden_methods
                ):
                    continue
            visible.append(
                _redact(
                    child,
                    hidden,
                    hidden_claims,
                    hidden_methods,
                    key=key,
                    fail_closed=fail_closed,
                    hidden_records=hidden_records,
                )
            )
        return visible
    if isinstance(value, dict):
        return {
            child_key: _redact(
                child,
                hidden,
                hidden_claims,
                hidden_methods,
                key=str(child_key),
                fail_closed=fail_closed,
                hidden_records=hidden_records,
            )
            for child_key, child in value.items()
        }
    return value


def _contact_records(value: Any, key: str = ""):
    if isinstance(value, dict):
        if key in _CONTACT_LISTS:
            yield value
        for child_key, child in value.items():
            yield from _contact_records(child, str(child_key))
    elif isinstance(value, list):
        for child in value:
            yield from _contact_records(child, key)


def _add_keys(keys: set[tuple[str, str]], entries: Iterable[tuple[str, str]]) -> None:
    """Keep ledger bind count and intermediate allocations bounded."""
    if len(keys) > MAX_HISTORY_KEYS:
        return
    for key in entries:
        keys.add(key)
        if len(keys) > MAX_HISTORY_KEYS:
            return


def _same(value: Any, names: set[str]) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = " ".join(value.split()).casefold()
    return any(normalized == " ".join(name.split()).casefold() for name in names)


def project_saved_history_privacy(
    session: Session,
    item: dict[str, Any],
    *,
    _claim_ids: set[UUID] | None = None,
    _contact_tokens_only: bool = False,
) -> dict[str, Any]:
    """Project copied cards using bounded retained project/claim identity history.

    Current and older saved project UUIDs select retained DB claims; names or
    snapshot company/person IDs never create identity links. Former members of a
    saved group remain in scope after the current Pursuit cohort changes.
    """
    result = deepcopy(item)
    cards = []
    if isinstance(result.get("saved_card"), dict):
        cards.append(result["saved_card"])
    for version in result.get("versions") or []:
        if isinstance(version, dict) and isinstance(version.get("saved_card"), dict):
            cards.append(version["saved_card"])
    notes_projection = None
    if isinstance(result.get("notes"), list) and result["notes"]:
        # Notes are their own copied projection under the DB-supplied Pursuit
        # cohort, including receipts that have no saved card at all.
        notes_projection = {
            "project_id": item.get("project_id"),
            "related_project_ids": item.get("related_project_ids") or [],
            "notes": result["notes"],
        }
        cards.append(notes_projection)
    if not cards:
        return result
    outer_projects = _project_ids(item)
    projects_by_card = {id(card): outer_projects | _project_ids(card) for card in cards}
    projects = set().union(*projects_by_card.values())
    overflow = len(projects) > MAX_HISTORY_PROJECTS
    claims: Sequence[BuyingChainClaim] = []
    if projects and not overflow and (_claim_ids is None or _claim_ids):
        claims = session.scalars(
            select(BuyingChainClaim)
            .where(BuyingChainClaim.project_id.in_(projects))
            .order_by(BuyingChainClaim.id)
            .limit(MAX_HISTORY_CLAIMS + 1)
        ).all()
    overflow |= len(claims) > MAX_HISTORY_CLAIMS
    claims = claims[:MAX_HISTORY_CLAIMS]
    if _claim_ids is not None:
        # Internal evidence-bound callers select exact retained entity lineages.
        selected_pairs = {
            (claim.project_id, claim.entity_key) for claim in claims if claim.id in _claim_ids
        }
        claims = [
            claim for claim in claims if (claim.project_id, claim.entity_key) in selected_pairs
        ]
    claim_ids = {claim.id for claim in claims}
    links: Sequence[BuyingChainIdentityLink] = []
    corrections: Sequence[BuyingChainCorrection] = []
    if claim_ids and not overflow:
        links = session.scalars(
            select(BuyingChainIdentityLink)
            .where(BuyingChainIdentityLink.claim_id.in_(claim_ids))
            .order_by(BuyingChainIdentityLink.id)
            .limit(MAX_HISTORY_LINKS + 1)
        ).all()
        corrections = session.scalars(
            select(BuyingChainCorrection)
            .where(BuyingChainCorrection.claim_id.in_(claim_ids))
            .order_by(BuyingChainCorrection.id)
            .limit(MAX_HISTORY_LINKS + 1)
        ).all()
    overflow |= len(links) > MAX_HISTORY_LINKS or len(corrections) > MAX_HISTORY_LINKS
    claims_by_id = {claim.id: claim for claim in claims}
    companies: dict[tuple[UUID, str], set[UUID]] = defaultdict(set)
    people: dict[tuple[UUID, str], set[UUID]] = defaultdict(set)
    for link in links[:MAX_HISTORY_LINKS]:
        claim = claims_by_id.get(link.claim_id)
        if claim is None:
            continue
        pair = (claim.project_id, claim.entity_key)
        if link.company_identity_id is not None:
            companies[pair].add(link.company_identity_id)
        if link.person_identity_id is not None:
            people[pair].add(link.person_identity_id)
    ambiguous_pairs = {
        pair
        for pair in companies.keys() | people.keys()
        if len(companies[pair]) > 1 or len(people[pair]) > 1
    }
    correction_values: dict[UUID, list[dict]] = defaultdict(list)
    for correction in corrections[:MAX_HISTORY_LINKS]:
        correction_values[correction.claim_id].append(correction.values or {})
    keys: set[tuple[str, str]] = set()
    owned_methods: dict[UUID, set[tuple[str, str]]] = {}
    names: dict[UUID, set[str]] = {}
    organizations: dict[UUID, set[str]] = {}
    for claim in claims:
        pair = (claim.project_id, claim.entity_key)
        values = correction_values[claim.id]
        names[claim.id] = {
            str(name).strip()
            for name in [claim.person_name, *(value.get("person_name") for value in values)]
            if name
        }
        organizations[claim.id] = {
            str(name).strip()
            for name in [claim.organization, *(value.get("organization") for value in values)]
            if name
        }
        methods = _methods({"public_contacts": claim.public_contacts or []})
        for value in values:
            if value.get("public_contact_value"):
                methods.add(
                    (
                        str(value.get("public_contact_kind") or "general"),
                        str(value["public_contact_value"]),
                    )
                )
        owned_methods[claim.id] = methods
        overflow |= len(methods) > MAX_HISTORY_METHODS
        for company_id in companies[pair]:
            keys.add(("company", company_suppression_key(company_id)))
            if pair in ambiguous_pairs:
                continue
            _add_keys(
                keys,
                (("person", person_suppression_key(company_id, name)) for name in names[claim.id]),
            )
            _add_keys(
                keys,
                (
                    ("method", method_suppression_key(company_id, None, kind, method))
                    for kind, method in methods
                ),
            )
        _add_keys(
            keys,
            (("person", global_person_suppression_key(person_id)) for person_id in people[pair]),
        )
        _add_keys(
            keys,
            (("method", global_method_suppression_key(kind, method)) for kind, method in methods),
        )
    methods_by_card = {id(card): _methods(card) for card in cards}
    record_claims: dict[int, set[UUID]] = {}
    companies_by_card: dict[int, set[UUID]] = {}
    unresolved_by_card: dict[int, set[int]] = defaultdict(set)
    for card in cards:
        card_claims = [claim for claim in claims if claim.project_id in projects_by_card[id(card)]]
        pairs = {(claim.project_id, claim.entity_key) for claim in card_claims}
        for record in _contact_records(card):
            pointer = record.get("claim_id")
            if pointer is None and record.get("id") in {str(claim.id) for claim in card_claims}:
                pointer = record["id"]
            pointer_id = _uuid(pointer)
            pointed = claims_by_id.get(pointer_id) if pointer_id is not None else None
            matching = []
            if pointed is not None and pointed.project_id in projects_by_card[id(card)]:
                matching = [pointed]
            elif pointer:
                unresolved_by_card[id(card)].add(id(record))
            else:
                company = record.get("organization") or record.get("company")
                name = record.get("person") or record.get("person_name") or record.get("name")
                matching = [
                    claim
                    for claim in card_claims
                    if (not company or _same(company, organizations[claim.id]))
                    and (not name or _same(name, names[claim.id]))
                    and (company or (name and len(pairs) == 1))
                ]
                matching_pairs = {(claim.project_id, claim.entity_key) for claim in matching}
                if len(matching_pairs) != 1:
                    matching = []
            record_claims[id(record)] = {claim.id for claim in matching}
            saved_methods = _methods(record)
            for claim in matching:
                if len(owned_methods[claim.id]) <= MAX_HISTORY_METHODS:
                    owned_methods[claim.id].update(saved_methods)
        # A lone retained DB account is an unambiguous scope for older prose
        # that has no claim pointer. Never cross-product unrelated accounts.
        account_ids = set().union(*(companies[pair] for pair in pairs)) if pairs else set()
        if (len(account_ids) == 1 or _contact_tokens_only) and not (pairs & ambiguous_pairs):
            companies_by_card[id(card)] = account_ids
            _add_keys(
                keys,
                (
                    ("method", method_suppression_key(company_id, None, kind, method))
                    for company_id in account_ids
                    for kind, method in methods_by_card[id(card)]
                ),
            )
        for claim in card_claims:
            pair = (claim.project_id, claim.entity_key)
            methods = owned_methods[claim.id]
            overflow |= len(methods) > MAX_HISTORY_METHODS
            if pair in ambiguous_pairs:
                continue
            _add_keys(
                keys,
                (
                    ("method", method_suppression_key(company_id, None, kind, method))
                    for company_id in companies[pair]
                    for kind, method in methods
                ),
            )
    for methods in methods_by_card.values():
        overflow |= len(methods) > MAX_HISTORY_METHODS
        _add_keys(
            keys,
            (("method", global_method_suppression_key(kind, method)) for kind, method in methods),
        )
    overflow |= len(keys) > MAX_HISTORY_KEYS
    states = _ledger_states(session, keys) if not overflow else {}
    for card in cards:
        hidden, hidden_claims, hidden_methods = set(), set(), set()
        card_projects = projects_by_card[id(card)]
        for claim in claims:
            if claim.project_id not in card_projects:
                continue
            pair = (claim.project_id, claim.entity_key)
            ambiguous = pair in ambiguous_pairs
            company_hidden = any(
                states.get(("company", company_suppression_key(company_id))) == "suppress"
                for company_id in companies[pair]
            )
            person_hidden = any(
                states.get(("person", global_person_suppression_key(person_id))) == "suppress"
                for person_id in people[pair]
            ) or any(
                states.get(("person", person_suppression_key(company_id, name))) == "suppress"
                for company_id in companies[pair]
                for name in names[claim.id]
            )
            if company_hidden or person_hidden or ambiguous:
                hidden_claims.add(claim.id)
                hidden.update(names[claim.id])
                if company_hidden:
                    hidden.update(organizations[claim.id])
            for kind, method in owned_methods[claim.id]:
                if (
                    company_hidden
                    or person_hidden
                    or ambiguous
                    or any(
                        states.get(
                            ("method", method_suppression_key(company_id, None, kind, method))
                        )
                        == "suppress"
                        for company_id in companies[pair]
                    )
                ):
                    hidden_methods.add(_method_parts(kind, method))
        card_pairs = {
            (claim.project_id, claim.entity_key)
            for claim in claims
            if claim.project_id in card_projects
        }
        if card_pairs & ambiguous_pairs or hidden_claims:
            # Unattributed contact tokens cannot safely be assigned to one of
            # the conflicting identities. Preserve explicitly owned methods
            # belonging to other unambiguous subjects in this same cohort.
            protected_methods = {
                _method_parts(kind, method)
                for claim in claims
                if claim.project_id in card_projects
                and (claim.project_id, claim.entity_key) not in ambiguous_pairs
                and claim.id not in hidden_claims
                for kind, method in owned_methods[claim.id]
            }
            explicit_profiles = set(_explicit_profiles(card))
            hidden_methods.update(
                _method_parts(kind, method)
                for kind, method in methods_by_card[id(card)]
                if _method_parts(kind, method) not in protected_methods
                and (
                    kind not in {"profile", "website", "url"}
                    or _method_parts(kind, method) in explicit_profiles
                )
            )
        card_companies = companies_by_card.get(id(card), set())
        for kind, method in methods_by_card[id(card)]:
            globally_hidden = (
                states.get(("method", global_method_suppression_key(kind, method))) == "suppress"
            )
            company_method_hidden = any(
                states.get(("method", method_suppression_key(company_id, None, kind, method)))
                == "suppress"
                or states.get(("company", company_suppression_key(company_id))) == "suppress"
                for company_id in card_companies
            )
            if globally_hidden or company_method_hidden:
                hidden_methods.add(_method_parts(kind, method))
            if _method_parts(kind, method) in hidden_methods:
                hidden.add(method)
        hidden_records = {
            record_id for record_id, ids in record_claims.items() if ids & hidden_claims
        }
        # A stored pointer outside the retained project cohort is ambiguous;
        # remove its assertion rather than deriving identity from its labels.
        hidden_records.update(unresolved_by_card[id(card)])
        if overflow and _contact_tokens_only:
            # Permit projections retain engineering facts even if privacy scope
            # exceeds a bound; hide contact tokens and known subject labels.
            hidden.update(
                name
                for claim in claims
                if claim.project_id in card_projects
                for name in names[claim.id] | organizations[claim.id]
            )
        projected = _redact(
            card,
            hidden,
            hidden_claims,
            hidden_methods,
            fail_closed=overflow and not _contact_tokens_only,
            hidden_records=hidden_records,
        )
        if overflow and _contact_tokens_only:
            projected = _redact_all_contact_tokens(projected)
        card.clear()
        card.update(projected)
    if notes_projection is not None:
        result["notes"] = notes_projection["notes"]
    return result
