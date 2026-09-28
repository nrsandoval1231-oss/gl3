import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from gridlens.domain.lifecycle import classify_event
from gridlens.domain.news_interpretation import (
    EVALUATOR_VERSION,
    assess_news,
    prospect_power_activity,
    signal_power_activity,
)
from gridlens.domain.permit_interpretation import assess_permit
from gridlens.domain.permit_interpretation import evaluator_version as permit_evaluator_version
from gridlens.domain.qualification import assess_signal
from gridlens.ingestion.adapters import retrieve_source
from gridlens.ingestion.adapters.govinfo_pdf import MAX_PDFS_PER_RUN, retrieve_companion
from gridlens.intelligence.lifecycle_service import apply_lifecycle_observation
from gridlens.intelligence.matching import interpret
from gridlens.intelligence.project_identity import (
    conflicting_geography,
    decide_project_match,
    labeled_site,
    labeled_sites,
    normalized_identity,
    physical_site,
    same_physical_site,
    stable_asset_identity,
)
from gridlens.jobs.queue import assert_fence
from gridlens.persistence.models import (
    ChangeEvent,
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    ProjectMatchDecision,
    Source,
)

PERMIT_RETRIEVAL_METHODS = {"socrata-permits", "georgia-air-permits"}


def _optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _hash(record: dict[str, Any]) -> str:
    if record.get("permit") and record.get("source_hash"):
        return str(record["source_hash"])
    stable_fields = {
        "title": " ".join(record["title"].split()),
        "abstract": " ".join((record.get("abstract") or "").split()),
        "publication_date": record["publication_date"],
        "url": record.get("html_url"),
    }
    raw = json.dumps(stable_fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _source_version_hash(record: dict[str, Any]) -> str:
    raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _permit_assessment_payload(
    assessment: dict[str, Any],
    evidence: Evidence | None,
    record: dict[str, Any],
    digest: str,
    evidence_digest: str,
    previous: dict[str, Any] | None,
    prior_evaluator_version: str | None,
) -> dict[str, Any]:
    current_evaluator = permit_evaluator_version(record)
    payload = {
        **assessment,
        "semantic_hash": digest,
        "evidence_hash": evidence_digest,
        "evidence": {
            "id": str(evidence.id) if evidence else None,
            "url": record["html_url"],
            "issue_date": record["event_date"]
            if str(record.get("event_date_label", "")).startswith("Permit issue date")
            else None,
            "event_date": record.get("event_date"),
            "event_date_label": record.get("event_date_label"),
            "publication_date": record.get("publication_date"),
        },
        "evaluator_version": current_evaluator,
    }
    if previous and (
        previous.get("semantic_hash") != digest
        or previous.get("power_activity") != assessment.get("power_activity")
        or previous.get("rental_category") != assessment.get("rental_category")
        or previous.get("decision") != assessment.get("decision")
        or prior_evaluator_version != current_evaluator
    ):
        history = list(previous.get("previous_decisions", []))
        prior_entry = {key: value for key, value in previous.items() if key != "previous_decisions"}
        if prior_evaluator_version:
            prior_entry["evaluator_version"] = prior_evaluator_version
        history.append(prior_entry)
        payload["previous_decisions"] = history
    elif previous and previous.get("previous_decisions"):
        payload["previous_decisions"] = previous["previous_decisions"]
    return payload


def news_power_activity(assessment: dict[str, Any]) -> str | None:
    if assessment.get("tier") == "Signal":
        return signal_power_activity(
            assessment.get("action") if isinstance(assessment.get("action"), str) else None
        )
    if assessment.get("tier") == "Prospect":
        return prospect_power_activity(
            str(assessment.get("subject") or ""),
            str(assessment.get("demand_quote") or ""),
            str(assessment.get("supply_quote") or ""),
        )
    return None


def _news_identity_key(
    title: str, abstract: str | None, source_id: str, external_id: str, assessment: dict[str, Any]
) -> str:
    # Exact retained title/summary copies may share an event; no fuzzy publisher matching.
    material = {
        "title": " ".join(title.split()).casefold(),
        "abstract": " ".join((abstract or "").split()).casefold(),
        "subject": assessment.get("subject"),
        "location": assessment.get("location"),
        "action": assessment.get("action"),
    }
    if not all(
        (
            material["title"],
            material["subject"],
            material["location"],
            material["action"],
        )
    ):
        material = {"source_id": source_id, "external_id": external_id}
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"rss:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _reported_mw(assessment: dict[str, Any]) -> str | None:
    value = assessment.get("demand_mw")
    return value if isinstance(value, str) and value else None


def _asset_type_conflicts(candidate_type: str, classification: Any | None) -> bool:
    return bool(
        classification
        and candidate_type != "unknown"
        and candidate_type != classification.asset_type.value
    )


def _need_has_current_support(session: Session, need: PowerNeed, project: Project) -> bool:
    rows = session.execute(
        select(Observation, Interpretation)
        .join(NeedObservation, NeedObservation.observation_id == Observation.id)
        .outerjoin(Interpretation, Interpretation.observation_id == Observation.id)
        .where(NeedObservation.need_id == need.id)
    ).all()
    for linked_observation, interpretation in rows:
        if (
            interpretation is None
            or interpretation.status != "accepted"
            or interpretation.content_hash != linked_observation.content_hash
        ):
            continue
        assessment = interpretation.assessment or {}
        if assessment.get("semantic_hash") not in {None, linked_observation.content_hash}:
            continue
        identity_key = assessment.get("project_identity_key")
        if identity_key is not None and identity_key != project.identity_key:
            continue
        activity = assessment.get("power_activity") or assessment.get("activity_key")
        if activity is not None and activity != need.activity_key:
            continue
        evidence_hash = assessment.get("evidence_hash")
        if isinstance(evidence_hash, str):
            bound = session.scalar(
                select(Evidence.id).where(
                    Evidence.observation_id == linked_observation.id,
                    Evidence.content_hash == evidence_hash,
                )
            )
            if bound is None:
                continue
        elif (
            session.scalar(
                select(Evidence.id).where(Evidence.observation_id == linked_observation.id)
            )
            is None
        ):
            continue
        return True
    return False


def _current_need_claims(
    session: Session, need: PowerNeed, project: Project
) -> list[dict[str, Any]]:
    rows = session.execute(
        select(Observation, Interpretation)
        .join(NeedObservation, NeedObservation.observation_id == Observation.id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .where(NeedObservation.need_id == need.id)
    ).all()
    claims: list[dict[str, Any]] = []
    for observation, interpretation in rows:
        if (
            interpretation.status != "accepted"
            or interpretation.content_hash != observation.content_hash
        ):
            continue
        assessment = interpretation.assessment or {}
        if assessment.get("semantic_hash") not in {None, observation.content_hash}:
            continue
        if assessment.get("project_identity_key") not in {None, project.identity_key}:
            continue
        activity = assessment.get("power_activity") or assessment.get("activity_key")
        if activity not in {None, need.activity_key}:
            continue
        evidence_hash = assessment.get("evidence_hash")
        if not isinstance(evidence_hash, str) or session.scalar(
            select(Evidence.id).where(
                Evidence.observation_id == observation.id,
                Evidence.content_hash == evidence_hash,
            )
        ) is None:
            continue

        tier = assessment.get("tier")
        reason = assessment.get("reason") or assessment.get("rationale")
        if tier == "Prospect":
            if not all(
                isinstance(assessment.get(key), str) and assessment[key].strip()
                for key in ("demand_mw", "demand_quote", "supply_quote")
            ) or not isinstance(reason, str) or not reason.strip():
                continue
            claim = {**assessment, "reason": reason, "tier": "Prospect"}
        elif tier == "Signal" or (tier is None and assessment.get("decision") == "accepted"):
            if not isinstance(reason, str) or not reason.strip():
                continue
            claim = {
                "tier": "Signal",
                "reason": reason,
                "demand_mw": None,
            }
        else:
            continue
        claims.append(
            {
                "claim": claim,
                "priority": 0 if claim["tier"] == "Prospect" else 1,
                "content_hash": observation.content_hash,
                "source_id": observation.source_id,
                "external_id": observation.external_id,
            }
        )
    claims.sort(
        key=lambda row: (
            row["priority"],
            row["content_hash"],
            row["source_id"],
            row["external_id"],
        )
    )
    return [row["claim"] for row in claims]


def _assessment_payload(
    observation: Observation, evidence: Evidence, assessment: dict[str, Any]
) -> dict[str, Any]:
    source_text = (observation.title, observation.abstract or "")
    for key in ("demand_quote", "supply_quote"):
        quote = assessment.get(key)
        if quote is not None and not any(quote in span for span in source_text):
            raise ValueError(f"{key} does not cite a retained title or summary span")
    action = assessment.get("action")
    if action and not any(action.casefold() in span.casefold() for span in source_text):
        raise ValueError("physical action does not occur in retained evidence")
    if assessment.get("decision") == "accepted":
        for key in ("tier", "reason", "subject", "action", "location"):
            if not assessment.get(key):
                raise ValueError(f"accepted assessment is missing {key}")
    return {
        "schema_version": 1,
        "semantic_hash": observation.content_hash,
        "evidence_hash": evidence.content_hash,
        "evidence": {
            "id": str(evidence.id),
            "url": evidence.url,
            "published_at": evidence.published_at.isoformat() if evidence.published_at else None,
            "extraction_location": evidence.extraction_location,
        },
        **assessment,
    }


def assess_retained_news(
    session: Session,
    observation: Observation,
    evidence: Evidence,
    *,
    job_id: Any | None = None,
    worker_id: str | None = None,
    fence: int | None = None,
) -> bool:
    """Evaluate one durable RSS version; return True when a new decision was stored."""
    interpretation = session.scalar(
        select(Interpretation)
        .where(Interpretation.observation_id == observation.id)
        .with_for_update()
    )
    if interpretation is None:
        interpretation = Interpretation(
            observation_id=observation.id,
            content_hash=observation.content_hash,
            status="pending",
            attempts=0,
        )
        session.add(interpretation)
        session.flush()
    if (
        interpretation.status in {"accepted", "rejected"}
        and interpretation.content_hash == observation.content_hash
        and interpretation.evaluator_version == EVALUATOR_VERSION
        and interpretation.assessment is not None
        and interpretation.assessment.get("semantic_hash") == observation.content_hash
        and interpretation.assessment.get("evidence_hash") == evidence.content_hash
    ):
        return False
    if job_id is not None:
        assert worker_id is not None and fence is not None
        assert_fence(session, job_id, worker_id, fence)

    prior_assessment = interpretation.assessment
    prior_identity = prior_assessment.get("project_identity_key") if prior_assessment else None
    try:
        claim = assess_news(observation.title, observation.abstract).as_dict()
        payload = _assessment_payload(observation, evidence, claim)
        activity_key = news_power_activity(claim)
        if claim.get("decision") == "accepted" and activity_key is None:
            raise ValueError(
                "Prospect evidence does not bind demand and supply to one power activity"
            )
        if claim.get("decision") == "accepted":
            payload["power_activity"] = activity_key
            payload["project_identity_key"] = _news_identity_key(
                observation.title,
                observation.abstract,
                observation.source_id,
                observation.external_id,
                claim,
            )
            if (
                prior_assessment
                and prior_assessment.get("subject") == claim.get("subject")
                and prior_assessment.get("location") == claim.get("location")
                and prior_assessment.get("project_identity_key")
            ):
                payload["project_identity_key"] = prior_assessment["project_identity_key"]
        if prior_identity and prior_assessment:
            same_site = prior_assessment.get("subject") == claim.get(
                "subject"
            ) and prior_assessment.get("location") == claim.get("location")
            prior_activity = prior_assessment.get("power_activity")
            if (
                claim.get("decision") == "rejected"
                or not same_site
                or prior_activity != activity_key
            ):
                payload["superseded_project_identity_key"] = prior_identity
    except Exception as exc:
        interpretation.status = "failed"
        interpretation.content_hash = observation.content_hash
        interpretation.error = type(exc).__name__
        interpretation.attempts += 1
        session.flush()
        return False

    history: list[dict[str, Any]] = []
    if prior_assessment:
        history.extend(prior_assessment.get("previous_decisions", []))
        if (
            prior_assessment.get("semantic_hash") != observation.content_hash
            or interpretation.evaluator_version != EVALUATOR_VERSION
        ):
            history.append(
                {
                    key: value
                    for key, value in prior_assessment.items()
                    if key != "previous_decisions"
                }
            )
    if history:
        payload["previous_decisions"] = history

    old_needs = session.scalars(
        select(PowerNeed)
        .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
        .where(NeedObservation.observation_id == observation.id)
        .with_for_update()
    ).all()
    interpretation.content_hash = observation.content_hash
    interpretation.evaluator_version = EVALUATOR_VERSION
    interpretation.assessment = payload
    interpretation.error = None
    interpretation.attempts += 1
    interpretation.status = "accepted" if claim["decision"] == "accepted" else "rejected"

    current_need: PowerNeed | None = None
    if claim["decision"] == "accepted":
        identity_key = payload["project_identity_key"]
        project = session.scalar(
            select(Project).where(Project.identity_key == identity_key).with_for_update()
        )
        if project is not None and project.source_id != observation.source_id:
            exact_copy = session.scalar(
                select(ProjectMatchDecision).where(
                    ProjectMatchDecision.observation_id == observation.id,
                    ProjectMatchDecision.candidate_project_id == project.id,
                    ProjectMatchDecision.evidence_id == evidence.id,
                )
            )
            if exact_copy is None:
                session.add(
                    ProjectMatchDecision(
                        observation_id=observation.id,
                        candidate_project_id=project.id,
                        evidence_id=evidence.id,
                        decision="matched",
                        reason=(
                            "Exact retained title and summary copy with identical cited "
                            "project facts."
                        ),
                        matched_facts=[
                            "exact title",
                            "exact summary",
                            "same cited subject, location, and action",
                        ],
                        identity_facts={
                            "title": observation.title,
                            "abstract_hash": hashlib.sha256(
                                (observation.abstract or "").encode("utf-8")
                            ).hexdigest(),
                            "project_name": claim["subject"],
                            "site": labeled_site(
                                f"{observation.title} {observation.abstract or ''}"
                            )
                            or claim["location"],
                        },
                    )
                )
        if project is None:
            candidates = session.scalars(select(Project).with_for_update()).all()
            matching_candidates: list[tuple[Project, Any]] = []
            identity_decisions = []
            site_claims = labeled_sites(f"{observation.title} {observation.abstract or ''}")
            site_claim = site_claims[0] if len(site_claims) == 1 else None
            ambiguous_sites = len(site_claims) > 1
            for candidate in candidates:
                aliases = (candidate.identity_facts or {}).get("project_aliases", [])
                same_name = normalized_identity(candidate.name) == normalized_identity(
                    claim["subject"]
                ) or any(
                    normalized_identity(alias) == normalized_identity(claim["subject"])
                    for alias in aliases
                    if isinstance(alias, str)
                )
                candidate_site = (candidate.identity_facts or {}).get("site") or (
                    candidate.location
                )
                incoming_site = site_claim or claim.get("location")
                same_site = not ambiguous_sites and same_physical_site(
                    candidate_site, incoming_site
                )
                decision = decide_project_match(
                    same_address=same_site,
                    same_project_name=same_name,
                    conflicting_geography=bool(
                        conflicting_geography(candidate.location, claim.get("location"))
                    ),
                    conflicting_asset_type=_asset_type_conflicts(
                        candidate.asset_type,
                        classify_event(observation.title, observation.abstract),
                    ),
                )
                identity_decisions.append((candidate, decision))
                if decision.decision == "matched":
                    matching_candidates.append((candidate, decision))
            if len(matching_candidates) == 1:
                project = matching_candidates[0][0]
                payload["project_identity_key"] = project.identity_key
            else:
                project = Project(
                    identity_key=identity_key,
                    name=claim["subject"],
                    location=claim["location"],
                    source_id=observation.source_id,
                    external_id=observation.external_id,
                    identity_facts={
                        "project_name": claim["subject"],
                        "project_aliases": [claim["subject"]],
                        "site": site_claim or claim["location"],
                    },
                )
                session.add(project)
                session.flush()
            if matching_candidates or any(
                decision.matched_facts for _, decision in identity_decisions
            ):
                for candidate, decision in identity_decisions:
                    if not decision.matched_facts and len(matching_candidates) < 2:
                        continue
                    row = session.scalar(
                        select(ProjectMatchDecision)
                        .where(
                            ProjectMatchDecision.observation_id == observation.id,
                            ProjectMatchDecision.candidate_project_id == candidate.id,
                            ProjectMatchDecision.evidence_id == evidence.id,
                        )
                        .with_for_update()
                    )
                    if row is None:
                        row = ProjectMatchDecision(
                            observation_id=observation.id,
                            candidate_project_id=candidate.id,
                            decision="separate",
                            reason="Pending identity decision.",
                            matched_facts=[],
                        )
                        session.add(row)
                    row.decision = "matched" if len(matching_candidates) == 1 else "separate"
                    row.reason = (
                        decision.reason
                        if len(matching_candidates) == 1
                        and not ambiguous_sites
                        else "Multiple supported project candidates; retained separately."
                    )
                    if ambiguous_sites:
                        row.reason = (
                            "Multiple distinct labeled site addresses; identity ambiguous, "
                            "so the record remains separate."
                        )
                    row.matched_facts = list(decision.matched_facts)
                    row.evidence_id = evidence.id
                    row.identity_facts = {
                        "project_name": claim["subject"],
                        "project_aliases": [claim["subject"]],
                        "site": site_claim or claim["location"],
                        "site_candidates": list(site_claims),
                    }
            if not matching_candidates:
                unmatched = session.scalar(
                    select(ProjectMatchDecision).where(
                        ProjectMatchDecision.observation_id == observation.id,
                        ProjectMatchDecision.candidate_project_id.is_(None),
                        ProjectMatchDecision.evidence_id == evidence.id,
                    )
                )
                if unmatched is None:
                    session.add(
                        ProjectMatchDecision(
                            observation_id=observation.id,
                            candidate_project_id=None,
                            evidence_id=evidence.id,
                            decision="separate",
                        reason=(
                            "Multiple distinct labeled site addresses; identity ambiguous, "
                            "so the record remains separate."
                            if ambiguous_sites
                            else "No supported existing project candidate met conservative "
                            "identity evidence."
                            ),
                            matched_facts=[],
                            identity_facts={
                                "project_name": claim["subject"],
                                "site": site_claim or claim["location"],
                                "site_candidates": list(site_claims),
                            },
                        )
                    )
        identity_key = project.identity_key
        activity_key = payload["power_activity"]
        if activity_key == "construction":
            permit_activity_need = session.scalar(
                select(PowerNeed)
                .where(
                    PowerNeed.project_id == project.id,
                    PowerNeed.activity_key == "facility-expansion",
                )
                .with_for_update()
            )
            if permit_activity_need is not None:
                activity_key = "facility-expansion"
                payload["power_activity"] = activity_key
        current_need = session.scalar(
            select(PowerNeed)
            .where(PowerNeed.project_id == project.id, PowerNeed.activity_key == activity_key)
            .with_for_update()
        )
        was_active = current_need.active if current_need else False
        previous_rationale = current_need.rationale if current_need else None
        if current_need is None:
            current_need = PowerNeed(
                project_id=project.id,
                activity_key=activity_key,
                tier=claim["tier"],
                rationale=claim["reason"],
                required_mw=_reported_mw(claim),
                supply="Unknown",
            )
            session.add(current_need)
            session.flush()
        current_need.active = True
        current_need.tier = claim["tier"]
        current_need.rationale = claim["reason"]
        current_need.required_mw = _reported_mw(claim)
        current_need.supply = "Reported constraint" if claim["tier"] == "Prospect" else "Unknown"
        payload["project_identity_key"] = identity_key
        # Assign a fresh JSON value before support queries can autoflush it.
        interpretation.assessment = {**payload}
        flag_modified(interpretation, "assessment")
        if (
            session.scalar(
                select(NeedObservation.id).where(
                    NeedObservation.need_id == current_need.id,
                    NeedObservation.observation_id == observation.id,
                )
            )
            is None
        ):
            session.add(NeedObservation(need_id=current_need.id, observation_id=observation.id))
        apply_lifecycle_observation(session, project, observation, evidence)
        if (
            not was_active
            or previous_rationale != claim["reason"]
            or (prior_identity is not None and prior_identity != identity_key)
            or (
                prior_assessment
                and prior_assessment.get("semantic_hash") != observation.content_hash
            )
        ):
            session.add(
                ChangeEvent(
                    observation_id=observation.id,
                    content_hash=observation.content_hash,
                    kind="reclassified" if prior_assessment else "discovered",
                )
            )

    impacted_ids = {need.id for need in old_needs}
    if current_need is not None:
        impacted_ids.add(current_need.id)
    impacted = (
        session.scalars(
            select(PowerNeed).where(PowerNeed.id.in_(impacted_ids)).with_for_update()
        ).all()
        if impacted_ids
        else []
    )
    for need in impacted:
        project = session.get(Project, need.project_id)
        if project is None:
            continue
        supported = _need_has_current_support(session, need, project)
        if need.active and not supported:
            need.active = False
            need.tier = "Signal"
            need.required_mw = None
            need.supply = "Unknown"
            need.rationale = "No current accepted evidence supports this activity."
            session.add(
                ChangeEvent(
                    observation_id=observation.id,
                    content_hash=observation.content_hash,
                    kind="closed",
                )
            )
        elif supported:
            claims = _current_need_claims(session, need, project)
            if claims:
                selected = claims[0]
                need.active = True
                need.tier = selected["tier"]
                need.rationale = selected["reason"]
                need.required_mw = _reported_mw(selected)
                need.supply = (
                    "Reported constraint" if selected["tier"] == "Prospect" else "Unknown"
                )
    # Reassign after in-place edits so SQLAlchemy marks the JSON value dirty.
    interpretation.assessment = {**payload}
    flag_modified(interpretation, "assessment")
    if job_id is not None:
        assert worker_id is not None and fence is not None
        job = assert_fence(session, job_id, worker_id, fence)
        job.checkpoint = observation.external_id
        job.lease_until = datetime.now(UTC) + timedelta(seconds=90)
    session.flush()
    return True


def process_job(
    session: Session,
    job_id: Any,
    worker_id: str,
    fence: int,
    source_definition: dict[str, Any],
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    records = retrieve_source(source_definition, client)
    if source_definition.get("retrieval_method") == "publisher-rss":
        return _process_collection_only(
            session, job_id, worker_id, fence, source_definition, records
        )
    counts: dict[str, Any] = {
        "new": 0,
        "changed": 0,
        "unchanged": 0,
        "signals": 0,
        "retrieved_records": len(records),
        "parsed_records": len(records),
        "records_scanned": len(records),
        "permit_accepted": 0,
        "permit_rejected": 0,
        "latest_publication_date": None,
        "latest_public_comment_deadline": None,
        "pdf_candidates": 0,
        "pdf_eligible": 0,
        "pdf_enriched": 0,
        "pdf_skipped_not_signal": 0,
        "pdf_skipped_limit": 0,
    }
    if source_definition.get("retrieval_method") == "georgia-air-permits":
        counts["snapshot_item_count"] = len(records)
        counts["documents_extracted"] = sum(len(record.get("companions", [])) for record in records)
        counts["unextracted_public_notice_references"] = sum(
            "public notice" in record.get("permit", {}).get("unextracted_document_links", {})
            for record in records
        )
    pdf_documents = 0
    for record in records:
        assert_fence(session, job_id, worker_id, fence)
        source = session.get(Source, source_definition["id"])
        assert source is not None
        external_id = record["document_number"]
        digest = _hash(record)
        evidence_digest = record.get("source_hash") or _source_version_hash(record)
        if record.get("publication_date"):
            counts["latest_publication_date"] = max(
                counts["latest_publication_date"] or "0000-00-00", record["publication_date"]
            )
        permit_info = record.get("permit")
        if isinstance(permit_info, dict) and permit_info.get("public_comment_deadline"):
            counts["earliest_public_comment_deadline"] = min(
                counts.get("earliest_public_comment_deadline")
                or permit_info["public_comment_deadline"],
                permit_info["public_comment_deadline"],
            )
            counts["latest_public_comment_deadline"] = max(
                counts["latest_public_comment_deadline"] or "0000-00-00",
                permit_info["public_comment_deadline"],
            )
        is_permit_source = source_definition.get("retrieval_method") in PERMIT_RETRIEVAL_METHODS
        if source_definition.get("retrieval_method") == "socrata-permits":
            counts["latest_permit_issue_date"] = counts["latest_publication_date"]
        observation = session.scalar(
            select(Observation)
            .where(Observation.source_id == source.id, Observation.external_id == external_id)
            .with_for_update()
        )
        is_new = observation is None
        same_material_fields = bool(
            observation
            and observation.title == record["title"]
            and " ".join((observation.abstract or "").split())
            == " ".join((record.get("abstract") or "").split())
            and observation.published_at == _optional_date(record.get("publication_date"))
            and observation.url == record["html_url"]
        )
        # Accept the prior candidate's hash during the first replay after this
        # semantic fingerprint is introduced; compare retained claims, not
        # provider-side representation links or irrelevant source markup.
        same_version = observation is not None and (
            observation.content_hash == digest or (not is_permit_source and same_material_fields)
        )
        change_kind = "discovered" if is_new else "updated"
        if is_new:
            observation = Observation(
                source_id=source.id,
                external_id=external_id,
                title=record["title"],
                abstract=record.get("abstract"),
                published_at=_optional_date(record.get("publication_date")),
                url=record["html_url"],
                content_hash=digest,
            )
            session.add(observation)
            session.flush()
            counts["new"] += 1
        elif same_version:
            counts["unchanged"] += 1
        else:
            assert observation is not None
            observation.title = record["title"]
            observation.abstract = record.get("abstract")
            observation.published_at = _optional_date(record.get("publication_date"))
            observation.url = record["html_url"]
            observation.content_hash = digest
            counts["changed"] += 1
        assert observation is not None
        if (
            session.scalar(
                select(Evidence.id).where(
                    Evidence.observation_id == observation.id,
                    Evidence.content_hash == evidence_digest,
                )
            )
            is None
        ):
            session.add(
                Evidence(
                    observation_id=observation.id,
                    content_hash=evidence_digest,
                    title=record["title"],
                    abstract=record.get("abstract"),
                    url=record["html_url"],
                    published_at=_optional_date(record.get("publication_date")),
                    extraction_location=record.get("extraction_location", "title and abstract"),
                    event_date=date.fromisoformat(record["event_date"])
                    if record.get("event_date")
                    else None,
                    event_date_label=(
                        record.get("event_date_label")
                        or ("Permit issue date" if is_permit_source else None)
                    ),
                )
            )
        session.commit()  # Keep retrieved source evidence durable if PDF enrichment fails.
        companions = record.get("companions", [])
        if not isinstance(companions, list):
            raise ValueError("Source companions must be a list")
        for companion in companions:
            if not isinstance(companion, dict) or not all(
                companion.get(key)
                for key in ("content_hash", "title", "url", "extraction_location")
            ):
                raise ValueError("Source companion evidence is incomplete")
            if (
                session.scalar(
                    select(Evidence.id).where(
                        Evidence.observation_id == observation.id,
                        Evidence.content_hash == companion["content_hash"],
                    )
                )
                is None
            ):
                session.add(
                    Evidence(
                        observation_id=observation.id,
                        content_hash=companion["content_hash"],
                        title=companion["title"],
                        abstract=companion.get("abstract"),
                        url=companion["url"],
                        published_at=_optional_date(companion.get("published_at")),
                        extraction_location=companion["extraction_location"],
                        event_date=_optional_date(companion.get("event_date")),
                        event_date_label=companion.get("event_date_label"),
                    )
                )
        if companions:
            session.commit()
        # The PDF is an alternate representation of the FR record. Attach its
        # content hash and page citation to this observation only.
        if record.get("pdf_url"):
            counts["pdf_candidates"] += 1
            eligible = (
                source.id == "federal-register-eis"
                and assess_signal(record["title"], record.get("abstract")) is not None
            )
            if not eligible:
                counts["pdf_skipped_not_signal"] += 1
                pdf_citations: list[dict[str, str]] = []
            else:
                counts["pdf_eligible"] += 1
                if pdf_documents >= MAX_PDFS_PER_RUN:
                    counts["pdf_skipped_limit"] += 1
                    pdf_citations = []
                else:
                    pdf_documents += 1
                    pdf_citations = retrieve_companion(record, client)
                    counts["pdf_enriched"] += 1
                    # Network retrieval can outlast this worker's lease. Reclaim
                    # the fence before inspecting or persisting its result.
                    assert_fence(session, job_id, worker_id, fence)
            if pdf_citations:
                pdf = pdf_citations[0]
                if (
                    session.scalar(
                        select(Evidence.id).where(
                            Evidence.observation_id == observation.id,
                            Evidence.content_hash == pdf["content_hash"],
                        )
                    )
                    is None
                ):
                    session.add(
                        Evidence(
                            observation_id=observation.id,
                            content_hash=pdf["content_hash"],
                            title=pdf["title"],
                            abstract=pdf["abstract"],
                            url=pdf["url"],
                            published_at=_optional_date(pdf.get("published_at")),
                            extraction_location=pdf["extraction_location"],
                            event_date=None,
                        )
                    )
                    session.commit()
        # PDF evidence has its own commit boundary. Reacquire the current fence
        # before creating or updating the durable interpretation backlog.
        assert_fence(session, job_id, worker_id, fence)
        interpretation = session.scalar(
            select(Interpretation)
            .where(Interpretation.observation_id == observation.id)
            .with_for_update()
        )
        prior_interpretation_status = interpretation.status if interpretation is not None else None
        prior_assessment = interpretation.assessment if interpretation is not None else None
        prior_evaluator_version = (
            interpretation.evaluator_version if interpretation is not None else None
        )
        if (
            is_permit_source
            and interpretation is not None
            and interpretation.status in {"accepted", "rejected"}
            and interpretation.content_hash == digest
            and interpretation.evaluator_version == permit_evaluator_version(record)
            and interpretation.assessment is not None
            and interpretation.assessment.get("semantic_hash") == digest
            and interpretation.assessment.get("evidence_hash") == evidence_digest
            and not (
                interpretation.assessment.get("review_after")
                and date.fromisoformat(interpretation.assessment["review_after"]) < date.today()
            )
        ):
            counts[
                "permit_accepted" if interpretation.status == "accepted" else "permit_rejected"
            ] += 1
            job = assert_fence(session, job_id, worker_id, fence)
            job.checkpoint = external_id
            job.lease_until = datetime.now(UTC) + timedelta(seconds=90)
            session.commit()
            continue
        if interpretation is None:
            interpretation = Interpretation(
                observation_id=observation.id, content_hash=digest, attempts=1
            )
            session.add(interpretation)
        else:
            interpretation.content_hash = digest
            interpretation.status, interpretation.error = "pending", None
            interpretation.attempts += 1
        session.flush()
        session.commit()  # Raw evidence and the interpretation backlog survive a crash.

        try:
            permit_assessment = assess_permit(record) if is_permit_source else None
            interpreted = (
                {
                    "name": permit_assessment["subject"],
                    "activity_key": permit_assessment["power_activity"],
                    "rationale": permit_assessment["reason"],
                    "location": permit_assessment["location"],
                }
                if permit_assessment and permit_assessment["decision"] == "accepted"
                else None
                if permit_assessment
                else interpret({**record, "source_id": source.id})
            )
        except Exception as exc:
            assert_fence(session, job_id, worker_id, fence)
            interpretation.status, interpretation.error = "failed", type(exc).__name__
            session.commit()
            continue
        assert_fence(session, job_id, worker_id, fence)

        project_key = f"{source.id}:{external_id}"
        project = session.scalar(
            select(Project).where(Project.identity_key == project_key).with_for_update()
        )
        if interpreted is None:
            impacted_needs = session.scalars(
                select(PowerNeed)
                .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
                .where(NeedObservation.observation_id == observation.id)
                .with_for_update()
            ).all()
            if project is None and impacted_needs:
                impacted_project_ids = {need.project_id for need in impacted_needs}
                if len(impacted_project_ids) == 1:
                    project = session.get(Project, next(iter(impacted_project_ids)))
            interpretation.status = "rejected"
            interpretation.content_hash = digest
            current_evidence = session.scalar(
                select(Evidence).where(
                    Evidence.observation_id == observation.id,
                    Evidence.content_hash == evidence_digest,
                )
            )
            if permit_assessment:
                counts["permit_rejected"] += 1
                interpretation.evaluator_version = permit_evaluator_version(record)
                interpretation.assessment = _permit_assessment_payload(
                    permit_assessment,
                    current_evidence,
                    record,
                    digest,
                    evidence_digest,
                    prior_assessment,
                    prior_evaluator_version,
                )
                if project is not None:
                    interpretation.assessment["project_identity_key"] = project.identity_key
            else:
                interpretation.assessment = {
                    "semantic_hash": digest,
                    "evidence_hash": evidence_digest,
                    "decision": "rejected",
                    "project_identity_key": project.identity_key if project else None,
                }
            needs = list(impacted_needs)
            if project is not None:
                activity_keys = (
                    {
                        "facility-expansion",
                        "backup-power",
                        "temporary-power",
                        "bridge-power",
                        "event-power",
                    }
                    if permit_assessment
                    else {
                        "facility-expansion" if source.id == "nc-commerce" else "mine-development"
                    }
                )
                project_needs = session.scalars(
                    select(PowerNeed)
                    .where(
                        PowerNeed.project_id == project.id,
                        PowerNeed.activity_key.in_(activity_keys),
                    )
                    .with_for_update()
                ).all()
                needs.extend(project_needs)
            unique_needs = {need.id: need for need in needs}
            impacted_project_ids = set()
            for stale_need in unique_needs.values():
                impacted_project_ids.add(stale_need.project_id)
                if (
                    current_evidence is not None
                    and session.scalar(
                        select(NeedObservation.id).where(
                            NeedObservation.need_id == stale_need.id,
                            NeedObservation.observation_id == observation.id,
                        )
                    )
                    is None
                ):
                    session.add(
                        NeedObservation(need_id=stale_need.id, observation_id=observation.id)
                    )
                stale_project = session.get(Project, stale_need.project_id)
                has_support = bool(
                    stale_project and _need_has_current_support(session, stale_need, stale_project)
                )
                if stale_need.active and not has_support:
                    stale_need.active = False
                    session.add(
                        ChangeEvent(
                            observation_id=observation.id,
                            content_hash=digest,
                            kind=(
                                "reclassified"
                                if same_version and prior_interpretation_status == "accepted"
                                else "closed"
                            ),
                        )
                    )
            if current_evidence is not None:
                for impacted_project_id in impacted_project_ids:
                    impacted_project = session.get(Project, impacted_project_id)
                    if impacted_project is not None:
                        apply_lifecycle_observation(
                            session, impacted_project, observation, current_evidence
                        )
        else:
            if permit_assessment:
                counts["permit_accepted"] += 1
            project_name = interpreted["name"]
            activity_key = interpreted["activity_key"]
            rationale = interpreted["rationale"]
            project_location = interpreted.get("location")
            assert project_name is not None and activity_key is not None and rationale is not None
            assert project_location is None or isinstance(project_location, str)
            if project is None:
                asset_identity = stable_asset_identity(record, source.id)
                candidates = session.scalars(select(Project).with_for_update()).all()
                supported: list[tuple[Project, Any]] = []
                decisions: list[tuple[Project, Any]] = []
                permit_alias = (
                    permit_assessment.get("project_hint")
                    if permit_assessment and isinstance(permit_assessment.get("project_hint"), str)
                    else None
                )
                for candidate in candidates:
                    candidate_aliases = (candidate.identity_facts or {}).get("project_aliases", [])
                    same_name = (
                        normalized_identity(candidate.name) == normalized_identity(project_name)
                        or any(
                            normalized_identity(alias) == normalized_identity(project_name)
                            for alias in candidate_aliases
                            if isinstance(alias, str)
                        )
                        or bool(
                            permit_alias
                            and normalized_identity(permit_alias)
                            in {
                                normalized_identity(candidate.name),
                                *{
                                    normalized_identity(alias)
                                    for alias in candidate_aliases
                                    if isinstance(alias, str)
                                },
                            }
                        )
                    )
                    candidate_site = (candidate.identity_facts or {}).get(
                        "site"
                    ) or candidate.location
                    same_site = same_physical_site(candidate_site, project_location) or (
                        physical_site(project_location)
                        and physical_site(candidate.location)
                        and normalized_identity(candidate.location)
                        == normalized_identity(project_location)
                    )
                    same_asset = bool(asset_identity) and candidate.identity_facts.get(
                        "asset_identity"
                    ) == (list(asset_identity) if asset_identity else None)
                    geographic_conflict = conflicting_geography(
                        candidate.location, project_location
                    )
                    decision = decide_project_match(
                        same_address=same_site,
                        same_project_name=same_name,
                        same_asset_identity=same_asset,
                        conflicting_geography=geographic_conflict,
                        conflicting_asset_type=_asset_type_conflicts(
                            candidate.asset_type,
                            classify_event(observation.title, observation.abstract),
                        ),
                    )
                    decisions.append((candidate, decision))
                    if decision.decision == "matched":
                        supported.append((candidate, decision))
                if len(supported) == 1:
                    project = supported[0][0]
                else:
                    project = Project(
                        identity_key=project_key,
                        name=project_name,
                        location=project_location,
                        source_id=source.id,
                        external_id=external_id,
                    )
                    session.add(project)
                    session.flush()
                for candidate, decision in decisions:
                    if (
                        decision.decision == "matched"
                        or len(supported) > 1
                        or decision.matched_facts
                    ):
                        match_row = session.scalar(
                            select(ProjectMatchDecision)
                            .where(
                                ProjectMatchDecision.observation_id == observation.id,
                                ProjectMatchDecision.candidate_project_id == candidate.id,
                                ProjectMatchDecision.evidence_id
                                == session.scalar(
                                    select(Evidence.id).where(
                                        Evidence.observation_id == observation.id,
                                        Evidence.content_hash == evidence_digest,
                                    )
                                ),
                            )
                            .with_for_update()
                        )
                        if match_row is None:
                            match_row = ProjectMatchDecision(
                                observation_id=observation.id,
                                candidate_project_id=candidate.id,
                                decision="separate",
                                reason="Pending identity decision.",
                                matched_facts=[],
                            )
                            session.add(match_row)
                        match_row.decision = (
                            "matched"
                            if len(supported) == 1 and decision.decision == "matched"
                            else "separate"
                        )
                        match_row.reason = (
                            decision.reason
                            if len(supported) <= 1
                            else "Multiple supported project candidates; retained separately."
                        )
                        match_row.matched_facts = list(decision.matched_facts)
                        match_row.evidence_id = session.scalar(
                            select(Evidence.id).where(
                                Evidence.observation_id == observation.id,
                                Evidence.content_hash == evidence_digest,
                            )
                        )
                        match_row.identity_facts = {
                            "project_name": project_name,
                            "site": project_location,
                            "asset_identity": list(asset_identity) if asset_identity else None,
                        }
                if not supported:
                    match_evidence_id = session.scalar(
                        select(Evidence.id).where(
                            Evidence.observation_id == observation.id,
                            Evidence.content_hash == evidence_digest,
                        )
                    )
                    unmatched = session.scalar(
                        select(ProjectMatchDecision).where(
                            ProjectMatchDecision.observation_id == observation.id,
                            ProjectMatchDecision.candidate_project_id.is_(None),
                            ProjectMatchDecision.evidence_id == match_evidence_id,
                        )
                    )
                    if unmatched is None:
                        session.add(
                            ProjectMatchDecision(
                                observation_id=observation.id,
                                candidate_project_id=None,
                                evidence_id=match_evidence_id,
                                decision="separate",
                                reason=(
                                    "No single existing project candidate met "
                                    "conservative identity evidence."
                                ),
                                matched_facts=[],
                                identity_facts={
                                    "project_name": project_name,
                                    "site": project_location,
                                    "asset_identity": list(asset_identity)
                                    if asset_identity
                                    else None,
                                },
                            )
                        )
                if not supported or len(supported) != 1:
                    project.identity_facts = {
                        "asset_identity": list(asset_identity) if asset_identity else None,
                        "site": project_location,
                        "project_name": project_name,
                    }
                elif supported[0][1].decision == "matched":
                    project.identity_facts = {
                        **(project.identity_facts or {}),
                        "asset_identity": list(asset_identity)
                        if asset_identity
                        else (project.identity_facts or {}).get("asset_identity"),
                        "site": project_location or (project.identity_facts or {}).get("site"),
                        "project_name": project_name,
                    }
                if permit_alias:
                    current_facts = dict(project.identity_facts or {})
                    aliases = [
                        value
                        for value in current_facts.get("project_aliases", [])
                        if isinstance(value, str)
                    ]
                    if normalized_identity(permit_alias) not in {
                        normalized_identity(value) for value in aliases
                    }:
                        aliases.append(permit_alias)
                    current_facts["project_aliases"] = aliases
                    project.identity_facts = current_facts
            else:
                project.name = project_name
                if project_location and project.location != project_location:
                    project.location = project_location
            if permit_assessment:
                superseded = session.scalars(
                    select(PowerNeed)
                    .where(
                        PowerNeed.project_id == project.id,
                        PowerNeed.active.is_(True),
                        PowerNeed.activity_key.in_(
                            {
                                "facility-expansion",
                                "backup-power",
                                "temporary-power",
                                "bridge-power",
                                "event-power",
                            }
                        ),
                        PowerNeed.activity_key != activity_key,
                    )
                    .with_for_update()
                ).all()
                for old_need in superseded:
                    old_need.active = False
                    if (
                        session.scalar(
                            select(NeedObservation.id).where(
                                NeedObservation.need_id == old_need.id,
                                NeedObservation.observation_id == observation.id,
                            )
                        )
                        is None
                    ):
                        session.add(
                            NeedObservation(need_id=old_need.id, observation_id=observation.id)
                        )
                    session.add(
                        ChangeEvent(
                            observation_id=observation.id, content_hash=digest, kind="reclassified"
                        )
                    )
                if activity_key == "facility-expansion":
                    news_activity_need = session.scalar(
                        select(PowerNeed)
                        .where(
                            PowerNeed.project_id == project.id,
                            PowerNeed.activity_key == "construction",
                        )
                        .with_for_update()
                    )
                    if news_activity_need is not None:
                        activity_key = "construction"
            need = session.scalar(
                select(PowerNeed)
                .where(
                    PowerNeed.project_id == project.id,
                    PowerNeed.activity_key == activity_key,
                )
                .with_for_update()
            )
            material_change = False
            reopened = need is not None and not need.active
            if need is None:
                need = PowerNeed(
                    project_id=project.id,
                    activity_key=activity_key,
                    tier="Signal",
                    rationale=rationale,
                    supply="Unknown",
                )
                session.add(need)
                session.flush()
                counts["signals"] += 1
                material_change = True
            elif not need.active or need.rationale != rationale or not same_version:
                material_change = True
                need.active = True
                need.rationale = rationale
            if (
                session.scalar(
                    select(NeedObservation.id).where(
                        NeedObservation.need_id == need.id,
                        NeedObservation.observation_id == observation.id,
                    )
                )
                is None
            ):
                session.add(NeedObservation(need_id=need.id, observation_id=observation.id))
            if material_change:
                event_kind = change_kind
                if same_version and prior_interpretation_status in {"accepted", "rejected"}:
                    event_kind = "reclassified"
                elif reopened:
                    event_kind = "reopened"
                session.add(
                    ChangeEvent(
                        observation_id=observation.id,
                        content_hash=digest,
                        kind=event_kind,
                    )
                )
            interpretation.status, interpretation.error = "accepted", None
            lifecycle_evidence = session.scalar(
                select(Evidence).where(
                    Evidence.observation_id == observation.id,
                    Evidence.content_hash == evidence_digest,
                )
            )
            if permit_assessment:
                current_evidence = session.scalar(
                    select(Evidence).where(
                        Evidence.observation_id == observation.id,
                        Evidence.content_hash == evidence_digest,
                    )
                )
                interpretation.evaluator_version = permit_evaluator_version(record)
                interpretation.assessment = _permit_assessment_payload(
                    permit_assessment,
                    current_evidence,
                    record,
                    digest,
                    evidence_digest,
                    prior_assessment,
                    prior_evaluator_version,
                )
                interpretation.assessment["project_identity_key"] = project.identity_key
                interpretation.assessment["power_activity"] = activity_key
            else:
                interpretation.assessment = {
                    "semantic_hash": digest,
                    "evidence_hash": evidence_digest,
                    "decision": "accepted",
                    "project_identity_key": project.identity_key,
                    "power_activity": activity_key,
                    "activity_key": activity_key,
                    "evidence": {
                        "id": str(lifecycle_evidence.id) if lifecycle_evidence else None,
                        "url": lifecycle_evidence.url if lifecycle_evidence else observation.url,
                    },
                }
            if lifecycle_evidence is not None:
                apply_lifecycle_observation(session, project, observation, lifecycle_evidence)

        job = assert_fence(session, job_id, worker_id, fence)
        job.checkpoint = external_id
        job.lease_until = datetime.now(UTC) + timedelta(seconds=90)
        session.commit()
    return counts


def _process_collection_only(
    session: Session,
    job_id: Any,
    worker_id: str,
    fence: int,
    source_definition: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Retain each RSS version, then run the shared deterministic project evaluator."""
    counts: dict[str, Any] = {
        "new": 0,
        "changed": 0,
        "unchanged": 0,
        "signals": 0,
        "retrieved_records": len(records),
        "parsed_records": len(records),
        "records_scanned": len(records),
        "latest_publication_date": None,
        "snapshot_item_count": len(records),
        "snapshot_oldest_publication_date": None,
        "snapshot_newest_publication_date": None,
    }
    publications = [row["publication_date"] for row in records]
    if publications:
        counts["snapshot_oldest_publication_date"] = min(publications)
        counts["snapshot_newest_publication_date"] = max(publications)
        counts["latest_publication_date"] = max(publications)
    for record in records:
        assert_fence(session, job_id, worker_id, fence)
        source = session.get(Source, source_definition["id"])
        assert source is not None
        external_id = record["document_number"]
        digest = _hash(record)
        evidence_digest = record.get("source_hash") or _source_version_hash(record)
        publication = date.fromisoformat(record["publication_date"])
        observation = session.scalar(
            select(Observation)
            .where(Observation.source_id == source.id, Observation.external_id == external_id)
            .with_for_update()
        )
        is_new = observation is None
        same_material_fields = bool(
            observation
            and observation.title == record["title"]
            and " ".join((observation.abstract or "").split())
            == " ".join((record.get("abstract") or "").split())
            and observation.published_at == publication
            and observation.url == record["html_url"]
        )
        if is_new:
            observation = Observation(
                source_id=source.id,
                external_id=external_id,
                title=record["title"],
                abstract=record.get("abstract"),
                published_at=publication,
                url=record["html_url"],
                content_hash=digest,
            )
            session.add(observation)
            session.flush()
            counts["new"] += 1
        elif same_material_fields:
            counts["unchanged"] += 1
        else:
            assert observation is not None
            observation.title, observation.abstract = record["title"], record.get("abstract")
            observation.published_at, observation.url, observation.content_hash = (
                publication,
                record["html_url"],
                digest,
            )
            counts["changed"] += 1
        assert observation is not None

        evidence = session.scalar(
            select(Evidence).where(
                Evidence.observation_id == observation.id,
                Evidence.content_hash == evidence_digest,
            )
        )
        if evidence is None:
            evidence = Evidence(
                observation_id=observation.id,
                content_hash=evidence_digest,
                title=record["title"],
                abstract=record.get("abstract"),
                url=record["html_url"],
                published_at=publication,
                extraction_location=record.get(
                    "extraction_location", "RSS item title and description/summary"
                ),
                event_date=None,
            )
            session.add(evidence)
            session.flush()

        interpretation = session.scalar(
            select(Interpretation)
            .where(Interpretation.observation_id == observation.id)
            .with_for_update()
        )
        reusable = bool(
            interpretation
            and interpretation.status in {"accepted", "rejected"}
            and interpretation.content_hash == digest
            and interpretation.evaluator_version == EVALUATOR_VERSION
            and interpretation.assessment
            and interpretation.assessment.get("semantic_hash") == digest
            and interpretation.assessment.get("evidence_hash") == evidence.content_hash
        )
        if interpretation is None:
            interpretation = Interpretation(
                observation_id=observation.id, content_hash=digest, status="pending", attempts=0
            )
            session.add(interpretation)
        elif not reusable:
            # Keep the previous structured assessment until a replacement commits.
            interpretation.content_hash, interpretation.status, interpretation.error = (
                digest,
                "pending",
                None,
            )
        job = assert_fence(session, job_id, worker_id, fence)
        job.checkpoint = external_id
        job.lease_until = datetime.now(UTC) + timedelta(seconds=90)
        session.commit()  # Evidence and a retryable pending row survive evaluator failure.

        assert_fence(session, job_id, worker_id, fence)
        changed_decision = assess_retained_news(
            session, observation, evidence, job_id=job_id, worker_id=worker_id, fence=fence
        )
        if not changed_decision:
            job = assert_fence(session, job_id, worker_id, fence)
            job.checkpoint = external_id
            job.lease_until = datetime.now(UTC) + timedelta(seconds=90)
        session.commit()
        if interpretation.status == "accepted" and interpretation.assessment:
            counts["signals"] += int(interpretation.assessment.get("tier") == "Signal")
    return counts
