from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from datetime import date as DateType
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import Date, func, or_, select

from gridlens.api.verticals import vertical_source_tags
from gridlens.domain.buying_chain import BuyingChainOut, BuyingEnrichBody
from gridlens.domain.commercial_presentation import commercial_size_status
from gridlens.domain.commercial_triage import POLICY_VERSION as COMMERCIAL_TRIAGE_POLICY
from gridlens.domain.commercial_triage import cards as make_commercial_cards
from gridlens.domain.pursuits import (
    AutonomousResearchBody,
    AutonomousResearchOut,
    CommercialResearchBody,
    CommercialResearchStatusOut,
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
from gridlens.intelligence.buying_chain import buying_chain_view, enrich_buying_chain
from gridlens.intelligence.lifecycle_service import lifecycle_event_supported
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
    PowerNeed,
    PowerNeedBrief,
    PowerNeedBriefVersion,
    Project,
    ProjectLifecycle,
    SignalDecision,
    Source,
)
from gridlens.security import (
    check_password,
    login_allowed,
    record_login_failure,
    require_same_origin,
    require_session,
    token_for,
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
    remote = request.client.host if request.client else "unknown"
    if not login_allowed(remote):
        raise HTTPException(429, "Too many login attempts")
    if not check_password(body.password.get_secret_value()):
        record_login_failure(remote)
        raise HTTPException(401, "Invalid credentials")
    expires = int(datetime.now(UTC).timestamp()) + settings.session_hours * 3600
    response.set_cookie(
        "gridlens_session",
        token_for(expires),
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

    if observation.source_id.startswith("research-public-") and assessment.get(
        "acquisition_capture_version"
    ) != CAPTURE_VERSION:
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
        for row in rows:
            definition = definitions.get(row.id, {})
            info = {
                "id": row.id,
                **row.health,
                "family": row.family,
                "geography": row.geography,
                "enabled": row.enabled,
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
                row.enabled
                and info["status"] not in {"Running", "Failed"}
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
        }


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
    dependencies=[Depends(require_session)],
)
def opportunities(tier: str | None = None, search: str | None = None):
    with SessionLocal() as session:
        return opportunity_projection(session, tier=tier, search=search)


def opportunity_projection(
    session,
    *,
    tier: str | None = None,
    search: str | None = None,
    include_below_floor: bool = False,
):
    query = (
        select(PowerNeed, Project)
        .join(Project, PowerNeed.project_id == Project.id)
        .where(PowerNeed.active.is_(True))
        .order_by(PowerNeed.updated_at.desc())
    )
    if search:
        query = query.where(Project.name.ilike(f"%{search[:100]}%"))
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

    research_by_project = {
        project_id: current_research_state(session, project_id) for project_id in set(project_ids)
    }
    result = []
    title_company_by_project = {}
    for need, project in rows:
        research_state = research_by_project.get(project.id, {}).get(str(need.id), {})
        links = links_by_need[need.id]
        if not _need_has_current_support(session, need, project, links=links):
            continue
        qualified = effective_need_qualification(session, need, project)
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
        precedence = {"SHOW": 0, "REVIEW": 1, "HOLD": 2}
        selected_decision = min(
            display_decisions,
            key=lambda item: precedence.get(item.decision, 1),
            default=None,
        )
        display_decision = (
            "SHOW"
            if any(item.decision == "SHOW" for item in display_decisions)
            else "REVIEW"
            if has_unadjudicated_current_signal
            else selected_decision.decision
            if selected_decision
            else None
        )
        display_source = (
            selected_decision.source
            if selected_decision
            and not (has_unadjudicated_current_signal and selected_decision.decision == "HOLD")
            else None
        )
        display_reason = (
            "One or more linked current Signal evidence versions have no decision."
            if has_unadjudicated_current_signal
            and (selected_decision is None or selected_decision.decision == "HOLD")
            else selected_decision.reason
            if selected_decision
            else None
        )
        display_state = (
            "adjudicated"
            if display_decisions and not has_unadjudicated_current_signal
            else "partially_adjudicated"
            if display_decisions
            else "unadjudicated"
        )
        if effective["tier"] == "Signal" and taylor_withdrawn:
            display_decision = "HOLD"
            display_source = "deterministic"
            display_reason = (
                "The current official planning application is withdrawn; earlier "
                "positive evidence remains historical and project viability is UNKNOWN."
            )
            display_state = "adjudicated"
        elif effective["tier"] == "Signal" and taylor_identity_conflict:
            display_decision = "REVIEW"
            display_source = "deterministic"
            display_reason = (
                "The latest Taylor revision conflicts with retained project or site facts; "
                "current application and project status are UNKNOWN."
            )
            display_state = "adjudicated"
        time_to_power_window = None
        if lifecycle and lifecycle.time_to_power_start and lifecycle.time_to_power_end:
            time_to_power_window = (
                f"{lifecycle.time_to_power_start.isoformat()} to "
                f"{lifecycle.time_to_power_end.isoformat()} (estimated)"
            )
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
        if project.id not in title_company_by_project:
            title_company = None
            title_company_role = None
            if project.source_id == "houston-weekly-permits":
                chain = buying_chain_view(session, project.id)
                owner_occupant = next(
                    (
                        fact["value"]
                        for summary in chain["permit_summaries"]
                        for fact in summary["facts"]
                        if fact["label"] == "Permit-listed owner / occupant"
                        and fact["value"].strip()
                    ),
                    None,
                )
                if owner_occupant:
                    title_company = owner_occupant
                    title_company_role = "permit-listed owner / occupant"
            title_company_by_project[project.id] = (title_company, title_company_role)
        title_company, title_company_role = title_company_by_project[project.id]
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
                    else need.rationale
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
                "conflict_state": "CONFLICT"
                if any(field.get("status") == "CONFLICT" for field in research_state.values())
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
                    if effective.get("qualification_version")
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
                "lifecycle_timeline": [
                    {
                        "state": event.state,
                        "event_type": event.event_type,
                        "date": event.occurred_on.isoformat() if event.occurred_on else None,
                        "value_kind": event.value_kind,
                        "evidence_url": lifecycle_evidence.url,
                        "current": event.id in current_lifecycle_ids
                        and (
                            not taylor_withdrawn
                            or event.event_type == "planning_application_withdrawn"
                        )
                        and not taylor_identity_conflict,
                        "published_at": lifecycle_evidence.published_at,
                        "event_date_label": lifecycle_evidence.event_date_label,
                    }
                    for event, lifecycle_evidence in lifecycle_rows
                ],
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
                **brief_preview(
                    session,
                    need,
                    project,
                    links,
                    sources,
                    briefs_by_need.get(need.id),
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
        ids = [str(enqueue(session, source["id"])) for source in definitions if source["enabled"]]
    return {"queued": ids}


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


def _commercial_triage_cards(session, limit: int) -> list[dict]:
    items = opportunity_projection(session, tier="Signal")
    shortlist = make_commercial_cards(items, {}, chicago_today(), limit)
    selected_ids = {need_id for card in shortlist for need_id in card["related_need_ids"]}
    selected = [item for item in items if str(item["id"]) in selected_ids]
    project_ids = {item["project_id"] for item in selected}
    chains = {str(project_id): buying_chain_view(session, project_id) for project_id in project_ids}
    return make_commercial_cards(selected, chains, chicago_today(), limit)


def _commercial_triage_payload(session, limit: int) -> dict:
    cards = _commercial_triage_cards(session, limit)
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
    for card in cards:
        row = workspaces.get(card["id"])
        card["pursuit_id"] = row.id if row else None
        card["notes"] = (
            [
                note_view(note)
                for note in session.scalars(
                    select(PursuitCallNote)
                    .where(PursuitCallNote.pursuit_id == row.id)
                    .order_by(PursuitCallNote.created_at.desc(), PursuitCallNote.id)
                )
            ]
            if row
            else []
        )
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
    return {
        "research_overview": research_overview(cards, questions, receipts, midnight),
        "evaluated_at": datetime.now(UTC),
        "policy_version": COMMERCIAL_TRIAGE_POLICY,
        "total": len(cards),
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


@app.get(
    "/api/commercial/triage",
    response_model=CommercialTriageOut,
    dependencies=[Depends(require_session)],
)
def commercial_triage(limit: int = Query(default=50, ge=1, le=50)):
    with SessionLocal() as session:
        return _commercial_triage_payload(session, limit)


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


@app.get(
    "/api/commercial/triage/history",
    response_model=CommercialTriageHistoryOut,
    dependencies=[Depends(require_session)],
)
def commercial_triage_history():
    """Read evaluated Pursuit snapshots; never refreshes live facts or dispositions."""
    with SessionLocal() as session:
        rows = list(
            session.scalars(select(Pursuit).where(Pursuit.identity_key.like("commercial-need:%")))
        )
        rows.sort(
            key=lambda row: (
                str((row.snapshot or {}).get("commercial_triage", {}).get("saved_at") or ""),
                str(row.id),
            ),
            reverse=True,
        )
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
        return {"items": history}


@app.post(
    "/api/commercial/triage/evaluate",
    response_model=CommercialTriageOut,
    dependencies=[Depends(require_session)],
)
def evaluate_commercial_triage(request: Request, limit: int = Query(default=50, ge=1, le=50)):
    require_same_origin(request)
    with SessionLocal.begin() as session:
        payload = _commercial_triage_payload(session, limit)
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
