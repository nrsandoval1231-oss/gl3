from datetime import UTC, date, datetime, timedelta
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
from gridlens.jobs.queue import enqueue
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (
    ChangeEvent,
    Evidence,
    Interpretation,
    Job,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
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
                }
            )
        return result


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
