import hashlib
import io
import json
from collections import defaultdict
from csv import DictWriter
from datetime import UTC, date, datetime, timedelta
from datetime import date as DateType
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import Date, Text, and_, cast, func, or_, select
from sqlalchemy.orm import joinedload

from gridlens.api.verticals import vertical_source_tags
from gridlens.domain.buying_chain import BuyingChainOut, BuyingEnrichBody
from gridlens.domain.commercial_presentation import commercial_size_status, exact_mw_interval
from gridlens.domain.commercial_triage import POLICY_VERSION as COMMERCIAL_TRIAGE_POLICY
from gridlens.domain.commercial_triage import (
    cards as make_commercial_cards,
)
from gridlens.domain.commercial_triage import (
    grouped_need_groups,
)
from gridlens.domain.pursuits import (
    AutonomousResearchBody,
    AutonomousResearchOut,
    CommercialResearchBody,
    CommercialResearchStatusOut,
    CommercialTriageHistoryItem,
    CommercialTriageHistoryOut,
    CommercialTriageOut,
)
from gridlens.domain.signal_admission import admitted_from_source, source_origin
from gridlens.ingestion.registry import load_registry
from gridlens.ingestion.service import _need_has_current_support
from gridlens.intelligence.briefs import (
    BriefUnavailable,
    brief_fingerprint,
    brief_input,
    brief_preview,
    brief_view,
    request_brief,
)
from gridlens.intelligence.buying_chain import (
    buying_chain_view,
    buying_chain_views,
    enrich_buying_chain,
)
from gridlens.intelligence.lifecycle_service import lifecycle_event_supported
from gridlens.intelligence.opportunity_browse import (
    add_browse_evidence,
    grouped_opportunities,
    grouped_signal_decision,
    matched_opportunity,
    normalized_dimension,
    opportunity_group_id,
)
from gridlens.intelligence.opportunity_browse import (
    cohort_token as build_opportunity_cohort_token,
)
from gridlens.intelligence.opportunity_browse import (
    project_title as opportunity_project_title,
)
from gridlens.intelligence.project_state import project_state as read_project_state
from gridlens.intelligence.signal_adjudication import POLICY_VERSION, adjudicate_current_signals
from gridlens.jobs.queue import enqueue
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (
    BuyingChainEvidence,
    ChangeEvent,
    Evidence,
    Interpretation,
    Job,
    LifecycleEvent,
    NeedObservation,
    Observation,
    PlannerState,
    PowerNeed,
    PowerNeedBrief,
    PowerNeedBriefVersion,
    Project,
    ProjectLifecycle,
    SignalDecision,
    Source,
    SourceCheckReceipt,
    SourceDueCheck,
    SourceScheduleEpoch,
    WorkerHeartbeat,
)
from gridlens.security import (
    check_password,
    client_ip,
    consume_login_attempt,
    create_session,
    require_same_origin,
    require_session,
    revoke_token,
)
from gridlens.settings import settings

app = FastAPI(title="GridLens API", version="1.0.0", openapi_url=None)


def chicago_today(now: datetime | None = None) -> date:
    current = now or datetime.now(UTC)
    return current.astimezone(ZoneInfo("America/Chicago")).date()


class EvidenceOut(BaseModel):
    id: UUID
    title: str
    abstract: str | None
    url: str
    published_at: date | None
    retrieved_at: datetime
    extraction_location: str
    content_hash: str
    event_date: date | None
    event_date_label: str
    source_id: str
    document_number: str
    source_origin: str = "Source evidence"
    assessment_current: bool = False
    permit_status: str | None = None


class LifecycleEventOut(BaseModel):
    state: str
    event_type: str
    date: str | None
    value_kind: str
    evidence_url: str
    current: bool = True
    published_at: DateType | None = None
    event_date_label: str | None = None


class OpportunityOut(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    location: str | None
    tier: str
    workflow_status: str = "UNKNOWN"
    activity: str
    rationale: str
    signal_evidence_state: str = "active_evidence"
    required_mw: str | None
    commercial_size_status: str | None = None
    start_window: str | None
    duration: str | None
    supply: str
    next_action: str
    conflict_state: str
    assessment_reason: str | None = None
    supported_subject: str | None = None
    supported_action: str | None = None
    title_company: str | None = None
    title_company_role: str | None = None
    demand_quote: str | None = None
    supply_quote: str | None = None
    missing_facts: list[str] = Field(default_factory=list)
    reported_power_facts: list[str] = Field(default_factory=list)
    evidence: list[EvidenceOut]
    asset_type: str | None = None
    lifecycle_state: str | None = None
    lifecycle_timeline: list[LifecycleEventOut] = Field(default_factory=list)
    expected_next_milestone: str | None = None
    expected_power_event: str | None = None
    time_to_power_window: str | None = None
    estimate_basis: dict | None = None
    estimate_version: str | None = None
    lifecycle_open_questions: list[str] = Field(default_factory=list)
    monitoring_requirements: list[str] = Field(default_factory=list)
    signal_display_decision: str | None = None
    signal_display_decision_state: str = "unadjudicated"
    signal_display_source: str | None = None
    signal_display_reason: str | None = None
    signal_admission_origin: str | None = None
    brief_status: str = "unavailable"
    brief_summary: str | None = None
    brief_generated_at: datetime | None = None
    brief_stale: bool = False
    group_id: str | None = None
    group_title: str | None = None
    group_total_filtered: int | None = None
    group_loaded_on_page: int | None = None
    group_complete_on_page: bool | None = None
    matched_search: bool | None = None
    priority_segment: int | None = None
    priority_label: str | None = None


class OpportunityGroupPageOut(BaseModel):
    items: list[OpportunityOut]
    total: int
    limit: int
    offset: int
    next_offset: int | None
    cohort_token: str


_BROWSE_FILTER_NAMES = {
    "geography",
    "industry",
    "activity",
    "timing",
    "mw_status",
    "mw_min",
    "mw_max",
    "priority_segment",
    "status",
}
_BROWSE_QUERY_NAMES = _BROWSE_FILTER_NAMES | {
    "tier",
    "search",
    "decision",
    "cohort_token",
    "limit",
    "offset",
}
_PRIORITY_SEGMENT_LABELS = {
    0: "Data center project phase",
    1: "Data center commissioning",
    2: "Producing asset",
    3: "Explicit temporary or construction power scope",
    4: "Data center commissioning evidence",
    5: "Data center construction evidence",
    6: "Data center",
    7: "Oil and gas activity",
    8: "Other opportunity",
}


def _opportunity_priority_segment(item: dict[str, Any]) -> int | None:
    value = item.get("_priority_segment")
    return value if isinstance(value, int) else None


def _opportunity_priority_label(item: dict[str, Any]) -> str | None:
    segment = _opportunity_priority_segment(item)
    return _PRIORITY_SEGMENT_LABELS.get(segment) if segment is not None else None


def _validate_browse_query(request: Request) -> None:
    allowed = _BROWSE_QUERY_NAMES
    if request.url.path == "/api/opportunities/export.csv":
        allowed = allowed - {"offset"}
    unsupported = sorted(set(request.query_params.keys()) - allowed)
    if unsupported:
        raise HTTPException(
            422,
            {
                "message": "Unsupported opportunity browse query parameter",
                "unsupported": unsupported,
                "supported": sorted(allowed),
            },
        )


def _normalized_browse_filters(
    *,
    tier: str | None,
    decision: str | None,
    geography: str | None,
    industry: str | None,
    activity: str | None,
    timing: str | None,
    mw_status: str | None,
    mw_min: str | None,
    mw_max: str | None,
    priority_segment: str | None,
    status: str | None,
    search: str | None,
) -> dict[str, Any]:
    if tier is not None:
        tiers = {value.casefold(): value for value in ("Signal", "Prospect", "Lead")}
        tier = tiers.get(tier.strip().casefold())
        if tier is None:
            raise HTTPException(422, "tier must be Signal, Prospect, or Lead")
    if search is not None and len(search) > 250:
        raise HTTPException(422, "search must be at most 250 characters")

    def dimension(name: str, value: str | None) -> str | None:
        if value is None:
            return None
        clean = normalized_dimension(value)
        if not clean or len(clean) > 128:
            raise HTTPException(422, f"{name} must contain 1 to 128 characters")
        return "UNKNOWN" if clean == "unknown" else clean

    def enum(name: str, value: str | None, accepted: set[str]) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if normalized not in accepted:
            raise HTTPException(422, f"{name} must be one of {', '.join(sorted(accepted))}")
        return normalized

    decision = enum("decision", decision, {"ALL", "SHOW", "REVIEW", "HOLD"})
    if decision not in {None, "ALL"} and tier != "Signal":
        raise HTTPException(422, "Signal decisions can only filter Signal opportunities")
    timing = enum("timing", timing, {"KNOWN", "UNKNOWN"})
    mw_status = enum("mw_status", mw_status, {"KNOWN", "UNKNOWN"})
    status = enum("status", status, {"UNKNOWN"})

    def decimal_bound(name: str, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or len(value) > 64:
            raise HTTPException(422, f"{name} must be a finite nonnegative decimal MW value")
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise HTTPException(
                422, f"{name} must be a finite nonnegative decimal MW value"
            ) from exc
        if not number.is_finite() or number < 0:
            raise HTTPException(422, f"{name} must be a finite nonnegative decimal MW value")
        parts = number.as_tuple()
        digits = list(parts.digits)
        exponent = int(parts.exponent)
        while digits and digits[-1] == 0:
            digits.pop()
            exponent += 1
        if not digits:
            return "0"
        coefficient = "".join(str(digit) for digit in digits)
        adjusted_exponent = exponent + len(coefficient) - 1
        mantissa = coefficient[0] + (f".{coefficient[1:]}" if len(coefficient) > 1 else "")
        return f"{mantissa}e{adjusted_exponent}"

    minimum = decimal_bound("mw_min", mw_min)
    maximum = decimal_bound("mw_max", mw_max)
    if minimum is not None and maximum is not None and Decimal(minimum) > Decimal(maximum):
        raise HTTPException(422, "mw_min must be less than or equal to mw_max")
    if mw_status == "UNKNOWN" and (minimum is not None or maximum is not None):
        raise HTTPException(422, "Numeric MW bounds cannot be combined with mw_status=UNKNOWN")
    if priority_segment is None:
        priority = None
    elif not priority_segment.isdecimal() or not 0 <= int(priority_segment) <= 8:
        raise HTTPException(422, "priority_segment must be an integer from 0 through 8")
    else:
        priority = int(priority_segment)
    return {
        "tier": tier,
        "search": search,
        "decision": decision,
        "geography": dimension("geography", geography),
        "industry": dimension("industry", industry),
        "activity": dimension("activity", activity),
        "timing": timing,
        "mw_status": mw_status,
        "mw_min": minimum,
        "mw_max": maximum,
        "priority_segment": priority,
        "status": status,
    }


def _filter_opportunity_summaries(
    items: list[dict[str, Any]], filters: dict[str, Any]
) -> list[dict[str, Any]]:
    minimum = Decimal(filters["mw_min"]) if filters.get("mw_min") is not None else None
    maximum = Decimal(filters["mw_max"]) if filters.get("mw_max") is not None else None

    def dimension_matches(
        item: dict[str, Any],
        field: str,
        value: str | None,
        *,
        unknown_word: bool = False,
    ) -> bool:
        if value is None:
            return True
        actual = normalized_dimension(item.get(field))
        if value == "UNKNOWN":
            return not actual or (unknown_word and actual == "unknown")
        return bool(actual) and actual == value

    selected: list[dict[str, Any]] = []
    for item in items:
        if not dimension_matches(item, "location", filters.get("geography")):
            continue
        if not dimension_matches(item, "asset_type", filters.get("industry"), unknown_word=True):
            continue
        if not dimension_matches(item, "activity", filters.get("activity")):
            continue
        effective_timing = item.get("start_window")
        has_timing = (
            isinstance(effective_timing, str)
            and bool(effective_timing.strip())
            and normalized_dimension(effective_timing) != "unknown"
        )
        if filters.get("timing") == "KNOWN" and not has_timing:
            continue
        if filters.get("timing") == "UNKNOWN" and has_timing:
            continue
        demand = exact_mw_interval(item.get("required_mw"))
        is_known_mw = demand is not None
        if filters.get("mw_status") == "KNOWN" and not is_known_mw:
            continue
        if filters.get("mw_status") == "UNKNOWN" and is_known_mw:
            continue
        if minimum is not None or maximum is not None:
            if demand is None:
                continue
            low, high = demand
            if minimum is not None and high < minimum:
                continue
            if maximum is not None and low > maximum:
                continue
        if (
            filters.get("priority_segment") is not None
            and item.get("_priority_segment") != filters["priority_segment"]
        ):
            continue
        # No canonical pursuit-workflow status exists yet; UNKNOWN truthfully
        # selects the current cohort while other values fail validation.
        selected.append(item)
    return selected


class CommercialTriagePageOut(CommercialTriageOut):
    limit: int | None = None
    offset: int | None = None
    grouped_total: int | None = None
    next_offset: int | None = None


class CommercialTriageHistoryPageOut(CommercialTriageHistoryOut):
    total: int | None = None
    limit: int | None = None
    offset: int | None = None
    next_offset: int | None = None


_MAX_OPPORTUNITY_EVIDENCE_ROWS = 500
_MAX_OPPORTUNITY_LIFECYCLE_ROWS = 500
_MAX_OPPORTUNITY_PAGE_BYTES = 4_000_000
_MAX_OPPORTUNITY_SEARCH_FIELD_BYTES = 1_000_000
_MAX_OPPORTUNITY_SEARCH_COHORT_BYTES = 512_000_000
_MAX_COMMERCIAL_CARD_BYTES = 2_000_000
_MAX_COMMERCIAL_CARD_EVIDENCE_ROWS = 500
_MAX_COMMERCIAL_CARD_LIFECYCLE_ROWS = 500
_MAX_COMMERCIAL_CARD_RELATIONSHIP_ROWS = 500
_MAX_COMMERCIAL_CARD_NOTES = 500
_MAX_SAVED_SNAPSHOT_BYTES = 1_000_000
_MAX_COMMERCIAL_HISTORY_PAGE_BYTES = 2_000_000


def _signal_display_metadata(
    decisions: list[SignalDecision],
    has_unadjudicated_current_signal: bool,
    *,
    is_signal: bool,
    lifecycle_state: str | None = None,
    identity_conflict: bool = False,
) -> dict[str, Any]:
    if not is_signal:
        decisions = []
        has_unadjudicated_current_signal = False
    precedence = {"SHOW": 0, "REVIEW": 1, "HOLD": 2}
    selected = min(
        decisions,
        key=lambda item: precedence.get(item.decision, 1),
        default=None,
    )
    display = (
        "SHOW"
        if any(item.decision == "SHOW" for item in decisions)
        else "REVIEW"
        if has_unadjudicated_current_signal
        else selected.decision
        if selected
        else None
    )
    source = (
        selected.source
        if selected
        and not (has_unadjudicated_current_signal and selected.decision == "HOLD")
        else None
    )
    reason = (
        "One or more linked current Signal evidence versions have no decision."
        if has_unadjudicated_current_signal
        and (selected is None or selected.decision == "HOLD")
        else selected.reason
        if selected
        else None
    )
    state = (
        "adjudicated"
        if decisions and not has_unadjudicated_current_signal
        else "partially_adjudicated"
        if decisions
        else "unadjudicated"
    )
    if is_signal and lifecycle_state == "planning_application_withdrawn":
        display = "HOLD"
        source = "deterministic"
        reason = (
            "The current official planning application is withdrawn; earlier "
            "positive evidence remains historical and project viability is UNKNOWN."
        )
        state = "adjudicated"
    elif is_signal and identity_conflict:
        display = "REVIEW"
        source = "deterministic"
        reason = (
            "The latest Taylor revision conflicts with retained project or site facts; "
            "current application and project status are UNKNOWN."
        )
        state = "adjudicated"
    return {
        "signal_display_decision": display,
        "signal_display_source": source,
        "signal_display_reason": reason,
        "signal_display_decision_state": state,
    }


def _bounded_opportunity_payload(items: list[dict]) -> list[dict]:
    encoded_size = len(json.dumps(items, default=str, separators=(",", ":")).encode("utf-8"))
    if encoded_size > _MAX_OPPORTUNITY_PAGE_BYTES:
        raise HTTPException(
            413, "Opportunity page exceeds the complete response byte budget"
        )
    for item in items:
        if len(item.get("evidence", [])) > _MAX_OPPORTUNITY_EVIDENCE_ROWS:
            raise HTTPException(
                413, "Opportunity has too many retained evidence rows for one response"
            )
        if len(item.get("lifecycle_timeline", [])) > _MAX_OPPORTUNITY_LIFECYCLE_ROWS:
            raise HTTPException(
                413, "Opportunity has too many lifecycle rows for one response"
            )
    return items


def _begin_consistent_read(session) -> None:
    """Pin multi-query reads to one PostgreSQL cohort snapshot."""
    session.connection(execution_options={"isolation_level": "REPEATABLE READ"})


def _preflight_opportunity_details(session, rows: list[dict]) -> None:
    need_ids = [UUID(str(row["id"])) for row in rows]
    if not need_ids:
        return
    evidence_counts = dict(
        session.execute(
            select(NeedObservation.need_id, func.count(Evidence.id))
            .join(Observation, Observation.id == NeedObservation.observation_id)
            .join(Evidence, Evidence.observation_id == Observation.id)
            .outerjoin(
                Interpretation,
                and_(
                    Interpretation.observation_id == Observation.id,
                    Interpretation.content_hash == Observation.content_hash,
                ),
            )
            .where(NeedObservation.need_id.in_(need_ids))
            .group_by(NeedObservation.need_id)
        ).all()
    )
    project_ids = {UUID(str(row["project_id"])) for row in rows}
    lifecycle_counts = dict(
        session.execute(
            select(LifecycleEvent.project_id, func.count(LifecycleEvent.id))
            .where(LifecycleEvent.project_id.in_(project_ids))
            .group_by(LifecycleEvent.project_id)
        ).all()
    )
    for row in rows:
        if evidence_counts.get(UUID(str(row["id"])), 0) > _MAX_OPPORTUNITY_EVIDENCE_ROWS:
            raise HTTPException(
                413, "Opportunity has too many retained evidence rows for one response"
            )
        if lifecycle_counts.get(UUID(str(row["project_id"])), 0) > _MAX_OPPORTUNITY_LIFECYCLE_ROWS:
            raise HTTPException(
                413, "Opportunity has too many lifecycle rows for one response"
            )


def _preflight_streamed_evidence_text(
    session, need_ids: list[UUID], project_ids: list[UUID]
) -> None:
    scopes = []
    if need_ids:
        scopes.append(
            select(Evidence.id)
            .join(Observation, Observation.id == Evidence.observation_id)
            .join(NeedObservation, NeedObservation.observation_id == Observation.id)
            .where(NeedObservation.need_id.in_(need_ids))
        )
    if project_ids:
        scopes.append(
            select(Evidence.id)
            .join(LifecycleEvent, LifecycleEvent.evidence_id == Evidence.id)
            .where(LifecycleEvent.project_id.in_(project_ids))
        )
    for evidence_scope in scopes:
        text_fields = (
            func.octet_length(func.coalesce(Evidence.title, "")),
            func.octet_length(func.coalesce(Evidence.abstract, "")),
            func.octet_length(func.coalesce(Evidence.url, "")),
            func.octet_length(func.coalesce(Observation.external_id, "")),
            func.octet_length(func.coalesce(Observation.source_id, "")),
            func.coalesce(func.octet_length(cast(Interpretation.assessment, Text)), 0),
        )
        query = (
            select(
                func.max(func.greatest(*text_fields)),
                func.coalesce(func.sum(sum(text_fields)), 0),
            )
            .select_from(Evidence)
            .join(Observation, Observation.id == Evidence.observation_id)
            .outerjoin(
                Interpretation,
                and_(
                    Interpretation.observation_id == Observation.id,
                    Interpretation.content_hash == Observation.content_hash,
                ),
            )
            .where(Evidence.id.in_(evidence_scope))
        )
        max_field, total_bytes = session.execute(query).one()
        if max_field and max_field > _MAX_OPPORTUNITY_SEARCH_FIELD_BYTES:
            raise HTTPException(
                413, "Retained evidence text exceeds the bounded processing field limit"
            )
        if total_bytes > _MAX_OPPORTUNITY_SEARCH_COHORT_BYTES:
            raise HTTPException(
                413, "Retained evidence text exceeds the bounded processing cohort limit"
            )


def _commercial_bound_error(identity: str, count: int, cap: int, resource: str) -> HTTPException:
    return HTTPException(
        413,
        {
            "code": "commercial_group_exceeds_resource_bound",
            "group_id": "cg_" + hashlib.sha256(identity.encode()).hexdigest()[:32],
            "resource": resource,
            "resource_count": count,
            "resource_cap": cap,
            "message": (
                "The complete commercial work group exceeds this response budget; "
                "no partial card was returned."
            ),
        },
    )


def _check_saved_history_bounds(row: Any, note_count: int) -> None:
    snapshot = row.snapshot or {}
    snapshot_size = len(json.dumps(snapshot, default=str, separators=(",", ":")).encode("utf-8"))
    if snapshot_size > _MAX_SAVED_SNAPSHOT_BYTES:
        raise _commercial_bound_error(
            row.identity_key, snapshot_size, _MAX_SAVED_SNAPSHOT_BYTES, "saved_snapshot_bytes"
        )
    if note_count > _MAX_COMMERCIAL_CARD_NOTES:
        raise _commercial_bound_error(
            row.identity_key, note_count, _MAX_COMMERCIAL_CARD_NOTES, "notes"
        )
    receipt = snapshot.get("commercial_triage", {})
    versions = receipt.get("versions")
    if isinstance(versions, list) and len(versions) > _MAX_COMMERCIAL_CARD_NOTES:
        raise _commercial_bound_error(
            row.identity_key, len(versions), _MAX_COMMERCIAL_CARD_NOTES, "saved_versions"
        )
    cards = [receipt.get("saved_card")]
    if isinstance(versions, list):
        cards.extend(version.get("saved_card") for version in versions if isinstance(version, dict))
    for card in cards:
        if not isinstance(card, dict):
            continue
        for key in ("evidence", "lifecycle_timeline", "contacts", "notes"):
            value = card.get(key)
            if isinstance(value, list) and len(value) > _MAX_COMMERCIAL_CARD_NOTES:
                raise _commercial_bound_error(
                    row.identity_key, len(value), _MAX_COMMERCIAL_CARD_NOTES, f"saved_{key}"
                )


class BriefStatementOut(BaseModel):
    text: str
    evidence_id: str


class BriefContentOut(BaseModel):
    event_summary: list[BriefStatementOut]
    commercial_hypothesis: BriefStatementOut
    unknowns: list[str]
    next_step: str


class BriefCitationOut(BaseModel):
    evidence_id: str
    title: str
    url: str
    publisher: str
    excerpt: str


class BriefOut(BaseModel):
    status: str
    stale: bool = False
    generated_at: datetime | None = None
    result: BriefContentOut | None = None
    citations: list[BriefCitationOut] = Field(default_factory=list)
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


class BriefRequestOut(BriefOut):
    job_id: UUID | None = None


class HealthSourceOut(BaseModel):
    id: str
    status: str
    family: str
    geography: str
    enabled: bool = True
    freshness: str = "UNKNOWN"
    due_checks_7d: int = 0
    verified_successes_7d: int = 0
    last_attempt: str | None = None
    last_success: str | None = None
    new_records: int = 0
    changed_records: int = 0
    parse_failures: int = 0
    pdf_candidates: int = 0
    pdf_eligible: int = 0
    pdf_enriched: int = 0
    pdf_skipped_not_signal: int = 0
    pdf_skipped_limit: int = 0
    generator_facts: int = 0
    generator_excerpts_omitted: int = 0
    missing_application_documents: int = 0
    error: str | None = None
    latest_publication_date: str | None = None
    latest_permit_issue_date: str | None = None
    latest_public_comment_deadline: str | None = None
    earliest_public_comment_deadline: str | None = None
    records_scanned: int = 0
    permit_accepted: int = 0
    permit_rejected: int = 0
    documents_extracted: int = 0
    unextracted_public_notice_references: int = 0
    snapshot_item_count: int | None = None
    snapshot_oldest_publication_date: str | None = None
    snapshot_newest_publication_date: str | None = None
    collection_scope: str | None = None
    coverage_limitation: str | None = None


class HealthOut(BaseModel):
    sources: list[HealthSourceOut]
    backlog: int
    pending_interpretations: int
    worker_liveness: str = "UNKNOWN"
    readiness: bool = False
    collection_freshness: str = "UNKNOWN"
    planners: dict[str, dict] = Field(default_factory=dict)


class ChangeSourceOut(BaseModel):
    id: UUID
    title: str
    url: str
    published_at: date | None


class ChangeOut(BaseModel):
    kind: str
    title: str
    url: str
    published_at: date | None
    sources: list[ChangeSourceOut]


class ProjectChangeOut(BaseModel):
    kind: str
    field: str | None
    prior: dict | None
    new: dict | None
    evidence_id: UUID | None
    buying_chain_evidence_id: UUID | None
    sources: list[ChangeSourceOut]
    source_date: date | None
    detected_at: datetime


class ProjectStateOut(BaseModel):
    project_id: UUID
    identity_key: str
    state: dict
    organizations_and_roles: list[dict]
    lifecycle_events: list[dict]
    evidence: list[dict]
    candidate_matches: list[dict]
    unresolved: list[str]
    disclosure: str


class LoginBody(BaseModel):
    password: SecretStr


class LoginOut(BaseModel):
    authenticated: bool
    expires_at: int


class SessionOut(BaseModel):
    authenticated: bool


class LogoutOut(BaseModel):
    authenticated: bool


class RefreshOut(BaseModel):
    queued: list[str]


class SourceEnabledIn(BaseModel):
    enabled: bool


class SourceEnabledOut(BaseModel):
    id: str
    registry_enabled: bool
    operator_enabled: bool
    effective_enabled: bool


class IngestionItemOut(BaseModel):
    source_id: str
    source_origin: str = "Source evidence"
    publisher: str
    endpoint: str
    verticals: list[str]
    source_scope: str
    external_id: str
    title: str
    published_at: date | None
    event_date: date | None = None
    event_date_label: str | None = None
    first_seen_at: datetime
    latest_evidence_at: datetime
    excerpt: str | None
    extraction_location: str
    content_hash: str
    citation_url: str
    collection_state: str
    qualification_state: str
    assessment_current: bool = False
    assessment_reason: str | None = None
    supported_subject: str | None = None
    supported_action: str | None = None
    demand_quote: str | None = None
    supply_quote: str | None = None
    missing_facts: list[str] = Field(default_factory=list)
    reported_power_facts: list[str] = Field(default_factory=list)
    permit_status: str | None = None


class IngestionPageOut(BaseModel):
    items: list[IngestionItemOut]
    total: int
    limit: int
    offset: int


@app.get("/openapi.json", include_in_schema=False)
def private_openapi(request: Request):
    require_session(request)
    return app.openapi()


@app.post("/api/auth/login", response_model=LoginOut)
def login(body: LoginBody, request: Request, response: Response):
    require_same_origin(request)
    remote = client_ip(request)
    if not consume_login_attempt(remote):
        raise HTTPException(429, "Too many login attempts")
    if not check_password(body.password.get_secret_value()):
        raise HTTPException(401, "Invalid credentials")
    token, expires = create_session()
    response.set_cookie(
        "gridlens_session",
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.session_hours * 3600,
        path="/",
    )
    return {"authenticated": True, "expires_at": expires}


@app.post("/api/auth/logout", response_model=LogoutOut)
def logout(request: Request, response: Response):
    require_same_origin(request)
    revoke_token(request.cookies.get("gridlens_session"))
    response.delete_cookie(
        "gridlens_session",
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )
    return {"authenticated": False}


@app.get("/api/auth/session", response_model=SessionOut)
def auth_session(request: Request):
    return {"authenticated": bool(request.cookies.get("gridlens_session")) and _valid(request)}


def _valid(request: Request) -> bool:
    from gridlens.security import valid_token

    return valid_token(request.cookies.get("gridlens_session"))


def _assessment_for_evidence(
    interpretation: Interpretation | None, observation: Observation, evidence: Evidence
) -> dict | None:
    if interpretation is None or not interpretation.assessment:
        return None
    assessment = interpretation.assessment
    from gridlens.ingestion.adapters.buying_chain_public import CAPTURE_VERSION

    if (
        observation.source_id.startswith("research-public-")
        and assessment.get("acquisition_capture_version") != CAPTURE_VERSION
    ):
        return None
    if (
        assessment.get("semantic_hash") != observation.content_hash
        or assessment.get("evidence_hash") != evidence.content_hash
        or assessment.get("evidence", {}).get("id") != str(evidence.id)
    ):
        return None
    return assessment


@app.get("/api/health", response_model=HealthOut, dependencies=[Depends(require_session)])
def health():
    with SessionLocal() as session:
        rows = session.scalars(select(Source).order_by(Source.id)).all()
        definitions = {source["id"]: source for source in load_registry()}
        checked_at = datetime.now(UTC)
        jobs = (
            session.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.status.in_(["queued", "running", "failed"]))
            )
            or 0
        )
        pending = (
            session.scalar(
                select(func.count())
                .select_from(Interpretation)
                .where(Interpretation.status.in_(["pending", "failed"]))
            )
            or 0
        )
        source_health = []
        window_start = chicago_today(checked_at) - timedelta(days=6)
        window_start_utc = datetime.combine(
            window_start, datetime.min.time(), tzinfo=ZoneInfo("America/Chicago")
        ).astimezone(UTC)
        due_rows = session.scalars(
            select(SourceDueCheck).where(
                SourceDueCheck.scheduled_for >= window_start_utc,
                SourceDueCheck.scheduled_for < checked_at,
            )
        ).all()
        due_by_key = {due.due_key: due for due in due_rows}
        attempts = session.execute(
            select(SourceCheckReceipt, SourceDueCheck, Job)
            .join(SourceDueCheck, SourceDueCheck.due_key == SourceCheckReceipt.due_key)
            .join(Job, Job.id == SourceCheckReceipt.job_id)
            .where(
                SourceDueCheck.scheduled_for >= window_start_utc,
                SourceDueCheck.scheduled_for < checked_at,
            )
            .order_by(SourceCheckReceipt.recorded_at)
        ).all()
        latest_attempt = {}
        for receipt, due, job in attempts:
            current = latest_attempt.get(receipt.due_key)
            receipt_order = (receipt.fence, receipt.recorded_at, str(receipt.id))
            current_order = (
                (current[0].fence, current[0].recorded_at, str(current[0].id)) if current else None
            )
            if current_order is None or receipt_order > current_order:
                latest_attempt[receipt.due_key] = (receipt, due, job)
        worker = session.scalar(
            select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen_at.desc()).limit(1)
        )
        worker_liveness = (
            "UNKNOWN"
            if worker is None
            else "LIVE"
            if worker.last_seen_at >= checked_at - timedelta(seconds=30)
            else "STALE"
        )
        planners = {
            state.planner_key: {
                "last_attempt_at": state.last_attempt_at.isoformat()
                if state.last_attempt_at
                else None,
                "last_success_at": state.last_success_at.isoformat()
                if state.last_success_at
                else None,
                "consecutive_failures": state.consecutive_failures,
                "next_retry_at": state.next_retry_at.isoformat() if state.next_retry_at else None,
                "error_class": state.error_class,
            }
            for state in session.scalars(select(PlannerState))
        }
        freshness_states = []
        from gridlens.jobs.worker import _due_key, _scheduled_instants, _source_registry_drift

        for row in rows:
            definition = definitions.get(row.id, {})
            epochs = session.scalars(
                select(SourceScheduleEpoch)
                .where(
                    SourceScheduleEpoch.source_id == row.id,
                    SourceScheduleEpoch.effective_from < checked_at,
                    or_(
                        SourceScheduleEpoch.effective_until.is_(None),
                        SourceScheduleEpoch.effective_until > window_start_utc,
                    ),
                )
                .order_by(SourceScheduleEpoch.effective_from)
            ).all()
            covered_until = window_start_utc
            history_known = bool(epochs)
            schedule_inputs_known = True
            expected_due: dict[str, tuple[SourceScheduleEpoch, datetime]] = {}
            if not definition:
                history_known = False
            else:
                try:
                    if epochs:
                        latest_epoch = max(epochs, key=lambda epoch: epoch.effective_from)
                        if (
                            latest_epoch.effective_until is None
                            and latest_epoch.history_known
                            and _source_registry_drift(definition, row, latest_epoch)
                        ):
                            history_known = False
                except (AttributeError, KeyError, TypeError, ValueError):
                    history_known = False
                    schedule_inputs_known = False
            for epoch in epochs:
                try:
                    epoch_end = min(epoch.effective_until or checked_at, checked_at)
                    epoch_start = max(epoch.effective_from, window_start_utc)
                except (TypeError, ValueError, OverflowError):
                    history_known = False
                    schedule_inputs_known = False
                    continue
                if epoch_end <= epoch_start:
                    continue
                if epoch_start > covered_until or not epoch.history_known:
                    history_known = False
                if epoch_start <= covered_until and epoch_end > covered_until:
                    covered_until = epoch_end
                if not (epoch.history_known and epoch.registry_enabled and epoch.operator_enabled):
                    continue
                try:
                    for scheduled_for in _scheduled_instants(
                        epoch, checked_at, not_before=window_start_utc
                    ):
                        due_key = _due_key(epoch, scheduled_for)
                        expected_due[due_key] = (epoch, scheduled_for)
                except (
                    AttributeError,
                    KeyError,
                    OverflowError,
                    TypeError,
                    ValueError,
                    ZeroDivisionError,
                ):
                    schedule_inputs_known = False
                    history_known = False
            expected_history = (
                history_known and schedule_inputs_known and covered_until >= checked_at
            )
            successes = 0
            missing_due = False
            invalid_receipt = False
            dispositions = []
            for due_key, (epoch, scheduled_for) in expected_due.items():
                due = due_by_key.get(due_key)
                if due is None:
                    missing_due = True
                    continue
                expected_local_day = scheduled_for.astimezone(ZoneInfo("America/Chicago")).date()
                if (
                    due.source_id != row.id
                    or due.epoch_id != epoch.id
                    or due.scheduled_for != scheduled_for
                    or due.local_day != expected_local_day
                    or due.configuration != epoch.configuration
                ):
                    invalid_receipt = True
                    continue
                attempt = latest_attempt.get(due_key)
                if due.job_id is None or attempt is None:
                    missing_due = True
                    continue
                receipt, receipt_due, job = attempt
                if (
                    receipt_due.due_key != due_key
                    or receipt_due.job_id != due.job_id
                    or receipt.job_id != due.job_id
                    or job.id != due.job_id
                    or job.source_id != row.id
                    or job.kind != "ingestion"
                    or job.fence < 1
                    or receipt.fence != job.fence
                    or job.lease_owner is not None
                    or job.lease_until is not None
                ):
                    invalid_receipt = True
                    continue
                try:
                    canonical_counts = json.dumps(
                        receipt.check_counts,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    )
                except (TypeError, ValueError):
                    invalid_receipt = True
                    continue
                if hashlib.sha256(canonical_counts.encode()).hexdigest() != receipt.digest:
                    invalid_receipt = True
                    continue
                if receipt.disposition == "succeeded":
                    counts = receipt.check_counts
                    if (
                        job.status != "succeeded"
                        or not isinstance(counts, dict)
                        or any(
                            type(counts.get(field)) is not int or counts[field] < 0
                            for field in ("new", "changed", "unchanged")
                        )
                    ):
                        invalid_receipt = True
                        continue
                    successes += 1
                elif receipt.disposition in {"failed", "partial", "unknown"}:
                    if job.status not in {"queued", "failed", "succeeded"}:
                        invalid_receipt = True
                    else:
                        dispositions.append(receipt.disposition)
                else:
                    invalid_receipt = True
            if not expected_history or not expected_due:
                freshness = "UNKNOWN"
            elif "failed" in dispositions:
                freshness = "FAILED"
            elif "partial" in dispositions:
                freshness = "PARTIAL"
            elif "unknown" in dispositions or invalid_receipt:
                freshness = "UNKNOWN"
            elif missing_due or successes != len(expected_due):
                freshness = "OVERDUE"
            else:
                freshness = "FRESH"
            freshness_states.append(freshness)
            effective_enabled = (
                row.enabled and row.registry_enabled and bool(definition.get("enabled", False))
            )
            info = {
                "id": row.id,
                **row.health,
                "family": row.family,
                "geography": row.geography,
                "enabled": effective_enabled,
                "freshness": freshness,
                "due_checks_7d": len(expected_due),
                "verified_successes_7d": successes,
                "collection_scope": (
                    definition.get("collection_scope")
                    or row.health.get("collection_scope")
                    or row.geography
                ),
            }
            if row.family == "news":
                info["collection_scope"] = row.geography
                info["coverage_limitation"] = (
                    "Latest publisher snapshot only; rolling feeds can omit items "
                    "between snapshots. "
                    "Hourly checks do not guarantee catch-up after local downtime."
                )
            elif definition.get("coverage_limitation"):
                info["coverage_limitation"] = definition["coverage_limitation"]
            last_attempt = row.health.get("last_attempt")
            if (
                effective_enabled
                and info["status"] not in {"Running", "Failed", "RegistryUnavailable"}
                and (
                    not last_attempt
                    or datetime.fromisoformat(last_attempt)
                    < checked_at - timedelta(hours=row.cadence_hours)
                )
            ):
                info["status"] = "Overdue"
            source_health.append(info)
        return {
            "sources": source_health,
            "backlog": jobs,
            "pending_interpretations": pending,
            "worker_liveness": worker_liveness,
            "readiness": True,
            "planners": planners,
            "collection_freshness": (
                "UNKNOWN"
                if not freshness_states or "UNKNOWN" in freshness_states
                else "FRESH"
                if all(state == "FRESH" for state in freshness_states)
                else "OVERDUE"
            ),
        }


@app.get("/health/live")
def process_liveness():
    """Report API process liveness without depending on database connectivity."""
    return {"api_process": "LIVE"}


@app.get("/health/ready")
def runtime_readiness():
    """Report whether the API can query its database and queue state."""
    try:
        with SessionLocal() as session:
            session.execute(select(func.count()).select_from(Job)).scalar_one()
    except Exception as exc:
        raise HTTPException(503, "Database or queue is unavailable") from exc
    return {"readiness": "READY"}


def _ingestion_filters(source_id: str | None, vertical: str | None):
    predicates = []
    if source_id:
        predicates.append(Observation.source_id == source_id)
    if vertical:
        predicates.append(
            or_(*(Source.industries.contains([tag]) for tag in vertical_source_tags(vertical)))
        )
    return predicates


@app.get(
    "/api/ingestion",
    response_model=IngestionPageOut,
    dependencies=[Depends(require_session)],
)
def ingestion(
    source_id: str | None = None,
    vertical: str | None = None,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
):
    predicates = _ingestion_filters(source_id, vertical)
    with SessionLocal() as session:
        base = (
            select(Evidence, Observation, Source, Interpretation)
            .join(Observation, Evidence.observation_id == Observation.id)
            .join(Source, Observation.source_id == Source.id)
            .outerjoin(Interpretation, Interpretation.observation_id == Observation.id)
            .where(*predicates)
        )
        total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = session.execute(
            base.order_by(
                Evidence.observed_at.desc(),
                Observation.source_id,
                Observation.external_id,
                Evidence.content_hash,
            )
            .limit(limit)
            .offset(offset)
        ).all()
        items = []
        for evidence, observation, source, interpretation in rows:
            assessment = _assessment_for_evidence(interpretation, observation, evidence)
            items.append(
                {
                    "source_id": source.id,
                    "source_origin": source_origin(source.family, source.retrieval_method),
                    "publisher": source.publisher,
                    "endpoint": source.endpoint,
                    "verticals": source.industries,
                    "source_scope": source.geography,
                    "external_id": observation.external_id,
                    "title": evidence.title,
                    "published_at": evidence.published_at,
                    "event_date": evidence.event_date,
                    "event_date_label": evidence.event_date_label,
                    "first_seen_at": observation.first_seen_at,
                    "latest_evidence_at": evidence.observed_at,
                    "excerpt": evidence.abstract,
                    "extraction_location": evidence.extraction_location,
                    "content_hash": evidence.content_hash,
                    "citation_url": evidence.url,
                    "collection_state": "Evidence retained",
                    "qualification_state": (
                        "Context only; no standalone opportunity"
                        if assessment
                        and assessment.get("admission_status")
                        in {"context_only", "supplement_unmatched", "supplement_unknown"}
                        else "Supplemental evidence linked to admitted project need"
                        if assessment and assessment.get("admission_status") == "supplemental"
                        else "Linked to opportunity"
                        if session.scalar(
                            select(func.count())
                            .select_from(NeedObservation)
                            .where(NeedObservation.observation_id == observation.id)
                        )
                        or (
                            assessment
                            and assessment.get("decision") == "accepted"
                            and session.scalar(
                                select(func.count())
                                .select_from(Project)
                                .join(PowerNeed, PowerNeed.project_id == Project.id)
                                .where(
                                    Project.source_id == observation.source_id,
                                    Project.external_id == observation.external_id,
                                    PowerNeed.active.is_(True),
                                )
                            )
                        )
                        else f"{assessment['tier']} created"
                        if assessment and assessment.get("decision") == "accepted"
                        else "Reviewed; no project Signal"
                        if assessment and assessment.get("decision") == "rejected"
                        else "Interpretation failed"
                        if interpretation and interpretation.status == "failed"
                        else "Reassessment required"
                        if interpretation and interpretation.assessment
                        else "Not assessed"
                    ),
                    "assessment_current": assessment is not None,
                    "assessment_reason": assessment.get("reason") if assessment else None,
                    "supported_subject": assessment.get("subject") if assessment else None,
                    "supported_action": assessment.get("action") if assessment else None,
                    "demand_quote": assessment.get("demand_quote") if assessment else None,
                    "supply_quote": assessment.get("supply_quote") if assessment else None,
                    "missing_facts": assessment.get("missing_facts", []) if assessment else [],
                    "reported_power_facts": assessment.get("reported_power_facts", [])
                    if assessment
                    else [],
                    "permit_status": assessment.get("permit_status") if assessment else None,
                }
            )
        return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.get(
    "/api/opportunities",
    response_model=list[OpportunityOut],
    dependencies=[Depends(require_session), Depends(_validate_browse_query)],
)
def opportunities(
    tier: str | None = None,
    search: str | None = None,
    decision: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    cohort: Annotated[str | None, Query(alias="cohort_token")] = None,
    response: Response = None,  # type: ignore[assignment]
    *,
    geography: str | None = None,
    industry: str | None = None,
    activity: str | None = None,
    timing: str | None = None,
    mw_status: str | None = None,
    mw_min: str | None = None,
    mw_max: str | None = None,
    priority_segment: str | None = None,
    status: str | None = None,
):
    response = response or Response()
    filters = _normalized_browse_filters(
        tier=tier, decision=decision, geography=geography, industry=industry,
        activity=activity, timing=timing, mw_status=mw_status, mw_min=mw_min,
        mw_max=mw_max, priority_segment=priority_segment, status=status, search=search,
    )
    if offset > 0 and (cohort is None or not cohort.strip()):
        raise HTTPException(422, "cohort_token is required when offset is greater than zero")
    tier = filters["tier"]
    decision = filters["decision"]
    with SessionLocal() as session:
        _begin_consistent_read(session)
        summaries = opportunity_projection(session, tier=tier, summary_only=True)
        items = _filter_opportunity_summaries(
            [
            {
                **item,
                "_browse_first_evidence": {},
                "_browse_action_candidates": item.get("_browse_action_candidates", []),
            }
                for item in summaries
            ],
            filters,
        )
        evidence_matches = _opportunity_evidence_search_matches(session, items, search)
        items.sort(key=lambda item: str(item["id"]))
        items.sort(key=lambda item: item.get("_updated_at") or datetime.min, reverse=True)
        groups = grouped_opportunities(items)
        key_by_id = {str(member["id"]): key for key, members in groups for member in members}
        matched_by_id = {
            str(item["id"]): matched_opportunity(
                item, search or "", evidence_matches.get(str(item["id"]), False)
            )
            for item in items
        }
        matching_group_keys = {
            key_by_id[str(item["id"])] for item in items if matched_by_id[str(item["id"])]
        }
        search_groups = [(key, members) for key, members in groups if key in matching_group_keys]
        decision_counts = {
            value: sum(grouped_signal_decision(members) == value for _key, members in search_groups)
            for value in ("SHOW", "REVIEW", "HOLD")
        }
        filtered_groups = [
            (key, members)
            for key, members in search_groups
            if decision in {None, "ALL"} or grouped_signal_decision(members) == decision
        ]
        filtered = [member for _key, members in filtered_groups for member in members]
        # The canonical record order is preserved across group membership and page slices.
        filtered.sort(key=lambda item: str(item["id"]))
        filtered.sort(key=lambda item: item.get("_updated_at") or datetime.min, reverse=True)
        filtered_keys = [key_by_id[str(item["id"])] for item in filtered]
        token_rows = filtered
        token = build_opportunity_cohort_token(filters, token_rows, filtered_keys)
        if cohort is not None and cohort != token:
            raise HTTPException(409, "Opportunity cohort changed; restart pagination")
        page_summaries = filtered[offset : offset + limit]
        page_ids = {UUID(str(item["id"])) for item in page_summaries}
        _preflight_opportunity_details(session, page_summaries)
        page_details = opportunity_projection(
            session, tier=tier, selected_need_ids=page_ids, include_below_floor=False
        )
        details_by_id = {str(item["id"]): item for item in page_details}
        summary_by_id = {str(item["id"]): item for item in page_summaries}
        page = [
            details_by_id[str(item["id"])]
            for item in page_summaries
            if str(item["id"]) in details_by_id
        ]
        loaded_by_key: dict[str, int] = {}
        total_by_key: dict[str, int] = {}
        for _item, key in zip(filtered, filtered_keys, strict=True):
            total_by_key[key] = total_by_key.get(key, 0) + 1
        for item in page:
            key = key_by_id[str(item["id"])]
            loaded_by_key[key] = loaded_by_key.get(key, 0) + 1
        output = []
        group_title_by_key = {
            key: opportunity_project_title(members[0]) for key, members in groups
        }
        for item in page:
            key = key_by_id[str(item["id"])]
            summary = summary_by_id[str(item["id"])]
            output.append(
                {
                    **item,
                    "group_id": opportunity_group_id(key),
                    "group_title": group_title_by_key[key],
                    "group_total_filtered": total_by_key[key],
                    "group_loaded_on_page": loaded_by_key[key],
                    "group_complete_on_page": loaded_by_key[key] == total_by_key[key],
                    "matched_search": matched_by_id[str(item["id"])],
                    "priority_segment": _opportunity_priority_segment(summary),
                    "priority_label": _opportunity_priority_label(summary),
                    "workflow_status": "UNKNOWN",
                }
            )
        response.headers.update(
            {
                "X-Total-Count": str(len(filtered)),
                "X-Group-Total-Count": str(len(filtered_groups)),
                "X-Page-Record-Count": str(len(page)),
                "X-Page-Group-Count": str(len({key_by_id[str(item["id"])] for item in page})),
                "X-Limit": str(limit),
                "X-Offset": str(offset),
                "X-Cohort-Token": token,
                "X-Decision-Counts": json.dumps(decision_counts, separators=(",", ":")),
            }
        )
        if offset + len(page) < len(filtered):
            response.headers["X-Next-Offset"] = str(offset + len(page))
        return _bounded_opportunity_payload(output)


def _opportunity_evidence_search_matches(
    session, items: list[dict], search: str | None
) -> dict[str, bool]:
    from gridlens.intelligence.opportunity_browse import normalized

    term = normalized(search)
    matches = {str(item["id"]): False for item in items}
    fingerprints = {key: hashlib.sha256() for key in matches}
    states: dict[str, tuple[str, bool]] = {}
    tail_length = max(len(term) - 1, 0)
    for item in items:
        key = str(item["id"])
        states[key] = ("", False)
    need_ids = [UUID(key) for key in matches]
    largest_search_field = session.scalar(
        select(
            func.max(
                func.greatest(
                    func.octet_length(func.coalesce(Evidence.title, "")),
                    func.octet_length(func.coalesce(Evidence.abstract, "")),
                    func.octet_length(func.coalesce(Evidence.url, "")),
                    func.octet_length(func.coalesce(Observation.external_id, "")),
                    func.octet_length(func.coalesce(Observation.source_id, "")),
                    func.octet_length(cast(Interpretation.assessment, Text)),
                )
            )
        )
        .select_from(NeedObservation)
        .join(Observation, Observation.id == NeedObservation.observation_id)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .outerjoin(
            Interpretation,
            and_(
                Interpretation.observation_id == Observation.id,
                Interpretation.content_hash == Observation.content_hash,
            ),
        )
        .where(NeedObservation.need_id.in_(need_ids))
    ) if need_ids else 0
    if largest_search_field and largest_search_field > _MAX_OPPORTUNITY_SEARCH_FIELD_BYTES:
        raise HTTPException(413, "Opportunity evidence text exceeds the searchable field limit")
    search_text_bytes = session.scalar(
        select(
            func.coalesce(
                func.sum(
                    func.octet_length(func.coalesce(Evidence.title, ""))
                    + func.octet_length(func.coalesce(Evidence.abstract, ""))
                    + func.octet_length(func.coalesce(Evidence.url, ""))
                    + func.octet_length(func.coalesce(Observation.external_id, ""))
                    + func.octet_length(func.coalesce(Observation.source_id, ""))
                    + func.coalesce(
                        func.octet_length(cast(Interpretation.assessment, Text)), 0
                    )
                ),
                0,
            )
        )
        .select_from(NeedObservation)
        .join(Observation, Observation.id == NeedObservation.observation_id)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .outerjoin(
            Interpretation,
            and_(
                Interpretation.observation_id == Observation.id,
                Interpretation.content_hash == Observation.content_hash,
            ),
        )
        .where(NeedObservation.need_id.in_(need_ids))
    ) if need_ids else 0
    if search_text_bytes > _MAX_OPPORTUNITY_SEARCH_COHORT_BYTES:
        raise HTTPException(413, "Opportunity evidence text exceeds the searchable cohort limit")
    evidence_statement = (
        select(
            NeedObservation.need_id,
            Evidence.id,
            Evidence.title,
            Evidence.abstract,
            Evidence.url,
            Evidence.content_hash,
            Observation.external_id,
            Observation.source_id,
            Observation.content_hash,
            Interpretation.assessment,
        )
        .join(Observation, Observation.id == NeedObservation.observation_id)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .outerjoin(
            Interpretation,
            and_(
                Interpretation.observation_id == Observation.id,
                Interpretation.content_hash == Observation.content_hash,
            ),
        )
        .where(NeedObservation.need_id.in_(need_ids))
        .order_by(
            NeedObservation.need_id,
            Evidence.observed_at.desc(),
            Evidence.content_hash.desc(),
            Evidence.id,
        )
    )
    item_by_id = {str(item["id"]): item for item in items}
    for (
        need_id,
        evidence_id,
        title,
        abstract,
        url,
        content_hash,
        document_number,
        source_id,
        observation_hash,
        assessment,
    ) in session.execute(evidence_statement).yield_per(32):
        key = str(need_id)
        fingerprints[key].update(
            "\x1f".join(
                (
                    str(evidence_id),
                    str(content_hash),
                    str(observation_hash),
                    str(source_id),
                    str(document_number),
                )
            ).encode("utf-8")
        )
        fingerprints[key].update(
            hashlib.sha256(
                "\x1f".join(str(value or "") for value in (title, abstract, url))
                .encode("utf-8")
            ).digest()
        )
        fingerprints[key].update(
            hashlib.sha256(
                json.dumps(
                    assessment or {}, sort_keys=True, separators=(",", ":"), default=str
                ).encode(
                    "utf-8"
                )
            ).digest()
        )
        fingerprints[key].update(b"\x1e")
        item = item_by_id[key]
        add_browse_evidence(
            item,
            {
                "id": evidence_id,
                "title": title,
                "abstract": abstract,
                "url": url,
                "content_hash": content_hash,
                "document_number": document_number,
                "source_id": source_id,
                "assessment_current": bool(
                    assessment
                    and assessment.get("semantic_hash") == observation_hash
                    and observation_hash == content_hash
                    and assessment.get("evidence_hash") == content_hash
                    and assessment.get("evidence", {}).get("id") == str(evidence_id)
                    and assessment.get("project_identity_key")
                    == item.get("_cohort_project_identity")
                    and (assessment.get("power_activity") or assessment.get("activity_key"))
                    == item.get("activity")
                ),
            },
        )
    for key, item in item_by_id.items():
        item["_browse_evidence_fingerprint"] = fingerprints[key].hexdigest()
        prefix = " ".join(
            normalized(value)
            for value in (
                item.get("name"),
                opportunity_project_title(item),
                item.get("location"),
                item.get("activity"),
                item.get("supported_subject"),
                item.get("supported_action"),
                item.get("assessment_reason"),
            )
            if value
        )
        found = bool(term) and term in prefix
        tail = prefix[-tail_length:] if tail_length else ""
        states[key] = (tail, found)
    if term:
        for (
            need_id,
            _evidence_id,
            title,
            abstract,
            _url,
            _content_hash,
            document_number,
            source_id,
            _observation_hash,
            _assessment,
        ) in session.execute(evidence_statement).yield_per(32):
            key = str(need_id)
            tail, found = states[key]
            for value in (title, abstract, document_number, source_id):
                part = normalized(value)
                candidate = f"{tail} {part}".strip()
                found = found or term in candidate
                tail = candidate[-tail_length:] if tail_length else ""
            states[key] = (tail, found)
    return {key: found for key, (_tail, found) in states.items()}


@app.get(
    "/api/opportunity-groups/{group_id}",
    response_model=OpportunityGroupPageOut,
    dependencies=[Depends(require_session), Depends(_validate_browse_query)],
)
def opportunity_group_page(
    group_id: str,
    cohort_token: str,
    tier: str | None = None,
    search: str | None = None,
    decision: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    *,
    geography: str | None = None,
    industry: str | None = None,
    activity: str | None = None,
    timing: str | None = None,
    mw_status: str | None = None,
    mw_min: str | None = None,
    mw_max: str | None = None,
    priority_segment: str | None = None,
    status: str | None = None,
):
    filters = _normalized_browse_filters(
        tier=tier, decision=decision, geography=geography, industry=industry,
        activity=activity, timing=timing, mw_status=mw_status, mw_min=mw_min,
        mw_max=mw_max, priority_segment=priority_segment, status=status, search=search,
    )
    tier = filters["tier"]
    decision = filters["decision"]
    with SessionLocal() as session:
        _begin_consistent_read(session)
        summaries = opportunity_projection(session, tier=tier, summary_only=True)
        all_items = _filter_opportunity_summaries([
            {
                **item,
                "_browse_first_evidence": {},
                "_browse_action_candidates": item.get("_browse_action_candidates", []),
            }
            for item in summaries
        ], filters)
        evidence_matches = _opportunity_evidence_search_matches(session, all_items, search)
        member_matches = {
            str(member["id"]): matched_opportunity(
                member, search or "", evidence_matches.get(str(member["id"]), False)
            )
            for member in all_items
        }
        groups = grouped_opportunities(all_items)
        filtered_groups = [
            (key, members)
            for key, members in groups
            if any(member_matches[str(member["id"])] for member in members)
            and (decision in {None, "ALL"} or grouped_signal_decision(members) == decision)
        ]
        rows = [member for _key, members in filtered_groups for member in members]
        keys = [key for key, members in filtered_groups for _member in members]
        ordered = sorted(zip(rows, keys, strict=True), key=lambda pair: str(pair[0]["id"]))
        ordered.sort(key=lambda pair: pair[0].get("_updated_at") or datetime.min, reverse=True)
        rows = [row for row, _key in ordered]
        keys = [key for _row, key in ordered]
        token_rows = rows
        current_token = build_opportunity_cohort_token(filters, token_rows, keys)
        if current_token != cohort_token:
            raise HTTPException(409, "Opportunity cohort changed; restart pagination")
        target = next(
            (members for key, members in filtered_groups if opportunity_group_id(key) == group_id),
            None,
        )
        if target is None:
            raise HTTPException(404, "Opportunity group not found")
        target.sort(key=lambda item: str(item["id"]))
        target.sort(key=lambda item: item.get("_updated_at") or datetime.min, reverse=True)
        page_summaries = target[offset : offset + limit]
        page_ids = {UUID(str(item["id"])) for item in page_summaries}
        _preflight_opportunity_details(session, page_summaries)
        details = opportunity_projection(
            session, tier=tier, selected_need_ids=page_ids, include_below_floor=False
        )
        details_by_id = {str(item["id"]): item for item in details}
        summary_by_id = {str(item["id"]): item for item in page_summaries}
        page = [
            details_by_id[str(item["id"])]
            for item in page_summaries
            if str(item["id"]) in details_by_id
        ]
        output_items: list[dict[str, Any]] = [
            {
                **member,
                "group_id": group_id,
                "group_title": opportunity_project_title(target[0]),
                "group_total_filtered": len(target),
                "group_loaded_on_page": len(page),
                "group_complete_on_page": offset == 0 and len(page) == len(target),
                "matched_search": member_matches[str(member["id"])],
                "priority_segment": _opportunity_priority_segment(
                    summary_by_id[str(member["id"])]
                ),
                "priority_label": _opportunity_priority_label(
                    summary_by_id[str(member["id"])]
                ),
                "workflow_status": "UNKNOWN",
            }
            for member in page
        ]
        result = {
            "items": output_items,
            "total": len(target),
            "limit": limit,
            "offset": offset,
            "next_offset": offset + len(page) if offset + len(page) < len(target) else None,
            "cohort_token": current_token,
        }
        _bounded_opportunity_payload(output_items)
        return result


@app.get(
    "/api/opportunities/needs/{need_id}",
    response_model=OpportunityOut,
    dependencies=[Depends(require_session), Depends(_validate_browse_query)],
)
def opportunity_need_detail(
    need_id: UUID,
    tier: str | None = None,
    search: str | None = None,
    decision: str | None = None,
    cohort_token: str | None = None,
    *,
    geography: str | None = None,
    industry: str | None = None,
    activity: str | None = None,
    timing: str | None = None,
    mw_status: str | None = None,
    mw_min: str | None = None,
    mw_max: str | None = None,
    priority_segment: str | None = None,
    status: str | None = None,
):
    filters = _normalized_browse_filters(
        tier=tier, decision=decision, geography=geography, industry=industry,
        activity=activity, timing=timing, mw_status=mw_status, mw_min=mw_min,
        mw_max=mw_max, priority_segment=priority_segment, status=status, search=search,
    )
    tier = filters["tier"]
    decision = filters["decision"]
    with SessionLocal() as session:
        _begin_consistent_read(session)
        summaries = _filter_opportunity_summaries(
            opportunity_projection(session, tier=tier, summary_only=True), filters
        )
        summaries = [
            {
                **item,
                "_browse_first_evidence": {},
                "_browse_action_candidates": item.get("_browse_action_candidates", []),
            }
            for item in summaries
        ]
        evidence_matches = _opportunity_evidence_search_matches(session, summaries, search)
        groups = grouped_opportunities(summaries)
        member_matches = {
            str(member["id"]): matched_opportunity(
                member, search or "", evidence_matches.get(str(member["id"]), False)
            )
            for member in summaries
        }
        group_keys_by_id = {
            str(member["id"]): key for key, members in groups for member in members
        }
        selected_groups = [
            (key, members)
            for key, members in groups
            if any(member_matches[str(member["id"])] for member in members)
            and (decision in {None, "ALL"} or grouped_signal_decision(members) == decision)
        ]
        selected = [member for _key, members in selected_groups for member in members]
        selected.sort(key=lambda item: str(item["id"]))
        selected.sort(key=lambda item: item.get("_updated_at") or datetime.min, reverse=True)
        selected_keys = [group_keys_by_id[str(item["id"])] for item in selected]
        current_token = build_opportunity_cohort_token(filters, selected, selected_keys)
        if cohort_token is not None and cohort_token != current_token:
            raise HTTPException(409, "Opportunity cohort changed; reopen the selected record")
        summary = next((item for item in selected if item["id"] == need_id), None)
        if summary is None:
            raise HTTPException(404, "Opportunity is outside the requested filtered cohort")
        _preflight_opportunity_details(session, [summary])
        items = opportunity_projection(session, selected_need_ids={need_id})
        if not items:
            raise HTTPException(404, "Opportunity not found")
        detail = _bounded_opportunity_payload(items)[0]
        detail["priority_segment"] = _opportunity_priority_segment(summary)
        detail["priority_label"] = _opportunity_priority_label(summary)
        detail["workflow_status"] = "UNKNOWN"
        return detail


def _csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if text.lstrip(" \t\r\n\x00\x0b\x0c\x1b\x7f").startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


@app.get(
    "/api/opportunities/export.csv",
    dependencies=[Depends(require_session), Depends(_validate_browse_query)],
)
def export_opportunities_csv(
    tier: str | None = None,
    search: str | None = None,
    decision: str | None = None,
    cohort_token: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    *,
    geography: str | None = None,
    industry: str | None = None,
    activity: str | None = None,
    timing: str | None = None,
    mw_status: str | None = None,
    mw_min: str | None = None,
    mw_max: str | None = None,
    priority_segment: str | None = None,
    status: str | None = None,
):
    filters = _normalized_browse_filters(
        tier=tier, decision=decision, geography=geography, industry=industry,
        activity=activity, timing=timing, mw_status=mw_status, mw_min=mw_min,
        mw_max=mw_max, priority_segment=priority_segment, status=status, search=search,
    )
    tier = filters["tier"]
    decision = filters["decision"]
    with SessionLocal() as session:
        _begin_consistent_read(session)
        summaries = opportunity_projection(session, tier=tier, summary_only=True)
        items = _filter_opportunity_summaries([
            {
                **item,
                "_browse_first_evidence": {},
                "_browse_action_candidates": item.get("_browse_action_candidates", []),
            }
            for item in summaries
        ], filters)
        evidence_matches = _opportunity_evidence_search_matches(session, items, search)
        matches = {
            str(item["id"]): matched_opportunity(
                item, search or "", evidence_matches.get(str(item["id"]), False)
            )
            for item in items
        }
        groups = grouped_opportunities(items)
        selected_groups = [
            (key, members)
            for key, members in groups
            if any(matches[str(member["id"])] for member in members)
            and (decision in {None, "ALL"} or grouped_signal_decision(members) == decision)
        ]
        key_by_id = {
            str(member["id"]): key for key, members in selected_groups for member in members
        }
        selected = [member for _key, members in selected_groups for member in members]
        selected.sort(key=lambda item: str(item["id"]))
        selected.sort(key=lambda item: item.get("_updated_at") or datetime.min, reverse=True)
        selected_keys = [key_by_id[str(item["id"])] for item in selected]
        token = build_opportunity_cohort_token(filters, selected, selected_keys)
        if cohort_token is not None and cohort_token != token:
            raise HTTPException(409, "Opportunity cohort changed; restart export")
        if len(selected) > limit:
            raise HTTPException(
                413,
                {
                    "code": "opportunity_export_row_limit",
                    "total": len(selected),
                    "max_rows": limit,
                    "message": "Narrow filters before exporting; no rows were omitted silently.",
                },
            )
        _preflight_opportunity_details(session, selected)
        selected_ids = [UUID(str(item["id"])) for item in selected]
        fields = [
            "need_id",
            "project_id",
            "name",
            "location",
            "tier",
            "signal_decision",
            "workflow_status",
            "priority_segment",
            "priority_label",
            "activity",
            "required_mw",
            "supply",
            "source_ids",
            "evidence_urls",
            "evidence_hashes",
            "signal_evidence_state",
            "export_scope",
            "cohort_token",
        ]
        chunks: list[bytes] = []
        total_bytes = 0
        buffer = io.StringIO()
        writer = DictWriter(buffer, fieldnames=fields, lineterminator="\r\n")
        writer.writeheader()
        chunks.append(buffer.getvalue().encode("utf-8"))
        total_bytes += len(chunks[-1])
        selected_by_id = {str(item["id"]): item for item in selected}
        for start in range(0, len(selected_ids), 50):
            batch_ids = selected_ids[start : start + 50]
            records = _bounded_opportunity_payload(
                opportunity_projection(session, tier=tier, selected_need_ids=set(batch_ids))
            )
            by_id = {str(record["id"]): record for record in records}
            for need_id in batch_ids:
                record = by_id.get(str(need_id))
                if record is None:
                    raise HTTPException(409, "Opportunity cohort changed during export")
                summary = selected_by_id[str(need_id)]
                export_priority_segment = _opportunity_priority_segment(summary)
                values = {
                    "need_id": record["id"],
                    "project_id": record["project_id"],
                    "name": record["name"],
                    "location": record["location"] or "UNKNOWN",
                    "tier": record["tier"],
                    "signal_decision": record.get("signal_display_decision") or "UNKNOWN",
                    "workflow_status": "UNKNOWN",
                    "priority_segment": (
                        str(export_priority_segment)
                        if export_priority_segment is not None
                        else "UNKNOWN"
                    ),
                    "priority_label": _opportunity_priority_label(summary) or "UNKNOWN",
                    "activity": record["activity"],
                    "required_mw": record.get("required_mw") or "UNKNOWN",
                    "supply": record.get("supply") or "UNKNOWN",
                    "source_ids": json.dumps(
                        sorted({evidence["source_id"] for evidence in record["evidence"]}),
                        separators=(",", ":"),
                    ),
                    "evidence_urls": json.dumps(
                        [evidence["url"] for evidence in record["evidence"]],
                        separators=(",", ":"),
                    ),
                    "evidence_hashes": json.dumps(
                        [evidence["content_hash"] for evidence in record["evidence"]],
                        separators=(",", ":"),
                    ),
                    "signal_evidence_state": record.get("signal_evidence_state") or "UNKNOWN",
                    "export_scope": "all_filtered_matches",
                    "cohort_token": token,
                }
                buffer.seek(0)
                buffer.truncate(0)
                writer.writerow({key: _csv_cell(value) for key, value in values.items()})
                encoded_row = buffer.getvalue().encode("utf-8")
                total_bytes += len(encoded_row)
                if total_bytes > 20_000_000:
                    raise HTTPException(413, "CSV exceeds the declared 20 MB export budget")
                chunks.append(encoded_row)

    filename = f"gridlens-opportunities-{chicago_today().isoformat()}.csv"
    return StreamingResponse(
        iter(chunks),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Export-Scope": "all_filtered_matches",
            "X-Total-Count": str(len(selected_ids)),
        },
    )


_BROWSE_SUMMARY_BATCH_SIZE = 128
_BROWSE_BUYING_CHAIN_PROJECT_BATCH_SIZE = 32


def _opportunity_summary_projection(
    session,
    *,
    tier: str | None,
    search: str | None,
    include_below_floor: bool,
    selected_need_ids: set[UUID] | None,
    diagnostics: dict[str, int] | None,
) -> list[dict]:
    """Stream compact candidate inputs; selected details use the regular projection."""
    from gridlens.domain.commercial_triage import PriorityInputAccumulator, _priority
    from gridlens.ingestion.service import CurrentNeedQualificationAccumulator
    from gridlens.intelligence.project_state import ResearchSummaryAccumulator

    sources = {source.id: source for source in session.scalars(select(Source))}
    caller_owned_orm_ids = {id(row) for row in session.identity_map.values()}

    def release_streamed_row(orm_row: Any) -> None:
        if orm_row is not None and orm_row in session and id(orm_row) not in caller_owned_orm_ids:
            session.expunge(orm_row)

    summaries: list[dict] = []
    metrics = diagnostics if diagnostics is not None else {}
    metrics.update(
        {
            "candidate_rows_scanned": 0,
            "max_candidate_batch_size": 0,
            "max_current_link_rows_per_batch": 0,
            "max_current_link_rows_per_need": 0,
            "max_resident_link_orm_rows": 0,
            "max_resident_lifecycle_orm_rows": 0,
            "link_fetch_chunk_size": 128,
            "lifecycle_fetch_chunk_size": 128,
            "max_compact_need_states_per_batch": 0,
            "historical_date_rows_aggregated": 0,
            "historical_evidence_orm_rows": 0,
            "lifecycle_rows_streamed": 0,
            "supported_lifecycle_rows": 0,
            "brief_orm_rows": 0,
            "summary_candidate_count": 0,
            "title_company_project_count": 0,
            "title_company_batch_count": 0,
            "max_title_company_batch_size": 0,
        }
    )
    cursor: UUID | None = None
    houston_project_ids: set[UUID] = set()
    while True:
        query = (
            select(PowerNeed, Project)
            .join(Project, PowerNeed.project_id == Project.id)
            .where(PowerNeed.active.is_(True))
            .order_by(PowerNeed.id)
            .limit(_BROWSE_SUMMARY_BATCH_SIZE)
        )
        if search:
            query = query.where(Project.name.ilike(f"%{search[:100]}%"))
        if selected_need_ids is not None:
            query = query.where(PowerNeed.id.in_(selected_need_ids))
        elif cursor is not None:
            query = query.where(PowerNeed.id > cursor)
        batch = session.execute(query).all()
        if not batch:
            break
        metrics["candidate_rows_scanned"] += len(batch)
        metrics["max_candidate_batch_size"] = max(metrics["max_candidate_batch_size"], len(batch))
        if selected_need_ids is None:
            cursor = batch[-1][0].id
        needs = [need for need, _project in batch]
        projects_by_id = {project.id: project for _need, project in batch}
        houston_project_ids.update(
            project.id
            for project in projects_by_id.values()
            if project.source_id == "houston-weekly-permits"
        )
        need_ids = [need.id for need in needs]
        project_ids = list(projects_by_id)
        _preflight_streamed_evidence_text(session, need_ids, project_ids)

        latest_retained_date: dict[UUID, str] = {}
        date_rows = session.execute(
            select(
                NeedObservation.need_id,
                func.max(func.coalesce(Evidence.published_at, Evidence.event_date)),
            )
            .join(Observation, Observation.id == NeedObservation.observation_id)
            .join(Evidence, Evidence.observation_id == Observation.id)
            .where(NeedObservation.need_id.in_(need_ids))
            .group_by(NeedObservation.need_id)
        )
        for need_id, retained_date in date_rows:
            metrics["historical_date_rows_aggregated"] += 1
            if retained_date is None:
                continue
            value = (
                retained_date.isoformat()
                if hasattr(retained_date, "isoformat")
                else str(retained_date)
            )
            if len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-":
                day = value[:10]
                latest_retained_date[need_id] = max(
                    latest_retained_date.get(need_id, "0000-00-00"), day
                )

        lifecycle_state_by_project = dict(
            session.execute(
                select(ProjectLifecycle.project_id, ProjectLifecycle.current_state).where(
                    ProjectLifecycle.project_id.in_(project_ids)
                )
            ).all()
        )
        project_priority_inputs = {
            project.id: PriorityInputAccumulator(lifecycle_state_by_project.get(project.id))
            for project in projects_by_id.values()
        }
        lifecycle_rows = session.execute(
            select(LifecycleEvent, Evidence, Interpretation)
            .join(Evidence, Evidence.id == LifecycleEvent.evidence_id)
            .join(Observation, Observation.id == Evidence.observation_id)
            .join(
                Interpretation,
                and_(
                    Interpretation.observation_id == Observation.id,
                    Interpretation.content_hash == Observation.content_hash,
                    Evidence.content_hash == Interpretation.assessment["evidence_hash"].as_string(),
                ),
            )
            .where(LifecycleEvent.project_id.in_(project_ids))
            .options(joinedload(Evidence.observation))
            .order_by(
                Evidence.published_at.asc().nullslast(),
                Evidence.observed_at,
                LifecycleEvent.recorded_at,
            )
        ).yield_per(128)
        for lifecycle_event, lifecycle_evidence, lifecycle_interpretation in lifecycle_rows:
            metrics["lifecycle_rows_streamed"] += 1
            project = projects_by_id.get(lifecycle_event.project_id)
            is_supported = project is not None and lifecycle_event_supported(
                lifecycle_event.event_type,
                lifecycle_evidence,
                lifecycle_interpretation,
                project,
                lifecycle_event.state,
                event=lifecycle_event,
            )
            if is_supported:
                metrics["supported_lifecycle_rows"] += 1
                project_priority_inputs[lifecycle_event.project_id].add_lifecycle(
                    lifecycle_event.event_type, lifecycle_event.state
                )
            for orm_row in (
                lifecycle_event,
                lifecycle_evidence,
                lifecycle_evidence.observation,
                lifecycle_interpretation,
            ):
                release_streamed_row(orm_row)
            metrics["max_resident_lifecycle_orm_rows"] = max(
                metrics["max_resident_lifecycle_orm_rows"],
                sum(
                    isinstance(row, LifecycleEvent | Evidence | Observation | Interpretation)
                    for row in session.identity_map.values()
                ),
            )

        need_states: dict[UUID, dict[str, Any]] = {}
        for need, project in batch:
            priority_inputs = PriorityInputAccumulator(lifecycle_state_by_project.get(project.id))
            project_inputs = project_priority_inputs[project.id]
            priority_inputs.lifecycle_phase = project_inputs.lifecycle_phase
            priority_inputs.lifecycle_producing = project_inputs.lifecycle_producing
            need_states[need.id] = {
                "need": need,
                "project": project,
                "priority": priority_inputs,
                "taylor_priority": PriorityInputAccumulator(
                    lifecycle_state_by_project.get(project.id)
                ),
                "qualification": CurrentNeedQualificationAccumulator(
                    session, need, project, sources=sources
                ),
                "research": ResearchSummaryAccumulator(need, project),
                "has_current_support": False,
                "taylor_identity_conflict": False,
                "first_priority_identity": None,
                "first_non_taylor_priority_identity": None,
                "first_admitted": None,
                "first_non_taylor_admitted": None,
                "signal_decisions": [],
                "has_unadjudicated_current_signal": False,
                "current_link_rows": 0,
            }
        metrics["max_compact_need_states_per_batch"] = max(
            metrics["max_compact_need_states_per_batch"], len(need_states)
        )

        current_link_rows = 0
        current_links = session.execute(
            select(NeedObservation.need_id, Observation, Evidence, Interpretation, SignalDecision)
            .join(Observation, Observation.id == NeedObservation.observation_id)
            .join(
                Interpretation,
                and_(
                    Interpretation.observation_id == Observation.id,
                    Interpretation.content_hash == Observation.content_hash,
                    Interpretation.assessment["semantic_hash"].as_string()
                    == Observation.content_hash,
                ),
            )
            .join(
                Evidence,
                and_(
                    Evidence.observation_id == Observation.id,
                    Evidence.content_hash == Interpretation.assessment["evidence_hash"].as_string(),
                ),
            )
            .outerjoin(
                SignalDecision,
                and_(
                    SignalDecision.observation_id == Observation.id,
                    SignalDecision.content_hash == Evidence.content_hash,
                    SignalDecision.policy_version == POLICY_VERSION,
                ),
            )
            .where(NeedObservation.need_id.in_(need_ids))
            .order_by(
                NeedObservation.need_id,
                Evidence.observed_at.desc(),
                Evidence.content_hash.desc(),
            )
        ).yield_per(128)
        for need_id, observation, evidence, interpretation, signal_decision in current_links:
            state = need_states[need_id]
            need = state["need"]
            project = state["project"]
            current_link_rows += 1
            state["current_link_rows"] += 1
            row = (observation, evidence, interpretation)
            state["has_current_support"] = state["has_current_support"] or (
                interpretation is not None
                and _need_has_current_support(
                    session,
                    need,
                    project,
                    links=[row],
                    sources=sources,
                )
            )
            state["qualification"].add_link(*row)
            if interpretation is not None:
                state["research"].add(observation, evidence, interpretation)
                if (
                    observation.source_id == "taylor-development-newsflash"
                    and "conflicting project or site facts"
                    in str((interpretation.assessment or {}).get("reason") or "")
                ):
                    state["taylor_identity_conflict"] = True

            assessment = _assessment_for_evidence(interpretation, observation, evidence)
            if assessment is not None and (
                assessment.get("project_identity_key") != project.identity_key
                or (assessment.get("power_activity") or assessment.get("activity_key"))
                != need.activity_key
            ):
                assessment = None
            is_taylor = observation.source_id == "taylor-development-newsflash"
            taylor_withdrawn = (
                lifecycle_state_by_project.get(project.id) == "planning_application_withdrawn"
            )
            if taylor_withdrawn and is_taylor:
                assessment = None
            if assessment is not None:
                identity = {
                    "id": evidence.id,
                    "source_id": observation.source_id,
                    "document_number": observation.external_id,
                }
                if state["first_priority_identity"] is None:
                    state["first_priority_identity"] = identity
                if not is_taylor and state["first_non_taylor_priority_identity"] is None:
                    state["first_non_taylor_priority_identity"] = identity
            state["priority"].add_evidence(
                published_at=evidence.published_at,
                event_date=evidence.event_date,
                supporting=assessment is not None and not is_taylor,
                title=evidence.title,
                abstract=evidence.abstract,
            )
            if assessment is not None and is_taylor:
                state["taylor_priority"].add_evidence(
                    title=evidence.title,
                    abstract=evidence.abstract,
                    supporting=True,
                )

            source = sources.get(observation.source_id)
            if (
                assessment is not None
                and source is not None
                and admitted_from_source(source, assessment, evidence).admitted
            ):
                if signal_decision is None:
                    state["has_unadjudicated_current_signal"] = True
                else:
                    state["signal_decisions"].append(signal_decision)
                action = {
                    "action": assessment.get("action"),
                    "reason": assessment.get("reason"),
                    "subject": assessment.get("subject"),
                    "reported_power_facts": assessment.get("reported_power_facts", []),
                }
                if state["first_admitted"] is None:
                    state["first_admitted"] = action
                if not is_taylor and state["first_non_taylor_admitted"] is None:
                    state["first_non_taylor_admitted"] = action
            for orm_row in (signal_decision, interpretation, evidence, observation):
                release_streamed_row(orm_row)
            metrics["max_resident_link_orm_rows"] = max(
                metrics["max_resident_link_orm_rows"],
                sum(
                    isinstance(row, SignalDecision | Evidence | Observation | Interpretation)
                    for row in session.identity_map.values()
                ),
            )
        metrics["max_current_link_rows_per_batch"] = max(
            metrics["max_current_link_rows_per_batch"], current_link_rows
        )
        metrics["max_current_link_rows_per_need"] = max(
            metrics["max_current_link_rows_per_need"],
            max((state["current_link_rows"] for state in need_states.values()), default=0),
        )

        for need, project in batch:
            state = need_states[need.id]
            if not state["has_current_support"]:
                continue
            research_state = state["research"].finish()
            qualified = state["qualification"].finish(research_state)
            effective = qualified or {
                "tier": "Signal",
                "required_mw": None,
                "supply": "Unknown",
            }
            if tier in {"Signal", "Prospect", "Lead"} and effective["tier"] != tier:
                continue
            current_lifecycle_state = lifecycle_state_by_project.get(project.id)
            signal_metadata = _signal_display_metadata(
                state["signal_decisions"],
                state["has_unadjudicated_current_signal"],
                is_signal=effective["tier"] == "Signal",
                lifecycle_state=current_lifecycle_state,
                identity_conflict=state["taylor_identity_conflict"],
            )
            taylor_withdrawn = current_lifecycle_state == "planning_application_withdrawn"
            max_date = latest_retained_date.get(need.id)
            if max_date:
                state["priority"].add_evidence(published_at=max_date, supporting=False)
                state["taylor_priority"].add_evidence(published_at=max_date, supporting=False)
            taylor_suppressed = taylor_withdrawn or state["taylor_identity_conflict"]
            if not taylor_suppressed:
                state["priority"].merge_supporting_evidence(state["taylor_priority"])
            first_admitted = (
                state["first_non_taylor_admitted"] if taylor_suppressed else state["first_admitted"]
            )
            identity = (
                state["first_non_taylor_priority_identity"]
                if taylor_suppressed
                else state["first_priority_identity"]
            )
            summary_evidence = (
                [
                    {
                        **identity,
                        "assessment_current": True,
                    }
                ]
                if identity is not None
                else []
            )
            if (
                not include_below_floor
                and commercial_size_status(
                    effective.get("required_mw"),
                    need.activity_key,
                    first_admitted.get("action") if first_admitted else None,
                    first_admitted.get("reported_power_facts", []) if first_admitted else [],
                    remaining_gap=(
                        effective.get("qualified_remaining_gap")
                        if effective.get("tier") == "Lead"
                        and effective.get("qualification_version")
                        else None
                    ),
                )
                == "below_floor"
            ):
                continue
            summary = {
                "id": need.id,
                "project_id": project.id,
                "_cohort_project_identity": project.identity_key,
                "_cohort_active": need.active,
                "name": project.name,
                "location": project.location,
                "tier": effective["tier"],
                "required_mw": effective.get("required_mw"),
                "start_window": effective.get("start_window"),
                "_updated_at": need.updated_at,
                "_cohort_version": need.updated_at.isoformat() if need.updated_at else "",
                "activity": need.activity_key,
                "supported_action": first_admitted.get("action") if first_admitted else None,
                "assessment_reason": first_admitted.get("reason") if first_admitted else None,
                "supported_subject": first_admitted.get("subject") if first_admitted else None,
                "asset_type": project.asset_type,
                "lifecycle_state": current_lifecycle_state,
                **signal_metadata,
                "lifecycle_timeline": [],
                "evidence": summary_evidence,
                "_browse_action_candidates": [first_admitted.get("action")]
                if first_admitted and first_admitted.get("action")
                else [],
                "_priority_features": state["priority"].snapshot(),
            }
            summary["_priority_segment"] = _priority(summary)[0]
            summaries.append(summary)
        metrics["summary_candidate_count"] = len(summaries)
        if selected_need_ids is not None:
            break
    summary_project_ids = {UUID(str(item["project_id"])) for item in summaries}
    houston_project_ids.intersection_update(summary_project_ids)
    if houston_project_ids:
        metrics["title_company_project_count"] = len(houston_project_ids)
        ordered_project_ids = sorted(houston_project_ids, key=str)
        for start in range(0, len(ordered_project_ids), _BROWSE_BUYING_CHAIN_PROJECT_BATCH_SIZE):
            project_batch = set(
                ordered_project_ids[
                    start : start + _BROWSE_BUYING_CHAIN_PROJECT_BATCH_SIZE
                ]
            )
            metrics["title_company_batch_count"] += 1
            metrics["max_title_company_batch_size"] = max(
                metrics["max_title_company_batch_size"], len(project_batch)
            )
            chain_views = buying_chain_views(session, project_batch)
            for summary in summaries:
                project_id = summary.get("project_id")
                if project_id not in project_batch:
                    continue
                title_company, title_company_role = _opportunity_title_company(
                    chain_views.get(str(project_id), {})
                )
                summary["title_company"] = title_company
                summary["title_company_role"] = title_company_role
    return summaries


def _opportunity_title_company(chain: dict) -> tuple[str | None, str | None]:
    owner_occupant = next(
        (
            fact["value"]
            for permit in chain.get("permit_summaries", [])
            for fact in permit.get("facts", [])
            if fact.get("label") == "Permit-listed owner / occupant"
            and str(fact.get("value") or "").strip()
        ),
        None,
    )
    if owner_occupant:
        return owner_occupant, "permit-listed owner / occupant"
    return None, None


def opportunity_projection(
    session,
    *,
    tier: str | None = None,
    search: str | None = None,
    include_below_floor: bool = False,
    selected_need_ids: set[UUID] | None = None,
    summary_only: bool = False,
    summary_diagnostics: dict[str, int] | None = None,
):
    if summary_only:
        return _opportunity_summary_projection(
            session,
            tier=tier,
            search=search,
            include_below_floor=include_below_floor,
            selected_need_ids=selected_need_ids,
            diagnostics=summary_diagnostics,
        )
    query = (
        select(PowerNeed, Project)
        .join(Project, PowerNeed.project_id == Project.id)
        .where(PowerNeed.active.is_(True))
        .order_by(PowerNeed.updated_at.desc(), PowerNeed.id)
    )
    if search:
        query = query.where(Project.name.ilike(f"%{search[:100]}%"))
    if selected_need_ids is not None:
        query = query.where(PowerNeed.id.in_(selected_need_ids))
    rows = session.execute(query).all()
    # One set of evidence/lifecycle reads for the list, preserving the same
    # version-bound admission checks used by ingestion and detail rendering.
    need_ids = [need.id for need, _ in rows]
    project_ids = [project.id for _, project in rows]
    sources = {source.id: source for source in session.scalars(select(Source))}
    lifecycle_by_project = {
        life.project_id: life
        for life in session.scalars(
            select(ProjectLifecycle).where(ProjectLifecycle.project_id.in_(project_ids))
        )
    }
    links_by_need = defaultdict(list)
    interpretations = {}
    for need_id, observation, evidence_row, interpretation in session.execute(
        select(NeedObservation.need_id, Observation, Evidence, Interpretation)
        .join(Observation, NeedObservation.observation_id == Observation.id)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .outerjoin(Interpretation, Interpretation.observation_id == Observation.id)
        .where(NeedObservation.need_id.in_(need_ids))
        .order_by(Evidence.observed_at.desc(), Evidence.content_hash.desc())
    ):
        links_by_need[need_id].append((observation, evidence_row, interpretation))
        interpretations[observation.id] = interpretation
    briefs_by_need = {
        brief.need_id: brief
        for brief in session.scalars(
            select(PowerNeedBrief).where(PowerNeedBrief.need_id.in_(need_ids))
        )
    }
    lifecycles_by_project = defaultdict(list)
    lifecycle_observations = set()
    for event, evidence_row in session.execute(
        select(LifecycleEvent, Evidence)
        .join(Evidence, LifecycleEvent.evidence_id == Evidence.id)
        .where(LifecycleEvent.project_id.in_(project_ids))
        .order_by(
            Evidence.published_at.asc().nullslast(),
            Evidence.observed_at,
            LifecycleEvent.recorded_at,
        )
    ):
        lifecycles_by_project[event.project_id].append((event, evidence_row))
        lifecycle_observations.add(event.observation_id)
    interpretations.update(
        {
            item.observation_id: item
            for item in session.scalars(
                select(Interpretation).where(
                    Interpretation.observation_id.in_(lifecycle_observations)
                )
            )
        }
    )
    decisions_by_version: dict[tuple[UUID, str], SignalDecision] = {}
    for decision_row in session.scalars(
        select(SignalDecision)
        .where(
            SignalDecision.observation_id.in_(list(interpretations)),
            SignalDecision.policy_version == POLICY_VERSION,
        )
        .order_by(SignalDecision.id.desc())
    ):
        decisions_by_version.setdefault(
            (decision_row.observation_id, decision_row.content_hash), decision_row
        )
    from gridlens.ingestion.service import effective_need_qualification
    from gridlens.intelligence.project_state import current_research_state

    projects_by_id = {project.id: project for _, project in rows}
    research_rows_by_project: dict[
        UUID, list[tuple[PowerNeed, Observation, Evidence, Interpretation]]
    ] = defaultdict(list)
    for need, project in rows:
        research_rows_by_project[project.id].extend(
            (need, observation, evidence_row, interpretation)
            for observation, evidence_row, interpretation in links_by_need[need.id]
            if interpretation is not None
        )
    research_by_project = {
        project_id: current_research_state(
            session,
            project_id,
            project=project,
            rows=research_rows_by_project.get(project_id, []),
        )
        for project_id, project in projects_by_id.items()
    }
    chain_project_ids = {
        project.id
        for need, project in rows
        if not summary_only
        and (
            project.source_id == "houston-weekly-permits" or briefs_by_need.get(need.id) is not None
        )
    }
    buying_chains_by_project = buying_chain_views(session, chain_project_ids)
    result = []
    title_company_by_project = {}
    lifecycle_timeline_by_state = {}
    for need, project in rows:
        research_state = research_by_project.get(project.id, {}).get(str(need.id), {})
        links = links_by_need[need.id]
        if not _need_has_current_support(session, need, project, links=links):
            continue
        qualified = effective_need_qualification(
            session,
            need,
            project,
            links=links,
            sources=sources,
            research_state=research_state,
        )
        effective = qualified or {
            "tier": "Signal",
            "rationale": need.rationale,
            "required_mw": None,
            "start_window": None,
            "duration": None,
            "supply": "Unknown",
        }
        if tier in {"Signal", "Prospect", "Lead"} and effective["tier"] != tier:
            continue
        lifecycle = lifecycle_by_project.get(project.id)
        lifecycle_rows = lifecycles_by_project[project.id]
        current_lifecycle_ids = set()
        for lifecycle_event, lifecycle_evidence in lifecycle_rows:
            lifecycle_interpretation = interpretations.get(lifecycle_event.observation_id)
            if lifecycle_event_supported(
                lifecycle_event.event_type,
                lifecycle_evidence,
                lifecycle_interpretation,
                project,
                lifecycle_event.state,
                event=lifecycle_event,
            ):
                current_lifecycle_ids.add(lifecycle_event.id)
        taylor_withdrawn = bool(
            lifecycle and lifecycle.current_state == "planning_application_withdrawn"
        )
        taylor_identity_conflict = any(
            obs.source_id == "taylor-development-newsflash"
            and interpretation is not None
            and "conflicting project or site facts"
            in str((interpretation.assessment or {}).get("reason") or "")
            for obs, _, interpretation in links
        )
        evidence = []
        current_assessments = []
        for obs, ev, interpretation in links:
            evidence_source = sources.get(obs.source_id)
            current_assessment = _assessment_for_evidence(interpretation, obs, ev)
            if current_assessment is not None:
                assessment_project = current_assessment.get("project_identity_key")
                assessment_activity = current_assessment.get(
                    "power_activity"
                ) or current_assessment.get("activity_key")
                if (
                    assessment_project != project.identity_key
                    or assessment_activity != need.activity_key
                ):
                    current_assessment = None
            if (
                taylor_withdrawn or taylor_identity_conflict
            ) and obs.source_id == "taylor-development-newsflash":
                current_assessment = None
            if (
                current_assessment
                and evidence_source is not None
                and admitted_from_source(evidence_source, current_assessment, ev).admitted
            ):
                current_assessments.append(current_assessment)
            if summary_only:
                evidence.append(
                    {
                        "id": ev.id,
                        "title": ev.title,
                        "abstract": ev.abstract,
                        "url": ev.url,
                        "published_at": ev.published_at,
                        "content_hash": ev.content_hash,
                        "event_date": ev.event_date,
                        "source_id": obs.source_id,
                        "document_number": obs.external_id,
                        "assessment_current": current_assessment is not None,
                        "permit_status": current_assessment.get("permit_status")
                        if current_assessment
                        else None,
                    }
                )
            else:
                evidence.append(
                    {
                        "id": ev.id,
                        "title": ev.title,
                        "abstract": ev.abstract,
                        "url": ev.url,
                        "published_at": ev.published_at,
                        "retrieved_at": ev.observed_at,
                        "extraction_location": ev.extraction_location,
                        "content_hash": ev.content_hash,
                        "event_date": ev.event_date,
                        "event_date_label": ev.event_date_label
                        or (
                            "Permit issue date (source publication date unknown)"
                            if ev.event_date and obs.source_id.endswith("-building-permits")
                            else "Source event date"
                            if ev.event_date
                            else "Unknown"
                        ),
                        "source_id": obs.source_id,
                        "source_origin": source_origin(
                            evidence_source.family, evidence_source.retrieval_method
                        )
                        if evidence_source is not None
                        else "Source evidence",
                        "document_number": obs.external_id,
                        "assessment_current": current_assessment is not None,
                        "permit_status": current_assessment.get("permit_status")
                        if current_assessment
                        else None,
                    }
                )
        current_assessment = current_assessments[0] if current_assessments else None
        display_decisions: list[SignalDecision] = []
        has_unadjudicated_current_signal = False
        for obs, ev, interpretation in links:
            if effective["tier"] != "Signal" or not _assessment_for_evidence(
                interpretation, obs, ev
            ):
                continue
            source = sources.get(obs.source_id)
            assessment = _assessment_for_evidence(interpretation, obs, ev)
            if assessment is not None:
                assessment_project = assessment.get("project_identity_key")
                assessment_activity = assessment.get("power_activity") or assessment.get(
                    "activity_key"
                )
                if (
                    assessment_project != project.identity_key
                    or assessment_activity != need.activity_key
                ):
                    assessment = None
            if (
                source is None
                or assessment is None
                or not admitted_from_source(source, assessment, ev).admitted
            ):
                continue
            decision = decisions_by_version.get((obs.id, ev.content_hash))
            if decision is not None:
                display_decisions.append(decision)
            else:
                has_unadjudicated_current_signal = True
        display_metadata = _signal_display_metadata(
            display_decisions,
            has_unadjudicated_current_signal,
            is_signal=effective["tier"] == "Signal",
            lifecycle_state=lifecycle.current_state if lifecycle else None,
            identity_conflict=taylor_identity_conflict,
        )
        display_decision = display_metadata["signal_display_decision"]
        display_source = display_metadata["signal_display_source"]
        display_reason = display_metadata["signal_display_reason"]
        display_state = display_metadata["signal_display_decision_state"]
        time_to_power_window = None
        if lifecycle and lifecycle.time_to_power_start and lifecycle.time_to_power_end:
            time_to_power_window = (
                f"{lifecycle.time_to_power_start.isoformat()} to "
                f"{lifecycle.time_to_power_end.isoformat()} (estimated)"
            )
        timeline_key = (project.id, taylor_withdrawn, taylor_identity_conflict)
        if timeline_key not in lifecycle_timeline_by_state:
            lifecycle_timeline_by_state[timeline_key] = [
                {
                    "state": event.state,
                    "event_type": event.event_type,
                    "date": event.occurred_on.isoformat() if event.occurred_on else None,
                    "value_kind": event.value_kind,
                    "evidence_url": lifecycle_evidence.url,
                    "current": event.id in current_lifecycle_ids
                    and (
                        not taylor_withdrawn or event.event_type == "planning_application_withdrawn"
                    )
                    and not taylor_identity_conflict,
                    "published_at": lifecycle_evidence.published_at,
                    "event_date_label": lifecycle_evidence.event_date_label,
                }
                for event, lifecycle_evidence in lifecycle_rows
            ]
        missing_facts = (
            current_assessment.get("missing_facts", [])
            if current_assessment
            else [
                label
                for value, label in (
                    (effective["required_mw"], "activity-specific power requirement"),
                    (effective["supply"] != "Unknown", "suitable supply"),
                    (effective["start_window"], "start window"),
                    (effective["duration"], "duration"),
                )
                if not value
            ]
        )
        reported_power_facts = (
            current_assessment.get("reported_power_facts", []) if current_assessment else []
        )
        supported_action = current_assessment.get("action") if current_assessment else None
        size_status = commercial_size_status(
            effective["required_mw"],
            need.activity_key,
            supported_action,
            reported_power_facts,
            remaining_gap=(
                effective.get("qualified_remaining_gap")
                if effective["tier"] == "Lead" and effective.get("qualification_version")
                else None
            ),
        )
        if size_status == "below_floor" and not include_below_floor:
            continue
        if not summary_only and project.id not in title_company_by_project:
            title_company = None
            title_company_role = None
            if project.source_id == "houston-weekly-permits":
                chain = buying_chains_by_project.get(str(project.id), {})
                title_company, title_company_role = _opportunity_title_company(chain)
            title_company_by_project[project.id] = (title_company, title_company_role)
        title_company, title_company_role = title_company_by_project.get(project.id, (None, None))
        result.append(
            {
                "id": need.id,
                "project_id": project.id,
                "name": project.name,
                "location": project.location,
                "tier": effective["tier"],
                "activity": need.activity_key,
                "rationale": (
                    "The latest linked Taylor revision withdraws this planning application. "
                    "Earlier project evidence remains historical; current project viability "
                    "and power need are UNKNOWN."
                    if taylor_withdrawn
                    else "A later Taylor revision conflicts with retained project or "
                    "site facts. "
                    "The earlier planning evidence remains historical; current application "
                    "and project status are UNKNOWN."
                    if taylor_identity_conflict
                    else effective["rationale"]
                ),
                "signal_evidence_state": (
                    "planning_application_withdrawn"
                    if taylor_withdrawn
                    else "planning_status_unknown"
                    if taylor_identity_conflict
                    else "active_evidence"
                ),
                "required_mw": effective["required_mw"],
                "commercial_size_status": size_status,
                "start_window": effective["start_window"],
                "duration": effective["duration"],
                "supply": effective["supply"],
                "next_action": effective.get("qualification_next_action")
                or (
                    "Confirm timing, duration, and remaining suitable supply for this activity."
                    if effective["tier"] == "Prospect"
                    else "Confirm activity power needs, timing, duration, and service plan."
                ),
                "research_state": research_state,
                # Internal raw-card proof; absence of current authority is not clearance.
                "qualification_conflict": effective.get("qualification_conflict", False)
                if qualified is not None
                else None,
                "conflict_state": "CONFLICT"
                if effective.get("qualification_conflict")
                or any(field.get("status") == "CONFLICT" for field in research_state.values())
                else "Not assessed",
                "assessment_reason": (
                    "The latest linked Taylor revision withdraws this planning application. "
                    "Earlier project evidence remains historical; current project viability "
                    "and power need are UNKNOWN."
                    if taylor_withdrawn
                    else "A later Taylor revision conflicts with retained project or "
                    "site facts. "
                    "The earlier planning evidence remains historical; current application "
                    "and project status are UNKNOWN."
                    if taylor_identity_conflict
                    else effective["rationale"]
                    if qualified is not None
                    else current_assessment.get("reason", need.rationale)
                    if current_assessment
                    else need.rationale
                ),
                "supported_subject": current_assessment.get("subject", project.name)
                if current_assessment
                else project.name,
                "supported_action": supported_action,
                "title_company": title_company,
                "title_company_role": title_company_role,
                "demand_quote": current_assessment.get("demand_quote")
                if current_assessment
                else None,
                "supply_quote": current_assessment.get("supply_quote")
                if current_assessment
                else None,
                "missing_facts": missing_facts,
                "reported_power_facts": reported_power_facts,
                "evidence": evidence,
                "asset_type": project.asset_type,
                "lifecycle_state": lifecycle.current_state if lifecycle else None,
                "lifecycle_timeline": lifecycle_timeline_by_state[timeline_key],
                "expected_next_milestone": (
                    None
                    if taylor_withdrawn or taylor_identity_conflict
                    else lifecycle.expected_next_milestone
                    if lifecycle
                    else None
                ),
                "expected_power_event": (
                    None
                    if taylor_withdrawn or taylor_identity_conflict
                    else lifecycle.expected_power_event
                    if lifecycle
                    else None
                ),
                "time_to_power_window": (
                    None if taylor_withdrawn or taylor_identity_conflict else time_to_power_window
                ),
                "estimate_basis": (
                    None
                    if taylor_withdrawn or taylor_identity_conflict
                    else lifecycle.estimate_basis
                    if lifecycle
                    else None
                ),
                "estimate_version": (
                    None if taylor_withdrawn else lifecycle.estimate_version if lifecycle else None
                ),
                "lifecycle_open_questions": lifecycle.open_questions if lifecycle else [],
                "monitoring_requirements": lifecycle.monitoring_requirements if lifecycle else [],
                "signal_display_decision": display_decision,
                "signal_display_decision_state": display_state,
                "signal_display_source": display_source,
                "signal_display_reason": display_reason,
                "signal_admission_origin": (need.admission_basis or {}).get("origin"),
                **(
                    {}
                    if summary_only
                    else brief_preview(
                        session,
                        need,
                        project,
                        links,
                        sources,
                        briefs_by_need.get(need.id),
                        buying_chains_by_project.get(str(project.id)),
                    )
                ),
            }
        )
    return result


class SignalDecisionCountsOut(BaseModel):
    show: int
    review: int
    hold: int
    unadjudicated: int


@app.get(
    "/api/signals/decisions",
    response_model=SignalDecisionCountsOut,
    dependencies=[Depends(require_session)],
)
def signal_decision_counts():
    """Count active Signal opportunity records using the same lifecycle policy as browse."""
    counts = {"show": 0, "review": 0, "hold": 0, "unadjudicated": 0}
    for item in opportunities(tier="Signal"):
        decision = item["signal_display_decision"]
        counts[decision.casefold() if decision else "unadjudicated"] += 1
    return counts


@app.post("/api/signals/decisions/adjudicate", dependencies=[Depends(require_session)])
def adjudicate_signal_batch(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
):
    """Explicit bounded replay/backfill; unchanged evidence and policy are idempotent."""
    require_same_origin(request)
    with SessionLocal.begin() as session:
        return adjudicate_current_signals(session, limit=limit)


def _change_sources(session, event: ChangeEvent) -> list[dict]:
    if event.buying_chain_evidence_id is not None:
        stored_ids = (event.new_state or {}).get("buying_chain_evidence_ids")
        ids = stored_ids if isinstance(stored_ids, list) else [event.buying_chain_evidence_id]
        sources = [session.get(BuyingChainEvidence, UUID(str(source_id))) for source_id in ids]
    else:
        sources = [session.get(Evidence, event.evidence_id)] if event.evidence_id else []
    return [
        {
            "id": source.id,
            "title": source.title,
            "url": source.url,
            "published_at": source.published_at,
        }
        for source in sources
        if source is not None
    ]


@app.get("/api/changes", response_model=list[ChangeOut], dependencies=[Depends(require_session)])
def changes():
    with SessionLocal() as session:
        today = chicago_today()
        rows = session.execute(
            select(ChangeEvent, Evidence, BuyingChainEvidence)
            .outerjoin(Evidence, Evidence.id == ChangeEvent.evidence_id)
            .outerjoin(
                BuyingChainEvidence, BuyingChainEvidence.id == ChangeEvent.buying_chain_evidence_id
            )
            .where(
                ChangeEvent.material.is_(True),
                func.timezone("America/Chicago", ChangeEvent.created_at).cast(Date) == today,
            )
            .order_by(ChangeEvent.created_at.desc())
        ).all()
        return [
            {
                "kind": event.kind,
                "title": buying.title if buying else evidence.title,
                "url": buying.url if buying else evidence.url,
                "published_at": (
                    (buying.published_at if buying else evidence.published_at).isoformat()
                    if (buying.published_at if buying else evidence.published_at)
                    else None
                ),
                "sources": _change_sources(session, event),
            }
            for event, evidence, buying in rows
        ]


@app.get(
    "/api/projects/{project_id}/state",
    response_model=ProjectStateOut,
    dependencies=[Depends(require_session)],
)
def project_state_endpoint(project_id: UUID):
    with SessionLocal() as session:
        state = read_project_state(session, project_id)
        if state is None:
            raise HTTPException(404, "Project not found")
        return state


@app.get(
    "/api/projects/{project_id}/changes",
    response_model=list[ProjectChangeOut],
    dependencies=[Depends(require_session)],
)
def project_changes_endpoint(project_id: UUID, limit: int = Query(default=100, ge=1, le=250)):
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(404, "Project not found")
        events = session.scalars(
            select(ChangeEvent)
            .where(ChangeEvent.project_id == project_id, ChangeEvent.material.is_(True))
            .order_by(ChangeEvent.created_at.desc(), ChangeEvent.id.desc())
            .limit(limit)
        ).all()
        return [
            {
                "kind": e.kind,
                "field": e.field_name,
                "prior": e.prior_state,
                "new": e.new_state,
                "evidence_id": str(e.evidence_id) if e.evidence_id else None,
                "buying_chain_evidence_id": (
                    str(e.buying_chain_evidence_id) if e.buying_chain_evidence_id else None
                ),
                "sources": _change_sources(session, e),
                "source_date": e.source_date,
                "detected_at": e.created_at,
            }
            for e in events
        ]


@app.post("/api/refresh", response_model=RefreshOut, dependencies=[Depends(require_session)])
def refresh(request: Request):
    require_same_origin(request)
    from gridlens.jobs.worker import sync_registry

    definitions = sync_registry()
    with SessionLocal.begin() as session:
        sources = {
            row.id: row
            for row in session.scalars(
                select(Source).where(Source.id.in_([d["id"] for d in definitions]))
            )
        }
        ids = [
            str(enqueue(session, item["id"]))
            for item in definitions
            if sources[item["id"]].enabled and sources[item["id"]].registry_enabled
        ]
    return {"queued": ids}


@app.post(
    "/api/sources/{source_id}/enabled",
    response_model=SourceEnabledOut,
    dependencies=[Depends(require_session)],
)
def set_source_enabled_endpoint(source_id: str, body: SourceEnabledIn, request: Request):
    require_same_origin(request)
    from gridlens.jobs.worker import set_source_enabled

    try:
        set_source_enabled(source_id, body.enabled)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise HTTPException(404, "Source not found")
        return {
            "id": source.id,
            "registry_enabled": source.registry_enabled,
            "operator_enabled": source.enabled,
            "effective_enabled": source.enabled and source.registry_enabled,
        }


@app.get(
    "/api/projects/{project_id}/buying-chain",
    response_model=BuyingChainOut,
    dependencies=[Depends(require_session)],
)
def project_buying_chain(project_id: UUID, history: bool = False):
    with SessionLocal() as session:
        try:
            return buying_chain_view(session, project_id, history=history)
        except LookupError as exc:
            raise HTTPException(404, "Project not found") from exc


@app.get(
    "/api/power-needs/{need_id}/brief",
    response_model=BriefOut,
    dependencies=[Depends(require_session)],
)
def get_power_need_brief(need_id: UUID):
    with SessionLocal() as session:
        try:
            payload, _ = brief_input(session, need_id)
        except LookupError as exc:
            raise HTTPException(404, "Power need not found") from exc
        except BriefUnavailable:
            payload = None
        row = session.get(PowerNeedBrief, need_id)
        return brief_view(row, brief_fingerprint(payload) if payload else None)


@app.post(
    "/api/power-needs/{need_id}/brief",
    response_model=BriefRequestOut,
    dependencies=[Depends(require_session)],
)
def create_power_need_brief(need_id: UUID, request: Request):
    require_same_origin(request)
    with SessionLocal.begin() as session:
        try:
            return request_brief(session, need_id)
        except LookupError as exc:
            raise HTTPException(404, "Power need not found") from exc
        except BriefUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc


@app.post(
    "/api/projects/{project_id}/buying-chain/enrich",
    response_model=BuyingChainOut,
    dependencies=[Depends(require_session)],
)
def enrich_project_buying_chain(
    project_id: UUID, request: Request, body: BuyingEnrichBody | None = None
):
    require_same_origin(request)
    with SessionLocal.begin() as session:
        try:
            return enrich_buying_chain(
                session, project_id, source_urls=body.source_urls if body else []
            )
        except LookupError as exc:
            raise HTTPException(404, "Project not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc


# Commercial action workflow is independent of the existing evidence tiers.
from gridlens.domain.pursuits import (  # noqa: E402
    CallNoteBody,
    CallNoteOut,
    PursuitJobOut,
    PursuitOut,
    PursuitsOut,
)
from gridlens.intelligence.pursuits import (  # noqa: E402
    job_view,
    list_pursuits,
    note_view,
    pursuit_view,
)
from gridlens.persistence.models import Pursuit, PursuitCallNote  # noqa: E402


@app.get("/api/pursuits", response_model=PursuitsOut, dependencies=[Depends(require_session)])
def pursuits(include_dropped: bool = False, offset: int = Query(default=0, ge=0, le=10000)):
    with SessionLocal() as session:
        return list_pursuits(session, include_dropped=include_dropped, offset=offset)


@app.get(
    "/api/pursuits/{pursuit_id}", response_model=PursuitOut, dependencies=[Depends(require_session)]
)
def pursuit_detail(pursuit_id: UUID):
    with SessionLocal() as session:
        row = session.get(Pursuit, pursuit_id)
        if not row or not row.snapshot:
            raise HTTPException(404, "Pursuit not found")
        if row.identity_key.startswith("commercial-need:"):
            raise HTTPException(
                404,
                "Commercial triage workspaces are available through /api/commercial/triage",
            )
        return pursuit_view(session, row)


@app.post(
    "/api/pursuits/refresh", response_model=PursuitJobOut, dependencies=[Depends(require_session)]
)
def refresh_pursuits(request: Request, force: bool = False):
    require_same_origin(request)
    with SessionLocal.begin() as session:
        try:
            job_id = enqueue(session, "austin-building-permits", kind="pursuit_research")
        except ValueError as exc:
            raise HTTPException(409, "Enable and reconcile Austin ingestion first") from exc
        job = session.get(Job, job_id)
        assert job
        if job.status == "queued" and job.attempts == 0 and job.checkpoint is None:
            import json

            job.checkpoint = json.dumps({"force": force})
        return job_view(job)


@app.post(
    "/api/pursuits/{pursuit_id}/notes",
    response_model=CallNoteOut,
    dependencies=[Depends(require_session)],
)
def save_pursuit_note(pursuit_id: UUID, body: CallNoteBody, request: Request):
    require_same_origin(request)
    with SessionLocal.begin() as session:
        row = session.scalar(select(Pursuit).where(Pursuit.id == pursuit_id).with_for_update())
        if row is None:
            raise HTTPException(404, "Pursuit not found")
        prior = session.scalar(
            select(PursuitCallNote).where(
                PursuitCallNote.pursuit_id == pursuit_id,
                PursuitCallNote.client_id == body.client_id,
            )
        )
        if prior:
            if any(getattr(prior, key) != value for key, value in body.model_dump().items()):
                raise HTTPException(
                    409, "This note request was already saved with different content"
                )
            return note_view(prior)
        note = PursuitCallNote(pursuit_id=pursuit_id, owner="Nick Sandoval", **body.model_dump())
        session.add(note)
        session.flush()
        return note_view(note)


def _commercial_triage_page(
    session, limit: int, offset: int = 0
) -> tuple[list[dict], int]:
    history_count = int(
        session.scalar(
            select(func.count()).select_from(Pursuit).where(
                Pursuit.identity_key.like("commercial-need:%")
            )
        )
        or 0
    )
    if history_count > _MAX_COMMERCIAL_CARD_NOTES:
        raise HTTPException(413, "Saved commercial history exceeds the triage overview row budget")
    max_snapshot_size = int(
        session.scalar(
            select(func.max(func.octet_length(cast(Pursuit.snapshot, Text)))).where(
                Pursuit.identity_key.like("commercial-need:%")
            )
        )
        or 0
    )
    if max_snapshot_size > _MAX_SAVED_SNAPSHOT_BYTES:
        raise HTTPException(413, "Saved commercial history exceeds the triage overview byte budget")
    from gridlens.persistence.models import PursuitResearchQuestion

    question_count = int(
        session.scalar(select(func.count()).select_from(PursuitResearchQuestion)) or 0
    )
    if question_count > _MAX_COMMERCIAL_CARD_NOTES:
        raise HTTPException(
            413, "Commercial research history exceeds the triage overview row budget"
        )
    summaries = opportunity_projection(session, tier="Signal", summary_only=True)
    all_keyed_groups = grouped_need_groups(summaries)
    selected_keyed_groups = all_keyed_groups[offset : offset + limit]
    for identity, group in selected_keyed_groups:
        if len(group) > 50:
            raise HTTPException(
                413,
                {
                    "code": "commercial_group_too_large",
                    "group_id": "cg_" + hashlib.sha256(identity.encode()).hexdigest()[:32],
                    "group_member_count": len(group),
                    "max_group_members": 50,
                    "message": (
                        "This work group exceeds the supported card size; "
                        "no evaluation was saved."
                    ),
                },
            )
    selected_groups = [need_ids for _identity, need_ids in selected_keyed_groups]
    selected_ids = {UUID(need_id) for group in selected_groups for need_id in group}
    summary_by_id = {str(item["id"]): item for item in summaries}

    evidence_counts_by_need = dict(
        session.execute(
            select(NeedObservation.need_id, func.count(Evidence.id))
            .select_from(NeedObservation)
            .join(Observation, Observation.id == NeedObservation.observation_id)
            .join(Evidence, Evidence.observation_id == Observation.id)
            .outerjoin(
                Interpretation,
                and_(
                    Interpretation.observation_id == Observation.id,
                    Interpretation.content_hash == Observation.content_hash,
                ),
            )
            .where(NeedObservation.need_id.in_(selected_ids))
            .group_by(NeedObservation.need_id)
        ).all()
    )
    project_ids_by_need = {
        UUID(need_id): UUID(str(summary_by_id[need_id]["project_id"]))
        for group in selected_groups
        for need_id in group
    }
    selected_project_ids = set(project_ids_by_need.values())
    lifecycle_counts_by_project = dict(
        session.execute(
            select(LifecycleEvent.project_id, func.count(LifecycleEvent.id))
            .where(LifecycleEvent.project_id.in_(selected_project_ids))
            .group_by(LifecycleEvent.project_id)
        ).all()
    )
    relationship_counts_by_project = dict(
        session.execute(
            select(BuyingChainEvidence.project_id, func.count(BuyingChainEvidence.id))
            .where(BuyingChainEvidence.project_id.in_(selected_project_ids))
            .group_by(BuyingChainEvidence.project_id)
        ).all()
    )
    workspace_ids_by_need = {
        UUID(need_id): f"commercial-need:{need_id}"
        for group in selected_groups
        for need_id in group
    }
    selected_workspace_ids = set(workspace_ids_by_need.values())
    workspace_sizes = dict(
        session.execute(
            select(Pursuit.identity_key, func.octet_length(cast(Pursuit.snapshot, Text))).where(
                Pursuit.identity_key.in_(selected_workspace_ids)
            )
        ).all()
    )
    note_counts_by_workspace = dict(
        session.execute(
            select(Pursuit.identity_key, func.count(PursuitCallNote.id))
            .join(Pursuit, Pursuit.id == PursuitCallNote.pursuit_id)
            .where(Pursuit.identity_key.in_(selected_workspace_ids))
            .group_by(Pursuit.identity_key)
        ).all()
    )

    for identity, group in selected_keyed_groups:
        group_need_ids = {UUID(need_id) for need_id in group}
        evidence_rows = sum(evidence_counts_by_need.get(need_id, 0) for need_id in group_need_ids)
        if evidence_rows > _MAX_COMMERCIAL_CARD_EVIDENCE_ROWS:
            raise _commercial_bound_error(
                identity, evidence_rows, _MAX_COMMERCIAL_CARD_EVIDENCE_ROWS, "evidence_rows"
            )
        project_ids_for_group = {project_ids_by_need[need_id] for need_id in group_need_ids}
        lifecycle_rows = sum(
            lifecycle_counts_by_project.get(project_id, 0)
            for project_id in project_ids_for_group
        )
        if lifecycle_rows > _MAX_COMMERCIAL_CARD_LIFECYCLE_ROWS:
            raise _commercial_bound_error(
                identity,
                lifecycle_rows,
                _MAX_COMMERCIAL_CARD_LIFECYCLE_ROWS,
                "lifecycle_rows",
            )
        relationship_rows = sum(
            relationship_counts_by_project.get(project_id, 0)
            for project_id in project_ids_for_group
        )
        if relationship_rows > _MAX_COMMERCIAL_CARD_RELATIONSHIP_ROWS:
            raise _commercial_bound_error(
                identity,
                relationship_rows,
                _MAX_COMMERCIAL_CARD_RELATIONSHIP_ROWS,
                "relationship_rows",
            )
        group_workspace_ids = [workspace_ids_by_need[need_id] for need_id in group_need_ids]
        for workspace_id in group_workspace_ids:
            snapshot_size = workspace_sizes.get(workspace_id)
            if snapshot_size and snapshot_size > _MAX_SAVED_SNAPSHOT_BYTES:
                raise _commercial_bound_error(
                    identity,
                    snapshot_size,
                    _MAX_SAVED_SNAPSHOT_BYTES,
                    "saved_snapshot_bytes",
                )
        note_count = sum(
            note_counts_by_workspace.get(workspace_id, 0) for workspace_id in group_workspace_ids
        )
        if note_count > _MAX_COMMERCIAL_CARD_NOTES:
            raise _commercial_bound_error(identity, note_count, _MAX_COMMERCIAL_CARD_NOTES, "notes")
    selected = opportunity_projection(session, tier="Signal", selected_need_ids=selected_ids)
    project_ids = {item["project_id"] for item in selected}
    chains = buying_chain_views(session, project_ids)
    cards = make_commercial_cards(selected, chains, chicago_today(), limit)
    encoded_size = len(json.dumps(cards, default=str, separators=(",", ":")).encode("utf-8"))
    if encoded_size > _MAX_COMMERCIAL_CARD_BYTES:
        identity = selected_keyed_groups[0][0] if selected_keyed_groups else "empty"
        raise _commercial_bound_error(
            identity, encoded_size, _MAX_COMMERCIAL_CARD_BYTES, "card_bytes"
        )
    return cards, len(all_keyed_groups)


def _commercial_triage_cards(session, limit: int) -> list[dict]:
    """Return the legacy complete shortlist shape used by research callers."""
    cards, _grouped_total = _commercial_triage_page(session, limit)
    return cards


def _commercial_triage_payload(session, limit: int, offset: int = 0) -> dict:
    _begin_consistent_read(session)
    cards, grouped_total = _commercial_triage_page(session, limit, offset)
    today = chicago_today().isoformat()
    identities = ["commercial-need:" + item["id"] for item in cards]
    workspaces = (
        {
            row.identity_key.removeprefix("commercial-need:"): row
            for row in session.scalars(select(Pursuit).where(Pursuit.identity_key.in_(identities)))
        }
        if identities
        else {}
    )
    notes_by_pursuit: dict[UUID, list[dict]] = {row.id: [] for row in workspaces.values()}
    if notes_by_pursuit:
        for note in session.scalars(
            select(PursuitCallNote)
            .where(PursuitCallNote.pursuit_id.in_(list(notes_by_pursuit)))
            .order_by(PursuitCallNote.created_at.desc(), PursuitCallNote.id)
        ):
            notes_by_pursuit[note.pursuit_id].append(note_view(note))
    for card in cards:
        row = workspaces.get(card["id"])
        card["pursuit_id"] = row.id if row else None
        card["notes"] = notes_by_pursuit.get(row.id, []) if row else []
    cohort = {
        key: sum(card["disposition"] == label for card in cards)
        for key, label in (
            ("action_now", "ACTION NOW"),
            ("research", "RESEARCH"),
            ("watch", "WATCH"),
            ("reject", "REJECT"),
        )
    }
    receipts = list(
        session.scalars(select(Pursuit).where(Pursuit.identity_key.like("commercial-need:%")))
    )
    evaluated = sum(
        (row.snapshot or {}).get("commercial_triage", {}).get("evaluated_on") == today
        for row in receipts
    )
    surfaced = sum(
        (row.snapshot or {}).get("commercial_triage", {}).get("surfaced_on") == today
        for row in receipts
    )
    midnight = (
        datetime.now(UTC)
        .astimezone(ZoneInfo("America/Chicago"))
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(UTC)
    )

    def outcome_count(outcomes: list[str]) -> int:
        return int(
            session.scalar(
                select(func.count(func.distinct(PursuitCallNote.pursuit_id)))
                .join(Pursuit)
                .where(
                    Pursuit.identity_key.like("commercial-need:%"),
                    PursuitCallNote.created_at >= midnight,
                    PursuitCallNote.outcome.in_(outcomes),
                )
            )
            or 0
        )

    from gridlens.intelligence.research_metrics import research_overview
    from gridlens.persistence.models import PursuitResearchQuestion

    questions = list(session.scalars(select(PursuitResearchQuestion)))
    payload = {
        "research_overview": research_overview(cards, questions, receipts, midnight),
        "evaluated_at": datetime.now(UTC),
        "policy_version": COMMERCIAL_TRIAGE_POLICY,
        "total": len(cards),
        "limit": limit,
        "offset": offset,
        "grouped_total": grouped_total,
        "next_offset": offset + len(cards) if offset + len(cards) < grouped_total else None,
        "cohort_counts": cohort,
        "daily": {
            "evaluated": evaluated,
            "surfaced": surfaced,
            "contacted": outcome_count(
                ["Contacted", "Needs follow-up", "Reached buying organization", "Qualified"]
            ),
            "reached_buyer": outcome_count(["Reached buying organization"]),
            "qualified": outcome_count(["Qualified"]),
            "promoted_prospects": None,
            "promoted_leads": None,
            "supported_mw": None,
            "metric_scope": [
                "Daily outcomes count explicit operator notes. Triage never writes tier "
                "promotions or MW totals."
            ],
            "unavailable_metrics": [
                "Prospect/Lead promotion history is unavailable in retained change events.",
                "A corpus MW total is unavailable because work identities are grouped; "
                "use cited need-level values on cards.",
                "Reached/qualified counts are operator-reported and do not change evidence tiers.",
            ],
        },
        "items": cards,
    }
    size = len(json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8"))
    if size > _MAX_COMMERCIAL_CARD_BYTES:
        identity = "commercial-page:" + str(offset)
        raise _commercial_bound_error(
            identity, size, _MAX_COMMERCIAL_CARD_BYTES, "triage_page_bytes"
        )
    return payload


@app.get(
    "/api/commercial/triage",
    response_model=CommercialTriagePageOut,
    dependencies=[Depends(require_session)],
)
def commercial_triage(
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    with SessionLocal() as session:
        return _commercial_triage_payload(session, limit, offset)


@app.get(
    "/api/commercial/triage/{need_id}/autonomous-research",
    response_model=AutonomousResearchOut,
    dependencies=[Depends(require_session)],
)
def autonomous_research_status(need_id: UUID):
    from gridlens.intelligence.pursuit_questions import question_view
    from gridlens.persistence.models import PursuitResearchQuestion

    with SessionLocal() as session:
        if session.get(PowerNeed, need_id) is None:
            raise HTTPException(404, "Power need not found")
        rows = session.scalars(
            select(PursuitResearchQuestion)
            .where(PursuitResearchQuestion.need_id == need_id)
            .order_by(PursuitResearchQuestion.created_at.desc(), PursuitResearchQuestion.id)
            .limit(30)
        )
        return {"items": [question_view(row) for row in rows]}


@app.post(
    "/api/commercial/triage/{need_id}/autonomous-research",
    response_model=AutonomousResearchOut,
    dependencies=[Depends(require_session)],
)
def request_autonomous_research(need_id: UUID, body: AutonomousResearchBody, request: Request):
    require_same_origin(request)
    from gridlens.intelligence.pursuit_questions import question_view, schedule_questions

    with SessionLocal.begin() as session:
        cards = _commercial_triage_cards(session, 50)
        card = next((card for card in cards if str(card["id"]) == str(need_id)), None)
        if card is None:
            raise HTTPException(409, "Power need is not in the current commercial cohort")
        rows = schedule_questions(session, [card], force=body.force, origin="manual")
        return {"items": [question_view(row) for row in rows]}


def _commercial_history_item(row: Any, notes: list[dict]) -> dict:
    receipt = (row.snapshot or {}).get("commercial_triage", {})
    saved_card = receipt.get("saved_card")
    if isinstance(saved_card, dict):
        saved_card = {**saved_card, "pursuit_id": str(row.id), "notes": []}
    else:
        saved_card = None
    stored_versions = receipt.get("versions")
    versions = stored_versions if isinstance(stored_versions, list) and stored_versions else [
        {
            "version": 1,
            "disposition": receipt.get("disposition")
            or (saved_card or {}).get("disposition")
            or "UNKNOWN",
            "evaluated_at": receipt.get("saved_at"),
            "evaluated_on": receipt.get("evaluated_on"),
            "input_hash": receipt.get("input_hash") or (saved_card or {}).get("input_hash"),
            "snapshot_status": "saved_as_of" if saved_card else "metadata_only",
            "live_status": "not_rechecked",
            "saved_card": saved_card,
        }
    ]
    normalized_versions = []
    for index, version in enumerate(versions, start=1):
        version_card = version.get("saved_card")
        if isinstance(version_card, dict):
            version_card = {**version_card, "pursuit_id": str(row.id), "notes": []}
        else:
            version_card = None
        normalized_versions.append(
            {
                **version,
                "version": version.get("version") or index,
                "snapshot_status": "saved_as_of" if version_card else "metadata_only",
                "live_status": "not_rechecked",
                "saved_card": version_card,
            }
        )
    return {
        "pursuit_id": row.id,
        "need_id": receipt.get("need_id") or row.identity_key.removeprefix("commercial-need:"),
        "project_id": row.project_id,
        "related_project_ids": row.project_ids or [str(row.project_id)],
        "disposition": receipt.get("disposition")
        or (saved_card or {}).get("disposition")
        or "UNKNOWN",
        "evaluated_at": receipt.get("saved_at"),
        "evaluated_on": receipt.get("evaluated_on"),
        "input_hash": receipt.get("input_hash") or (saved_card or {}).get("input_hash"),
        "snapshot_status": "saved_as_of" if saved_card else "metadata_only",
        "live_status": "not_rechecked",
        "saved_card": saved_card,
        "notes": notes,
        "versions": normalized_versions,
    }


@app.get(
    "/api/commercial/triage/history",
    response_model=CommercialTriageHistoryPageOut,
    dependencies=[Depends(require_session)],
)
def commercial_triage_history(
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Read evaluated Pursuit snapshots; never refreshes live facts or dispositions."""
    with SessionLocal() as session:
        _begin_consistent_read(session)
        history_scope = Pursuit.identity_key.like("commercial-need:%")
        total = int(
            session.scalar(select(func.count()).select_from(Pursuit).where(history_scope)) or 0
        )
        saved_at = Pursuit.snapshot["commercial_triage"]["saved_at"].astext
        history_ids = list(
            session.scalars(
                select(Pursuit.id)
                .where(history_scope)
                .order_by(saved_at.desc().nullslast(), Pursuit.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        snapshot_sizes: dict[UUID, int | None] = {
            pursuit_id: size
            for pursuit_id, size in session.execute(
                select(Pursuit.id, func.octet_length(cast(Pursuit.snapshot, Text))).where(
                    Pursuit.id.in_(history_ids)
                )
            ).all()
        } if history_ids else {}
        oversized_snapshot = next(
            (
                (pursuit_id, size)
                for pursuit_id, size in snapshot_sizes.items()
                if size and size > _MAX_SAVED_SNAPSHOT_BYTES
            ),
            None,
        )
        if oversized_snapshot:
            raise _commercial_bound_error(
                str(oversized_snapshot[0]),
                oversized_snapshot[1],
                _MAX_SAVED_SNAPSHOT_BYTES,
                "saved_snapshot_bytes",
            )
        note_counts: dict[UUID, int] = {
            pursuit_id: count
            for pursuit_id, count in session.execute(
                select(PursuitCallNote.pursuit_id, func.count(PursuitCallNote.id))
                .where(PursuitCallNote.pursuit_id.in_(history_ids))
                .group_by(PursuitCallNote.pursuit_id)
            ).all()
        } if history_ids else {}
        note_bytes_by_pursuit: dict[UUID, int] = {
            pursuit_id: byte_count
            for pursuit_id, byte_count in session.execute(
                select(
                    PursuitCallNote.pursuit_id,
                    func.sum(
                        func.octet_length(PursuitCallNote.note)
                        + func.octet_length(PursuitCallNote.outcome)
                        + func.octet_length(PursuitCallNote.next_action)
                    ),
                )
                .where(PursuitCallNote.pursuit_id.in_(history_ids))
                .group_by(PursuitCallNote.pursuit_id)
            ).all()
        } if history_ids else {}
        page_note_count = sum(note_counts.values())
        page_bytes = sum(size or 0 for size in snapshot_sizes.values()) + sum(
            note_bytes_by_pursuit.values()
        )
        if page_note_count > _MAX_COMMERCIAL_CARD_NOTES:
            raise _commercial_bound_error(
                str(history_ids[0]), page_note_count, _MAX_COMMERCIAL_CARD_NOTES, "page_notes"
            )
        if page_bytes > _MAX_COMMERCIAL_HISTORY_PAGE_BYTES:
            raise _commercial_bound_error(
                str(history_ids[0]),
                page_bytes,
                _MAX_COMMERCIAL_HISTORY_PAGE_BYTES,
                "history_page_bytes",
            )
        rows_by_id = {
            row.id: row
            for row in session.scalars(select(Pursuit).where(Pursuit.id.in_(history_ids)))
        } if history_ids else {}
        rows = [rows_by_id[pursuit_id] for pursuit_id in history_ids]
        for row in rows:
            _check_saved_history_bounds(row, note_counts.get(row.id, 0))
        notes_by_pursuit: dict[UUID, list[dict]] = {row.id: [] for row in rows}
        if rows:
            notes = session.scalars(
                select(PursuitCallNote)
                .where(PursuitCallNote.pursuit_id.in_(list(notes_by_pursuit)))
                .order_by(PursuitCallNote.created_at.desc(), PursuitCallNote.id)
            )
            for note in notes:
                notes_by_pursuit[note.pursuit_id].append(note_view(note))
        history = []
        for row in rows:
            receipt = (row.snapshot or {}).get("commercial_triage", {})
            saved_card = receipt.get("saved_card")
            if isinstance(saved_card, dict):
                saved_card = {
                    **saved_card,
                    "pursuit_id": str(row.id),
                    "notes": [],
                }
            else:
                saved_card = None
            stored_versions = receipt.get("versions")
            if isinstance(stored_versions, list) and stored_versions:
                versions = stored_versions
            else:
                versions = [
                    {
                        "version": 1,
                        "disposition": receipt.get("disposition")
                        or (saved_card or {}).get("disposition")
                        or "UNKNOWN",
                        "evaluated_at": receipt.get("saved_at"),
                        "evaluated_on": receipt.get("evaluated_on"),
                        "input_hash": receipt.get("input_hash")
                        or (saved_card or {}).get("input_hash"),
                        "snapshot_status": "saved_as_of" if saved_card else "metadata_only",
                        "live_status": "not_rechecked",
                        "saved_card": saved_card,
                    }
                ]
            normalized_versions = []
            for index, version in enumerate(versions, start=1):
                version_card = version.get("saved_card")
                if isinstance(version_card, dict):
                    version_card = {**version_card, "pursuit_id": str(row.id), "notes": []}
                else:
                    version_card = None
                normalized_versions.append(
                    {
                        **version,
                        "version": version.get("version") or index,
                        "snapshot_status": "saved_as_of" if version_card else "metadata_only",
                        "live_status": "not_rechecked",
                        "saved_card": version_card,
                    }
                )
            history.append(
                {
                    "pursuit_id": row.id,
                    "need_id": receipt.get("need_id")
                    or row.identity_key.removeprefix("commercial-need:"),
                    "project_id": row.project_id,
                    "related_project_ids": row.project_ids or [str(row.project_id)],
                    "disposition": receipt.get("disposition")
                    or (saved_card or {}).get("disposition")
                    or "UNKNOWN",
                    "evaluated_at": receipt.get("saved_at"),
                    "evaluated_on": receipt.get("evaluated_on"),
                    "input_hash": receipt.get("input_hash") or (saved_card or {}).get("input_hash"),
                    "snapshot_status": "saved_as_of" if saved_card else "metadata_only",
                    "live_status": "not_rechecked",
                    "saved_card": saved_card,
                    "notes": notes_by_pursuit[row.id],
                    "versions": normalized_versions,
                }
            )
        result = {
            "items": history,
            "total": total,
            "limit": limit,
            "offset": offset,
            "next_offset": offset + len(history) if offset + len(history) < total else None,
        }
        response_size = len(json.dumps(result, default=str, separators=(",", ":")).encode("utf-8"))
        if response_size > _MAX_COMMERCIAL_HISTORY_PAGE_BYTES:
            raise _commercial_bound_error(
                f"commercial-history-page:{offset}",
                response_size,
                _MAX_COMMERCIAL_HISTORY_PAGE_BYTES,
                "history_page_bytes",
            )
        return result


@app.get(
    "/api/commercial/triage/history/{pursuit_id}",
    response_model=CommercialTriageHistoryItem,
    dependencies=[Depends(require_session)],
)
def commercial_triage_history_detail(pursuit_id: UUID):
    """Hydrate one bounded saved snapshot without rechecking live evidence."""
    with SessionLocal() as session:
        _begin_consistent_read(session)
        identity_key = session.scalar(
            select(Pursuit.identity_key).where(Pursuit.id == pursuit_id)
        )
        if identity_key is None or not identity_key.startswith("commercial-need:"):
            raise HTTPException(404, "Saved commercial snapshot not found")
        snapshot_size = int(
            session.scalar(
                select(func.octet_length(cast(Pursuit.snapshot, Text))).where(
                    Pursuit.id == pursuit_id
                )
            )
            or 0
        )
        if snapshot_size > _MAX_SAVED_SNAPSHOT_BYTES:
            raise _commercial_bound_error(
                identity_key, snapshot_size, _MAX_SAVED_SNAPSHOT_BYTES, "saved_snapshot_bytes"
            )
        note_count = int(
            session.scalar(
                select(func.count(PursuitCallNote.id)).where(
                    PursuitCallNote.pursuit_id == pursuit_id
                )
            )
            or 0
        )
        note_bytes = int(
            session.scalar(
                select(
                    func.coalesce(
                        func.sum(
                            func.octet_length(PursuitCallNote.note)
                            + func.octet_length(PursuitCallNote.outcome)
                            + func.octet_length(PursuitCallNote.next_action)
                        ),
                        0,
                    )
                ).where(PursuitCallNote.pursuit_id == pursuit_id)
            )
            or 0
        )
        if note_count > _MAX_COMMERCIAL_CARD_NOTES:
            raise _commercial_bound_error(
                identity_key, note_count, _MAX_COMMERCIAL_CARD_NOTES, "notes"
            )
        if snapshot_size + note_bytes > _MAX_COMMERCIAL_CARD_BYTES:
            raise _commercial_bound_error(
                identity_key,
                snapshot_size + note_bytes,
                _MAX_COMMERCIAL_CARD_BYTES,
                "history_detail_bytes",
            )
        row = session.get(Pursuit, pursuit_id)
        if row is None:
            raise HTTPException(404, "Saved commercial snapshot not found")
        _check_saved_history_bounds(row, note_count)
        notes = [
            note_view(note)
            for note in session.scalars(
                select(PursuitCallNote)
                .where(PursuitCallNote.pursuit_id == row.id)
                .order_by(PursuitCallNote.created_at.desc(), PursuitCallNote.id)
            )
        ]
        result = _commercial_history_item(row, notes)
        size = len(json.dumps(result, default=str, separators=(",", ":")).encode("utf-8"))
        if size > _MAX_COMMERCIAL_CARD_BYTES:
            raise _commercial_bound_error(
                row.identity_key, size, _MAX_COMMERCIAL_CARD_BYTES, "history_detail_bytes"
            )
        return result


@app.post(
    "/api/commercial/triage/evaluate",
    response_model=CommercialTriagePageOut,
    dependencies=[Depends(require_session)],
)
def evaluate_commercial_triage(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    require_same_origin(request)
    with SessionLocal.begin() as session:
        payload = _commercial_triage_payload(session, limit, offset)
        today = chicago_today().isoformat()
        saved_at = datetime.now(UTC).isoformat()
        payload["evaluated_at"] = saved_at
        from gridlens.intelligence.commercial_evaluation import save_evaluations

        save_evaluations(session, payload["items"])
        receipts = list(
            session.scalars(select(Pursuit).where(Pursuit.identity_key.like("commercial-need:%")))
        )
        payload["daily"]["evaluated"] = sum(
            (row.snapshot or {}).get("commercial_triage", {}).get("evaluated_on") == today
            for row in receipts
        )
        payload["daily"]["surfaced"] = sum(
            (row.snapshot or {}).get("commercial_triage", {}).get("surfaced_on") == today
            for row in receipts
        )
        return payload


@app.post(
    "/api/commercial/triage/{need_id}/research",
    response_model=BriefRequestOut,
    dependencies=[Depends(require_session)],
)
def research_commercial_need(need_id: UUID, body: CommercialResearchBody, request: Request):
    require_same_origin(request)
    question = body.question.strip()
    if len(question) < 12:
        raise HTTPException(422, "Question must contain at least 12 non-space characters")
    with SessionLocal.begin() as session:
        try:
            payload, _ = brief_input(session, need_id, question)
            fingerprint = brief_fingerprint(payload)
            row = session.get(PowerNeedBrief, need_id)
            if row and row.generated_fingerprint == fingerprint and row.result:
                return {"job_id": None, **brief_view(row, fingerprint)}
            return request_brief(session, need_id, question)
        except LookupError as exc:
            raise HTTPException(404, "Power need not found") from exc
        except BriefUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc


@app.get(
    "/api/commercial/triage/{need_id}/research",
    response_model=CommercialResearchStatusOut,
    dependencies=[Depends(require_session)],
)
def commercial_research_status(need_id: UUID, question: str = Query(..., min_length=12)):
    question = question.strip()
    if len(question) < 12:
        raise HTTPException(422, "Question must contain at least 12 non-space characters")
    with SessionLocal() as session:
        try:
            payload, _ = brief_input(session, need_id, question)
        except LookupError as exc:
            raise HTTPException(404, "Power need not found") from exc
        except BriefUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc
        fingerprint = brief_fingerprint(payload)
        row = session.get(PowerNeedBrief, need_id)
        if row and row.generated_fingerprint == fingerprint and row.result:
            return {
                "status": "ready",
                "job_id": None,
                "input_hash": fingerprint,
                "generated_at": row.generated_at,
                "result": row.result,
                "citations": row.citations,
                "error": None,
            }
        version = session.scalar(
            select(PowerNeedBriefVersion)
            .where(
                PowerNeedBriefVersion.need_id == need_id,
                PowerNeedBriefVersion.input_fingerprint == fingerprint,
            )
            .order_by(PowerNeedBriefVersion.generated_at.desc(), PowerNeedBriefVersion.id.desc())
            .limit(1)
        )
        if version:
            return {
                "status": "ready",
                "job_id": None,
                "input_hash": fingerprint,
                "generated_at": version.generated_at,
                "result": version.result,
                "citations": version.citations,
                "error": None,
            }
        if row and row.requested_fingerprint == fingerprint:
            active_job = session.scalar(
                select(Job)
                .where(
                    Job.kind == "power_need_brief",
                    Job.target_id == need_id,
                    Job.status.in_(["queued", "running"]),
                )
                .order_by(Job.created_at.desc(), Job.id.desc())
                .limit(1)
            )
            if active_job or row.status in {"pending", "running"}:
                return {
                    "status": "pending",
                    "job_id": active_job.id if active_job else None,
                    "input_hash": fingerprint,
                    "generated_at": None,
                    "result": None,
                    "citations": [],
                    "error": None,
                }
            if row.status == "failed":
                return {
                    "status": "failed",
                    "job_id": None,
                    "input_hash": fingerprint,
                    "generated_at": None,
                    "result": None,
                    "citations": [],
                    "error": row.error,
                }
        status = "superseded" if row and row.requested_fingerprint else "not_requested"
        return {
            "status": status,
            "job_id": None,
            "input_hash": fingerprint,
            "generated_at": None,
            "result": None,
            "citations": [],
            "error": None,
        }
