"""One bounded selected-project enrichment pass. No queue, tier or outreach changes."""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from gridlens.domain.buying_chain import (
    CATEGORY_PRIORITY,
    MAX_CANDIDATES,
    MAX_DOCUMENTS,
    MAX_SOURCE_URLS,
    POLICY_VERSION,
    ROLE_MAX_AGE_DAYS,
)
from gridlens.ingestion.adapters.buying_chain_public import (
    PublicDocument,
    retrieve,
    validate_public_url,
)
from gridlens.ingestion.adapters.retained_permits import GEORGIA, chicago_contacts, georgia_identity
from gridlens.ingestion.adapters.retained_permits import facts as permit_facts
from gridlens.intelligence.buying_chain_extraction import (
    Extracted,
    document_content_hash,
    document_key,
    extract_organizations,
    extract_people,
    extract_retained_permit_organizations,
    organization_key,
    project_document_match,
)
from gridlens.intelligence.project_identity import normalized_identity
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainEvidence,
    BuyingChainRun,
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)

MAX_SECONDS = 35


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _accepted_version(interpretation: Interpretation | None, evidence: Evidence) -> bool:
    if interpretation is None or not interpretation.assessment:
        return False
    assessment = interpretation.assessment
    # Processing failure/pending is not a new factual decision. The ingestion
    # service deliberately keeps the last accepted, evidence-bound assessment.
    accepted = interpretation.status == "accepted" or (
        interpretation.status in {"failed", "pending"} and assessment.get("decision") == "accepted"
    )
    return accepted and assessment.get("evidence_hash") == evidence.content_hash


def _retained(session: Session, project: Project) -> list[Evidence]:
    observations = (
        select(NeedObservation.observation_id)
        .join(
            PowerNeed,
            PowerNeed.id == NeedObservation.need_id,
        )
        .where(PowerNeed.project_id == project.id)
    )
    rows = session.execute(
        select(Evidence, Interpretation)
        .join(Observation, Observation.id == Evidence.observation_id)
        .outerjoin(Interpretation, Interpretation.observation_id == Observation.id)
        .where(
            or_(
                Observation.id.in_(observations),
                (Observation.source_id == project.source_id)
                & (Observation.external_id == project.external_id),
            )
        )
        .order_by(Evidence.observed_at.desc(), Evidence.id)
        .limit(24)
    ).all()
    # Only the currently accepted evidence version can introduce relationships.
    return [
        evidence for evidence, interpretation in rows if _accepted_version(interpretation, evidence)
    ][:4]


def _store_document(
    session: Session,
    project: Project,
    doc: PublicDocument,
    reason: str,
    retained_id: UUID | None = None,
    *,
    seen_at: datetime,
) -> BuyingChainEvidence:
    digest = document_content_hash(doc)
    existing = session.scalar(
        select(BuyingChainEvidence).where(
            BuyingChainEvidence.project_id == project.id,
            BuyingChainEvidence.url == doc.url,
            BuyingChainEvidence.content_hash == digest,
        )
    )
    if existing:
        # Preserve first-observed time, content hash and excerpt on unchanged replay.
        existing.last_seen_at = max(existing.last_seen_at, seen_at)
        return existing
    row = BuyingChainEvidence(
        project_id=project.id,
        retained_evidence_id=retained_id,
        url=doc.url,
        title=doc.title,
        excerpt=doc.text,
        content_hash=digest,
        extraction_location=doc.extraction_location,
        published_at=doc.published_at,
        observed_at=doc.observed_at,
        last_seen_at=seen_at,
        project_match_reason=reason,
    )
    session.add(row)
    session.flush()
    return row


def _entity_key(item: Extracted) -> str:
    return _hash(
        [
            organization_key(item.organization),
            normalized_identity(item.person_name),
            item.category if item.person_name is None else "person",
        ]
    )


def _deduplicate(items: list[Extracted]) -> list[Extracted]:
    grouped: dict[str, Extracted] = {}
    for item in items:
        key = _entity_key(item)
        prior = grouped.get(key)
        if prior is None:
            grouped[key] = item
            continue
        different = (
            normalized_identity(prior.title) != normalized_identity(item.title)
            or prior.organization_relationship != item.organization_relationship
            or prior.person_organization_relationship != item.person_organization_relationship
            or prior.person_project_relationship != item.person_project_relationship
        )
        if different:
            prior.person_project_relationship = "UNKNOWN"
            if prior.person_name:
                prior.person_organization_relationship = "UNKNOWN"
            if prior.organization_relationship != item.organization_relationship:
                prior.organization_relationship = "UNKNOWN"
            prior.evidence_strength = "Low"
            prior.reason = (
                "Conflicting relationship or title evidence; current responsibility is UNKNOWN."
            )
        for citation in item.citations:
            if citation not in prior.citations:
                prior.citations.append(citation)
        for contact in item.public_contacts:
            if contact not in prior.public_contacts:
                prior.public_contacts.append(contact)
    return sorted(
        grouped.values(),
        key=lambda item: (
            CATEGORY_PRIORITY.get(item.category, 99),
            item.person_name is None,
            organization_key(item.organization),
            item.person_name or "",
        ),
    )


def _retain_unchecked_assignments(
    session: Session,
    project_id: UUID,
    candidates: list[Extracted],
    saved: dict[str, BuyingChainEvidence],
    retrieved_urls: set[str],
    now: datetime,
) -> None:
    """A source outage cannot retract a still-valid explicit person assignment.

    Merge only an unchanged, independently current role with a previously direct
    assignment that the normal view still validates for freshness and conflicts.
    Different titles, UNKNOWN roles and successfully retracted sources never qualify.
    """
    prior_view = buying_chain_view(session, project_id, now=now)
    prior_candidates = {str(item["id"]): item for item in prior_view["candidates"]}
    for prior_id, previous in prior_candidates.items():
        if previous["person_project_relationship"] != "DIRECT":
            continue
        prior = session.get(BuyingChainClaim, UUID(prior_id))
        if prior is None:
            continue
        for item in candidates:
            if (
                _entity_key(item) != prior.entity_key
                or normalized_identity(item.title) != normalized_identity(prior.title)
                or item.person_organization_relationship != "CURRENT"
                or item.organization_relationship != "DIRECT"
                or item.person_project_relationship != "ROLE_SUPPORTED"
            ):
                continue
            assignments = [
                citation
                for citation in prior.citations
                if citation["supports"] == "person_project_assignment"
                and citation["url"] not in retrieved_urls
            ]
            if not assignments:
                continue
            for citation in assignments:
                evidence = session.get(BuyingChainEvidence, UUID(citation["evidence_id"]))
                if evidence is None:
                    continue
                key = evidence.url + ":" + evidence.content_hash
                saved[key] = evidence
                retained_citation = {
                    **{key: value for key, value in citation.items() if key != "evidence_id"},
                    "document_key": key,
                }
                if retained_citation not in item.citations:
                    item.citations.append(retained_citation)
            item.person_project_relationship = "DIRECT"
            item.evidence_strength = "High"
            item.reason = (
                "Previously explicit assignment retained while its source is unchecked; "
                "the same current role is supported. Purchasing authority remains unverified."
            )


def enrich_buying_chain(
    session: Session,
    project_id: UUID,
    *,
    source_urls: list[str] | None = None,
    fetcher: Callable[[str], PublicDocument] = retrieve,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    # Lock one project during this bounded pass to serialize replay without another queue.
    project = session.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise LookupError("Project not found")
    if len(source_urls or []) > MAX_SOURCE_URLS:
        raise ValueError("At most four additional public source URLs are allowed")
    supplied = [validate_public_url(url) for url in source_urls or []]
    previous_run = session.scalar(
        select(BuyingChainRun)
        .where(
            BuyingChainRun.project_id == project.id,
        )
        .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
    )
    started = time.monotonic()
    deadline = started + MAX_SECONDS
    unresolved: list[str] = []
    documents: list[tuple[PublicDocument, bool, str, UUID | None]] = []
    for evidence in _retained(session, project):
        documents.append(
            (
                PublicDocument(
                    evidence.url,
                    evidence.title,
                    f"{evidence.title}\n{evidence.abstract or ''}",
                    evidence.published_at,
                    evidence.observed_at,
                    evidence.extraction_location,
                    retained_version=evidence.content_hash,
                ),
                True,
                "Previously accepted evidence linked to this selected physical project.",
                evidence.id,
            )
        )
    urls: list[str] = []
    retained_permit = project.source_id == "chicago-building-permits" and any(
        chicago_contacts(doc.text) for doc, _, _, _ in documents
    )
    retained_permit = retained_permit or (
        project.source_id == GEORGIA
        and any(georgia_identity(doc.text) for doc, _, _, _ in documents)
    )
    if retained_permit:
        # The ordinary permit worker refreshes these accepted fields. A redundant
        # network round trip must not be required to make retained evidence useful.
        pass
    elif project.source_id == "chicago-building-permits" and project.external_id.isdigit():
        registered_source = session.get(Source, project.source_id)
        if registered_source and registered_source.endpoint.startswith(
            "https://data.cityofchicago.org/resource/"
        ):
            urls.append(
                registered_source.endpoint.split("?")[0]
                + "?"
                + urlencode(
                    {
                        "$where": f"id='{project.external_id}'",
                        "$limit": 1,
                    }
                )
            )
    else:
        urls.extend(doc.url for doc, _, _, _ in documents[:2])
    urls.extend(supplied)
    # Recheck previously supported role sources within the same small fetch bound.
    if previous_run:
        for evidence_id in previous_run.evidence_ids:
            previous_evidence = session.get(BuyingChainEvidence, UUID(evidence_id))
            if (
                previous_evidence
                and previous_evidence.retained_evidence_id is None
                and not (
                    retained_permit and previous_evidence.url in {d.url for d, _, _, _ in documents}
                )
            ):
                urls.append(previous_evidence.url)
    urls = list(dict.fromkeys(urls))
    checked_urls: set[str] = set()
    retrieval_failed = False
    # Network budget is independent of retained-document count.
    while urls and len(checked_urls) < MAX_DOCUMENTS and len(documents) < MAX_DOCUMENTS:
        if time.monotonic() - started >= MAX_SECONDS:
            retrieval_failed = True
            unresolved.append("Public research stopped at the 35-second elapsed-time limit.")
            break
        url = urls.pop(0)
        if url in checked_urls:
            continue
        checked_urls.add(url)
        try:
            doc = retrieve(url, deadline=deadline) if fetcher is retrieve else fetcher(url)
            validate_public_url(doc.url)
            matched, reason = project_document_match(project, doc)
            documents.append((doc, matched, reason, None))
            # Only same-host, relevant links found on a scoped document. No crawl expansion.
            if matched:
                urls.extend(
                    link for link in doc.links if link not in checked_urls and link not in urls
                )
        except Exception as exc:
            retrieval_failed = True
            # Never include exception text, credentials, response bodies or stack traces in API.
            unresolved.append(f"Public retrieval unavailable for {url}: {type(exc).__name__}.")
    research_incomplete = retrieval_failed or bool(urls)
    if urls:
        unresolved.append(
            "Public research reached its time or document bound; some sources remain unchecked."
        )
    retrieved_by_url = {doc.url: doc for doc, _, _, retained_id in documents if retained_id is None}
    organizations: list[Extracted] = []
    saved: dict[str, BuyingChainEvidence] = {}
    for doc, matched, reason, retained_id in documents:
        if matched:
            row = _store_document(
                session,
                project,
                doc,
                reason,
                retained_id,
                seen_at=doc.observed_at if retained_id else now,
            )
            saved[document_key(doc)] = row
            if retained_id:
                original = session.get(Evidence, retained_id)
                observation = (
                    session.get(Observation, original.observation_id) if original else None
                )
                if observation:
                    organizations.extend(
                        extract_retained_permit_organizations(doc, observation.source_id)
                    )
            organizations.extend(extract_organizations(doc, project))
    organizations = _deduplicate(organizations)
    people: list[Extracted] = []
    for doc, matched, reason, retained_id in documents:
        results = extract_people(
            doc, organizations, project, project_scoped=matched, today=now.date()
        )
        if results:
            row = _store_document(
                session,
                project,
                doc,
                reason
                if matched
                else "Organization-role source only; no person-project assignment inferred.",
                retained_id,
                seen_at=doc.observed_at if retained_id else now,
            )
            saved[document_key(doc)] = row
            people.extend(results)
        elif not matched:
            # A successfully rechecked known role page can retract a role. Retain
            # its changed version even when it now has no extractable relationship.
            known_source = session.scalar(
                select(BuyingChainEvidence.id)
                .where(
                    BuyingChainEvidence.project_id == project.id,
                    BuyingChainEvidence.url == doc.url,
                )
                .limit(1)
            )
            if known_source is not None:
                row = _store_document(
                    session,
                    project,
                    doc,
                    "Previously supported source rechecked; no supported relationship remains.",
                    retained_id,
                    seen_at=doc.observed_at if retained_id else now,
                )
                saved[document_key(doc)] = row
            unresolved.append(
                f"No supported project or relevant role relationship extracted from {doc.url}."
            )
    candidates = _deduplicate([*organizations, *people])
    if previous_run and research_incomplete:
        _retain_unchecked_assignments(
            session, project.id, candidates, saved, set(retrieved_by_url), now
        )
    if len(candidates) > MAX_CANDIDATES:
        unresolved.append(
            "Eight-candidate result limit reached; lower-priority relationships were not added."
        )
    candidates = candidates[:MAX_CANDIDATES]
    added = 0
    current_claim_ids = []
    for item in candidates:
        citations = []
        for citation in item.citations:
            source = saved[citation["document_key"]]
            if citation["quote"] not in source.excerpt:
                raise ValueError("Citation does not match retained evidence version")
            citations.append(
                {
                    **{k: v for k, v in citation.items() if k != "document_key"},
                    "evidence_id": str(source.id),
                }
            )
        state: dict[str, Any] = {
            "policy_version": POLICY_VERSION,
            "organization": item.organization,
            "person_name": item.person_name,
            "title": item.title,
            "category": item.category,
            "organization_relationship": item.organization_relationship,
            "person_organization_relationship": item.person_organization_relationship,
            "person_project_relationship": item.person_project_relationship,
            "evidence_strength": item.evidence_strength,
            "reason": item.reason,
            "citations": sorted(citations, key=lambda c: (c["url"], c["supports"], c["quote"])),
            "public_contacts": item.public_contacts,
        }
        fingerprint = _hash(
            {
                **state,
                "public_contacts": [
                    {key: value for key, value in contact.items() if key != "observed_at"}
                    for contact in state["public_contacts"]
                ],
            }
        )
        existing_claim = session.scalar(
            select(BuyingChainClaim).where(
                BuyingChainClaim.project_id == project.id,
                BuyingChainClaim.fingerprint == fingerprint,
            )
        )
        if existing_claim:
            current_claim_ids.append(str(existing_claim.id))
            continue
        evidence_times = [
            saved[citation["document_key"]].observed_at for citation in item.citations
        ]
        new_claim = BuyingChainClaim(
            project_id=project.id,
            entity_key=_entity_key(item),
            fingerprint=fingerprint,
            **state,
            observed_at=max(evidence_times),
            verified_at=now if item.organization_relationship == "DIRECT" else None,
        )
        session.add(new_claim)
        session.flush()
        current_claim_ids.append(str(new_claim.id))
        added += 1
    if not candidates:
        unresolved.append("No explicit buying-chain relationship found; buyer remains UNKNOWN.")
    if not any(item.person_project_relationship == "DIRECT" for item in candidates):
        unresolved.append(
            "Named individual project assignment and purchasing authority remain UNKNOWN."
        )
    current_evidence_ids = [str(row.id) for row in saved.values()]
    if previous_run and research_incomplete:
        # An outage or unvisited source is not negative evidence. A successful
        # source retraction is: never carry a claim contradicted by a checked version.
        known_entities = {_entity_key(item) for item in candidates}
        for prior_id in previous_run.claim_ids:
            prior_claim = session.get(BuyingChainClaim, UUID(prior_id))
            if prior_claim is None or prior_claim.entity_key in known_entities:
                continue
            has_unchecked_source = any(
                citation["url"] not in retrieved_by_url for citation in prior_claim.citations
            )
            contradicted = any(
                citation["url"] in retrieved_by_url
                and citation["quote"] not in retrieved_by_url[citation["url"]].text
                for citation in prior_claim.citations
            )
            if has_unchecked_source and not contradicted:
                current_claim_ids.append(prior_id)
        current_evidence_ids = list(
            dict.fromkeys(
                [
                    *previous_run.evidence_ids,
                    *current_evidence_ids,
                ]
            )
        )
    unresolved = list(dict.fromkeys(unresolved))
    status = (
        "partial"
        if current_claim_ids and unresolved
        else "complete"
        if current_claim_ids
        else "unresolved"
    )
    input_hash = _hash(
        {
            "policy": POLICY_VERSION,
            "evidence": sorted(current_evidence_ids),
            "claims": sorted(current_claim_ids),
            "unresolved": unresolved,
        }
    )
    if previous_run is None or previous_run.input_hash != input_hash or added:
        session.add(
            BuyingChainRun(
                project_id=project.id,
                input_hash=input_hash,
                policy_version=POLICY_VERSION,
                evidence_ids=current_evidence_ids,
                claim_ids=current_claim_ids,
                status=status,
                documents_checked=len(documents),
                candidates_added=added,
                unresolved=unresolved,
                created_at=now,
            )
        )
    session.flush()
    return buying_chain_view(session, project.id, now=now)


def buying_chain_view(
    session: Session, project_id: UUID, *, now: datetime | None = None, history: bool = False
) -> dict:
    now = now or datetime.now(UTC)
    if session.get(Project, project_id) is None:
        raise LookupError("Project not found")
    runs = session.scalars(
        select(BuyingChainRun)
        .where(
            BuyingChainRun.project_id == project_id,
        )
        .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
        .limit(10)
    ).all()
    claims = session.scalars(
        select(BuyingChainClaim)
        .where(
            BuyingChainClaim.project_id == project_id,
        )
        .order_by(BuyingChainClaim.created_at.desc(), BuyingChainClaim.id.desc())
    ).all()
    sources = session.scalars(
        select(BuyingChainEvidence)
        .where(
            BuyingChainEvidence.project_id == project_id,
        )
        .order_by(BuyingChainEvidence.last_seen_at.desc(), BuyingChainEvidence.id.desc())
    ).all()
    by_id = {str(row.id): row for row in sources}
    newest_by_url: dict[str, UUID] = {}
    for source_version in sorted(
        sources,
        key=lambda source: (source.last_seen_at, source.retained_evidence_id is None),
        reverse=True,
    ):
        newest_by_url.setdefault(source_version.url, source_version.id)
    if runs:
        for evidence_id in runs[0].evidence_ids:
            if evidence_id in by_id:
                latest_run_source = by_id[evidence_id]
                current_source = by_id[str(newest_by_url[latest_run_source.url])]
                if (
                    latest_run_source.last_seen_at,
                    latest_run_source.retained_evidence_id is None,
                ) >= (current_source.last_seen_at, current_source.retained_evidence_id is None):
                    newest_by_url[latest_run_source.url] = latest_run_source.id
    grouped: dict[str, list[BuyingChainClaim]] = defaultdict(list)
    for claim in claims:
        grouped[claim.entity_key].append(claim)
    selected = (
        claims if history else [row for row in claims if runs and str(row.id) in runs[0].claim_ids]
    )
    candidates: list[dict[str, Any]] = []
    for claim in selected:
        evidence = []
        stale = False
        organization_stale = False
        role_stale = False
        for citation in claim.citations:
            row = by_id.get(citation["evidence_id"])
            if row is None or citation["quote"] not in row.excerpt:
                stale = True
                continue
            newest = by_id[str(newest_by_url[row.url])]
            source_superseded = newest.id != row.id and citation["quote"] not in newest.excerpt
            age_basis = row.published_at or row.last_seen_at.date()
            role_aged = (
                citation["supports"] in {"organization_person_role", "person_project_assignment"}
                and (now.date() - age_basis).days > ROLE_MAX_AGE_DAYS
            )
            if row.retained_evidence_id:
                original = session.get(Evidence, row.retained_evidence_id)
                interpretation = (
                    session.scalar(
                        select(Interpretation).where(
                            Interpretation.observation_id == original.observation_id,
                        )
                    )
                    if original
                    else None
                )
                # The accepted observation version is authoritative for retained
                # fields. Native lines and earlier live JSON use different quote
                # formats; a later research fetch cannot retract accepted evidence.
                source_superseded = not (original and _accepted_version(interpretation, original))
            if citation["supports"] in {"project_organization", "organization_category"}:
                organization_stale = organization_stale or source_superseded
            elif citation["supports"] != "person_project_assignment":
                role_stale = role_stale or source_superseded or role_aged
            # Assignment freshness is independent of a newly verified employment role.
            stale = stale or source_superseded or role_aged
            evidence.append(
                {
                    "id": row.id,
                    "url": row.url,
                    "quote": citation["quote"],
                    "supports": citation["supports"],
                    "extraction_location": row.extraction_location,
                    "published_at": row.published_at,
                    "observed_at": row.observed_at,
                    "content_hash": row.content_hash,
                }
            )
        independent_conflict = False
        if claim.person_name and not history:
            role_urls = {
                c["url"] for c in claim.citations if c["supports"] == "organization_person_role"
            }
            for prior in grouped[claim.entity_key]:
                if normalized_identity(prior.title) == normalized_identity(claim.title):
                    continue
                for prior_citation in prior.citations:
                    if (
                        prior_citation["supports"] != "organization_person_role"
                        or prior_citation["url"] in role_urls
                    ):
                        continue
                    prior_source = by_id.get(prior_citation["evidence_id"])
                    if prior_source is None:
                        continue
                    current_source = by_id[str(newest_by_url[prior_source.url])]
                    age = (
                        now.date() - (prior_source.published_at or prior_source.last_seen_at.date())
                    ).days
                    if (
                        age > ROLE_MAX_AGE_DAYS
                        or prior_citation["quote"] not in current_source.excerpt
                    ):
                        continue
                    independent_conflict = role_stale = stale = True
                    evidence.append(
                        {
                            "id": prior_source.id,
                            "url": prior_source.url,
                            "quote": prior_citation["quote"],
                            "supports": "conflicting_organization_person_role",
                            "extraction_location": prior_source.extraction_location,
                            "published_at": prior_source.published_at,
                            "observed_at": prior_source.observed_at,
                            "content_hash": prior_source.content_hash,
                        }
                    )
        candidates.append(
            {
                "id": claim.id,
                "organization": claim.organization,
                "person_name": claim.person_name,
                "title": claim.title,
                "category": claim.category,
                "organization_relationship": "UNKNOWN"
                if organization_stale
                else claim.organization_relationship,
                "person_organization_relationship": "UNKNOWN"
                if role_stale
                else claim.person_organization_relationship,
                "person_project_relationship": "UNKNOWN"
                if stale
                else claim.person_project_relationship,
                "evidence_strength": "Low" if stale else claim.evidence_strength,
                "reason": (
                    "Conflicting independent role evidence; "
                    "current role and assignment are UNKNOWN."
                )
                if independent_conflict
                else "Aged or superseded evidence; affected relationships are UNKNOWN. "
                + claim.reason
                if stale
                else claim.reason,
                "observed_at": claim.observed_at,
                "verified_at": claim.verified_at,
                "public_contacts": claim.public_contacts,
                "evidence": evidence,
                "history_count": len(grouped[claim.entity_key]),
                "stale": stale,
            }
        )
    candidates.sort(
        key=lambda item: (
            CATEGORY_PRIORITY.get(item["category"], 99),
            item["person_name"] is None,
            item["organization"],
            item["person_name"] or "",
        )
    )
    runs = session.scalars(
        select(BuyingChainRun)
        .where(
            BuyingChainRun.project_id == project_id,
        )
        .order_by(BuyingChainRun.created_at.desc(), BuyingChainRun.id.desc())
        .limit(10)
    ).all()
    unresolved = (
        list(runs[0].unresolved)
        if runs
        else ["Buying chain has not been researched for this project."]
    )
    if any(item["stale"] for item in candidates):
        unresolved.append("Some evidence is stale or superseded; verify current responsibility.")
    return {
        "project_id": project_id,
        "status": runs[0].status if runs else "not_researched",
        "candidates": candidates if history else candidates[:MAX_CANDIDATES],
        "unresolved": unresolved,
        "runs": [
            {
                "id": row.id,
                "status": row.status,
                "documents_checked": row.documents_checked,
                "candidates_added": row.candidates_added,
                "unresolved": row.unresolved,
                "created_at": row.created_at,
            }
            for row in runs
        ],
        "permit_summaries": _permit_summaries(session, project_id),
        "policy_version": POLICY_VERSION,
    }


def _permit_summaries(session: Session, project_id: UUID) -> list[dict]:
    project = session.get(Project, project_id)
    if project is None:
        return []
    summaries = []
    for evidence in _retained(session, project):
        observation = session.get(Observation, evidence.observation_id)
        if observation is None:
            continue
        facts = permit_facts(observation.source_id, evidence.abstract or "")
        if facts:
            summaries.append(
                {
                    "evidence_id": evidence.id,
                    "source_id": observation.source_id,
                    "url": evidence.url,
                    "title": evidence.title,
                    "observed_at": evidence.observed_at,
                    "extraction_location": evidence.extraction_location,
                    "facts": facts,
                }
            )
    return summaries
