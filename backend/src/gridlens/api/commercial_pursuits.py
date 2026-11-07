"""Authenticated owner-managed pursuit workspace routes (single-owner deployment).

"Today" for follow-up and power-timing attention rules is the America/Chicago calendar day.
Activity ``occurred_at`` must carry a timezone offset; naive datetimes are rejected with 422.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gridlens.domain.commercial_pursuits import (
    REASON_LABELS,
    OpenTask,
    attention_reasons,
    valid_stage,
)
from gridlens.persistence.commercial_pursuit_models import (
    CLOSED_STAGES,
    CommercialPursuit,
    PursuitActivity,
    PursuitTask,
)
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import PowerNeed, Project
from gridlens.security import require_same_origin, require_session

router = APIRouter(
    prefix="/api/commercial-pursuits",
    tags=["commercial-pursuits"],
    dependencies=[Depends(require_session)],
)

Stage = Literal["New", "Contacted", "Engaged", "Proposal", "Won", "Lost"]
UserKind = Literal["call", "email", "meeting", "note"]


def _today() -> date:
    """Return the calendar day used by pursuit follow-up attention rules."""
    return datetime.now(UTC).astimezone(ZoneInfo("America/Chicago")).date()


class TaskOut(BaseModel):
    id: UUID
    description: str
    due_date: date | None
    completed_at: datetime | None


class ActivityOut(BaseModel):
    id: UUID
    kind: str
    summary: str
    detail: str | None
    occurred_at: datetime


class ContactSummary(BaseModel):
    name: str | None = None
    role: str | None = None
    company: str | None = None
    phone: str | None = None
    email: str | None = None


class PursuitOut(BaseModel):
    id: UUID
    need_id: UUID
    project_id: UUID
    stage: Stage
    title: str
    location: str | None
    tier: str
    required_mw: str | None
    start_window: str | None
    contact: ContactSummary | None
    contact_status: Literal["available", "missing", "unknown"]
    attention: list[str]
    attention_labels: list[str]
    next_task: TaskOut | None
    created_at: datetime
    stage_changed_at: datetime
    tasks: list[TaskOut] | None = None
    activity: list[ActivityOut] | None = None


class PursuitCounts(BaseModel):
    total: int
    active: int
    needs_attention: int


class PursuitListOut(BaseModel):
    items: list[PursuitOut]
    counts: PursuitCounts
    total_matching: int
    has_more: bool
    next_offset: int | None


class CreateIn(BaseModel):
    need_id: UUID


class StageIn(BaseModel):
    stage: Stage


class TaskIn(BaseModel):
    """Follow-up details and an optional stable key for replay-safe submission."""

    description: str = Field(min_length=1, max_length=500)
    due_date: date | None = None
    client_id: UUID | None = Field(
        default=None,
        description="Optional retry key; exact replays return the existing task.",
    )

    @field_validator("description")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("description required")
        return value


class TaskPatch(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=500)
    due_date: date | None = None
    clear_due_date: bool = False
    completed: bool | None = None


class ActivityIn(BaseModel):
    kind: UserKind
    summary: str = Field(min_length=1, max_length=300)
    detail: str | None = Field(default=None, max_length=4000)
    occurred_at: datetime | None = None
    client_id: UUID | None = None
    confirmed: bool = Field(
        description="The user confirms this communication or event actually happened."
    )

    @field_validator("summary")
    @classmethod
    def _strip_summary(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("summary required")
        return value

    @field_validator("detail")
    @classmethod
    def _strip_detail(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @field_validator("occurred_at")
    @classmethod
    def _require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("occurred_at must include a timezone offset")
        return value


def _task_out(task: PursuitTask, description: str | None = None) -> TaskOut:
    """Project a persisted task while allowing its displayed text to be redacted."""
    return TaskOut(
        id=task.id,
        description=task.description if description is None else description,
        due_date=task.due_date,
        completed_at=task.completed_at,
    )


_WITHHELD = "[redacted]"


def _private_text(session: Session, project_id: UUID, texts: dict[str, str | None]):
    """Read-time suppression of saved free text; stored rows are never modified.

    Reuses the saved-history projection that protects commercial call notes: the text is
    projected as a copied note under the pursuit's project, so suppressed names, emails and
    phones of retained buying-chain claims are redacted. If the projection cannot run the
    text is withheld (fail closed).
    """
    present = {k: v for k, v in texts.items() if v}
    if not present:
        return dict(texts)
    from gridlens.intelligence.saved_history_privacy import project_saved_history_privacy

    item = {
        "project_id": str(project_id),
        "related_project_ids": [],
        "notes": [{"key": k, "text": v} for k, v in present.items()],
    }
    try:
        with session.begin_nested():
            projected = project_saved_history_privacy(session, item)["notes"]
        out = {note["key"]: note["text"] for note in projected}
    except Exception:
        out = {k: _WITHHELD for k in present}
    return {k: out.get(k, _WITHHELD) if v else v for k, v in texts.items()}


def _contact(session: Session, project_id: UUID) -> tuple[ContactSummary | None, str]:
    """Primary contact from the same projection the opportunity card uses.

    The lookup runs in a savepoint so a database error rolls back only the lookup (a failed
    statement otherwise aborts the whole Postgres transaction) and is reported as "unknown".
    """
    try:
        from gridlens.domain.opportunity_intelligence import contact_projection
        from gridlens.intelligence.buying_chain import buying_chain_view

        with session.begin_nested():
            people = contact_projection(buying_chain_view(session, project_id))
    except Exception:  # evidence unreadable: report unknown, never "missing"
        return None, "unknown"
    best = None
    for person in people:
        phone = next(
            (m["value"] for m in person.methods if m["kind"] in {"phone", "telephone"}), None
        )
        email = next((m["value"] for m in person.methods if m["kind"] == "email"), None)
        if phone or email:
            best = ContactSummary(
                name=person.name,
                role=person.title or person.role,
                company=person.company,
                phone=phone,
                email=email,
            )
            break
    return (best, "available") if best else (None, "missing")


class _Preload:
    """Needs, projects and tasks for a set of pursuits, loaded with a few IN queries."""

    def __init__(self, session: Session, rows: list[CommercialPursuit]):
        """Load related needs, projects and tasks in bounded bulk queries for this page."""
        need_ids = {r.need_id for r in rows}
        project_ids = {r.project_id for r in rows}
        pursuit_ids = [r.id for r in rows]
        self.needs: dict[UUID, PowerNeed] = (
            {n.id: n for n in session.scalars(select(PowerNeed).where(PowerNeed.id.in_(need_ids)))}
            if need_ids
            else {}
        )
        self.projects: dict[UUID, Project] = (
            {p.id: p for p in session.scalars(select(Project).where(Project.id.in_(project_ids)))}
            if project_ids
            else {}
        )
        self.tasks: dict[UUID, list[PursuitTask]] = {}
        if pursuit_ids:
            for task in session.scalars(
                select(PursuitTask)
                .where(PursuitTask.pursuit_id.in_(pursuit_ids))
                .order_by(
                    PursuitTask.completed_at.is_(None).desc(),
                    PursuitTask.due_date.asc().nulls_last(),
                )
            ):
                self.tasks.setdefault(task.pursuit_id, []).append(task)
        self.contacts: dict[UUID, tuple[ContactSummary | None, str]] = {}

    def contact(self, session: Session, project_id: UUID) -> tuple[ContactSummary | None, str]:
        """Reuse the contact projection cached for this project's response page."""
        if project_id not in self.contacts:
            self.contacts[project_id] = _contact(session, project_id)
        return self.contacts[project_id]


def _view(
    session: Session,
    row: CommercialPursuit,
    today: date,
    detail: bool,
    pre: _Preload | None = None,
    private: bool = True,
) -> PursuitOut:
    """Project a pursuit and its bounded history, suppressing contact text on read."""
    pre = pre or _Preload(session, [row])
    need = pre.needs.get(row.need_id)
    project = pre.projects.get(row.project_id)
    tasks = pre.tasks.get(row.id, [])
    open_tasks = [t for t in tasks if t.completed_at is None]
    contact, status = pre.contact(session, row.project_id)
    reasons = attention_reasons(
        stage=row.stage,
        open_tasks=[OpenTask(str(t.id), t.due_date) for t in open_tasks],
        has_usable_contact=None if status == "unknown" else status == "available",
        start_window=need.start_window if need else None,
        today=today,
    )
    nxt = min(open_tasks, key=lambda t: (t.due_date is None, t.due_date or date.max), default=None)
    out = PursuitOut(
        id=row.id,
        need_id=row.need_id,
        project_id=row.project_id,
        stage=row.stage,  # type: ignore[arg-type]
        title=project.name if project else "Unavailable project",
        location=project.location if project else None,
        tier=need.tier if need else "Signal",
        required_mw=need.required_mw if need else None,
        start_window=need.start_window if need else None,
        contact=contact,
        contact_status=status,  # type: ignore[arg-type]
        attention=reasons,
        attention_labels=[REASON_LABELS[r] for r in reasons],
        next_task=None,
        created_at=row.created_at,
        stage_changed_at=row.stage_changed_at,
    )
    activities = (
        list(
            session.scalars(
                select(PursuitActivity)
                .where(PursuitActivity.pursuit_id == row.id)
                .order_by(PursuitActivity.occurred_at.desc(), PursuitActivity.created_at.desc())
                .limit(200)
            )
        )
        if detail
        else []
    )
    # Saved free text may quote a contact that was later suppressed: project it at read time.
    texts: dict[str, str | None] = {}
    shown = tasks if detail else ([nxt] if nxt else [])
    for t in shown:
        texts[f"t{t.id}"] = t.description
    for a in activities:
        texts[f"s{a.id}"] = a.summary
        texts[f"d{a.id}"] = a.detail
    safe = _private_text(session, row.project_id, texts) if private else texts
    if nxt:
        out.next_task = _task_out(nxt, safe[f"t{nxt.id}"])
    if detail:
        out.tasks = [_task_out(t, safe[f"t{t.id}"]) for t in tasks]
        out.activity = [
            ActivityOut(
                id=a.id,
                kind=a.kind,
                summary=safe[f"s{a.id}"] or "",
                detail=safe[f"d{a.id}"],
                occurred_at=a.occurred_at,
            )
            for a in activities
        ]
    return out


def _log(
    session: Session,
    pursuit_id: UUID,
    kind: str,
    summary: str,
    when: datetime | None = None,
    **extra,
):
    """Stage one immutable activity row in the caller's transaction."""
    session.add(
        PursuitActivity(
            pursuit_id=pursuit_id,
            kind=kind,
            summary=summary,
            occurred_at=when or datetime.now(UTC),
            **extra,
        )
    )


def _get(session: Session, pursuit_id: UUID, lock: bool = False) -> CommercialPursuit:
    """Load a pursuit; ``lock`` takes a row lock so concurrent mutations serialise."""
    query = select(CommercialPursuit).where(CommercialPursuit.id == pursuit_id)
    if lock:
        query = query.with_for_update()
        session.expire_all()
    row = session.scalar(query)
    if row is None:
        raise HTTPException(404, "Pursuit not found")
    return row


@router.get("", response_model=PursuitListOut)
def list_pursuits(
    needs_attention: bool = False,
    active_only: bool = False,
    need_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List filtered pursuit projections and counts from persisted owner state."""
    today = _today()
    with SessionLocal() as session:
        # Counts and filters cover every pursuit (single-owner volumes are small); only the
        # returned page is limited, after filtering. Order is (created_at desc, id) so pages
        # neither overlap nor skip.
        rows = list(
            session.scalars(
                select(CommercialPursuit).order_by(
                    CommercialPursuit.created_at.desc(), CommercialPursuit.id
                )
            )
        )
        pre = _Preload(session, rows)
        # Free text is projected only for the returned page (below), not for every row.
        views = [_view(session, row, today, detail=False, pre=pre, private=False) for row in rows]
    counts = PursuitCounts(
        total=len(views),
        active=sum(v.stage not in CLOSED_STAGES for v in views),
        needs_attention=sum(bool(v.attention) for v in views),
    )
    matching = [
        v
        for v in views
        if (not needs_attention or v.attention)
        and (not active_only or v.stage not in CLOSED_STAGES)
        and (need_id is None or v.need_id == need_id)
    ]
    items = matching[offset : offset + limit]
    with SessionLocal() as session:
        for item in items:
            if item.next_task is not None:
                item.next_task.description = (
                    _private_text(session, item.project_id, {"t": item.next_task.description})["t"]
                    or ""
                )
    end = offset + len(items)
    has_more = end < len(matching)
    return PursuitListOut(
        items=items,
        counts=counts,
        total_matching=len(matching),
        has_more=has_more,
        next_offset=end if has_more else None,
    )


@router.post(
    "", response_model=PursuitOut, status_code=201, dependencies=[Depends(require_same_origin)]
)
def create_pursuit(body: CreateIn, response: Response):
    """Create or return the single pursuit attached to an active opportunity."""
    today = _today()
    with SessionLocal() as session:
        need = session.get(PowerNeed, body.need_id)
        if need is None or not need.active:
            raise HTTPException(404, "Opportunity not found")
        existing = session.scalar(
            select(CommercialPursuit).where(CommercialPursuit.need_id == body.need_id)
        )
        if existing is not None:
            response.status_code = 200
            return _view(session, existing, today, detail=True)
        row = CommercialPursuit(need_id=need.id, project_id=need.project_id, stage="New")
        session.add(row)
        try:
            session.flush()
        except IntegrityError:  # concurrent create: return the winner
            session.rollback()
            winner = session.scalar(
                select(CommercialPursuit).where(CommercialPursuit.need_id == body.need_id)
            )
            if winner is None:
                raise
            response.status_code = 200
            return _view(session, winner, today, detail=True)
        _log(session, row.id, "created", "Added to Pursuits")
        session.commit()
        session.refresh(row)
        return _view(session, row, today, detail=True)


@router.get("/{pursuit_id}", response_model=PursuitOut)
def pursuit_detail(pursuit_id: UUID):
    """Return a pursuit and its retained task and activity history."""
    with SessionLocal() as session:
        return _view(session, _get(session, pursuit_id), _today(), detail=True)


@router.patch(
    "/{pursuit_id}",
    response_model=PursuitOut,
    dependencies=[Depends(require_same_origin)],
)
def set_stage(pursuit_id: UUID, body: StageIn):
    """Persist an owner-selected stage and append its change to the activity history."""
    if not valid_stage(body.stage):
        raise HTTPException(422, "Unknown stage")
    with SessionLocal() as session:
        row = _get(session, pursuit_id, lock=True)
        if row.stage != body.stage:
            previous = row.stage
            row.stage = body.stage
            row.stage_changed_at = datetime.now(UTC)
            row.closed_at = row.stage_changed_at if body.stage in CLOSED_STAGES else None
            _log(session, row.id, "stage_change", f"Stage changed: {previous} → {body.stage}")
            session.commit()
            session.refresh(row)
        return _view(session, row, _today(), detail=True)


@router.post(
    "/{pursuit_id}/tasks",
    response_model=PursuitOut,
    status_code=201,
    dependencies=[Depends(require_same_origin)],
)
def add_task(pursuit_id: UUID, body: TaskIn, response: Response):
    """Add a task, or replay the same task when the caller supplies a stable client id."""
    with SessionLocal() as session:
        row = _get(session, pursuit_id, lock=True)

        def matching_replay() -> PursuitTask | None:
            """Return an exact retry match or reject reuse of its idempotency key."""
            if body.client_id is None:
                return None
            existing = session.get(PursuitTask, body.client_id)
            if existing is None:
                return None
            if (
                existing.pursuit_id != row.id
                or existing.description != body.description
                or existing.due_date != body.due_date
            ):
                raise HTTPException(409, "Task idempotency key was already used")
            return existing

        if matching_replay() is not None:
            response.status_code = 200
            return _view(session, row, _today(), detail=True)

        session.add(
            PursuitTask(
                id=body.client_id or uuid4(),
                pursuit_id=row.id,
                description=body.description,
                due_date=body.due_date,
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            if matching_replay() is None:
                raise
            row = _get(session, pursuit_id)
            response.status_code = 200
        return _view(session, row, _today(), detail=True)


@router.patch(
    "/{pursuit_id}/tasks/{task_id}",
    response_model=PursuitOut,
    dependencies=[Depends(require_same_origin)],
)
def update_task(pursuit_id: UUID, task_id: UUID, body: TaskPatch):
    """Update task details and log completion in the same database transaction."""
    with SessionLocal() as session:
        row = _get(session, pursuit_id, lock=True)
        task = session.get(PursuitTask, task_id)
        if task is None or task.pursuit_id != row.id:
            raise HTTPException(404, "Task not found")
        if body.description is not None:
            task.description = body.description.strip() or task.description
        if body.clear_due_date:
            task.due_date = None
        elif body.due_date is not None:
            task.due_date = body.due_date
        if body.completed is True and task.completed_at is None:
            task.completed_at = datetime.now(UTC)
            _log(
                session, row.id, "task_completed", f"Follow-up completed: {task.description[:240]}"
            )
        elif body.completed is False:
            task.completed_at = None
        session.commit()
        return _view(session, row, _today(), detail=True)


@router.post(
    "/{pursuit_id}/activity",
    response_model=PursuitOut,
    status_code=201,
    dependencies=[Depends(require_same_origin)],
)
def log_activity(pursuit_id: UUID, body: ActivityIn, response: Response):
    """Append confirmed activity once per supplied client id, including retry races."""
    if not body.confirmed:
        raise HTTPException(422, "Activity must be confirmed by the user before it is recorded")
    with SessionLocal() as session:
        row = _get(session, pursuit_id, lock=True)

        def existing() -> bool:
            return body.client_id is not None and bool(
                session.scalar(
                    select(PursuitActivity.id).where(
                        PursuitActivity.pursuit_id == row.id,
                        PursuitActivity.client_id == body.client_id,
                    )
                )
            )

        if existing():
            response.status_code = 200
            return _view(session, row, _today(), detail=True)
        _log(
            session,
            row.id,
            body.kind,
            body.summary.strip(),
            body.occurred_at or datetime.now(UTC),
            detail=(body.detail or "").strip() or None,
            client_id=body.client_id or uuid4(),
        )
        try:
            session.commit()
        except IntegrityError:  # retried request lost the race: return the recorded entry
            session.rollback()
            row = _get(session, pursuit_id)
            if not existing():
                raise
            response.status_code = 200
        return _view(session, row, _today(), detail=True)
