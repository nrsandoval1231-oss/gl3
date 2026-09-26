from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, SecretStr
from sqlalchemy import Date, func, select

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
    published_at: date
    retrieved_at: datetime
    extraction_location: str
    content_hash: str
    event_date: date | None
    event_date_label: str
    source_id: str
    document_number: str


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


class HealthOut(BaseModel):
    sources: list[HealthSourceOut]
    backlog: int
    pending_interpretations: int


class ChangeOut(BaseModel):
    kind: str
    title: str
    url: str
    published_at: date


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
                select(Observation, Evidence)
                .join(NeedObservation, NeedObservation.observation_id == Observation.id)
                .join(Evidence, Evidence.observation_id == Observation.id)
                .where(NeedObservation.need_id == need.id)
                .order_by(Evidence.observed_at.desc())
            ).all()
            evidence = [
                {
                    "title": ev.title,
                    "abstract": ev.abstract,
                    "url": ev.url,
                    "published_at": ev.published_at,
                    "retrieved_at": ev.observed_at,
                    "extraction_location": ev.extraction_location,
                    "content_hash": ev.content_hash,
                    "event_date": ev.event_date,
                    "event_date_label": ev.event_date.isoformat() if ev.event_date else "Unknown",
                    "source_id": obs.source_id,
                    "document_number": obs.external_id,
                }
                for obs, ev in links
            ]
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
                        "Confirm the project's construction power requirement, timing, "
                        "duration, and utility service plan."
                    ),
                    "conflict_state": "Not assessed",
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
                "published_at": obs.published_at.isoformat(),
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
