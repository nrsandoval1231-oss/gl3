from datetime import UTC, date, datetime, timedelta
from datetime import date as DateType
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import Date, func, select

from gridlens.domain.collection_watch import (
    candidate_expression as collection_watch_expression,
)
from gridlens.domain.collection_watch import (
    matched_terms as collection_watch_terms,
)
from gridlens.jobs.queue import enqueue, enqueue_owner_research, owner_research_ineligibility
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (
    ChangeEvent,
    Evidence,
    Interpretation,
    Job,
    LifecycleEvent,
    NeedObservation,
    Observation,
    Organization,
    PowerNeed,
    Project,
    ProjectLifecycle,
    ProjectRole,
    ResearchEvidence,
    ResearchJob,
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
    name: str
    location: str | None
    tier: str
    activity: str
    rationale: str
    required_mw: str | None
    start_window: str | None
    duration: str | None
    supply: str
    next_action: str
    conflict_state: str
    assessment_reason: str | None = None
    supported_subject: str | None = None
    supported_action: str | None = None
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
    research_status: str = "Not researched"
    research_next_action: str
    research_unavailable_reason: str | None = None
    research_recorded_identity: str | None = None
    research_recorded_evidence_status: str | None = None
    known_organizations: list[dict] = Field(default_factory=list)


class HealthSourceOut(BaseModel):
    id: str
    status: str
    family: str
    geography: str
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


class ChangeOut(BaseModel):
    kind: str
    title: str
    url: str
    published_at: date | None


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
    matched_terms: list[str]
    topic_label: str | None
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
            info = {
                "id": row.id,
                **row.health,
                "family": row.family,
                "geography": row.geography,
            }
            if row.family == "news":
                info["collection_scope"] = row.geography
                info["coverage_limitation"] = (
                    "Latest publisher snapshot only; rolling feeds can omit items "
                    "between snapshots. "
                    "Hourly checks do not guarantee catch-up after local downtime."
                )
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


def _ingestion_filters(source_id: str | None, vertical: str | None, watch_only: bool):
    predicates = []
    if source_id:
        predicates.append(Observation.source_id == source_id)
    if vertical:
        predicates.append(Source.industries.contains([vertical]))
    if watch_only:
        predicates.append(Observation.source_id == "mjbizdaily-news")
        predicates.append(collection_watch_expression(Evidence.title, Evidence.abstract))
    return predicates


@app.get(
    "/api/ingestion",
    response_model=IngestionPageOut,
    dependencies=[Depends(require_session)],
)
def ingestion(
    source_id: str | None = None,
    vertical: str | None = None,
    watch_only: bool = False,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
):
    predicates = _ingestion_filters(source_id, vertical, watch_only)
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
            terms = (
                collection_watch_terms(evidence.title, evidence.abstract)
                if observation.source_id == "mjbizdaily-news"
                else []
            )
            if watch_only:
                assert terms, "SQL topic filter and displayed topic matcher must agree"
            items.append(
                {
                    "source_id": source.id,
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
                        "Linked to opportunity"
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
                    "matched_terms": terms,
                    "topic_label": "Topic match - review required" if terms else None,
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
        query = (
            select(PowerNeed, Project)
            .join(Project, PowerNeed.project_id == Project.id)
            .where(PowerNeed.active.is_(True))
            .order_by(PowerNeed.updated_at.desc())
        )
        if tier in {"Signal", "Prospect", "Lead"}:
            query = query.where(PowerNeed.tier == tier)
        if search:
            query = query.where(Project.name.ilike(f"%{search[:100]}%"))
        rows = session.execute(query).all()
        result = []
        for need, project in rows:
            lifecycle = session.get(ProjectLifecycle, project.id)
            lifecycle_rows = session.execute(
                select(LifecycleEvent, Evidence)
                .join(Evidence, LifecycleEvent.evidence_id == Evidence.id)
                .where(LifecycleEvent.project_id == project.id)
                .order_by(LifecycleEvent.occurred_on.asc().nullslast(), LifecycleEvent.recorded_at)
            ).all()
            current_lifecycle_ids = set()
            for lifecycle_event, lifecycle_evidence in lifecycle_rows:
                lifecycle_interpretation = session.scalar(
                    select(Interpretation).where(
                        Interpretation.observation_id == lifecycle_event.observation_id
                    )
                )
                if (
                    lifecycle_interpretation is not None
                    and lifecycle_interpretation.status == "accepted"
                    and lifecycle_interpretation.assessment is not None
                    and lifecycle_interpretation.assessment.get("evidence_hash")
                    == lifecycle_evidence.content_hash
                ):
                    current_lifecycle_ids.add(lifecycle_event.id)
            links = session.execute(
                select(Observation, Evidence, Interpretation)
                .join(NeedObservation, NeedObservation.observation_id == Observation.id)
                .join(Evidence, Evidence.observation_id == Observation.id)
                .outerjoin(Interpretation, Interpretation.observation_id == Observation.id)
                .where(NeedObservation.need_id == need.id)
                .order_by(Evidence.observed_at.desc())
            ).all()
            evidence = []
            current_assessments = []
            for obs, ev, interpretation in links:
                current_assessment = _assessment_for_evidence(interpretation, obs, ev)
                if current_assessment:
                    current_assessments.append(current_assessment)
                evidence.append(
                    {
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
                        "document_number": obs.external_id,
                        "assessment_current": current_assessment is not None,
                        "permit_status": current_assessment.get("permit_status")
                        if current_assessment
                        else None,
                    }
                )
            current_assessment = current_assessments[0] if current_assessments else None
            research_row = session.execute(
                select(ResearchJob, Job)
                .join(Job, Job.id == ResearchJob.job_id)
                .where(ResearchJob.need_id == need.id)
                .order_by(Job.created_at.desc())
                .limit(1)
            ).first()
            role_rows = session.execute(
                select(ProjectRole, Organization, ResearchEvidence)
                .join(Organization, Organization.id == ProjectRole.organization_id)
                .join(ResearchEvidence, ResearchEvidence.id == ProjectRole.evidence_id)
                .where(
                    ProjectRole.project_id == project.id,
                    ProjectRole.role.in_(["Owner", "Developer"]),
                )
                .order_by(ResearchEvidence.retrieved_at.desc())
            ).all()
            research_ineligibility = owner_research_ineligibility(session, need.id)
            identity_facts = project.identity_facts or {}
            recorded_identity_keys = (
                ("owner", "Owner"),
                ("owner_name", "Owner"),
                ("developer", "Developer"),
                ("developer_name", "Developer"),
            )
            recorded_identity_values = [
                f"{label}: {value.strip()}"
                for key, label in recorded_identity_keys
                if isinstance((value := identity_facts.get(key)), str) and value.strip()
            ]
            has_recorded_identity = any(
                identity_facts.get(key) for key, _ in recorded_identity_keys
            )
            recorded_identity = "; ".join(dict.fromkeys(recorded_identity_values))
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
                        (need.required_mw, "activity-specific power requirement"),
                        (need.supply != "Unknown", "suitable supply"),
                        (need.start_window, "start window"),
                        (need.duration, "duration"),
                    )
                    if not value
                ]
            )
            next_missing_fact = next(
                iter(missing_facts),
            ) if missing_facts else next(
                (
                    label
                    for value, label in (
                        (need.required_mw, "activity-specific power requirement"),
                        (need.start_window, "start window"),
                        (need.duration, "duration"),
                        (need.supply if need.supply != "Unknown" else None, "suitable supply"),
                    )
                    if not value
                ),
                None,
            )
            result.append(
                {
                    "id": need.id,
                    "name": project.name,
                    "location": project.location,
                    "tier": need.tier,
                    "activity": need.activity_key,
                    "rationale": need.rationale,
                    "required_mw": need.required_mw,
                    "start_window": need.start_window,
                    "duration": need.duration,
                    "supply": need.supply,
                    "next_action": (
                        "Confirm timing, duration, and remaining suitable supply for this activity."
                        if need.tier == "Prospect"
                        else "Confirm activity power needs, timing, duration, and service plan."
                    ),
                    "conflict_state": "Not assessed",
                    "assessment_reason": current_assessment.get("reason", need.rationale)
                    if current_assessment
                    else need.rationale,
                    "supported_subject": current_assessment.get("subject", project.name)
                    if current_assessment
                    else project.name,
                    "supported_action": current_assessment.get("action")
                    if current_assessment
                    else None,
                    "demand_quote": current_assessment.get("demand_quote")
                    if current_assessment
                    else None,
                    "supply_quote": current_assessment.get("supply_quote")
                    if current_assessment
                    else None,
                    "missing_facts": missing_facts,
                    "reported_power_facts": current_assessment.get("reported_power_facts", [])
                    if current_assessment
                    else [],
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
                            "current": event.id in current_lifecycle_ids,
                            "published_at": lifecycle_evidence.published_at,
                            "event_date_label": lifecycle_evidence.event_date_label,
                        }
                        for event, lifecycle_evidence in lifecycle_rows
                    ],
                    "expected_next_milestone": lifecycle.expected_next_milestone
                    if lifecycle
                    else None,
                    "expected_power_event": lifecycle.expected_power_event if lifecycle else None,
                    "time_to_power_window": time_to_power_window,
                    "estimate_basis": lifecycle.estimate_basis if lifecycle else None,
                    "estimate_version": lifecycle.estimate_version if lifecycle else None,
                    "lifecycle_open_questions": lifecycle.open_questions if lifecycle else [],
                    "monitoring_requirements": lifecycle.monitoring_requirements
                    if lifecycle
                    else [],
                    "research_status": (
                        research_row[0].status.title()
                        if research_row
                        else "Known"
                        if role_rows
                        else "Recorded (unverified)"
                        if need.tier == "Signal" and has_recorded_identity
                        else "Unavailable (UNKNOWN)"
                        if (
                            need.tier == "Signal"
                            and research_ineligibility is not None
                            and not role_rows
                        )
                        else "Not queued"
                        if need.tier == "Signal"
                        else "Not researched"
                    ),
                    "research_next_action": (
                        research_row[0].next_action
                        if research_row
                        else (
                            "The project relationship is already supported by cited evidence. "
                            f"Review the next missing Signal fact: {next_missing_fact}. "
                            "No further developer verification is needed."
                            if next_missing_fact
                            else "The project relationship is already supported by cited "
                            "evidence; no further developer verification is needed."
                        )
                        if role_rows
                        else (
                            "Review the recorded owner/developer identity against an official, "
                            "project-specific source and retain a citation before treating it "
                            "as verified."
                        )
                        if need.tier == "Signal" and has_recorded_identity
                        else (
                            "Verify the developer in an official, project-specific planning "
                            "or development record. Keep the relationship UNKNOWN until the "
                            "record names the organization and ties it to this project."
                        )
                        if (
                            need.tier == "Signal"
                            and research_ineligibility is not None
                            and not role_rows
                        )
                        else (
                            "Research queues automatically when this accepted Signal is ingested; "
                            "no owner action is required."
                        )
                        if need.tier == "Signal"
                        else (
                            "Review the sourced project organization and identify "
                            "the next missing fact."
                        )
                        if role_rows
                        else "Research is available for active Signals."
                    ),
                    "research_unavailable_reason": (
                        "No identity-linked official project record currently supports the "
                        "developer relationship."
                        if not research_row
                        and not role_rows
                        and need.tier == "Signal"
                        and not has_recorded_identity
                        and research_ineligibility is not None
                        else None
                    ),
                    "research_recorded_identity": (
                        recorded_identity or "Owner/developer identity fact recorded"
                        if need.tier == "Signal" and has_recorded_identity and not role_rows
                        else None
                    ),
                    "research_recorded_evidence_status": (
                        "No cited ProjectRole evidence is recorded; review before verification."
                        if need.tier == "Signal" and has_recorded_identity and not role_rows
                        else None
                    ),
                    "known_organizations": [
                        {
                            "name": organization.name,
                            "role": role.role,
                            "evidence_url": evidence.source_url,
                            "source_date": evidence.source_date,
                            "retrieved_at": evidence.retrieved_at,
                            "excerpt": evidence.excerpt,
                            "label": evidence.label,
                            "basis": role.basis,
                            "confidence": role.confidence,
                        }
                        for role, organization, evidence in role_rows
                    ],
                }
            )
        return result


@app.post(
    "/api/opportunities/{need_id}/research",
    dependencies=[Depends(require_session)],
)
def queue_opportunity_research(need_id: UUID, request: Request):
    require_same_origin(request)
    try:
        with SessionLocal.begin() as session:
            job_id = enqueue_owner_research(session, need_id)
            research = session.get(ResearchJob, job_id)
            assert research is not None
            return {
                "job_id": str(job_id),
                "status": research.status,
                "question": research.question,
                "source_url": research.source_url,
                "max_sources": research.max_sources,
                "max_requests": research.max_requests,
                "max_seconds": research.max_seconds,
                "max_spend_cents": research.max_spend_cents,
            }
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/changes", response_model=list[ChangeOut], dependencies=[Depends(require_session)])
def changes():
    with SessionLocal() as session:
        today = chicago_today()
        rows = session.execute(
            select(ChangeEvent, Observation)
            .join(Observation)
            .join(NeedObservation, NeedObservation.observation_id == Observation.id)
            .where(func.timezone("America/Chicago", ChangeEvent.created_at).cast(Date) == today)
            .order_by(ChangeEvent.created_at.desc())
        ).all()
        return [
            {
                "kind": event.kind,
                "title": obs.title,
                "url": obs.url,
                "published_at": obs.published_at.isoformat() if obs.published_at else None,
            }
            for event, obs in rows
        ]


@app.post("/api/refresh", response_model=RefreshOut, dependencies=[Depends(require_session)])
def refresh(request: Request):
    require_same_origin(request)
    from gridlens.jobs.worker import sync_registry

    definitions = sync_registry()
    with SessionLocal.begin() as session:
        ids = [str(enqueue(session, source["id"])) for source in definitions if source["enabled"]]
    return {"queued": ids}
