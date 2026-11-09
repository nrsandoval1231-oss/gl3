"""Read-time privacy projection over immutable saved commercial history."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from copy import deepcopy
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
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
    BuyingChainEvidence,
    BuyingChainIdentityLink,
    ChangeEvent,
    Evidence,
)

MAX_HISTORY_PROJECTS = 64
MAX_HISTORY_CLAIMS = 256
MAX_HISTORY_LINKS = 512
MAX_HISTORY_METHODS = 128
MAX_HISTORY_KEYS = 2048
MAX_CHANGE_EVENTS = 250
_EMAIL = re.compile(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_PHONE = re.compile(r"\+?\d[\d(). \t-]{5,}\d")
_NANP = re.compile(r"(?<!\d)(?:\+?1[ \t.-]?)?(?:\(\d{3}\)|\d{3})[ \t.-]?\d{3}[ \t.-]?\d{4}(?!\d)")
_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_UUID_REFERENCE = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")
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
        "buying_chain_evidence_id",
        "buying_chain_evidence_ids",
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
_SUPPRESSED_ACTION = (
    "Research a replacement source-cited contact; the previously cited contact method was "
    "removed under a privacy suppression."
)


def _target_method_keys(kind: Any, value: str) -> set[tuple[str, str]]:
    """Suppression keys for a typed target.

    Permit summaries label the method ("Contractor phone"), while suppressions are keyed by
    canonical phone/email, so check both the raw label and the canonical type.
    """
    raw = str(kind or "")
    keys = {_method_parts(raw, value)}
    if re.search(r"phone|telephone|\btel\b", raw, re.I):
        keys.add(_method_parts("phone", value))
    if re.search(r"e-?mail", raw, re.I):
        keys.add(_method_parts("email", value))
    return keys


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _is_uuid_evidence_ref(value: Any, key: str) -> bool:
    """Recognize only canonical UUIDs in the structured evidence_refs field."""
    if key != "evidence_refs" or not isinstance(value, str) or not _UUID_REFERENCE.fullmatch(value):
        return False
    try:
        return str(UUID(value)) == value.casefold()
    except ValueError:
        return False


def _strings(value: Any, key: str = ""):
    if isinstance(value, str):
        if _is_uuid_evidence_ref(value, key):
            return
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
        if _is_uuid_evidence_ref(value, key):
            return value
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
        if _is_uuid_evidence_ref(value, key):
            return value
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
        target = value.get("next_action_target")
        if isinstance(target, dict) and isinstance(target.get("value"), str):
            if _target_method_keys(target.get("kind"), target["value"]) & hidden_methods:
                # The call text embeds the suppressed method, so it cannot be partially redacted.
                value = {
                    **value,
                    "next_action_target": None,
                    "next_action_type": "research_question",
                    "next_action": _SUPPRESSED_ACTION,
                }
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
    _validated_event_claim_ids_by_card: dict[int, set[UUID]] | None = None,
    _current_event_claim_ids_by_project: dict[UUID, set[UUID]] | None = None,
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
    validated_claims_by_card: dict[int, set[UUID]] = {id(card): set() for card in cards}
    if _validated_event_claim_ids_by_card is not None:
        for card_index, card in enumerate(cards):
            requested = _validated_event_claim_ids_by_card.get(card_index, set())
            if isinstance(requested, set) and len(requested) <= MAX_HISTORY_CLAIMS:
                validated_claims_by_card[id(card)] = {
                    claim_id for claim_id in requested if isinstance(claim_id, UUID)
                }
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
    claims_by_project_and_id = {(claim.project_id, claim.id) for claim in claims}
    for card in cards:
        validated_claims_by_card[id(card)] = {
            claim_id
            for claim_id in validated_claims_by_card[id(card)]
            if any(
                project_id in projects_by_card[id(card)] and claim_id == candidate_id
                for project_id, candidate_id in claims_by_project_and_id
            )
        }
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
    # A change-event caller may identify the exact claim only after matching
    # its semantic row and same-side source version to the current public view.
    # That proof can tolerate historical superseded aliases, but never active
    # ambiguity, invalid link states, or missing current ownership.
    links_by_pair: dict[tuple[UUID, str], list[BuyingChainIdentityLink]] = defaultdict(list)
    for link in links:
        claim = claims_by_id.get(link.claim_id)
        if claim is not None:
            links_by_pair[(claim.project_id, claim.entity_key)].append(link)
    validated_pairs_by_card: dict[int, set[tuple[UUID, str]]] = {}
    for card in cards:
        validated_pairs: set[tuple[UUID, str]] = set()
        for claim in claims:
            if claim.id not in validated_claims_by_card[id(card)]:
                continue
            pair = (claim.project_id, claim.entity_key)
            if pair not in ambiguous_pairs:
                continue
            pair_links = links_by_pair.get(pair, [])
            if not pair_links or any(
                link.state not in {"current", "superseded"}
                or (link.entity_type == "company" and link.company_identity_id is None)
                or (link.entity_type == "person" and link.person_identity_id is None)
                or link.entity_type not in {"company", "person"}
                for link in pair_links
            ):
                continue
            valid_aliases = True
            current_claim_ids = (
                _current_event_claim_ids_by_project.get(claim.project_id, set())
                if _current_event_claim_ids_by_project is not None
                else set()
            )
            if claim.id not in current_claim_ids:
                continue
            for entity_type in {link.entity_type for link in pair_links}:
                typed_links = [link for link in pair_links if link.entity_type == entity_type]
                current_ids = {
                    (link.company_identity_id, link.person_identity_id)
                    for link in typed_links
                    if link.state == "current" and link.claim_id in current_claim_ids
                }
                proved_ids = {
                    (link.company_identity_id, link.person_identity_id)
                    for link in typed_links
                    if link.state == "current" and link.claim_id == claim.id
                }
                if len(current_ids) != 1 or proved_ids != current_ids:
                    valid_aliases = False
                    break
            if valid_aliases:
                validated_pairs.add(pair)
        validated_pairs_by_card[id(card)] = validated_pairs
    key_ambiguous_pairs = ambiguous_pairs - set().union(*validated_pairs_by_card.values())
    correction_values: dict[UUID, list[dict]] = defaultdict(list)
    for correction in corrections[:MAX_HISTORY_LINKS]:
        correction_values[correction.claim_id].append(correction.values or {})
    keys: set[tuple[str, str]] = set()
    owned_methods: dict[UUID, set[tuple[str, str]]] = {}
    names: dict[UUID, set[str]] = {}
    organizations: dict[UUID, set[str]] = {}
    names_by_pair: dict[tuple[UUID, str], set[str]] = defaultdict(set)
    for claim in claims:
        pair = (claim.project_id, claim.entity_key)
        values = correction_values[claim.id]
        names[claim.id] = {
            str(name).strip()
            for name in [claim.person_name, *(value.get("person_name") for value in values)]
            if name
        }
        names_by_pair[pair].update(names[claim.id])
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
            if pair in key_ambiguous_pairs:
                continue
            _add_keys(
                keys,
                (("person", person_suppression_key(company_id, name)) for name in names[claim.id]),
            )
            _add_keys(
                keys,
                (
                    ("method", method_suppression_key(company_id, name, kind, method))
                    for kind, method in methods
                    for name in {None, *names[claim.id]}
                ),
            )
    for pair, pair_names in names_by_pair.items():
        if pair in key_ambiguous_pairs:
            continue
        for company_id in companies[pair]:
            _add_keys(
                keys,
                (("person", person_suppression_key(company_id, name)) for name in pair_names),
            )
            _add_keys(
                keys,
                (
                    ("method", method_suppression_key(company_id, name, kind, method))
                    for claim in claims
                    if (claim.project_id, claim.entity_key) == pair
                    for kind, method in owned_methods[claim.id]
                    for name in {None, *pair_names}
                ),
            )
        _add_keys(
            keys,
            (("person", global_person_suppression_key(person_id)) for person_id in people[pair]),
        )
        _add_keys(
            keys,
            (
                ("method", global_method_suppression_key(kind, method))
                for claim in claims
                if (claim.project_id, claim.entity_key) == pair
                for kind, method in owned_methods[claim.id]
            ),
        )
    methods_by_card = {id(card): _methods(card) for card in cards}
    record_claims: dict[int, set[UUID]] = {}
    companies_by_card: dict[int, set[UUID]] = {}
    unresolved_by_card: dict[int, set[int]] = defaultdict(set)
    for card in cards:
        card_claims = [claim for claim in claims if claim.project_id in projects_by_card[id(card)]]
        pairs = {(claim.project_id, claim.entity_key) for claim in card_claims}
        card_ambiguous_pairs = ambiguous_pairs - validated_pairs_by_card[id(card)]
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
        if (len(account_ids) == 1 or _contact_tokens_only) and not (pairs & card_ambiguous_pairs):
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
            if pair in card_ambiguous_pairs:
                continue
            _add_keys(
                keys,
                (
                    ("method", method_suppression_key(company_id, name, kind, method))
                    for company_id in companies[pair]
                    for kind, method in methods
                    for name in {None, *names_by_pair[pair]}
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
        card_ambiguous_pairs = ambiguous_pairs - validated_pairs_by_card[id(card)]
        for claim in claims:
            if claim.project_id not in card_projects:
                continue
            pair = (claim.project_id, claim.entity_key)
            ambiguous = pair in card_ambiguous_pairs
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
                for name in names_by_pair[pair]
            )
            if company_hidden or person_hidden or ambiguous:
                hidden_claims.add(claim.id)
                hidden.update(names_by_pair[pair])
                if company_hidden:
                    hidden.update(organizations[claim.id])
            for kind, method in owned_methods[claim.id]:
                if (
                    company_hidden
                    or person_hidden
                    or ambiguous
                    or any(
                        states.get(
                            ("method", method_suppression_key(company_id, name, kind, method))
                        )
                        == "suppress"
                        for company_id in companies[pair]
                        for name in {None, *names_by_pair[pair]}
                    )
                ):
                    hidden_methods.add(_method_parts(kind, method))
        card_pairs = {
            (claim.project_id, claim.entity_key)
            for claim in claims
            if claim.project_id in card_projects
        }
        if card_pairs & card_ambiguous_pairs or hidden_claims:
            # Unattributed contact tokens cannot safely be assigned to one of
            # the conflicting identities. Preserve explicitly owned methods
            # belonging to other unambiguous subjects in this same cohort.
            protected_methods = {
                _method_parts(kind, method)
                for claim in claims
                if claim.project_id in card_projects
                and (claim.project_id, claim.entity_key) not in card_ambiguous_pairs
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


_CHANGE_ROLE_FIELDS = frozenset({"buyer", "contractor"})
_CHANGE_ROW_FIELDS = (
    "organization",
    "person_name",
    "title",
    "category",
    "organization_relationship",
    "person_project_relationship",
)
_CHANGE_ROLE_SUPPORT = frozenset(
    {
        "project_organization",
        "organization_category",
        "organization_person_role",
        "person_project_assignment",
    }
)


def project_change_events_public(
    session: Session,
    entries: Sequence[tuple[ChangeEvent, dict[str, Any], str, str]],
    *,
    include_source_ids: bool = False,
) -> list[dict[str, Any] | None]:
    """Privacy-project copied change events without modifying their stored history.

    Buyer/contractor rows are displayable only when the exact original row and
    its same-side source version still occur in the current public projection.
    A new-side source never authenticates an unbound prior snapshot.
    """
    if not entries:
        return []
    if len(entries) > MAX_CHANGE_EVENTS:
        return [None for _ in entries]
    valid_entries = []
    valid_positions = []
    for index, entry in enumerate(entries):
        if (
            not isinstance(entry, tuple)
            or len(entry) != 4
            or not isinstance(entry[0], ChangeEvent)
            or not isinstance(entry[1], dict)
            or not isinstance(entry[2], str)
            or not isinstance(entry[3], str)
        ):
            continue
        event, item, before_key, after_key = entry
        if (event.field_name or "").casefold() not in _CHANGE_ROLE_FIELDS:
            valid_entries.append(entry)
            valid_positions.append(index)
            continue
        source_rows = item.get("sources", [])
        if not isinstance(source_rows, list) or len(source_rows) > MAX_HISTORY_METHODS:
            continue
        malformed = False
        for state in (
            item.get(before_key),
            item.get(after_key),
            event.prior_state,
            event.new_state,
        ):
            if state is None:
                continue
            if not isinstance(state, dict) or not isinstance(state.get("value"), list):
                malformed = True
                break
            if len(state["value"]) > MAX_HISTORY_CLAIMS or any(
                not isinstance(row, dict)
                or any(
                    row.get(key) is not None and not isinstance(row.get(key), str)
                    for key in _CHANGE_ROW_FIELDS
                )
                for row in state["value"]
            ):
                malformed = True
                break
            if "buying_chain_evidence_ids" in state:
                ids = state["buying_chain_evidence_ids"]
                if (
                    not isinstance(ids, list)
                    or len(ids) > MAX_HISTORY_METHODS
                    or any(_uuid(value) is None for value in ids)
                ):
                    malformed = True
                    break
        if not malformed:
            valid_entries.append(entry)
            valid_positions.append(index)

    if len(valid_entries) != len(entries):
        result: list[dict[str, Any] | None] = [None for _ in entries]
        if valid_entries:
            valid_results = project_change_events_public(
                session,
                valid_entries,
                include_source_ids=include_source_ids,
            )
            for index, value in zip(valid_positions, valid_results, strict=True):
                result[index] = value
        return result

    project_ids = {event.project_id for event, _, _, _ in entries if event.project_id is not None}
    if len(project_ids) > MAX_HISTORY_PROJECTS:
        return [None for _ in entries]

    from gridlens.intelligence.buying_chain import buying_chain_views

    views = buying_chain_views(session, project_ids) if project_ids else {}
    claims_by_project: dict[UUID, list[BuyingChainClaim]] = defaultdict(list)
    claims: Sequence[BuyingChainClaim] = []
    overflow_projects: set[UUID] = set()
    if project_ids:
        ranked_claim_ids = (
            select(
                BuyingChainClaim.id.label("claim_id"),
                BuyingChainClaim.project_id.label("project_id"),
                func.row_number()
                .over(
                    partition_by=BuyingChainClaim.project_id,
                    order_by=BuyingChainClaim.id,
                )
                .label("row_number"),
            )
            .where(BuyingChainClaim.project_id.in_(project_ids))
            .subquery()
        )
        claims = session.scalars(
            select(BuyingChainClaim)
            .join(ranked_claim_ids, ranked_claim_ids.c.claim_id == BuyingChainClaim.id)
            .where(ranked_claim_ids.c.row_number <= MAX_HISTORY_CLAIMS + 1)
            .order_by(ranked_claim_ids.c.project_id, BuyingChainClaim.id)
        ).all()
        for claim in claims:
            claims_by_project[claim.project_id].append(claim)

    overflow_projects.update(
        project_id
        for project_id, rows in claims_by_project.items()
        if len(rows) > MAX_HISTORY_CLAIMS
    )
    claim_ids = {claim.id for claim in claims}
    corrections_by_claim: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    if claim_ids:
        ranked_correction_ids = (
            select(
                BuyingChainCorrection.id.label("correction_id"),
                BuyingChainClaim.project_id.label("project_id"),
                func.row_number()
                .over(
                    partition_by=BuyingChainClaim.project_id,
                    order_by=BuyingChainCorrection.id,
                )
                .label("row_number"),
            )
            .join(BuyingChainClaim, BuyingChainClaim.id == BuyingChainCorrection.claim_id)
            .where(BuyingChainCorrection.claim_id.in_(claim_ids))
            .subquery()
        )
        corrections = session.scalars(
            select(BuyingChainCorrection)
            .join(
                ranked_correction_ids,
                ranked_correction_ids.c.correction_id == BuyingChainCorrection.id,
            )
            .where(ranked_correction_ids.c.row_number <= MAX_HISTORY_LINKS + 1)
            .order_by(ranked_correction_ids.c.project_id, BuyingChainCorrection.id)
        ).all()
        corrections_by_project: dict[UUID, int] = defaultdict(int)
        claims_by_id = {claim.id: claim for claim in claims}
        for correction in corrections:
            correction_claim = claims_by_id.get(correction.claim_id)
            if correction_claim is None:
                continue
            corrections_by_project[correction_claim.project_id] += 1
            corrections_by_claim[correction_claim.id].append(correction.values or {})
        overflow_projects.update(
            project_id
            for project_id, count in corrections_by_project.items()
            if count > MAX_HISTORY_LINKS
        )

    from gridlens.intelligence.buying_chain import has_public_research_provenance

    projected: list[dict[str, Any] | None] = []
    privacy_cards: dict[UUID, list[int]] = defaultdict(list)
    validated_claim_ids_by_index: dict[int, set[UUID]] = {}
    source_claims_by_index: dict[int, dict[str, set[str]]] = {}
    row_claims_by_index: dict[int, dict[str, list[str]]] = {}
    for event, original, before_key, after_key in entries:
        project_id = event.project_id
        if project_id is not None and project_id in overflow_projects:
            projected.append(None)
            continue

        item = deepcopy(original)
        view = views.get(str(project_id), {}) if project_id is not None else {}
        candidates = [
            candidate for candidate in view.get("candidates", []) if not candidate.get("stale")
        ]
        authorized_names = {
            str(candidate["person_name"]).strip()
            for candidate in candidates
            if candidate.get("person_name")
        }
        authorized_titles = {
            str(candidate["title"]).strip() for candidate in candidates if candidate.get("title")
        }
        hidden_names: set[str] = set()
        hidden_titles: set[str] = set()
        rejected_names: set[str] = set()
        rejected_titles: set[str] = set()
        validated_event_claim_ids: set[UUID] = set()
        validated_event_methods: list[dict[str, Any]] = []
        source_claims: dict[str, set[str]] = defaultdict(set)
        row_claims: dict[str, list[str]] = {}
        project_claims = claims_by_project.get(project_id, []) if project_id is not None else []
        for claim in project_claims:
            if claim.person_name and claim.person_name.strip() not in authorized_names:
                hidden_names.add(claim.person_name.strip())
            if claim.title and claim.title.strip() not in authorized_titles:
                hidden_titles.add(claim.title.strip())
            for correction_values in corrections_by_claim.get(claim.id, []):
                person_name = correction_values.get("person_name")
                title = correction_values.get("title")
                if isinstance(person_name, str) and person_name.strip() not in authorized_names:
                    hidden_names.add(person_name.strip())
                if isinstance(title, str) and title.strip() not in authorized_titles:
                    hidden_titles.add(title.strip())

        is_role_event = (event.field_name or "").casefold() in _CHANGE_ROLE_FIELDS
        if is_role_event:
            event_source_ids: set[str] = set()
            if event.buying_chain_evidence_id is not None:
                event_source_ids.add(str(event.buying_chain_evidence_id))
            new_state = event.new_state if isinstance(event.new_state, dict) else {}
            listed_ids = new_state.get("buying_chain_evidence_ids", [])
            if isinstance(listed_ids, list) and len(listed_ids) <= MAX_HISTORY_METHODS:
                event_source_ids.update(str(value) for value in listed_ids)
            else:
                event_source_ids.clear()

            source_by_id = {}
            parsed_ids = []
            source_lookup_ids = set(event_source_ids)
            for state_key in (before_key, after_key):
                state = item.get(state_key)
                raw_ids = (
                    state.get("buying_chain_evidence_ids", []) if isinstance(state, dict) else []
                )
                if isinstance(raw_ids, list) and len(raw_ids) <= MAX_HISTORY_METHODS:
                    source_lookup_ids.update(str(value) for value in raw_ids)
            if len(source_lookup_ids) > MAX_HISTORY_METHODS:
                source_lookup_ids.clear()
            for raw in source_lookup_ids:
                try:
                    parsed_ids.append(UUID(raw))
                except (TypeError, ValueError, AttributeError):
                    parsed_ids = []
                    break
            if parsed_ids:
                source_by_id = {
                    str(source.id): source
                    for source in session.scalars(
                        select(BuyingChainEvidence).where(BuyingChainEvidence.id.in_(parsed_ids))
                    )
                }

            def source_refs_for(
                state: Any,
                *,
                new_side: bool,
                candidate_rows: list[dict] = candidates,
                new_side_ids: set[str] = event_source_ids,
                source_rows: dict = source_by_id,
                project_key: UUID | None = project_id,
                rejected_name_tokens: set[str] = rejected_names,
                rejected_title_tokens: set[str] = rejected_titles,
                validated_ids: set[UUID] = validated_event_claim_ids,
                validated_methods: list[dict[str, Any]] = validated_event_methods,
                source_bindings: dict[str, set[str]] = source_claims,
            ) -> dict[str, tuple[str, str]]:
                if not isinstance(state, dict):
                    return {}
                if not isinstance(state.get("value"), list):
                    state["value"] = []
                    return {}
                side_ids: set[str] = set()
                if new_side:
                    side_ids = set(new_side_ids)
                else:
                    raw_ids = state.get("buying_chain_evidence_ids", [])
                    if isinstance(raw_ids, list) and len(raw_ids) <= MAX_HISTORY_METHODS:
                        side_ids = {str(value) for value in raw_ids}
                    else:
                        return {}
                accepted: dict[str, tuple[str, str]] = {}
                kept_rows: list[dict[str, Any]] = []
                for row in state["value"]:
                    if not isinstance(row, dict):
                        continue
                    semantic = tuple(row.get(key) for key in _CHANGE_ROW_FIELDS)
                    matches = [
                        candidate
                        for candidate in candidate_rows
                        if tuple(candidate.get(key) for key in _CHANGE_ROW_FIELDS) == semantic
                    ]
                    if len(matches) != 1:
                        if row.get("person_name"):
                            rejected_name_tokens.add(str(row["person_name"]).strip())
                        if row.get("title"):
                            rejected_title_tokens.add(str(row["title"]).strip())
                        continue
                    candidate = matches[0]
                    person_scoped = bool(row.get("person_name"))
                    needed_supports = (
                        {"organization_person_role", "person_project_assignment"}
                        if person_scoped
                        else _CHANGE_ROLE_SUPPORT
                    )
                    citations = candidate.get("evidence", [])
                    facts = []
                    if isinstance(citations, list):
                        for citation in citations:
                            if not isinstance(citation, dict):
                                continue
                            source_id = str(citation.get("id") or "")
                            if (
                                source_id not in side_ids
                                or source_id != str(citation.get("current_source_version_id") or "")
                                or not citation.get("current_support")
                                or citation.get("supports") not in needed_supports
                            ):
                                continue
                            source = source_rows.get(source_id)
                            source_hash = str(citation.get("content_hash") or "")
                            source_url = str(citation.get("url") or "")
                            if (
                                source is None
                                or source.project_id != project_key
                                or source.content_hash != source_hash
                                or source.url != source_url
                            ):
                                continue
                            facts.append((source_id, source_url, source_hash))
                    if not facts:
                        if row.get("person_name"):
                            rejected_name_tokens.add(str(row["person_name"]).strip())
                        if row.get("title"):
                            rejected_title_tokens.add(str(row["title"]).strip())
                        continue
                    candidate_id = _uuid(candidate.get("id"))
                    if candidate_id is not None:
                        validated_ids.add(candidate_id)
                    contacts = candidate.get("public_contacts", [])
                    if isinstance(contacts, list):
                        validated_methods.extend(
                            contact for contact in contacts if isinstance(contact, dict)
                        )
                    for source_id, source_url, source_hash in facts:
                        accepted[source_id] = (source_url, source_hash)
                        source_bindings[source_id].add(str(candidate_id))
                    # These copied records retain claim ownership through the
                    # generic privacy wrapper; neither these pointers nor any
                    # serialized field can grant the private lineage exception.
                    kept_rows.append({**row, "claim_id": str(candidate_id)})
                state["value"] = kept_rows
                return accepted

            # Prior state has no causal evidence pointers in current records;
            # it therefore fails closed unless its own original side carries IDs.
            before_state = item.get(before_key)
            after_state = item.get(after_key)
            before_sources = source_refs_for(before_state, new_side=False)
            after_sources = source_refs_for(after_state, new_side=True)
            allowed_sources = before_sources | after_sources
            original_rows = [
                row
                for state in (event.prior_state, event.new_state)
                if isinstance(state, dict) and isinstance(state.get("value"), list)
                for row in state["value"]
                if isinstance(row, dict)
            ]
            original_organization_rows = {
                tuple(row.get(key) for key in _CHANGE_ROW_FIELDS)
                for row in original_rows
                if not row.get("person_name") and not row.get("title")
            }
            # Pure organization-history sources can establish causal project
            # provenance even when a withdrawal means no current relationship
            # candidate cites that document. They cannot restore a role row.
            event_org_sources: dict[str, tuple[str, str]] = {}
            organization_provenance_claims: dict[UUID, BuyingChainClaim] = {}
            for source_id in event_source_ids:
                source = source_by_id.get(source_id)
                if source is None or source.project_id != project_id:
                    continue
                source_claims_in_history = [
                    claim
                    for claim in project_claims
                    if isinstance(claim.citations, list)
                    and any(
                        isinstance(citation, dict) and citation.get("url") == source.url
                        for citation in claim.citations
                    )
                ]
                # A generic person/contact source cannot come back through
                # organization provenance, even if a particular event side
                # happens to omit its person row. Historical URL lineages cover
                # withdrawal versions that intentionally have no current claim.
                if not source_claims_in_history or any(
                    claim.person_name
                    or claim.title
                    or claim.public_contacts
                    or any(
                        isinstance(citation, dict)
                        and citation.get("url") == source.url
                        and citation.get("supports")
                        in {
                            "organization_person_role",
                            "person_project_assignment",
                            "public_contact",
                            "permit_listed_contact",
                        }
                        for citation in claim.citations
                    )
                    for claim in source_claims_in_history
                ):
                    continue
                if not any(
                    tuple(getattr(claim, key) for key in _CHANGE_ROW_FIELDS)
                    in original_organization_rows
                    for claim in source_claims_in_history
                ):
                    continue
                valid_source = has_public_research_provenance(source)
                if source.retained_evidence_id is not None:
                    from gridlens.intelligence.company_contact_attribution import (
                        _source_hash_is_current,
                    )

                    retained_source = session.get(Evidence, source.retained_evidence_id)
                    valid_source = bool(
                        retained_source is not None
                        and source.url == retained_source.url
                        and source.excerpt
                        == f"{retained_source.title}\n{retained_source.abstract or ''}"
                        and _source_hash_is_current(
                            source, retained_version=retained_source.content_hash
                        )
                    )
                if valid_source:
                    event_org_sources[source_id] = (source.url, source.content_hash)
                    for claim in source_claims_in_history:
                        organization_provenance_claims[claim.id] = claim
                        source_claims[source_id].add(str(claim.id))
            allowed_sources.update(event_org_sources)
            item["sources"] = [
                source
                for source in item.get("sources", [])
                if isinstance(source, dict)
                and str(source.get("id") or "") in allowed_sources
                and source.get("url") == allowed_sources[str(source.get("id"))][0]
                and (
                    "content_hash" not in source
                    or source.get("content_hash") == allowed_sources[str(source.get("id"))][1]
                )
            ]
            if validated_event_methods:
                # Existing saved-history privacy uses structured methods to
                # apply company/person/global controls across historical aliases.
                # This temporary field is removed after that projection.
                item["public_contacts"] = validated_event_methods
            bound_contacts = []
            for claim in organization_provenance_claims.values():
                bound_contacts.append(
                    {
                        "claim_id": str(claim.id),
                        "organization": claim.organization,
                        "sources": [
                            source
                            for source in item["sources"]
                            if str(claim.id) in source_claims.get(str(source.get("id")), set())
                        ],
                    }
                )
            for state_key in (before_key, after_key):
                state = item.get(state_key)
                rows = state.get("value") if isinstance(state, dict) else None
                if not isinstance(rows, list):
                    continue
                row_claims[state_key] = [str(row.get("claim_id")) for row in rows]
                for row in rows:
                    bound_contacts.append(
                        {
                            **row,
                            "sources": [
                                source
                                for source in item["sources"]
                                if str(row.get("claim_id"))
                                in source_claims.get(str(source.get("id")), set())
                            ],
                        }
                    )
            item["contacts"] = bound_contacts
            validated_claim_ids_by_index[len(projected)] = validated_event_claim_ids
            source_claims_by_index[len(projected)] = dict(source_claims)
            row_claims_by_index[len(projected)] = row_claims

        event_rows: list[dict[str, Any]] = []
        for state_key in (before_key, after_key):
            state = item.get(state_key)
            values = state.get("value") if isinstance(state, dict) else None
            if isinstance(values, list):
                event_rows.extend(row for row in values if isinstance(row, dict))
        event_names = {
            str(row["person_name"]).strip() for row in event_rows if row.get("person_name")
        }
        event_titles = {str(row["title"]).strip() for row in event_rows if row.get("title")}
        hidden_names.difference_update(event_names)
        hidden_titles.difference_update(event_titles)
        hidden_names.update(rejected_names - event_names)
        hidden_titles.update(rejected_titles - event_titles)

        hidden = hidden_names | hidden_titles
        return_item = _redact(item, hidden, set(), set()) if hidden else item
        projected.append(return_item)
        if project_id is not None:
            privacy_cards[project_id].append(len(projected) - 1)

    # Batch the existing saved-history alias/suppression projector once per
    # bounded project cohort instead of issuing one history query per event.
    for project_id, indexes in privacy_cards.items():
        local_validated_claim_ids: dict[int, set[UUID]] = {}
        for card_index, projected_index in enumerate(indexes):
            local_validated_claim_ids[card_index] = validated_claim_ids_by_index.get(
                projected_index, set()
            )
        wrapped = {
            "project_id": str(project_id),
            "versions": [{"saved_card": projected[index]} for index in indexes],
        }
        sanitized = project_saved_history_privacy(
            session,
            wrapped,
            _validated_event_claim_ids_by_card=local_validated_claim_ids,
            _current_event_claim_ids_by_project={
                project_id: {
                    claim_id
                    for candidate in views.get(str(project_id), {}).get("candidates", [])
                    if not candidate.get("stale")
                    and (claim_id := _uuid(candidate.get("id"))) is not None
                },
            },
        )
        versions = sanitized.get("versions", [])
        if len(versions) != len(indexes):
            for index in indexes:
                projected[index] = None
            continue
        for index, version in zip(indexes, versions, strict=True):
            if not isinstance(version, dict) or not isinstance(version.get("saved_card"), dict):
                projected[index] = None
            else:
                saved_card = version["saved_card"]
                saved_card.pop("public_contacts", None)
                visible_claims = {
                    str(record.get("claim_id"))
                    for record in saved_card.pop("contacts", [])
                    if isinstance(record, dict)
                }
                for state_key in ("prior", "new", "before_state", "after_state"):
                    state = saved_card.get(state_key)
                    rows = state.get("value") if isinstance(state, dict) else None
                    if not isinstance(rows, list):
                        continue
                    if state_key in row_claims_by_index.get(index, {}):
                        state["value"] = [
                            {key: value for key, value in row.items() if key != "claim_id"}
                            for row in rows
                            if isinstance(row, dict) and str(row.get("claim_id")) in visible_claims
                        ]
                source_bindings = source_claims_by_index.get(index, {})
                if source_bindings:
                    saved_card["sources"] = [
                        source
                        for source in saved_card.get("sources", [])
                        if not isinstance(source, dict)
                        or str(source.get("id") or "") not in source_bindings
                        or bool(source_bindings[str(source.get("id"))] & visible_claims)
                    ]
                projected[index] = _redact_all_contact_tokens(saved_card)
    if not include_source_ids:
        for final_item in projected:
            if isinstance(final_item, dict) and isinstance(final_item.get("sources"), list):
                for source in final_item["sources"]:
                    if isinstance(source, dict):
                        source.pop("id", None)
    return projected
