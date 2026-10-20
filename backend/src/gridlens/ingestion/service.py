import hashlib
import json
import re
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import Text, cast, func, or_, select, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from gridlens.domain.call_facts import (
    MAX_CURRENT_OPERATOR_FACT_BYTES_PER_NEED,
    MAX_CURRENT_OPERATOR_FACTS_PER_NEED,
    CurrentOperatorInputBoundExceeded,
    qualification_from_facts,
)
from gridlens.domain.evaluation_clock import evaluation_now
from gridlens.domain.lifecycle import classify_event
from gridlens.domain.news_interpretation import (
    EVALUATOR_VERSION,
    assess_news,
    prospect_power_activity,
    signal_power_activity,
)
from gridlens.domain.permit_interpretation import assess_permit
from gridlens.domain.permit_interpretation import evaluator_version as permit_evaluator_version
from gridlens.domain.power_qualification import qualify_retained_official
from gridlens.domain.qualification import assess_signal
from gridlens.domain.signal_admission import (
    POLICY_VERSION as ADMISSION_POLICY_VERSION,
)
from gridlens.domain.signal_admission import (
    admit_standalone,
    admitted_from_source,
)
from gridlens.domain.taylor_planning import interpret_taylor_planning
from gridlens.ingestion.adapters import (
    retrieve_collection_segment,
    retrieve_companion,
    retrieve_source,
)
from gridlens.ingestion.adapters.acquisition_runtime import remaining_seconds
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.govinfo_pdf import MAX_PDFS_PER_RUN
from gridlens.ingestion.structured_collection import (
    apply_segment_result,
    collection_continuation_needed,
    collection_policy_digest,
    collection_status,
    prepare_collection_progress,
)
from gridlens.intelligence.change_detection import (
    lock_project,
    record_material_diff,
    seed_material_state,
)
from gridlens.intelligence.lifecycle_service import (
    apply_lifecycle_observation,
    apply_planning_withdrawal,
    refresh_lifecycle_projection,
)
from gridlens.intelligence.matching import interpret
from gridlens.intelligence.project_identity import (
    conflicting_geography,
    decide_project_match,
    labeled_site,
    labeled_sites,
    normalized_identity,
    phase_normalized_facility_scope,
    physical_site,
    same_physical_site,
    stable_asset_identity,
)
from gridlens.intelligence.signal_adjudication import POLICY_VERSION
from gridlens.intelligence.signal_adjudication import adjudicate as adjudicate_signal
from gridlens.intelligence.snapshot_presence import reconcile_snapshot
from gridlens.jobs.queue import assert_fence
from gridlens.persistence.models import (
    BuyingChainEvidence,
    CallFactDecision,
    CallFactVersion,
    ChangeEvent,
    Evidence,
    Interpretation,
    Job,
    LifecycleEvent,
    NeedObservation,
    NeedWorkflowStatusEvent,
    Observation,
    PowerNeed,
    Project,
    ProjectMatchDecision,
    SignalDecision,
    Source,
    SourceCollectionProgress,
)

PERMIT_RETRIEVAL_METHODS = {
    "socrata-permits",
    "georgia-air-permits",
    "boston-ckan-permits",
    "houston-weekly-permits",
    "dallas-monthly-permits",
    "el-paso-new-commercial-permits",
    "rrc-drilling-permits",
    "rrc-flare-exceptions",
    "ma-cultivation-applications",
    "tceq-nsr-pending",
    "tceq-temporary-batch-plants",
    "ceqanet-data-centers",
    "fort-worth-permits",
    "san-antonio-permits",
    "tdlr-tabs",
}


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


def _source_link_provenance(record: dict[str, Any], source_id: str) -> dict[str, Any]:
    """Return explicit publisher hrefs as inert provenance metadata."""
    links: dict[str, list[str]] = {}
    if source_id == "nc-commerce":
        source_url = record.get("source_url")
        if isinstance(source_url, str) and source_url:
            links["article"] = [source_url]
    raw_links = None
    if source_id in {"texas-tceq-nsr-pending", "california-ceqanet-data-centers"}:
        permit = record.get("permit")
        raw_links = permit.get("source_link_hrefs") if isinstance(permit, dict) else None
    if isinstance(raw_links, dict):
        for label, value in raw_links.items():
            if isinstance(label, str) and label and isinstance(value, str) and value:
                links[label] = [value]
    return {"raw_source_links": links} if links else {}


def _merge_source_link_provenance(
    current: dict[str, Any] | None, incoming: dict[str, Any]
) -> dict[str, Any]:
    """Union raw href aliases while preserving unrelated retained provenance."""
    merged = dict(current) if isinstance(current, dict) else {}
    old_links = merged.get("raw_source_links")
    old_links = old_links if isinstance(old_links, dict) else {}
    new_links = incoming.get("raw_source_links")
    if not isinstance(new_links, dict):
        return merged
    combined: dict[str, list[str]] = {}
    for label in set(old_links) | set(new_links):
        values: list[str] = []
        for candidate in (old_links.get(label), new_links.get(label)):
            candidates = candidate if isinstance(candidate, list) else [candidate]
            for value in candidates:
                if isinstance(value, str) and value and value not in values:
                    values.append(value)
        if values:
            combined[str(label)] = values
    merged["raw_source_links"] = combined
    return merged


def _taylor_article_identity_conflict(
    records: list[Observation | Evidence | dict[str, Any]],
) -> bool:
    project_labels: set[str] = set()
    site_addresses: set[str] = set()
    project_pattern = re.compile(r"\bProject\s+([A-Z0-9][A-Za-z0-9&'’-]*)\b", re.I)
    address_pattern = re.compile(r"\b\d{1,6}\s+(?:CR|FM|Hwy|Highway)\s+[\w-]+\b", re.I)
    for record in records:
        title = (
            record.title
            if isinstance(record, Observation | Evidence)
            else str(record.get("title") or "")
        )
        abstract = (
            record.abstract
            if isinstance(record, Observation | Evidence)
            else str(record.get("abstract") or "")
        )
        article_text = f"{title} {abstract}"
        project_labels.update(match.casefold() for match in project_pattern.findall(article_text))
        site_addresses.update(
            normalized_identity(match) for match in address_pattern.findall(article_text)
        )
    return len(project_labels) > 1 or len(site_addresses) > 1


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


def _need_has_current_support(
    session: Session,
    need: PowerNeed,
    project: Project,
    *,
    links: list[tuple[Observation, Evidence, Interpretation | None]] | None = None,
    sources: dict[str, Source] | None = None,
) -> bool:
    rows = (
        [(obs, interpretation) for obs, _, interpretation in links]
        if links is not None
        else session.execute(
            select(Observation, Interpretation)
            .join(NeedObservation, NeedObservation.observation_id == Observation.id)
            .outerjoin(Interpretation, Interpretation.observation_id == Observation.id)
            .where(NeedObservation.need_id == need.id)
        ).all()
    )
    for linked_observation, interpretation in rows:
        if (
            interpretation is None
            or interpretation.status != "accepted"
            or interpretation.content_hash != linked_observation.content_hash
        ):
            continue
        assessment = interpretation.assessment or {}
        if assessment.get("semantic_hash") != linked_observation.content_hash:
            continue
        identity_key = assessment.get("project_identity_key")
        if identity_key != project.identity_key:
            continue
        activity = assessment.get("power_activity") or assessment.get("activity_key")
        if activity != need.activity_key:
            continue
        evidence_hash = assessment.get("evidence_hash")
        if not isinstance(evidence_hash, str):
            continue
        evidence = (
            next(
                (
                    ev
                    for obs, ev, _ in links
                    if obs.id == linked_observation.id and ev.content_hash == evidence_hash
                ),
                None,
            )
            if links is not None
            else session.scalar(
                select(Evidence).where(
                    Evidence.observation_id == linked_observation.id,
                    Evidence.content_hash == evidence_hash,
                )
            )
        )
        if evidence is None:
            continue
        source = (
            sources.get(linked_observation.source_id)
            if sources is not None
            else session.get(Source, linked_observation.source_id)
        )
        if source is None or not admitted_from_source(source, assessment, evidence).admitted:
            continue
        return True
    return False


def _need_admission_basis_is_current(session: Session, need: PowerNeed, project: Project) -> bool:
    """Keep an existing citation when another unchanged permit supports the same need."""
    basis = need.admission_basis or {}
    source_id, evidence_hash = basis.get("source_id"), basis.get("evidence_hash")
    if not isinstance(source_id, str) or not isinstance(evidence_hash, str):
        return False
    rows = session.execute(
        select(Observation, Evidence, Interpretation)
        .join(NeedObservation, NeedObservation.observation_id == Observation.id)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .where(
            NeedObservation.need_id == need.id,
            Observation.source_id == source_id,
            Evidence.content_hash == evidence_hash,
        )
    ).all()
    for observation, evidence, interpretation in rows:
        source = session.get(Source, observation.source_id)
        if source is not None and _need_has_current_support(
            session, need, project, links=[(observation, evidence, interpretation)]
        ):
            expected = admitted_from_source(source, interpretation.assessment, evidence).as_basis(
                source.id, evidence.content_hash
            )
            if basis == expected:
                return True
    return False


class _QualificationClaimsSummary:
    """Canonical first-claim and conflict fold shared by full and streamed browse."""

    def __init__(self) -> None:
        self.best: dict[str, Any] | None = None
        self.best_key: tuple[Any, ...] | None = None
        self.field_values: dict[str, Any] = {}
        self.field_conflicts = {"demand_mw": False, "start_window": False, "duration": False}
        self.gap_value: tuple[Any, Any] | None = None
        self.has_gap = False
        self.gap_conflict = False
        self.qualification_conflict = False
        self.has_qualification_version = False
        self.has_claim = False

    def add(self, row: dict[str, Any]) -> None:
        claim = row["claim"]
        key = (row["priority"], row["content_hash"], row["source_id"], row["external_id"])
        if self.best_key is None or key < self.best_key:
            self.best_key = key
            self.best = claim
        self.has_claim = True
        if claim.get("tier") in {"Prospect", "Lead"}:
            for field in ("demand_mw", "start_window", "duration"):
                value = claim.get(field)
                if value is None:
                    continue
                if field not in self.field_values:
                    self.field_values[field] = value
                elif self.field_values[field] != value:
                    self.field_conflicts[field] = True
            gap = claim.get("qualified_remaining_gap")
            if isinstance(gap, dict):
                value = (gap.get("available_mw_min"), gap.get("available_mw_max"))
                if not self.has_gap:
                    self.gap_value = value
                    self.has_gap = True
                elif self.gap_value != value:
                    self.gap_conflict = True
        self.qualification_conflict = self.qualification_conflict or bool(
            claim.get("qualification_conflict")
        )
        self.has_qualification_version = self.has_qualification_version or bool(
            claim.get("qualification_version")
        )

    @property
    def conflicts(self) -> bool:
        return (
            any(self.field_conflicts.values()) or self.gap_conflict or self.qualification_conflict
        )


def _effective_qualification_from_claim(claim: dict[str, Any]) -> dict[str, Any]:
    tier = claim["tier"]
    closed_by_fact = bool(claim.get("closed_by_fact"))
    fact_timing = claim.get("fact_derived_timing")
    lower_tier_timing = (
        fact_timing
        if tier != "Lead" and isinstance(fact_timing, dict) and not closed_by_fact
        else None
    )
    result = {
        "tier": tier,
        "rationale": claim["reason"],
        # Only an explicit accepted-demand intersection may override the source
        # claim for calculation. Source-only claims keep the original projection.
        "required_mw": (
            None if closed_by_fact else claim.get("fact_derived_required_mw") or _reported_mw(claim)
        ),
        "start_window": (
            claim.get("start_window")
            if tier == "Lead"
            else lower_tier_timing.get("start_window")
            if lower_tier_timing
            else None
        ),
        "duration": (
            claim.get("duration")
            if tier == "Lead"
            else lower_tier_timing.get("duration")
            if lower_tier_timing
            else None
        ),
        "supply": (
            "Unknown"
            if closed_by_fact
            else "Reported constraint"
            if tier in {"Prospect", "Lead"}
            else "Unknown"
        ),
        "qualified_remaining_gap": claim.get("qualified_remaining_gap") if tier == "Lead" else None,
        "buying_role": claim.get("buying_role") if tier == "Lead" else None,
        "qualification_next_action": claim.get("qualification_next_action")
        if tier == "Lead"
        else None,
        "qualification_version": claim.get("qualification_version"),
        "qualification_conflict": bool(claim.get("qualification_conflict")),
        "closed_by_fact": closed_by_fact,
        "closure_basis": claim.get("closure_basis") if closed_by_fact else None,
    }
    if lower_tier_timing:
        result["timing_provenance"] = lower_tier_timing
    return result


def _current_need_claims(
    session: Session,
    need: PowerNeed,
    project: Project,
    *,
    links: list[tuple[Observation, Evidence, Interpretation | None]] | None = None,
    sources: dict[str, Source] | None = None,
    research_state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows: list[tuple[Observation, Interpretation | None]]
    if links is None:
        result_rows = session.execute(
            select(Observation, Interpretation)
            .join(NeedObservation, NeedObservation.observation_id == Observation.id)
            .join(Interpretation, Interpretation.observation_id == Observation.id)
            .where(NeedObservation.need_id == need.id)
        ).all()
        rows = [(row[0], row[1]) for row in result_rows]
    else:
        # Browse already loaded the linked, retained evidence versions in the
        # canonical observed-at/hash order. Collapse multiple evidence rows for
        # one observation just as the query above does.
        rows = list(
            {
                observation.id: (observation, interpretation)
                for observation, _evidence, interpretation in links
                if interpretation is not None
            }.values()
        )
    claims: list[dict[str, Any]] = []
    for observation, interpretation in rows:
        if (
            interpretation is None
            or interpretation.status != "accepted"
            or interpretation.content_hash != observation.content_hash
        ):
            continue
        assessment = interpretation.assessment or {}
        if assessment.get("semantic_hash") != observation.content_hash:
            continue
        if assessment.get("project_identity_key") != project.identity_key:
            continue
        activity = assessment.get("power_activity") or assessment.get("activity_key")
        if activity != need.activity_key:
            continue
        evidence_hash = assessment.get("evidence_hash")
        evidence = None
        if isinstance(evidence_hash, str):
            if links is None:
                evidence = session.scalar(
                    select(Evidence).where(
                        Evidence.observation_id == observation.id,
                        Evidence.content_hash == evidence_hash,
                    )
                )
            else:
                evidence = next(
                    (
                        candidate
                        for linked_observation, candidate, _ in links
                        if linked_observation.id == observation.id
                        and candidate.content_hash == evidence_hash
                    ),
                    None,
                )
        source = (
            sources.get(observation.source_id)
            if sources is not None
            else session.get(Source, observation.source_id)
        )
        if (
            evidence is None
            or source is None
            or not admitted_from_source(source, assessment, evidence).admitted
        ):
            continue

        qualified = qualify_retained_official(
            evidence.abstract or "", need.activity_key, project.location
        )
        tier = qualified.get("tier") or (
            "Signal" if assessment.get("qualification_version") else assessment.get("tier")
        )
        reason = qualified.get("reason") or assessment.get("reason") or assessment.get("rationale")
        if qualified:
            claim = {**assessment, **qualified}
        elif tier == "Lead":
            # A stored tier is not authority; the quoted Lead gate must replay.
            continue
        elif tier == "Prospect":
            if (
                not all(
                    isinstance(assessment.get(key), str) and assessment[key].strip()
                    for key in ("demand_mw", "demand_quote", "supply_quote")
                )
                or not isinstance(reason, str)
                or not reason.strip()
            ):
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
                "priority": {"Lead": 0, "Prospect": 1, "Signal": 2}[claim["tier"]],
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
    summary = _QualificationClaimsSummary()
    for row in claims:
        summary.add(row)
    if summary.conflicts and summary.has_qualification_version:
        return [
            {
                "tier": "Signal",
                "demand_mw": None,
                "reason": "Current official power claims conflict; qualification is unresolved.",
                "qualification_conflict": True,
                "_qualification_version_present": summary.has_qualification_version,
            }
        ]
    # New typed public reports may conservatively veto qualification, but
    # never supply its positive prerequisites or award a tier themselves.
    from gridlens.domain.project_research import qualification_veto

    if research_state is None:
        from gridlens.intelligence.project_state import current_research_state

        research_state = current_research_state(session, project.id, need.id).get(str(need.id), {})
    veto = qualification_veto(research_state)
    if claims and veto:
        return [{"tier": "Signal", "demand_mw": None, "reason": veto}]
    return [row["claim"] for row in claims]


class CurrentNeedQualificationAccumulator(_QualificationClaimsSummary):
    """Stream browse links through the same qualification and conflict policy."""

    def __init__(
        self,
        session: Session,
        need: PowerNeed,
        project: Project,
        *,
        sources: dict[str, Source],
        call_facts: list[CallFactVersion] | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self.need = need
        self.project = project
        self.sources = sources
        self.call_facts = call_facts or []

    def add_link(
        self,
        observation: Observation,
        evidence: Evidence,
        interpretation: Interpretation | None,
    ) -> None:
        claims = _current_need_claims(
            self.session,
            self.need,
            self.project,
            links=[(observation, evidence, interpretation)],
            sources=self.sources,
            research_state={},
        )
        for claim in claims:
            if claim.get("_qualification_version_present"):
                self.has_qualification_version = True
            if claim.get("qualification_conflict") and claim["tier"] == "Signal":
                # This is a row-local assessment, so the flag itself is an exact veto.
                self.add(
                    {
                        "claim": claim,
                        "priority": 2,
                        "content_hash": observation.content_hash,
                        "source_id": observation.source_id,
                        "external_id": observation.external_id,
                    }
                )
            else:
                self.add(
                    {
                        "claim": claim,
                        "priority": {"Lead": 0, "Prospect": 1, "Signal": 2}[claim["tier"]],
                        "content_hash": observation.content_hash,
                        "source_id": observation.source_id,
                        "external_id": observation.external_id,
                    }
                )

    def finish(self, research_state: dict[str, Any]) -> dict[str, Any] | None:
        if not self.has_claim or self.best is None:
            return None
        if self.conflicts and self.has_qualification_version:
            return _effective_qualification_from_claim(
                {
                    "tier": "Signal",
                    "demand_mw": None,
                    "reason": (
                        "Current official power claims conflict; qualification is unresolved."
                    ),
                    "qualification_conflict": True,
                }
            )
        from gridlens.domain.project_research import qualification_veto

        veto = qualification_veto(research_state)
        if veto:
            return _effective_qualification_from_claim(
                {"tier": "Signal", "demand_mw": None, "reason": veto}
            )
        claim = qualification_from_facts(
            self.best, self.call_facts, need=self.need, project=self.project
        )
        return _effective_qualification_from_claim(claim or self.best)


def effective_need_qualification(
    session: Session,
    need: PowerNeed,
    project: Project,
    *,
    links: list[tuple[Observation, Evidence, Interpretation | None]] | None = None,
    sources: dict[str, Source] | None = None,
    research_state: dict[str, Any] | None = None,
    call_facts: list[CallFactVersion] | None = None,
) -> dict[str, Any] | None:
    """Read-only replay of current admitted tier fields for API and persistence.

    None means there is no current authoritative claim. This does not modify
    the stored need/interpretation, and never gives supplemental evidence
    positive qualification authority. Stored historical Lead fields are omitted
    when their current gate or interval no longer supports that tier.
    """
    claims = _current_need_claims(
        session,
        need,
        project,
        links=links,
        sources=sources,
        research_state=research_state,
    )
    if not claims:
        return None
    if call_facts is None:
        current_facts_by_need, _statuses = load_current_need_operator_inputs(session, [need.id])
        call_facts = current_facts_by_need.get(need.id, [])
    claim = qualification_from_facts(claims[0], call_facts, need=need, project=project)
    return _effective_qualification_from_claim(claim or claims[0])


def load_current_need_operator_inputs(
    session: Session, need_ids: list[UUID], *, now: datetime | None = None
) -> tuple[dict[UUID, list[CallFactVersion]], dict[UUID, NeedWorkflowStatusEvent]]:
    """Bulk-load only current accepted fact versions and the latest status event."""
    if not need_ids:
        return {}, {}
    current = now or evaluation_now(datetime.now(UTC))
    ranked_decisions = (
        select(
            CallFactDecision,
            func.row_number()
            .over(
                partition_by=CallFactDecision.fact_version_id,
                order_by=CallFactDecision.version.desc(),
            )
            .label("rank"),
        )
        .where(CallFactDecision.need_id.in_(need_ids))
        .subquery()
    )
    current_fact_filter = (
        ranked_decisions.c.rank == 1,
        ranked_decisions.c.decision.in_(["accepted", "corrected"]),
        CallFactVersion.need_id.in_(need_ids),
        CallFactVersion.effective_from <= current,
        or_(CallFactVersion.effective_until.is_(None), CallFactVersion.effective_until > current),
    )
    fact_bytes = sum(
        (
            func.coalesce(func.octet_length(cast(CallFactVersion.value, Text)), 0),
            func.coalesce(func.octet_length(CallFactVersion.facility_scope), 0),
            func.coalesce(func.octet_length(CallFactVersion.source_reference), 0),
            func.coalesce(func.octet_length(CallFactVersion.reporter_name), 0),
            func.coalesce(func.octet_length(CallFactVersion.reporter_organization), 0),
            func.coalesce(func.octet_length(CallFactVersion.reporter_role), 0),
        )
    )
    current_fact_sizes = session.execute(
        select(CallFactVersion.need_id, func.count(CallFactVersion.id), func.sum(fact_bytes))
        .join(ranked_decisions, ranked_decisions.c.fact_version_id == CallFactVersion.id)
        .where(*current_fact_filter)
        .group_by(CallFactVersion.need_id)
    )
    for _need_id, fact_count, fact_byte_count in current_fact_sizes:
        if (
            fact_count > MAX_CURRENT_OPERATOR_FACTS_PER_NEED
            or (fact_byte_count or 0) > MAX_CURRENT_OPERATOR_FACT_BYTES_PER_NEED
        ):
            raise CurrentOperatorInputBoundExceeded(
                "Current accepted operator facts exceed the supported exact-need bound; "
                "no evidence was truncated."
            )
    fact_rows = session.execute(
        select(CallFactVersion, ranked_decisions.c.decision)
        .join(ranked_decisions, ranked_decisions.c.fact_version_id == CallFactVersion.id)
        .where(*current_fact_filter)
        .order_by(CallFactVersion.need_id, CallFactVersion.fact_type, CallFactVersion.content_hash)
    )
    facts: dict[UUID, list[CallFactVersion]] = {}
    for row, _decision in fact_rows:
        facts.setdefault(row.need_id, []).append(row)
    ranked_status = (
        select(
            NeedWorkflowStatusEvent,
            func.row_number()
            .over(
                partition_by=NeedWorkflowStatusEvent.need_id,
                order_by=NeedWorkflowStatusEvent.version.desc(),
            )
            .label("rank"),
        )
        .where(NeedWorkflowStatusEvent.need_id.in_(need_ids))
        .subquery()
    )
    statuses = {
        row.need_id: row
        for row in session.scalars(
            select(NeedWorkflowStatusEvent)
            .join(ranked_status, ranked_status.c.id == NeedWorkflowStatusEvent.id)
            .where(ranked_status.c.rank == 1)
        )
    }
    return facts, statuses


def _apply_current_qualification(session: Session, need: PowerNeed, project: Project) -> None:
    """Replay gates and clear obsolete Lead fields on every authoritative update."""
    effective = effective_need_qualification(session, need, project)
    if effective is None:
        need.tier = "Signal"
        need.rationale = "Current qualification support is unavailable."
        need.required_mw = None
        need.start_window = None
        need.duration = None
        need.supply = "Unknown"
        return
    for key in ("tier", "rationale", "required_mw", "start_window", "duration", "supply"):
        setattr(need, key, effective[key])
    if effective.get("closed_by_fact"):
        need.active = False
    else:
        need.active = True


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


def _attach_news_supplement(
    session: Session,
    observation: Observation,
    evidence: Evidence,
    claim: dict[str, Any],
    payload: dict[str, Any],
    material_baselines: dict[Any, Any] | None = None,
    locked_project_ids: set[Any] | None = None,
) -> tuple[PowerNeed | None, dict[str, Any]]:
    """Attach news only to one already-supported same-project, same-activity need."""
    phase_marker = re.compile(r"\bphases?\b", re.I)
    phase_value = re.compile(
        r"\b(\d+[a-z]?|[ivx]+|one|two|three|four|five|six|seven|eight|nine|ten)\b",
        re.I,
    )
    phase_clause = re.compile(
        r"phases?\s*[-:#]?\s*(?:\d+[a-z]?|[ivx]+|one|two|three|four|five|six|seven|eight|nine|ten)"
        r"(?:\s*(?:,|and|&|to|through|[-–—])\s*(?:\d+[a-z]?|[ivx]+|one|two|three|four|five|six|seven|eight|nine|ten))*",
        re.I,
    )
    phase_names = {
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "nine": "9",
        "ten": "10",
    }

    def phase_scope(text: str) -> tuple[set[str], bool]:
        phases: set[str] = set()
        unknown = False
        for marker in phase_marker.finditer(text):
            clause = phase_clause.match(text, marker.start())
            if clause is None:
                unknown = True
                continue
            values = [
                phase_names.get(value.casefold(), value.casefold())
                for value in phase_value.findall(clause.group())
            ]
            phases.update(values)
        return phases, unknown

    incoming_phases, incoming_phase_unknown = phase_scope(
        f"{observation.title} {observation.abstract or ''}"
    )
    if len(incoming_phases) > 1 or incoming_phase_unknown:
        return None, {
            **payload,
            "admission_status": "supplement_unknown",
            "admission_reason": "Conflicting phase labels; the activity link is UNKNOWN.",
            "phase_candidates": sorted(incoming_phases),
        }
    site_claims = labeled_sites(f"{observation.title} {observation.abstract or ''}")
    if len(site_claims) > 1:
        ambiguity_reason = (
            "Multiple distinct labeled site addresses; the project/activity link is UNKNOWN."
        )
        prior_match = session.scalar(
            select(ProjectMatchDecision).where(
                ProjectMatchDecision.observation_id == observation.id,
                ProjectMatchDecision.candidate_project_id.is_(None),
                ProjectMatchDecision.evidence_id == evidence.id,
            )
        )
        if prior_match is None:
            session.add(
                ProjectMatchDecision(
                    observation_id=observation.id,
                    candidate_project_id=None,
                    evidence_id=evidence.id,
                    decision="separate",
                    reason=ambiguity_reason,
                    matched_facts=[],
                    identity_facts={
                        "project_name": claim.get("subject"),
                        "site_candidates": list(site_claims),
                    },
                )
            )
        else:
            prior_match.reason = ambiguity_reason
            prior_match.identity_facts = {
                "project_name": claim.get("subject"),
                "site_candidates": list(site_claims),
            }
        return None, {
            **payload,
            "admission_status": "supplement_unknown",
            "admission_reason": ambiguity_reason,
            "site_candidates": list(site_claims),
        }
    incoming_site = site_claims[0] if site_claims else claim.get("location")
    matching_projects: list[Project] = []
    phase_conflict = False
    for candidate in session.scalars(select(Project)).all():
        aliases = (candidate.identity_facts or {}).get("project_aliases", [])
        same_name = normalized_identity(candidate.name) == normalized_identity(
            claim.get("subject")
        ) or any(
            isinstance(alias, str)
            and normalized_identity(alias) == normalized_identity(claim.get("subject"))
            for alias in aliases
        )
        candidate_site = (candidate.identity_facts or {}).get("site") or candidate.location
        same_site = same_physical_site(candidate_site, incoming_site)
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
        if decision.decision != "matched":
            continue
        if locked_project_ids is not None and candidate.id not in locked_project_ids:
            raise RuntimeError("Retained project candidate changed after ordered locks")
        retained_rows = session.execute(
            select(Evidence, Observation, Interpretation)
            .join(Observation, Observation.id == Evidence.observation_id)
            .join(NeedObservation, NeedObservation.observation_id == Observation.id)
            .join(PowerNeed, PowerNeed.id == NeedObservation.need_id)
            .join(Interpretation, Interpretation.observation_id == Observation.id)
            .where(PowerNeed.project_id == candidate.id, PowerNeed.active.is_(True))
        ).all()
        project_phases: set[str] = set()
        project_phase_unknown = False
        for prior_evidence, prior_observation, prior_interpretation in retained_rows:
            prior_source = session.get(Source, prior_observation.source_id)
            prior_assessment = prior_interpretation.assessment or {}
            if (
                prior_source is None
                or not admitted_from_source(prior_source, prior_assessment, prior_evidence).admitted
            ):
                continue
            prior_phases, prior_unknown = phase_scope(
                f"{prior_evidence.title} {prior_evidence.abstract or ''}"
            )
            project_phases.update(prior_phases)
            project_phase_unknown = project_phase_unknown or prior_unknown
        candidate_phase = (candidate.identity_facts or {}).get("phase")
        if isinstance(candidate_phase, str):
            project_phases.add(candidate_phase.casefold())
        if incoming_phases != project_phases and (incoming_phases or project_phases):
            phase_conflict = True
            continue
        if project_phase_unknown or len(project_phases) > 1:
            phase_conflict = True
            continue
        matching_projects.append(candidate)
    if len(matching_projects) != 1:
        status = (
            "supplement_unknown" if phase_conflict or matching_projects else "supplement_unmatched"
        )
        reason = (
            "Conflicting phase evidence; the project/activity link is UNKNOWN."
            if phase_conflict
            else "No supported physical project matched this news item; it remains context only."
            if not matching_projects
            else "Multiple physical projects matched this news item; the project link is UNKNOWN."
        )
        prior_match = session.scalar(
            select(ProjectMatchDecision).where(
                ProjectMatchDecision.observation_id == observation.id,
                ProjectMatchDecision.candidate_project_id.is_(None),
                ProjectMatchDecision.evidence_id == evidence.id,
            )
        )
        if prior_match is None:
            session.add(
                ProjectMatchDecision(
                    observation_id=observation.id,
                    candidate_project_id=None,
                    evidence_id=evidence.id,
                    decision="separate",
                    reason=reason,
                    matched_facts=[],
                    identity_facts={
                        "project_name": claim.get("subject"),
                        "site": incoming_site,
                        "site_candidates": list(site_claims),
                    },
                )
            )
        else:
            prior_match.reason = reason
            prior_match.identity_facts = {
                "project_name": claim.get("subject"),
                "site": incoming_site,
                "site_candidates": list(site_claims),
            }
        return None, {**payload, "admission_status": status, "admission_reason": reason}

    project = matching_projects[0]
    if material_baselines is not None:
        if project.id not in material_baselines:
            material_baselines[project.id] = seed_material_state(session, project)
    requested_activity = payload.get("power_activity")
    if requested_activity == "construction":
        requested_activity = "facility-expansion"
    need = session.scalar(
        select(PowerNeed)
        .where(
            PowerNeed.project_id == project.id,
            PowerNeed.activity_key == requested_activity,
            PowerNeed.active.is_(True),
        )
        .with_for_update()
    )
    if need is None or not _need_has_current_support(session, need, project):
        return None, {
            **payload,
            "admission_status": "supplement_unmatched",
            "admission_reason": (
                "The matched project has no currently admitted need for this activity."
            ),
        }
    match = session.scalar(
        select(ProjectMatchDecision).where(
            ProjectMatchDecision.observation_id == observation.id,
            ProjectMatchDecision.candidate_project_id == project.id,
            ProjectMatchDecision.evidence_id == evidence.id,
        )
    )
    if match is None:
        session.add(
            ProjectMatchDecision(
                observation_id=observation.id,
                candidate_project_id=project.id,
                evidence_id=evidence.id,
                decision="matched",
                reason=(
                    "Identity supported by physical address and project name/alias; "
                    "news is supplemental."
                ),
                matched_facts=["physical address", "project name/alias"],
                identity_facts={
                    "project_name": claim.get("subject"),
                    "site": incoming_site,
                    "site_candidates": list(site_claims),
                },
            )
        )
    else:
        match.decision = "matched"
        match.reason = (
            "Identity supported by physical address and project name/alias; news is supplemental."
        )
        match.matched_facts = ["physical address", "project name/alias"]
        match.identity_facts = {
            "project_name": claim.get("subject"),
            "site": incoming_site,
            "site_candidates": list(site_claims),
        }
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
    payload.update(
        {
            "project_identity_key": project.identity_key,
            "power_activity": need.activity_key,
            "admission_status": "supplemental",
            "admission_reason": (
                "News is attached as supplemental evidence to an admitted project need."
            ),
        }
    )
    return need, payload


def _retained_candidate_lock_ids(
    projects: Sequence[Project],
    observation: Observation,
    claim: dict[str, Any],
    admitted: bool,
    target_identity: str | None,
) -> set[Any]:
    """Discover every possible retained match-decision FK before ordered locks."""
    ids = {
        project.id
        for project in projects
        if target_identity and project.identity_key == target_identity
    }
    if admitted and ids:
        return ids
    if claim.get("decision") != "accepted" or not claim.get("subject") or not claim.get("location"):
        return ids
    site_claims = labeled_sites(f"{observation.title} {observation.abstract or ''}")
    incoming_site = site_claims[0] if len(site_claims) == 1 else claim.get("location")
    ambiguous_sites = len(site_claims) > 1
    matched = 0
    asset_type = classify_event(observation.title, observation.abstract)
    for project in projects:
        aliases = (project.identity_facts or {}).get("project_aliases", [])
        same_name = normalized_identity(project.name) == normalized_identity(
            claim["subject"]
        ) or any(
            isinstance(alias, str)
            and normalized_identity(alias) == normalized_identity(claim["subject"])
            for alias in aliases
        )
        site = (project.identity_facts or {}).get("site") or project.location
        same_site = same_physical_site(site, incoming_site)
        if not admitted:
            if same_name or same_site:
                ids.add(project.id)
            continue
        decision = decide_project_match(
            same_address=same_site and not ambiguous_sites,
            same_project_name=same_name,
            conflicting_geography=bool(conflicting_geography(project.location, claim["location"])),
            conflicting_asset_type=_asset_type_conflicts(project.asset_type, asset_type),
        )
        if decision.matched_facts:
            ids.add(project.id)
        if decision.decision == "matched":
            matched += 1
    # The existing ambiguous-match branch writes a separate decision even for
    # candidates with no matched facts. Preserve that behavior and its locks.
    if admitted and matched > 1:
        ids.update(project.id for project in projects)
    return ids


def assess_retained_news(
    session: Session,
    observation: Observation,
    evidence: Evidence,
    *,
    job_id: Any | None = None,
    worker_id: str | None = None,
    fence: int | None = None,
    rejection_reason: str | None = None,
    lease_expiry: datetime | None = None,
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
        rejection_reason is None
        and interpretation.status in {"accepted", "rejected"}
        and interpretation.content_hash == observation.content_hash
        and interpretation.evaluator_version == EVALUATOR_VERSION
        and interpretation.assessment is not None
        and interpretation.assessment.get("semantic_hash") == observation.content_hash
        and interpretation.assessment.get("evidence_hash") == evidence.content_hash
        and interpretation.assessment.get("admission_policy_version") == ADMISSION_POLICY_VERSION
        and interpretation.assessment.get("admission_status")
        not in {"supplement_unmatched", "supplement_unknown"}
    ):
        return False
    if job_id is not None:
        assert worker_id is not None and fence is not None
        assert_fence(session, job_id, worker_id, fence)

    prior_assessment = interpretation.assessment
    prior_identity = prior_assessment.get("project_identity_key") if prior_assessment else None
    source = session.get(Source, observation.source_id)
    if source is None:
        interpretation.status = "failed"
        interpretation.error = "SourceMissing"
        interpretation.attempts += 1
        session.flush()
        return False
    try:
        if rejection_reason is not None:
            # An acquisition/admission policy rejection is not a source fact.
            # Reuse the canonical correction path to retract prior support.
            claim = assess_news("", None).as_dict()
            claim["reason"] = rejection_reason
        else:
            claim = assess_news(observation.title, observation.abstract).as_dict()
        payload = _assessment_payload(observation, evidence, claim)
        payload["admission_policy_version"] = ADMISSION_POLICY_VERSION
        if rejection_reason is not None:
            payload["admission_status"] = "research_quarantine"
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
            or (prior_assessment or {}).get("admission_policy_version") != ADMISSION_POLICY_VERSION
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

    admission = admit_standalone(
        source_id=source.id,
        family=source.family,
        retrieval_method=source.retrieval_method,
        accepted=claim.get("decision") == "accepted",
        activity=activity_key,
        title=evidence.title,
        abstract=evidence.abstract,
    )

    old_project_ids = set(
        session.scalars(
            select(PowerNeed.project_id)
            .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
            .where(NeedObservation.observation_id == observation.id)
        ).all()
    )
    # Retained lifecycle/relationship history can outlive a need link. Its
    # support also changes when this interpretation is rebound or withdrawn.
    old_project_ids.update(
        session.scalars(
            select(LifecycleEvent.project_id).where(LifecycleEvent.observation_id == observation.id)
        ).all()
    )
    old_project_ids.update(
        session.scalars(
            select(BuyingChainEvidence.project_id)
            .join(Evidence, Evidence.id == BuyingChainEvidence.retained_evidence_id)
            .where(Evidence.observation_id == observation.id)
        ).all()
    )
    # Resolve every plausible existing target before locking any PowerNeed.
    # A retained version can be reassigned to a different supported project;
    # acquire old and candidate project/advisory locks in one stable order.
    candidate_project_ids = set(old_project_ids)
    candidate_projects = session.scalars(select(Project)).all()
    target_identity = payload.get("project_identity_key")
    candidate_project_ids.update(
        _retained_candidate_lock_ids(
            candidate_projects, observation, claim, admission.admitted, target_identity
        )
    )
    for candidate_project_id in sorted(candidate_project_ids, key=str):
        lock_project(session, candidate_project_id)
    # Discovery is read-only. A newly relevant FK target must not acquire a
    # late, out-of-order project lock after this point.
    current_candidates = session.scalars(
        select(Project).execution_options(populate_existing=True)
    ).all()
    current_project_ids = set(old_project_ids) | _retained_candidate_lock_ids(
        current_candidates, observation, claim, admission.admitted, target_identity
    )
    if not current_project_ids.issubset(candidate_project_ids):
        raise RuntimeError("Retained project candidate changed after ordered locks")
    # Capture persisted semantic state before an accepted decision is replaced
    # by a rejection/correction. This is deliberately before Interpretation is
    # invalidated so negative evidence can emit a real closure transition.
    # Lock projects before needs to match process_job's project -> advisory ->
    # need ordering and avoid a retained-news/permit lock inversion.
    material_baselines = {}
    for old_project_id in sorted(old_project_ids, key=str):
        old_project = session.get(Project, old_project_id)
        if old_project is not None:
            material_baselines[old_project.id] = seed_material_state(session, old_project)
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
    supplemental_only = claim["decision"] == "accepted" and not admission.admitted
    if supplemental_only:
        current_need, payload = _attach_news_supplement(
            session,
            observation,
            evidence,
            claim,
            payload,
            material_baselines,
            candidate_project_ids,
        )
        payload["admission_origin"] = admission.origin
        interpretation.assessment = {**payload}
        flag_modified(interpretation, "assessment")
    elif claim["decision"] == "accepted":
        identity_key = payload["project_identity_key"]
        project = session.scalar(
            select(Project)
            .where(Project.identity_key == identity_key)
            .execution_options(populate_existing=True)
        )
        if project is not None and project.id not in candidate_project_ids:
            raise RuntimeError("Retained project candidate changed after ordered locks")
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
            candidates = session.scalars(
                select(Project).execution_options(populate_existing=True)
            ).all()
            current_project_ids = _retained_candidate_lock_ids(
                candidates, observation, claim, True, identity_key
            )
            if not current_project_ids.issubset(candidate_project_ids):
                raise RuntimeError("Retained project candidate changed after ordered locks")
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
                        if len(matching_candidates) == 1 and not ambiguous_sites
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
        if project.id not in material_baselines:
            material_baselines[project.id] = seed_material_state(session, project)
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
        current_need.admission_basis = admission.as_basis(source.id, evidence.content_hash)
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
    if (
        current_need is not None
        and prior_assessment
        and prior_assessment.get("admission_status")
        in {"supplement_unmatched", "supplement_unknown"}
        and payload.get("admission_status") == "supplemental"
    ):
        session.add(
            ChangeEvent(
                observation_id=observation.id,
                content_hash=observation.content_hash,
                kind="supplemented",
            )
        )
    impacted = (
        session.scalars(
            select(PowerNeed).where(PowerNeed.id.in_(impacted_ids)).with_for_update()
        ).all()
        if impacted_ids
        else []
    )
    # Rebinding or rejecting retained evidence can invalidate lifecycle and
    # relationship support even when another observation keeps the old need
    # active. Rebuild every prior project under its existing material lock.
    materially_changed_projects: set[Any] = set(old_project_ids)
    for old_project_id in old_project_ids:
        old_project = session.get(Project, old_project_id)
        if old_project is not None:
            refresh_lifecycle_projection(session, old_project)
    for need in impacted:
        project = session.get(Project, need.project_id)
        if project is None:
            continue
        supported = _need_has_current_support(session, need, project)
        if need.active and not supported:
            need.active = False
            need.tier = "Signal"
            need.required_mw = None
            need.start_window = need.duration = None
            need.supply = "Unknown"
            need.rationale = "No current accepted evidence supports this activity."
            session.add(
                ChangeEvent(
                    observation_id=observation.id,
                    content_hash=observation.content_hash,
                    kind="closed",
                )
            )
            materially_changed_projects.add(project.id)
        elif supported:
            _apply_current_qualification(session, need, project)
            # A supported retained-news decision may create a need or alter its
            # tier/load/supply without taking the rejection/closure path below.
            materially_changed_projects.add(project.id)
    # A rejected correction is authoritative about the prior accepted state
    # becoming unsupported. It therefore records a material transition with
    # its immutable Evidence version, while unchanged replay has no diff.
    for project_id in materially_changed_projects:
        baseline = material_baselines[project_id]
        project = session.get(Project, project_id)
        if project is not None:
            record_material_diff(session, project, evidence, baseline)
    if current_need is not None and interpretation.status == "accepted":
        from gridlens.intelligence.buying_chain import enqueue_retained_buying_chain_research

        enqueue_retained_buying_chain_research(
            session,
            current_need.project_id,
            evidence.id,
            evidence.content_hash,
            ADMISSION_POLICY_VERSION,
        )
    # Reassign after in-place edits so SQLAlchemy marks the JSON value dirty.
    interpretation.assessment = {**payload}
    flag_modified(interpretation, "assessment")
    if job_id is not None:
        assert worker_id is not None and fence is not None
        job = assert_fence(session, job_id, worker_id, fence)
        job.checkpoint = observation.external_id
        _advance_job_lease(job, lease_expiry)
    session.flush()
    return True


def process_job(
    session: Session,
    job_id: Any,
    worker_id: str,
    fence: int,
    source_definition: dict[str, Any],
    client: httpx.Client | None = None,
    *,
    deadline: float | None = None,
    lease_expiry: datetime | None = None,
) -> dict[str, Any]:
    if source_definition.get("retrieval_method") in {
        "socrata-permits",
        "boston-ckan-permits",
    }:
        return _process_structured_collection_segment(
            session,
            job_id,
            worker_id,
            fence,
            source_definition,
            client,
            deadline=deadline,
            lease_expiry=lease_expiry,
        )
    if source_definition.get("retrieval_method") == "publisher-rss":
        retrieved = _retrieve_publisher_rss_conditionally(
            session, job_id, worker_id, fence, source_definition, client, deadline=deadline
        )
        if getattr(retrieved, "not_modified", False):
            source = _current_rss_source(session, source_definition)
            cached = (source.health or {}).get("publisher_rss_conditional", {})
            assert_fence(session, job_id, worker_id, fence)
            source.health = {
                **(source.health or {}),
                _RSS_CONDITIONAL_NAMESPACE: {
                    **cached,
                    "complete": True,
                    "last_checked_at": datetime.now(UTC).isoformat(),
                    "etag": getattr(retrieved, "etag", None) or cached.get("etag"),
                    "last_modified": getattr(retrieved, "last_modified", None)
                    or cached.get("last_modified"),
                },
            }
            # Keep the last complete snapshot facts; a 304 is a successful check,
            # not an empty snapshot and never a withdrawal signal.
            return {
                "new": 0,
                "changed": 0,
                "unchanged": 0,
                "signals": 0,
                "retrieved_records": 0,
                "parsed_records": 0,
                "records_scanned": 0,
                "latest_publication_date": cached.get("latest_publication_date"),
                "snapshot_item_count": cached.get("snapshot_item_count", 0),
                "snapshot_oldest_publication_date": cached.get("snapshot_oldest_publication_date"),
                "snapshot_newest_publication_date": cached.get("snapshot_newest_publication_date"),
                "conditional_checked": True,
            }
        counts = _process_collection_only(
            session,
            job_id,
            worker_id,
            fence,
            source_definition,
            [record for record in retrieved if not record.get("presence_only")],
            deadline=deadline,
            lease_expiry=lease_expiry,
        )
        remaining_seconds(deadline)
        _store_publisher_rss_checkpoint(
            session, job_id, worker_id, fence, source_definition, retrieved, counts
        )
        return counts

    retrieved = _retrieve_source_outside_transaction(
        session, job_id, worker_id, fence, source_definition, client, deadline=deadline
    )
    # Presence-only rows are listed by the source but withheld from processing this run
    # (for example, enrichment failed). They still count as present in the snapshot.
    records = [record for record in retrieved if not record.get("presence_only")]
    counts = process_records(
        session,
        job_id,
        worker_id,
        fence,
        source_definition,
        records,
        client=client,
        deadline=deadline,
        lease_expiry=lease_expiry,
    )
    if source_definition.get("snapshot_complete"):
        remaining_seconds(deadline)
        assert_fence(session, job_id, worker_id, fence)
        transitions = reconcile_snapshot(
            session,
            source_definition["id"],
            {str(record["document_number"]) for record in retrieved},
        )
        counts.update(transitions)
        # A listing departure or return is a source change; health must not read "No Change".
        counts["changed"] = counts.get("changed", 0) + sum(transitions.values())
        session.commit()
    return counts


def _collection_progress_checkpoint(
    progress: SourceCollectionProgress,
) -> tuple[
    str,
    str,
    str,
    datetime | None,
    datetime | None,
    datetime | None,
    str,
    str | None,
    datetime | None,
    datetime,
    str,
]:
    """Return immutable progress identity captured before public acquisition."""
    serialized_cursor = json.dumps(progress.cursor or {}, sort_keys=True, separators=(",", ":"))
    return (
        progress.source_id,
        progress.lane,
        progress.policy_digest,
        progress.window_start,
        progress.window_end,
        progress.completed_through,
        progress.status,
        progress.error_class,
        progress.last_attempt_at,
        progress.updated_at,
        serialized_cursor,
    )


def _process_structured_collection_segment(
    session: Session,
    job_id: Any,
    worker_id: str,
    fence: int,
    source_definition: dict[str, Any],
    client: httpx.Client | None,
    *,
    deadline: float | None,
    lease_expiry: datetime | None,
) -> dict[str, Any]:
    progress, digest, lanes = prepare_collection_progress(session, source_definition)
    lane = progress.lane
    window_start = progress.window_start
    window_end = progress.window_end
    if window_start is None or window_end is None:
        raise SourceParseError("Structured collection progress has no date window")
    start_day = window_start.astimezone(UTC).date()
    end_day = window_end.astimezone(UTC).date()
    cursor = dict(progress.cursor or {})
    expected_progress_state = _collection_progress_checkpoint(progress)
    progress_id = progress.id
    # Persist the attempt before releasing the database session for public I/O.
    session.commit()
    _prepare_acquisition_network(session, job_id, worker_id, fence, source_definition)
    result: dict[str, Any]
    acquisition_started_at = None
    acquisition_completed_at = None
    from gridlens.ingestion.registry import load_registry

    try:
        preflight_definition = next(
            (item for item in load_registry() if item.get("id") == source_definition["id"]),
            None,
        )
        if preflight_definition is None or collection_policy_digest(preflight_definition) != digest:
            result = {
                "records": [],
                "cursor": cursor,
                "partial": True,
                "error_class": "CollectionPolicyChanged",
                "window_complete": False,
                "expected_count": None,
                "observed_count": 0,
            }
        else:
            remaining_seconds(deadline)
            acquisition_started_at = session.scalar(text("SELECT clock_timestamp()"))
            session.commit()
            result = retrieve_collection_segment(
                source_definition,
                lane,
                start_day,
                end_day,
                cursor,
                client,
                deadline=deadline,
            )
            remaining_seconds(deadline)
    except SourceParseError as exc:
        from gridlens.ingestion.adapters.diagnostics import acquisition_diagnostics

        result = {
            "records": [],
            "cursor": cursor,
            "partial": True,
            "error_class": type(exc).__name__,
            **acquisition_diagnostics(exc),
            "window_complete": False,
            "expected_count": None,
            "observed_count": 0,
        }

    source = _lock_current_acquisition_source(session, job_id, worker_id, fence, source_definition)
    try:
        live_definition = next(
            (item for item in load_registry() if item.get("id") == source.id), None
        )
    except Exception:
        live_definition = None
    if live_definition is None or collection_policy_digest(live_definition) != digest:
        result = {
            "records": [],
            "cursor": cursor,
            "partial": True,
            "error_class": "CollectionPolicyChanged",
            "window_complete": False,
            "expected_count": result.get("expected_count"),
            "observed_count": 0,
        }
    records = result.get("records", [])
    if (
        not isinstance(records, list)
        or len(records) > 1000
        or any(not isinstance(record, dict) for record in records)
    ):
        raise SourceParseError("Structured source segment exceeded its record bound")
    current_progress = session.scalar(
        select(SourceCollectionProgress)
        .where(SourceCollectionProgress.id == progress_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if (
        current_progress is None
        or _collection_progress_checkpoint(current_progress) != expected_progress_state
    ):
        # A duplicate/stale worker may retain useful fetched rows, but cannot
        # checkpoint or claim completeness after another worker advanced it.
        result = {
            **result,
            "partial": True,
            "error_class": "CollectionCheckpointChanged",
            "cursor": cursor,
            "window_complete": False,
        }
    counts = process_records(
        session,
        job_id,
        worker_id,
        fence,
        source_definition,
        records,
        client=client,
        commit=False,
        deadline=deadline,
        lease_expiry=lease_expiry,
    )
    # Evidence is durable before the progress checkpoint. A crash between these
    # commits safely replays the same source rows and deduplicates evidence.
    segment_job = assert_fence(session, job_id, worker_id, fence)
    if records:
        last_external_id = str(records[-1]["document_number"])
        try:
            prior_checkpoint = json.loads(segment_job.checkpoint or "{}")
        except (TypeError, ValueError):
            prior_checkpoint = None
        if isinstance(prior_checkpoint, dict) and (
            prior_checkpoint.get("collection_continuation") is True
            or "collection_jobs_remaining" in prior_checkpoint
        ):
            segment_job.checkpoint = json.dumps(
                {
                    **prior_checkpoint,
                    "last_record_external_id": last_external_id,
                },
                sort_keys=True,
            )
        else:
            segment_job.checkpoint = last_external_id
    session.commit()
    acquisition_completed_at = session.scalar(text("SELECT clock_timestamp()"))

    source = _lock_current_acquisition_source(session, job_id, worker_id, fence, source_definition)
    try:
        latest_definition = next(
            (item for item in load_registry() if item.get("id") == source.id), None
        )
    except Exception:
        latest_definition = None
    latest_progress = session.scalar(
        select(SourceCollectionProgress)
        .where(SourceCollectionProgress.id == progress_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if (
        latest_definition is None
        or collection_policy_digest(latest_definition) != digest
        or latest_progress is None
        or _collection_progress_checkpoint(latest_progress) != expected_progress_state
    ):
        result = {
            **result,
            "partial": True,
            "error_class": "CollectionCheckpointChanged",
            "cursor": cursor,
            "window_complete": False,
        }
        progress_partial = True
        current_complete = all_complete = False
        continuation = False
    else:
        progress_partial = bool(result.get("partial"))
        completed_at = session.scalar(text("SELECT clock_timestamp()"))
        apply_segment_result(latest_progress, result, now=completed_at)
        current_complete, all_complete = collection_status(session, source.id, digest, lanes)
        continuation = not progress_partial and collection_continuation_needed(
            session,
            source.id,
            digest,
            lanes,
            source=source_definition,
        )
        if progress_partial:
            current_complete = all_complete = False
    counts.update(
        {
            "collection_lane": lane,
            "collection_status": "COMPLETE" if all_complete else "PARTIAL",
            "collection_current_complete": current_complete,
            "collection_continuation": continuation,
            "collection_window_start": start_day.isoformat(),
            "collection_window_end": end_day.isoformat(),
            "collection_expected_count": result.get("expected_count"),
            "collection_observed_count": result.get("observed_count", len(records)),
            "collection_error_class": result.get("error_class"),
            "collection_error_code": result.get("error_code"),
            "collection_error_stage": result.get("error_stage"),
            "collection_http_status": result.get("http_status"),
            "acquisition_started_at": acquisition_started_at.isoformat()
            if acquisition_started_at
            else None,
            "acquisition_completed_at": acquisition_completed_at.isoformat()
            if acquisition_completed_at
            else None,
            "partial": not all_complete,
        }
    )
    if result.get("partial"):
        counts["parse_failures"] = int(counts.get("parse_failures", 0)) + 1
    session.commit()
    return counts


_RSS_CONDITIONAL_NAMESPACE = "publisher_rss_conditional"
_RSS_PARSER_VERSION = "publisher-rss-v2"


def _advance_job_lease(job: Job, original_expiry: datetime | None) -> None:
    now = datetime.now(UTC)
    extension = now + timedelta(seconds=90)
    if original_expiry is not None:
        extension = min(extension, original_expiry + timedelta(seconds=5))
    if job.lease_until is None or extension > job.lease_until:
        job.lease_until = extension


def _require_clean_acquisition_session(session: Session) -> None:
    if session.new or session.dirty or session.deleted or session.in_nested_transaction():
        raise RuntimeError(
            "Acquisition network retrieval requires a clean, non-nested session; "
            "commit caller changes before retrieval"
        )


def _lock_current_acquisition_source(
    session: Session,
    job_id: Any,
    worker_id: str,
    fence: int,
    source_definition: dict[str, Any],
) -> Source:
    session.execute(text("SET LOCAL lock_timeout = '500ms'"))
    session.execute(text("SET LOCAL statement_timeout = '2500ms'"))
    job = assert_fence(session, job_id, worker_id, fence)
    source = session.scalar(
        select(Source)
        .where(Source.id == source_definition["id"])
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        source is None
        or not source.enabled
        or not source.registry_enabled
        or source.retrieval_method != source_definition.get("retrieval_method")
    ):
        raise SourceParseError("Acquisition source is currently disabled or changed")
    if source_definition.get("endpoint") and source.endpoint != source_definition["endpoint"]:
        raise SourceParseError("Acquisition source endpoint changed")
    if job.source_id != source.id:
        raise SourceParseError("Acquisition lease belongs to a different source")
    return source


def _prepare_acquisition_network(
    session: Session,
    job_id: Any,
    worker_id: str,
    fence: int,
    source_definition: dict[str, Any],
) -> None:
    _require_clean_acquisition_session(session)
    _lock_current_acquisition_source(session, job_id, worker_id, fence, source_definition)
    # This function refuses caller-owned writes before releasing row locks.
    if session.in_transaction():
        session.commit()


def _retrieve_source_outside_transaction(
    session: Session,
    job_id: Any,
    worker_id: str,
    fence: int,
    source_definition: dict[str, Any],
    client: httpx.Client | None,
    *,
    deadline: float | None = None,
) -> list[dict[str, Any]]:
    _prepare_acquisition_network(session, job_id, worker_id, fence, source_definition)
    remaining_seconds(deadline)
    records = (
        retrieve_source(source_definition, client)
        if deadline is None
        else retrieve_source(source_definition, client, deadline=deadline)
    )
    remaining_seconds(deadline)
    _lock_current_acquisition_source(session, job_id, worker_id, fence, source_definition)
    return records


def _retrieve_companion_outside_transaction(
    session: Session,
    job_id: Any,
    worker_id: str,
    fence: int,
    source_definition: dict[str, Any],
    record: dict[str, Any],
    client: httpx.Client | None,
    *,
    deadline: float | None = None,
) -> list[dict[str, str]]:
    _prepare_acquisition_network(session, job_id, worker_id, fence, source_definition)
    remaining_seconds(deadline)
    citations = (
        retrieve_companion(record, client)
        if deadline is None
        else retrieve_companion(record, client, deadline=deadline)
    )
    remaining_seconds(deadline)
    _lock_current_acquisition_source(session, job_id, worker_id, fence, source_definition)
    return citations


def _rss_policy_digest(source_definition: dict[str, Any]) -> str:
    policy = {
        "id": source_definition.get("id"),
        "endpoint": source_definition.get("endpoint"),
        "query": source_definition.get("query"),
        "retrieval_method": source_definition.get("retrieval_method"),
        "publisher": source_definition.get("publisher"),
        "parser_version": _RSS_PARSER_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "admission_policy_version": ADMISSION_POLICY_VERSION,
    }
    return hashlib.sha256(
        json.dumps(policy, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _retrieve_publisher_rss_conditionally(
    session: Session,
    job_id: Any,
    worker_id: str,
    fence: int,
    source_definition: dict[str, Any],
    client: httpx.Client | None,
    *,
    deadline: float | None = None,
) -> list[dict[str, Any]]:
    _require_clean_acquisition_session(session)
    source = _lock_current_acquisition_source(session, job_id, worker_id, fence, source_definition)
    cache = (source.health or {}).get(_RSS_CONDITIONAL_NAMESPACE, {})
    job = session.get(Job, job_id)
    if job is None:
        raise SourceParseError("RSS job disappeared before retrieval")
    checkpoint = job.checkpoint
    in_progress = False
    forced = False
    if checkpoint:
        try:
            checkpoint_value = json.loads(checkpoint)
        except (TypeError, ValueError):
            in_progress = True
        else:
            if isinstance(checkpoint_value, dict):
                forced = checkpoint_value.get("force") is True
                in_progress = any(key != "force" for key in checkpoint_value)
            else:
                in_progress = True
    eligible = bool(
        not forced
        and not in_progress
        and source.enabled is True
        and source.registry_enabled is True
        and cache.get("complete") is True
        and cache.get("endpoint") == source_definition.get("endpoint")
        and cache.get("parser_version") == _RSS_PARSER_VERSION
        and cache.get("policy_digest") == _rss_policy_digest(source_definition)
        and (cache.get("etag") or cache.get("last_modified"))
    )
    if client is None and deadline is not None:
        request_headers = {}
        if eligible and cache.get("etag"):
            request_headers["If-None-Match"] = cache["etag"]
        if eligible and cache.get("last_modified"):
            request_headers["If-Modified-Since"] = cache["last_modified"]
        if session.in_transaction():
            session.commit()
        remaining_seconds(deadline)
        retrieved = retrieve_source(
            source_definition, deadline=deadline, request_headers=request_headers
        )
        remaining_seconds(deadline)
        _current_rss_source(session, source_definition)
        assert_fence(session, job_id, worker_id, fence)
        return retrieved
    owned_client = client is None
    http_client = client or httpx.Client(timeout=25.0, follow_redirects=False)
    original_etag = http_client.headers.get("If-None-Match")
    original_modified = http_client.headers.get("If-Modified-Since")
    try:
        if session.in_transaction():
            session.commit()
        http_client.headers.pop("If-None-Match", None)
        http_client.headers.pop("If-Modified-Since", None)
        if eligible:
            if cache.get("etag"):
                http_client.headers["If-None-Match"] = cache["etag"]
            if cache.get("last_modified"):
                http_client.headers["If-Modified-Since"] = cache["last_modified"]
        else:
            http_client.headers.pop("If-None-Match", None)
            http_client.headers.pop("If-Modified-Since", None)
        remaining_seconds(deadline)
        retrieved = (
            retrieve_source(source_definition, http_client)
            if deadline is None
            else retrieve_source(source_definition, http_client, deadline=deadline)
        )
        remaining_seconds(deadline)
        _current_rss_source(session, source_definition)
        assert_fence(session, job_id, worker_id, fence)
        return retrieved
    finally:
        if owned_client:
            http_client.close()
        else:
            if original_etag is None:
                http_client.headers.pop("If-None-Match", None)
            else:
                http_client.headers["If-None-Match"] = original_etag
            if original_modified is None:
                http_client.headers.pop("If-Modified-Since", None)
            else:
                http_client.headers["If-Modified-Since"] = original_modified


def _current_rss_source(session: Session, source_definition: dict[str, Any]) -> Source:
    source = session.scalar(
        select(Source)
        .where(Source.id == source_definition["id"])
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        source is None
        or not source.enabled
        or not source.registry_enabled
        or source.retrieval_method != "publisher-rss"
    ):
        raise SourceParseError("RSS source was disabled during retrieval")
    if source_definition.get("endpoint") and source.endpoint != source_definition["endpoint"]:
        raise SourceParseError("RSS source endpoint changed during retrieval")
    return source


def _store_publisher_rss_checkpoint(
    session: Session,
    job_id: Any,
    worker_id: str,
    fence: int,
    source_definition: dict[str, Any],
    retrieved: list[dict[str, Any]],
    counts: dict[str, Any],
) -> None:
    source = session.get(Source, source_definition["id"])
    assert source is not None
    job = assert_fence(session, job_id, worker_id, fence)
    previous_health = source.health or {}
    current = {
        "complete": True,
        "endpoint": source_definition.get("endpoint"),
        "parser_version": _RSS_PARSER_VERSION,
        "policy_digest": _rss_policy_digest(source_definition),
        "etag": getattr(retrieved, "etag", None),
        "last_modified": getattr(retrieved, "last_modified", None),
        "snapshot_item_count": counts.get("snapshot_item_count", 0),
        "snapshot_oldest_publication_date": counts.get("snapshot_oldest_publication_date"),
        "snapshot_newest_publication_date": counts.get("snapshot_newest_publication_date"),
        "latest_publication_date": counts.get("latest_publication_date"),
        "snapshot_digest": hashlib.sha256(
            "\n".join(
                sorted(
                    f"{record.get('document_number')}:{record.get('source_hash', '')}"
                    for record in retrieved
                )
            ).encode()
        ).hexdigest(),
        "completed_at": datetime.now(UTC).isoformat(),
    }
    # A full 200 without validators invalidates old validators instead of reusing
    # a token for a representation/policy that the origin did not identify.
    source.health = {**previous_health, _RSS_CONDITIONAL_NAMESPACE: current}
    job.checkpoint = json.dumps(
        {"rss_snapshot_complete": True, "snapshot_digest": current["snapshot_digest"]},
        sort_keys=True,
    )


def process_records(
    session: Session,
    job_id: Any,
    worker_id: str,
    fence: int,
    source_definition: dict[str, Any],
    records: list[dict[str, Any]],
    client: httpx.Client | None = None,
    *,
    commit: bool = True,
    allow_model: bool = True,
    deadline: float | None = None,
    lease_expiry: datetime | None = None,
) -> dict[str, Any]:
    """Apply canonical source records; targeted research owns its enclosing transaction."""
    if commit and (
        session.new or session.dirty or session.deleted or session.in_nested_transaction()
    ):
        raise RuntimeError(
            "Committed ingestion requires a clean, non-nested caller session; "
            "commit caller changes first"
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
        "pdf_skipped_transaction": 0,
    }
    if source_definition.get("retrieval_method") == "georgia-air-permits":
        counts["snapshot_item_count"] = len(records)
        counts["documents_extracted"] = sum(len(record.get("companions", [])) for record in records)
        permits = [record.get("permit", {}) for record in records]
        counts["generator_facts"] = sum(
            len(permit.get("generator_facts", [])) for permit in permits
        )
        counts["generator_excerpts_omitted"] = sum(
            int(permit.get("generator_excerpts_omitted", 0)) for permit in permits
        )
        counts["missing_application_documents"] = sum(
            not bool(permit.get("application_document_available")) for permit in permits
        )
        counts["unextracted_public_notice_references"] = sum(
            "public notice" in record.get("permit", {}).get("unextracted_document_links", {})
            for record in records
        )
    pdf_documents = 0
    for record in records:
        remaining_seconds(deadline)
        assert_fence(session, job_id, worker_id, fence)
        source = session.get(Source, source_definition["id"])
        assert source is not None
        external_id = record["document_number"]
        digest = (
            (record.get("source_hash") or _hash(record))
            if source_definition.get("retrieval_method") == "boston-ckan-permits"
            else _hash(record)
        )
        evidence_digest = record.get("source_hash") or _source_version_hash(record)
        source_provenance = _source_link_provenance(record, source.id)
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
        # Older amendments can recur in rollover snapshots. Retain their exact
        # evidence but never let an older filing replace the current projection.
        if observation is not None and source.id == "texas-rrc-drilling-permits":
            from gridlens.ingestion.adapters.rrc_drilling import amendment_sequence

            retained_sequence = amendment_sequence(observation.abstract)
            incoming_sequence = amendment_sequence(record.get("abstract"))
            if retained_sequence is None or incoming_sequence is None:
                raise ValueError("RRC amendment identity is missing")
            if incoming_sequence > retained_sequence:
                prior = session.scalar(
                    select(Evidence.id).where(
                        Evidence.observation_id == observation.id,
                        Evidence.content_hash == evidence_digest,
                    )
                )
                if prior is None:
                    session.add(
                        Evidence(
                            observation_id=observation.id,
                            content_hash=evidence_digest,
                            title=record["title"],
                            abstract=record.get("abstract"),
                            url=record["html_url"],
                            published_at=_optional_date(record.get("publication_date")),
                            extraction_location=record["extraction_location"],
                            event_date=_optional_date(record.get("event_date")),
                            event_date_label=record.get("event_date_label"),
                        )
                    )
                counts["older_amendments_retained"] = counts.get("older_amendments_retained", 0) + 1
                counts["unchanged"] += 1
                job = assert_fence(session, job_id, worker_id, fence)
                if commit:
                    job.checkpoint = external_id
                    _advance_job_lease(job, lease_expiry)
                remaining_seconds(deadline)
                session.commit() if commit else session.flush()
                continue
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
        existing_evidence = session.scalar(
            select(Evidence).where(
                Evidence.observation_id == observation.id,
                Evidence.content_hash == evidence_digest,
            )
        )
        if existing_evidence is None:
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
                    provenance=source_provenance,
                )
            )
        elif source_provenance:
            # Reassignment is required for SQLAlchemy JSONB change tracking and
            # happens before the early evidence commit, even if later assessment fails.
            existing_evidence.provenance = _merge_source_link_provenance(
                existing_evidence.provenance, source_provenance
            )
        # Ordinary ingestion keeps evidence durable across enrichment failure.
        remaining_seconds(deadline)
        session.commit() if commit else session.flush()
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
            remaining_seconds(deadline)
        session.commit() if commit else session.flush()
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
                elif not commit:
                    # Research callers own this transaction. Preserve their
                    # commit=False contract and report the bounded skipped fetch.
                    counts["pdf_skipped_transaction"] += 1
                    pdf_citations = []
                else:
                    pdf_documents += 1
                    pdf_citations = _retrieve_companion_outside_transaction(
                        session,
                        job_id,
                        worker_id,
                        fence,
                        source_definition,
                        record,
                        client,
                        deadline=deadline,
                    )
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
                    remaining_seconds(deadline)
                    session.commit() if commit else session.flush()
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
            current_source = session.get(Source, source.id)
            current_evidence = session.scalar(
                select(Evidence).where(
                    Evidence.observation_id == observation.id,
                    Evidence.content_hash == interpretation.assessment.get("evidence_hash"),
                )
            )
            if current_source is not None and current_evidence is not None:
                admission = admitted_from_source(
                    current_source, interpretation.assessment, current_evidence
                )
                if admission.admitted:
                    project = session.scalar(
                        select(Project).where(
                            Project.identity_key
                            == interpretation.assessment.get("project_identity_key")
                        )
                    )
                    activity = interpretation.assessment.get("power_activity") or (
                        interpretation.assessment.get("activity_key")
                    )
                    need = (
                        session.scalar(
                            select(PowerNeed).where(
                                PowerNeed.project_id == project.id,
                                PowerNeed.activity_key == activity,
                                PowerNeed.active.is_(True),
                            )
                        )
                        if project is not None
                        else None
                    )
                    if (
                        need is not None
                        and project is not None
                        and _need_has_current_support(session, need, project)
                    ):
                        incoming_basis = admission.as_basis(
                            current_source.id, current_evidence.content_hash
                        )
                        if need.admission_basis != incoming_basis and not (
                            _need_admission_basis_is_current(session, need, project)
                        ):
                            need.admission_basis = incoming_basis
            counts[
                "permit_accepted" if interpretation.status == "accepted" else "permit_rejected"
            ] += 1
            job = assert_fence(session, job_id, worker_id, fence)
            if commit:
                job.checkpoint = external_id
                _advance_job_lease(job, lease_expiry)
            remaining_seconds(deadline)
            session.commit() if commit else session.flush()
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
        # Research admission instead owns the enclosing savepoint.
        remaining_seconds(deadline)
        session.commit() if commit else session.flush()

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
                else interpret_taylor_planning(record)
                if source.id == "taylor-development-newsflash"
                else interpret({**record, "source_id": source.id})
            )
        except Exception as exc:
            assert_fence(session, job_id, worker_id, fence)
            interpretation.status, interpretation.error = "failed", type(exc).__name__
            remaining_seconds(deadline)
            session.commit() if commit else session.flush()
            continue
        assert_fence(session, job_id, worker_id, fence)

        if interpreted is not None:
            activity = interpreted.get("activity_key")
            admission = admit_standalone(
                source_id=source.id,
                family=source.family,
                retrieval_method=source.retrieval_method,
                accepted=True,
                activity=activity if isinstance(activity, str) else None,
                title=record["title"],
                abstract=record.get("abstract"),
                dated=bool(record.get("publication_date") or record.get("event_date")),
                citation_url=record.get("html_url"),
                identified_project=bool(interpreted.get("name") and interpreted.get("location")),
            )
            if not admission.admitted:
                current_evidence = session.scalar(
                    select(Evidence).where(
                        Evidence.observation_id == observation.id,
                        Evidence.content_hash == evidence_digest,
                    )
                )
                interpretation.status = "accepted"
                interpretation.evaluator_version = (
                    permit_evaluator_version(record) if permit_assessment else "context-only-v1"
                )
                interpretation.error = None
                interpretation.assessment = {
                    "semantic_hash": digest,
                    "evidence_hash": evidence_digest,
                    "decision": "context_only",
                    "admission_status": "context_only",
                    "admission_origin": admission.origin,
                    "admission_reason": admission.reason,
                    "subject": interpreted.get("name"),
                    "action": interpreted.get("rationale"),
                    "location": interpreted.get("location"),
                    "reason": interpreted.get("rationale"),
                    "activity_key": activity,
                    "evidence": {
                        "id": str(current_evidence.id) if current_evidence else None,
                        "url": current_evidence.url if current_evidence else observation.url,
                    },
                    "previous_decisions": (
                        [
                            *((prior_assessment or {}).get("previous_decisions", [])),
                            {
                                key: value
                                for key, value in (prior_assessment or {}).items()
                                if key != "previous_decisions"
                            },
                        ]
                        if prior_assessment
                        else []
                    ),
                }
                job = assert_fence(session, job_id, worker_id, fence)
                if commit:
                    job.checkpoint = external_id
                    _advance_job_lease(job, lease_expiry)
                remaining_seconds(deadline)
                session.commit() if commit else session.flush()
                counts["context_only"] = counts.get("context_only", 0) + 1
                continue

        is_taylor = source.id == "taylor-development-newsflash"
        article_id = str(record.get("article_id") or "")
        project_key = (
            f"{source.id}:{article_id}"
            if is_taylor and article_id.isdigit()
            else f"{source.id}:{external_id}"
        )
        project_query = select(Project).where(Project.identity_key == project_key)
        # Negative/correction handling discovers every linked project below;
        # defer its lock so one identity-key row cannot precede a sorted set of
        # impacted projects. Accepted processing keeps its existing early lock.
        project = session.scalar(
            project_query.with_for_update() if interpreted is not None else project_query
        )
        if project is not None and interpreted is not None:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:project_id, 0))"),
                {"project_id": str(project.id)},
            )
        taylor_revision_ambiguous = False
        withdrawn_taylor = bool(
            is_taylor and record.get("disposition") == "withdrawn" and article_id.isdigit()
        )
        if is_taylor and article_id.isdigit() and interpreted is not None:
            prior_observations = session.scalars(
                select(Observation).where(
                    Observation.source_id == source.id,
                    Observation.id != observation.id,
                    or_(
                        Observation.external_id == article_id,
                        Observation.external_id.like(f"{article_id}:arcId=%"),
                    ),
                )
            ).all()
            retained_article_evidence = session.scalars(
                select(Evidence)
                .join(Observation, Evidence.observation_id == Observation.id)
                .where(
                    Observation.source_id == source.id,
                    or_(
                        Observation.external_id == article_id,
                        Observation.external_id.like(f"{article_id}:arcId=%"),
                    ),
                )
            ).all()
            prior_projects: dict[Any, Project] = {}
            for prior_observation in prior_observations:
                prior_interpretation = session.scalar(
                    select(Interpretation).where(
                        Interpretation.observation_id == prior_observation.id,
                        Interpretation.status == "accepted",
                        Interpretation.content_hash == prior_observation.content_hash,
                    )
                )
                if (
                    prior_interpretation is None
                    or not (prior_interpretation.assessment or {}).get("decision") == "accepted"
                ):
                    continue
                for prior_need in session.scalars(
                    select(PowerNeed)
                    .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
                    .where(NeedObservation.observation_id == prior_observation.id)
                ).all():
                    if (
                        prior_need.tier == "Signal"
                        and prior_need.activity_key == "facility-expansion"
                    ):
                        prior_project = session.get(Project, prior_need.project_id)
                        if prior_project is not None:
                            prior_projects[prior_project.id] = prior_project
            if (
                _taylor_article_identity_conflict(
                    [*prior_observations, *retained_article_evidence, record]
                )
                or len(prior_projects) > 1
            ):
                taylor_revision_ambiguous = True
            elif len(prior_projects) == 1:
                prior_project = next(iter(prior_projects.values()))
                if project is not None and project.id != prior_project.id:
                    taylor_revision_ambiguous = True
                else:
                    project = prior_project
                    project.identity_key = project_key
            if taylor_revision_ambiguous:
                interpreted = None
                project = None
        if interpreted is None:
            if withdrawn_taylor:
                retained_article_evidence = session.scalars(
                    select(Evidence)
                    .join(Observation, Evidence.observation_id == Observation.id)
                    .where(
                        Observation.source_id == source.id,
                        or_(
                            Observation.external_id == article_id,
                            Observation.external_id.like(f"{article_id}:arcId=%"),
                        ),
                    )
                ).all()
                taylor_revision_ambiguous = _taylor_article_identity_conflict(
                    [*retained_article_evidence, record]
                )
                if taylor_revision_ambiguous:
                    project = None
            impacted_need_ids = list(
                []
                if taylor_revision_ambiguous
                else session.scalars(
                    select(PowerNeed.id)
                    .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
                    .where(NeedObservation.observation_id == observation.id)
                ).all()
            )
            impacted_project_ids = set(
                session.scalars(
                    select(PowerNeed.project_id).where(PowerNeed.id.in_(impacted_need_ids))
                ).all()
            )
            if project is None and impacted_project_ids:
                if len(impacted_project_ids) == 1:
                    project = session.get(Project, next(iter(impacted_project_ids)))
            linked_withdrawn_need = None
            if withdrawn_taylor and not impacted_need_ids:
                prior_observations = session.scalars(
                    select(Observation).where(
                        Observation.source_id == source.id,
                        or_(
                            Observation.external_id == article_id,
                            Observation.external_id.like(f"{article_id}:arcId=%"),
                        ),
                        Observation.id != observation.id,
                    )
                ).all()
                retained_article_evidence = session.scalars(
                    select(Evidence)
                    .join(Observation, Evidence.observation_id == Observation.id)
                    .where(
                        Observation.source_id == source.id,
                        or_(
                            Observation.external_id == article_id,
                            Observation.external_id.like(f"{article_id}:arcId=%"),
                        ),
                    )
                ).all()
                taylor_revision_ambiguous = _taylor_article_identity_conflict(
                    [*prior_observations, *retained_article_evidence, record]
                )
                candidate_needs: dict[Any, PowerNeed] = {}
                for prior_observation in [] if taylor_revision_ambiguous else prior_observations:
                    prior_interpretation = session.scalar(
                        select(Interpretation).where(
                            Interpretation.observation_id == prior_observation.id,
                            Interpretation.status == "accepted",
                            Interpretation.content_hash == prior_observation.content_hash,
                        )
                    )
                    if prior_interpretation is None:
                        continue
                    assessment = prior_interpretation.assessment or {}
                    if assessment.get("decision") != "accepted":
                        continue
                    candidate_needs.update(
                        {
                            need.id: need
                            for need in session.scalars(
                                select(PowerNeed)
                                .join(NeedObservation, NeedObservation.need_id == PowerNeed.id)
                                .where(NeedObservation.observation_id == prior_observation.id)
                            ).all()
                            if need.tier == "Signal" and need.activity_key == "facility-expansion"
                        }
                    )
                if len(candidate_needs) == 1:
                    linked_withdrawn_need = next(iter(candidate_needs.values()))
                    project = session.get(Project, linked_withdrawn_need.project_id)
            # Capture the accepted semantic state before a replacement is
            # rejected or closes a current need. This covers legacy projects
            # that predate project_material_states as well as new projections.
            negative_baselines = {}
            if linked_withdrawn_need is not None:
                impacted_need_ids.append(linked_withdrawn_need.id)
                impacted_project_ids.add(linked_withdrawn_need.project_id)
            affected_project_ids = set(impacted_project_ids)
            if project is not None:
                affected_project_ids.add(project.id)
            for affected_project_id in sorted(affected_project_ids, key=str):
                impacted_project = session.get(Project, affected_project_id)
                if impacted_project is not None:
                    negative_baselines[impacted_project.id] = seed_material_state(
                        session, impacted_project
                    )
            impacted_needs = (
                session.scalars(
                    select(PowerNeed)
                    .where(PowerNeed.id.in_(set(impacted_need_ids)))
                    .order_by(PowerNeed.id)
                    .with_for_update()
                ).all()
                if impacted_need_ids
                else []
            )
            if linked_withdrawn_need is not None:
                if (
                    session.scalar(
                        select(NeedObservation.id).where(
                            NeedObservation.need_id == linked_withdrawn_need.id,
                            NeedObservation.observation_id == observation.id,
                        )
                    )
                    is None
                ):
                    session.add(
                        NeedObservation(
                            need_id=linked_withdrawn_need.id,
                            observation_id=observation.id,
                        )
                    )
                if (
                    session.scalar(
                        select(ChangeEvent.id).where(
                            ChangeEvent.observation_id == observation.id,
                            ChangeEvent.content_hash == digest,
                            ChangeEvent.kind == "withdrawn",
                        )
                    )
                    is None
                ):
                    session.add(
                        ChangeEvent(
                            observation_id=observation.id,
                            content_hash=digest,
                            kind="withdrawn",
                        )
                    )
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
                assessment_payload = {
                    "semantic_hash": digest,
                    "evidence_hash": evidence_digest,
                    "decision": "unknown"
                    if withdrawn_taylor or taylor_revision_ambiguous
                    else "rejected",
                    "reason": (
                        "Withdrawn revision retained; linked through accepted same-article "
                        "Signal; project status and power impact remain UNKNOWN."
                        if linked_withdrawn_need is not None
                        or (withdrawn_taylor and len(impacted_needs) == 1)
                        else "Taylor article identity spans conflicting project or site facts; "
                        "reason UNKNOWN."
                        if taylor_revision_ambiguous
                        else "Withdrawn revision retained; no unique accepted same-article "
                        "Signal; reason UNKNOWN."
                        if withdrawn_taylor
                        else None
                    ),
                    "project_identity_key": project.identity_key if project else None,
                }
                if taylor_revision_ambiguous and prior_assessment is not None:
                    prior_history = list(prior_assessment.get("previous_assessments", []))
                    prior_history.append(
                        {
                            key: value
                            for key, value in prior_assessment.items()
                            if key != "previous_assessments"
                        }
                    )
                    assessment_payload["previous_assessments"] = prior_history
                interpretation.assessment = assessment_payload
                if taylor_revision_ambiguous:
                    if current_evidence is not None:
                        prior_display = session.scalar(
                            select(SignalDecision)
                            .where(
                                SignalDecision.observation_id == observation.id,
                                SignalDecision.content_hash == current_evidence.content_hash,
                                SignalDecision.policy_version == POLICY_VERSION,
                            )
                            .order_by(SignalDecision.id.desc())
                        )
                        if (
                            prior_display is None
                            or prior_display.decision != "REVIEW"
                            or prior_display.source != "deterministic"
                        ):
                            session.add(
                                SignalDecision(
                                    observation_id=observation.id,
                                    content_hash=current_evidence.content_hash,
                                    policy_version=POLICY_VERSION,
                                    decision="REVIEW",
                                    source="deterministic",
                                    model_version=None,
                                    dimensions={"identity_conflict": True},
                                    reason=(
                                        "Taylor revision conflicts with retained project or "
                                        "site facts; application and project status are UNKNOWN."
                                    ),
                                )
                            )
                    previous_project = session.scalar(
                        select(Project).where(Project.identity_key == project_key)
                    )
                    if previous_project is not None:
                        refresh_lifecycle_projection(session, previous_project)
                if withdrawn_taylor and not taylor_revision_ambiguous and current_evidence:
                    supported_need = linked_withdrawn_need or (
                        impacted_needs[0] if len(impacted_needs) == 1 else None
                    )
                    if supported_need is not None:
                        interpretation.assessment["withdrawal_supported"] = True
                        supported_project = session.get(Project, supported_need.project_id)
                        if supported_project is not None:
                            # The current revision can be a rejected/withdrawn
                            # interpretation with no project identity of its own.
                            # Bind the explicit withdrawal only through the unique
                            # same-article accepted need that selected this project.
                            interpretation.assessment["project_identity_key"] = (
                                supported_project.identity_key
                            )
                            apply_planning_withdrawal(
                                session, supported_project, observation, current_evidence
                            )
                            prior_display = session.scalar(
                                select(SignalDecision)
                                .where(
                                    SignalDecision.observation_id == observation.id,
                                    SignalDecision.content_hash == current_evidence.content_hash,
                                    SignalDecision.policy_version == POLICY_VERSION,
                                )
                                .order_by(SignalDecision.id.desc())
                            )
                            if (
                                prior_display is None
                                or prior_display.decision != "HOLD"
                                or prior_display.source != "deterministic"
                            ):
                                session.add(
                                    SignalDecision(
                                        observation_id=observation.id,
                                        content_hash=current_evidence.content_hash,
                                        policy_version=POLICY_VERSION,
                                        decision="HOLD",
                                        source="deterministic",
                                        model_version=None,
                                        dimensions={"planning_application_withdrawn": True},
                                        reason=(
                                            "Official linked planning withdrawal; earlier project "
                                            "evidence remains historical and viability is UNKNOWN."
                                        ),
                                    )
                                )
                            if (
                                session.scalar(
                                    select(ChangeEvent.id).where(
                                        ChangeEvent.observation_id == observation.id,
                                        ChangeEvent.content_hash == digest,
                                        ChangeEvent.kind == "withdrawn",
                                    )
                                )
                                is None
                            ):
                                session.add(
                                    ChangeEvent(
                                        observation_id=observation.id,
                                        content_hash=digest,
                                        kind="withdrawn",
                                    )
                                )
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
            if withdrawn_taylor and not taylor_revision_ambiguous:
                supported_need = linked_withdrawn_need or (
                    impacted_needs[0] if len(impacted_needs) == 1 else None
                )
                if supported_need is not None:
                    impacted_project_ids.add(supported_need.project_id)
            for stale_need in (
                () if withdrawn_taylor or taylor_revision_ambiguous else unique_needs.values()
            ):
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
                    stale_need.tier = "Signal"
                    stale_need.required_mw = stale_need.start_window = stale_need.duration = None
                    stale_need.supply = "Unknown"
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
            if current_evidence is not None and not (withdrawn_taylor or taylor_revision_ambiguous):
                for impacted_project_id in impacted_project_ids:
                    impacted_project = session.get(Project, impacted_project_id)
                    if impacted_project is not None:
                        apply_lifecycle_observation(
                            session, impacted_project, observation, current_evidence
                        )
            if current_evidence is not None:
                for impacted_project_id in impacted_project_ids:
                    impacted_project = session.get(Project, impacted_project_id)
                    baseline = negative_baselines.get(impacted_project_id)
                    if impacted_project is not None and baseline is not None:
                        record_material_diff(session, impacted_project, current_evidence, baseline)
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
                facility_scope = phase_normalized_facility_scope(record)
                permit_data = record.get("permit")
                facility_source_address = (
                    permit_data.get("address")
                    if facility_scope and isinstance(permit_data, dict)
                    else None
                )
                permit_alias = (
                    permit_assessment.get("project_hint")
                    if permit_assessment and isinstance(permit_assessment.get("project_hint"), str)
                    else None
                )
                assert source is not None
                candidate_source_id = source.id
                event_asset_type = classify_event(observation.title, observation.abstract)

                def candidate_decisions(
                    rows: Sequence[Project],
                ) -> tuple[list[tuple[Project, Any]], list[tuple[Project, Any]]]:
                    decisions: list[tuple[Project, Any]] = []
                    supported: list[tuple[Project, Any]] = []
                    for candidate in rows:
                        decision = candidate_decision(candidate)
                        decisions.append((candidate, decision))
                        if decision.decision == "matched":
                            supported.append((candidate, decision))
                    return decisions, supported

                def candidate_decision(
                    candidate: Project,
                    context: tuple[Any, ...] = (
                        project_name,
                        permit_alias,
                        project_location,
                        facility_scope,
                        candidate_source_id,
                        facility_source_address,
                        asset_identity,
                        event_asset_type,
                    ),
                ) -> Any:
                    (
                        project_name,
                        permit_alias,
                        project_location,
                        facility_scope,
                        source_id,
                        facility_source_address,
                        asset_identity,
                        event_asset_type,
                    ) = context
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
                    same_facility_scope = bool(
                        facility_scope
                        and candidate.source_id == source_id
                        and same_site
                        and (candidate.identity_facts or {}).get("facility_scope") == facility_scope
                        and normalized_identity(
                            (candidate.identity_facts or {}).get("facility_source_address")
                        )
                        == normalized_identity(facility_source_address)
                    )
                    same_asset = bool(asset_identity) and candidate.identity_facts.get(
                        "asset_identity"
                    ) == (list(asset_identity) if asset_identity else None)
                    geographic_conflict = conflicting_geography(
                        candidate.location, project_location
                    )
                    return decide_project_match(
                        same_address=same_site,
                        same_project_name=same_name,
                        same_asset_identity=same_asset,
                        same_authoritative_scope=same_facility_scope,
                        conflicting_geography=geographic_conflict,
                        conflicting_asset_type=_asset_type_conflicts(
                            candidate.asset_type,
                            event_asset_type,
                        ),
                    )

                def decision_project_ids(
                    rows: Sequence[Project],
                    decisions: list[tuple[Project, Any]],
                    supported: list[tuple[Project, Any]],
                ) -> set[Any]:
                    if len(supported) > 1:
                        # The established ambiguous branch writes a separate
                        # decision for every candidate, including no-fact rows.
                        return {candidate.id for candidate in rows}
                    return {
                        candidate.id
                        for candidate, decision in decisions
                        if decision.decision == "matched" or decision.matched_facts
                    }

                # Discover every eventual match-decision FK, then lock only
                # those projects in the shared UUID order before need locks.
                candidates = session.scalars(select(Project)).all()
                decisions, supported = candidate_decisions(candidates)
                locked_candidate_ids = decision_project_ids(candidates, decisions, supported)
                for candidate_id in sorted(locked_candidate_ids, key=str):
                    lock_project(session, candidate_id)
                candidates = session.scalars(
                    select(Project).execution_options(populate_existing=True)
                ).all()
                decisions, supported = candidate_decisions(candidates)
                if not decision_project_ids(candidates, decisions, supported).issubset(
                    locked_candidate_ids
                ):
                    raise RuntimeError("Structured project candidate changed after ordered locks")
                if len(supported) == 1:
                    project = supported[0][0]
                else:
                    project = Project(
                        identity_key=project_key,
                        name=project_name,
                        location=project_location,
                        source_id=source.id,
                        external_id=external_id,
                        identity_facts={
                            "facility_scope": facility_scope,
                            "facility_source_address": facility_source_address,
                            "site": project_location,
                        }
                        if facility_scope
                        else {},
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
                        "facility_scope": facility_scope,
                        "facility_source_address": facility_source_address,
                    }
                elif supported[0][1].decision == "matched":
                    project.identity_facts = {
                        **(project.identity_facts or {}),
                        "asset_identity": list(asset_identity)
                        if asset_identity
                        else (project.identity_facts or {}).get("asset_identity"),
                        "site": project_location or (project.identity_facts or {}).get("site"),
                        "project_name": project_name,
                        "facility_scope": facility_scope
                        or (project.identity_facts or {}).get("facility_scope"),
                        "facility_source_address": facility_source_address
                        or (project.identity_facts or {}).get("facility_source_address"),
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
            material_baseline = seed_material_state(session, project)
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
                                "drilling",
                                "well-permit",
                            }
                        ),
                        PowerNeed.activity_key != activity_key,
                    )
                    .with_for_update()
                ).all()
                for old_need in superseded:
                    old_need.active = False
                    old_need.tier = "Signal"
                    old_need.required_mw = old_need.start_window = old_need.duration = None
                    old_need.supply = "Unknown"
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
            need.admission_basis = admission.as_basis(source.id, evidence_digest)
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
                    "tier": "Signal",
                    "subject": interpreted.get("name"),
                    "location": interpreted.get("location"),
                    "action": interpreted.get("rationale"),
                    "reason": interpreted.get("rationale"),
                    "project_identity_key": project.identity_key,
                    "power_activity": activity_key,
                    "activity_key": activity_key,
                    "evidence": {
                        "id": str(lifecycle_evidence.id) if lifecycle_evidence else None,
                        "url": lifecycle_evidence.url if lifecycle_evidence else observation.url,
                    },
                }
            if lifecycle_evidence is not None:
                # Source authority and existing identity/activity admission precede
                # qualification. Public/news supplements cannot take this path.
                if admitted_from_source(
                    source, interpretation.assessment, lifecycle_evidence
                ).admitted:
                    qualified = qualify_retained_official(
                        lifecycle_evidence.abstract or "", need.activity_key, project.location
                    )
                    if qualified:
                        interpretation.assessment = {**interpretation.assessment, **qualified}
                    session.flush()
                    _apply_current_qualification(session, need, project)
                apply_lifecycle_observation(session, project, observation, lifecycle_evidence)
                if need.tier == "Signal":
                    adjudicate_signal(
                        session,
                        observation,
                        lifecycle_evidence,
                        api_key=None if allow_model else "",
                    )
                # Snapshot diff excludes retry metadata, timestamps and rationale-only churn.
                record_material_diff(session, project, lifecycle_evidence, material_baseline)

        job = assert_fence(session, job_id, worker_id, fence)
        if commit:
            job.checkpoint = external_id
            _advance_job_lease(job, lease_expiry)
        remaining_seconds(deadline)
        session.commit() if commit else session.flush()
    return counts


def _process_collection_only(
    session: Session,
    job_id: Any,
    worker_id: str,
    fence: int,
    source_definition: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    deadline: float | None = None,
    lease_expiry: datetime | None = None,
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
        remaining_seconds(deadline)
        assert_fence(session, job_id, worker_id, fence)
        source = session.scalar(
            select(Source)
            .where(Source.id == source_definition["id"])
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert source is not None
        if (
            not source.enabled
            or not source.registry_enabled
            or source.retrieval_method != "publisher-rss"
        ):
            raise SourceParseError("RSS source was disabled during retained processing")
        if source_definition.get("endpoint") and source.endpoint != source_definition["endpoint"]:
            raise SourceParseError("RSS source endpoint changed during retained processing")
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
            and interpretation.assessment.get("admission_policy_version")
            == ADMISSION_POLICY_VERSION
            and interpretation.assessment.get("admission_status")
            not in {"supplement_unmatched", "supplement_unknown"}
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
        _advance_job_lease(job, lease_expiry)
        session.commit()  # Evidence and a retryable pending row survive evaluator failure.

        assert_fence(session, job_id, worker_id, fence)
        changed_decision = assess_retained_news(
            session,
            observation,
            evidence,
            job_id=job_id,
            worker_id=worker_id,
            fence=fence,
            lease_expiry=lease_expiry,
        )
        if interpretation.status == "accepted" and interpretation.assessment:
            current_source = session.get(Source, observation.source_id)
            current_admission = (
                admitted_from_source(current_source, interpretation.assessment, evidence)
                if current_source is not None
                else None
            )
            if current_admission and current_admission.admitted:
                counts["signals"] += int(interpretation.assessment.get("tier") == "Signal")
            if (
                current_admission
                and current_admission.admitted
                and interpretation.assessment.get("tier") == "Signal"
            ):
                adjudicate_signal(session, observation, evidence)
        if not changed_decision:
            job = assert_fence(session, job_id, worker_id, fence)
            job.checkpoint = external_id
            _advance_job_lease(job, lease_expiry)
        session.commit()
    return counts
