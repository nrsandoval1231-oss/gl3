from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gridlens.persistence.database import Base


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    publisher: Mapped[str] = mapped_column(String(200))
    endpoint: Mapped[str] = mapped_column(Text)
    family: Mapped[str] = mapped_column(String(50))
    geography: Mapped[str] = mapped_column(String(100))
    industries: Mapped[list[str]] = mapped_column(JSONB)
    retrieval_method: Mapped[str] = mapped_column(String(50))
    cadence_hours: Mapped[int] = mapped_column(Integer, default=24)
    enabled: Mapped[bool] = mapped_column(default=True)
    registry_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    health: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class SourceScheduleEpoch(Base):
    """Append-only, effective-dated source scheduling configuration."""

    __tablename__ = "source_schedule_epochs"
    __table_args__ = (
        Index(
            "uq_source_schedule_epoch_current",
            "source_id",
            unique=True,
            postgresql_where=text("effective_until IS NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    registry_enabled: Mapped[bool] = mapped_column(Boolean)
    operator_enabled: Mapped[bool] = mapped_column(Boolean)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cadence_hours: Mapped[int] = mapped_column(Integer)
    schedule_mode: Mapped[str] = mapped_column(String(20))
    timezone: Mapped[str] = mapped_column(String(80))
    anchor: Mapped[dict[str, Any]] = mapped_column(JSONB)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB)
    history_known: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class SourceDueCheck(Base):
    """One immutable scheduled occurrence and its at-most-once job assignment."""

    __tablename__ = "source_due_checks"
    __table_args__ = (UniqueConstraint("job_id", name="uq_source_due_checks_job"),)
    due_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    epoch_id: Mapped[UUID] = mapped_column(ForeignKey("source_schedule_epochs.id"), index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    local_day: Mapped[date] = mapped_column(Date)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB)
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)


class SourceCheckReceipt(Base):
    """Append-only terminal result for one fenced attempt at a due occurrence."""

    __tablename__ = "source_check_receipts"
    __table_args__ = (UniqueConstraint("job_id", "fence", name="uq_source_check_receipt_attempt"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    due_key: Mapped[str] = mapped_column(ForeignKey("source_due_checks.due_key"), index=True)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"))
    fence: Mapped[int] = mapped_column(Integer)
    disposition: Mapped[str] = mapped_column(String(20))
    check_counts: Mapped[dict[str, Any]] = mapped_column(JSONB)
    digest: Mapped[str] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PlannerState(Base):
    """Bounded retry and last-outcome state for an independent planner cycle."""

    __tablename__ = "planner_states"
    planner_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_class: Mapped[str | None] = mapped_column(String(80))


class WorkerHeartbeat(Base):
    """Process liveness, independent from API or collection freshness."""

    __tablename__ = "worker_heartbeats"
    worker_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    credential_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class AuthLoginBucket(Base):
    __tablename__ = "auth_login_buckets"
    id: Mapped[str] = mapped_column(String(72), primary_key=True)
    scope: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    kind: Mapped[str] = mapped_column(String(30), default="ingestion", server_default="ingestion")
    target_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    checkpoint: Mapped[str | None] = mapped_column(Text)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    fence: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    error: Mapped[str | None] = mapped_column(Text)


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_observation_source_external"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    url: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="observation")


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        UniqueConstraint("observation_id", "content_hash", name="uq_evidence_version"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    observation_id: Mapped[UUID] = mapped_column(ForeignKey("observations.id"))
    content_hash: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    published_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    extraction_location: Mapped[str] = mapped_column(String(100), default="title and abstract")
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    event_date_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'"), nullable=False
    )
    observation: Mapped[Observation] = relationship(back_populates="evidence")


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    identity_key: Mapped[str] = mapped_column(String(220), unique=True)
    name: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(String(200))
    asset_type: Mapped[str] = mapped_column(String(60), default="unknown", server_default="unknown")
    identity_facts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ProjectLifecycle(Base):
    """Current lifecycle projection; the immutable events below remain authoritative."""

    __tablename__ = "project_lifecycles"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    current_state: Mapped[str] = mapped_column(String(80))
    expected_next_milestone: Mapped[str | None] = mapped_column(Text)
    expected_power_event: Mapped[str | None] = mapped_column(Text)
    time_to_power_start: Mapped[date | None] = mapped_column(Date)
    time_to_power_end: Mapped[date | None] = mapped_column(Date)
    estimate_basis: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    estimate_version: Mapped[str | None] = mapped_column(String(50))
    open_questions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    monitoring_requirements: Mapped[list[str]] = mapped_column(JSONB, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LifecycleEvent(Base):
    __tablename__ = "lifecycle_events"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "observation_id",
            "evidence_id",
            "event_type",
            "state",
            name="uq_lifecycle_event_replay",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    observation_id: Mapped[UUID] = mapped_column(ForeignKey("observations.id"))
    evidence_id: Mapped[UUID] = mapped_column(ForeignKey("evidence.id"))
    event_type: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(80))
    value_kind: Mapped[str] = mapped_column(String(20), default="reported")
    occurred_on: Mapped[date | None] = mapped_column(Date)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProjectMatchDecision(Base):
    __tablename__ = "project_match_decisions"
    __table_args__ = (
        UniqueConstraint(
            "observation_id",
            "candidate_project_id",
            "evidence_id",
            name="uq_project_match_candidate_version",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observation_id: Mapped[UUID] = mapped_column(ForeignKey("observations.id"))
    candidate_project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True
    )
    decision: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    matched_facts: Mapped[list[str]] = mapped_column(JSONB, default=list)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    evidence_id: Mapped[UUID | None] = mapped_column(ForeignKey("evidence.id"), nullable=True)
    identity_facts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class PowerNeed(Base):
    __tablename__ = "power_needs"
    __table_args__ = (
        UniqueConstraint("project_id", "activity_key", name="uq_need_project_activity"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    activity_key: Mapped[str] = mapped_column(String(100))
    tier: Mapped[str] = mapped_column(String(20), default="Signal")
    rationale: Mapped[str] = mapped_column(Text)
    admission_basis: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    required_mw: Mapped[str | None] = mapped_column(String(100))
    start_window: Mapped[str | None] = mapped_column(String(100))
    duration: Mapped[str | None] = mapped_column(String(100))
    supply: Mapped[str] = mapped_column(String(30), default="Unknown")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CallFactVersion(Base):
    """Immutable, attributed operator fact version scoped to one exact need."""

    __tablename__ = "call_fact_versions"
    __table_args__ = (
        UniqueConstraint("need_id", "client_id", name="uq_call_fact_version_request"),
        Index("ix_call_fact_version_scope", "need_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    need_id: Mapped[UUID] = mapped_column(ForeignKey("power_needs.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    pursuit_id: Mapped[UUID | None] = mapped_column(ForeignKey("pursuits.id"), nullable=True)
    predecessor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    client_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    activity_key: Mapped[str] = mapped_column(String(100), nullable=False)
    facility_scope: Mapped[str] = mapped_column(Text, nullable=False)
    fact_type: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reporter_name: Mapped[str] = mapped_column(String(160), nullable=False)
    reporter_organization: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reporter_role: Mapped[str | None] = mapped_column(String(160), nullable=True)
    confirmation_channel: Mapped[str] = mapped_column(String(40), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CallFactDecision(Base):
    """Append-only decision receipt for a fact version; current state is derived."""

    __tablename__ = "call_fact_decisions"
    __table_args__ = (
        UniqueConstraint("need_id", "version", name="uq_call_fact_decision_version"),
        UniqueConstraint("need_id", "client_id", name="uq_call_fact_decision_request"),
        Index("ix_call_fact_decision_need", "need_id", "version"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    need_id: Mapped[UUID] = mapped_column(ForeignKey("power_needs.id"), nullable=False)
    fact_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("call_fact_versions.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    client_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NeedWorkflowStatusEvent(Base):
    """Append-only operator workflow assertion, independent from evidence tier."""

    __tablename__ = "need_workflow_status_events"
    __table_args__ = (
        UniqueConstraint("need_id", "version", name="uq_need_workflow_status_version"),
        UniqueConstraint("need_id", "client_id", name="uq_need_workflow_status_request"),
        Index("ix_need_workflow_status_need", "need_id", "version"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    need_id: Mapped[UUID] = mapped_column(ForeignKey("power_needs.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    pursuit_id: Mapped[UUID | None] = mapped_column(ForeignKey("pursuits.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    client_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PowerNeedBrief(Base):
    """Latest advisory brief and explicit request state for one physical need."""

    __tablename__ = "power_need_briefs"
    need_id: Mapped[UUID] = mapped_column(ForeignKey("power_needs.id"), primary_key=True)
    requested_fingerprint: Mapped[str | None] = mapped_column(String(64))
    generated_fingerprint: Mapped[str | None] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(40))
    schema_version: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="unavailable")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(80))


class PowerNeedBriefVersion(Base):
    __tablename__ = "power_need_brief_versions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    need_id: Mapped[UUID] = mapped_column(ForeignKey("power_needs.id"))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(40))
    schema_version: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(100))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)


class BriefDailyBudget(Base):
    __tablename__ = "brief_daily_budgets"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    reserved_requests: Mapped[int] = mapped_column(Integer, default=0)


class NeedObservation(Base):
    __tablename__ = "need_observations"
    __table_args__ = (UniqueConstraint("need_id", "observation_id", name="uq_need_observation"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    need_id: Mapped[UUID] = mapped_column(ForeignKey("power_needs.id"))
    observation_id: Mapped[UUID] = mapped_column(ForeignKey("observations.id"))


class ChangeEvent(Base):
    __tablename__ = "change_events"
    __table_args__ = (
        Index(
            "uq_change_replay_key",
            "replay_key",
            unique=True,
            postgresql_where=text("replay_key IS NOT NULL"),
        ),
        Index("ix_change_project_material", "project_id", "material", "created_at"),
        Index(
            "uq_project_change_revision",
            "project_id",
            "field_name",
            "replay_key",
            unique=True,
            postgresql_where=text("material IS TRUE AND replay_key IS NOT NULL"),
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observation_id: Mapped[UUID] = mapped_column(ForeignKey("observations.id"))
    content_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    evidence_id: Mapped[UUID | None] = mapped_column(ForeignKey("evidence.id"), nullable=True)
    buying_chain_evidence_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("buying_chain_evidence.id"), nullable=True
    )
    field_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prior_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    new_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    material: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    source_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    replay_key: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ProjectMaterialState(Base):
    __tablename__ = "project_material_states"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=0)


class EvidenceJudgeRun(Base):
    __tablename__ = "evidence_judge_runs"
    __table_args__ = (
        UniqueConstraint("input_key", name="uq_evidence_judge_input"),
        Index("ix_evidence_judge_status", "status", "started_at"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    evidence_id: Mapped[UUID] = mapped_column(ForeignKey("evidence.id"))
    candidate_project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id"))
    input_key: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(40), default="typesafe")
    status: Mapped[str] = mapped_column(String(20))
    deterministic: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_class: Mapped[str | None] = mapped_column(String(80))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)


class EvidenceJudgeScanCheckpoint(Base):
    """Singleton durable traversal position for bounded shadow scans."""

    __tablename__ = "evidence_judge_scan_checkpoints"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    evidence_id: Mapped[UUID | None] = mapped_column(ForeignKey("evidence.id"))
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id"))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Interpretation(Base):
    __tablename__ = "interpretations"
    __table_args__ = (UniqueConstraint("observation_id", name="uq_interpretation_observation"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observation_id: Mapped[UUID] = mapped_column(ForeignKey("observations.id"))
    content_hash: Mapped[str] = mapped_column(String(64))
    evaluator_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    assessment: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SignalDecision(Base):
    """Immutable, evidence and policy bound display-worthiness decision."""

    __tablename__ = "signal_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observation_id: Mapped[UUID] = mapped_column(ForeignKey("observations.id"))
    content_hash: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(40))
    decision: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(40))
    model_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    reason: Mapped[str] = mapped_column(Text)
    adjudicated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BuyingChainEvidence(Base):
    """Immutable excerpt/version with mutable last-seen retrieval metadata."""

    __tablename__ = "buying_chain_evidence"
    __table_args__ = (
        UniqueConstraint("project_id", "url", "content_hash", name="uq_buying_evidence_version"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    retained_evidence_id: Mapped[UUID | None] = mapped_column(ForeignKey("evidence.id"))
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    excerpt: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    extraction_location: Mapped[str] = mapped_column(String(100))
    published_at: Mapped[date | None] = mapped_column(Date)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    project_match_reason: Mapped[str] = mapped_column(Text)


class BuyingChainClaim(Base):
    """Append-only relationship snapshot; names are scoped to this physical project.

    No global person/company merge, no inferred emails, no opportunity tier writes.
    Each relationship has its own retained source quote in citations.
    """

    __tablename__ = "buying_chain_claims"
    __table_args__ = (UniqueConstraint("project_id", "fingerprint", name="uq_buying_claim_replay"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    entity_key: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(40))
    organization: Mapped[str] = mapped_column(Text)
    person_name: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40))
    organization_relationship: Mapped[str] = mapped_column(String(20))
    person_organization_relationship: Mapped[str] = mapped_column(String(20))
    person_project_relationship: Mapped[str] = mapped_column(String(20))
    evidence_strength: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    public_contacts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BuyingChainRun(Base):
    __tablename__ = "buying_chain_runs"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    input_hash: Mapped[str] = mapped_column(String(64))
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    claim_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    policy_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    documents_checked: Mapped[int] = mapped_column(Integer)
    candidates_added: Mapped[int] = mapped_column(Integer)
    unresolved: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Pursuit(Base):
    """One commercial research workspace per conservatively linked physical work scope."""

    __tablename__ = "pursuits"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    identity_key: Mapped[str] = mapped_column(String(220), unique=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    project_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    last_researched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    research_status: Mapped[str] = mapped_column(String(30), default="not_researched")
    research_errors: Mapped[list[str]] = mapped_column(JSONB, default=list)


class PursuitDocument(Base):
    __tablename__ = "pursuit_documents"
    __table_args__ = (
        UniqueConstraint("pursuit_id", "url", "content_hash", name="uq_pursuit_document_version"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    pursuit_id: Mapped[UUID] = mapped_column(ForeignKey("pursuits.id"))
    url: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[dict[str, Any]] = mapped_column(JSONB)


class PursuitResearchQuestion(Base):
    """One bounded attempt with immutable input context and an inspectable receipt."""

    __tablename__ = "pursuit_research_questions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    pursuit_id: Mapped[UUID] = mapped_column(ForeignKey("pursuits.id"), index=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    need_id: Mapped[UUID] = mapped_column(ForeignKey("power_needs.id"), index=True)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("pursuit_research_questions.id"))
    category: Mapped[str] = mapped_column(String(30))
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    query_fingerprint: Mapped[str] = mapped_column(String(64))
    evidence_fingerprint: Mapped[str] = mapped_column(String(64))
    context: Mapped[dict[str, Any]] = mapped_column(JSONB)
    budget: Mapped[dict[str, Any]] = mapped_column(JSONB)
    receipt: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PursuitResearchRun(Base):
    __tablename__ = "pursuit_research_runs"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"))
    pursuit_id: Mapped[UUID] = mapped_column(ForeignKey("pursuits.id"))
    input_hash: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="running")
    fetch_count: Mapped[int] = mapped_column(Integer, default=0)
    model_count: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[str]] = mapped_column(JSONB, default=list)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PursuitCallNote(Base):
    __tablename__ = "pursuit_call_notes"
    __table_args__ = (UniqueConstraint("pursuit_id", "client_id", name="uq_pursuit_note_request"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    pursuit_id: Mapped[UUID] = mapped_column(ForeignKey("pursuits.id"))
    client_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    owner: Mapped[str] = mapped_column(String(100), default="Nick Sandoval")
    note: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(40))
    next_action: Mapped[str] = mapped_column(Text)
    follow_up: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InterconnectionFactVersion(Base):
    """Append-only reviewed request facts bound to a retained evidence version."""

    __tablename__ = "interconnection_fact_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "evidence_id", name="uq_interconnection_fact_evidence"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    evidence_id: Mapped[UUID] = mapped_column(ForeignKey("evidence.id"), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EditorialDecision(Base):
    """Append-only human clearance, scoped to one immutable evidence version."""
    __tablename__ = 'editorial_decisions'
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    observation_id: Mapped[UUID] = mapped_column(ForeignKey('observations.id'), index=True)
    evidence_id: Mapped[UUID] = mapped_column(ForeignKey('evidence.id'))
    evidence_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    reviewer: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EditorialAssessment(Base):
    """Advisory model output; cannot establish clearance."""
    __tablename__ = 'editorial_assessments'
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    evidence_id: Mapped[UUID] = mapped_column(ForeignKey('evidence.id'), index=True)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BrowseState(Base):
    """Transactional input revision and atomically published generation pointer."""

    __tablename__ = "browse_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    input_revision: Mapped[int] = mapped_column(BigInteger, server_default="0")
    generation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    full_revision: Mapped[int] = mapped_column(BigInteger, server_default="0")
    prepared_generation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


class BrowseDirtyProject(Base):
    """Transactional tombstones; deliberately no FK to removable canonical projects."""

    __tablename__ = "browse_dirty_projects"
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger)


class BrowseGeneration(Base):
    __tablename__ = "browse_generations"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    input_revision: Mapped[int] = mapped_column(BigInteger)
    policy_version: Mapped[str] = mapped_column(String(100))
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    row_count: Mapped[int] = mapped_column(Integer)
    digest: Mapped[str] = mapped_column(String(64))
    counts: Mapped[dict] = mapped_column(JSONB)


class BrowseRow(Base):
    """Saved canonical inputs and compact output; never a qualification authority."""

    __tablename__ = "browse_rows"
    __table_args__ = (
        Index(
            "ix_browse_rank",
            "generation_id",
            "tier",
            text("rank_score DESC"),
            text("updated_at DESC"),
            "need_id",
        ),
        Index(
            "ix_browse_global_rank",
            "generation_id",
            text("rank_score DESC"),
            text("updated_at DESC"),
            "need_id",
        ),
        Index("ix_browse_updated", "generation_id", "tier", text("updated_at DESC"), "need_id"),
        Index("ix_browse_project", "generation_id", "project_id", "tier"),
        Index("ix_browse_dimensions", "generation_id", "location", "industry", "activity"),
        Index(
            "ix_browse_commercial",
            "generation_id",
            "tier",
            "commercial_group",
            "commercial_segment",
            "commercial_geography",
            "commercial_date",
            "project_id",
            "need_id",
        ),
    )
    generation_id: Mapped[UUID] = mapped_column(
        ForeignKey("browse_generations.id", ondelete="CASCADE"), primary_key=True
    )
    need_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    tier: Mapped[str] = mapped_column(String(20))
    location: Mapped[str] = mapped_column(Text)
    industry: Mapped[str] = mapped_column(Text)
    activity: Mapped[str] = mapped_column(Text)
    has_timing: Mapped[bool] = mapped_column(Boolean)
    mw_low: Mapped[Any | None] = mapped_column(Numeric)
    mw_high: Mapped[Any | None] = mapped_column(Numeric)
    priority_segment: Mapped[int] = mapped_column(Integer)
    workflow_status: Mapped[str] = mapped_column(String(30))
    signal_decision: Mapped[str] = mapped_column(String(10))
    project_group: Mapped[str] = mapped_column(String(43))
    single_group: Mapped[str] = mapped_column(String(43))
    rank_score: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    search_text: Mapped[str] = mapped_column(Text)
    display_title: Mapped[str] = mapped_column(Text)
    # NULL only in pre-0023 derived generations; policy fencing requires rebuilding.
    commercial_group: Mapped[str | None] = mapped_column(Text)
    commercial_segment: Mapped[int | None] = mapped_column(Integer)
    commercial_geography: Mapped[int | None] = mapped_column(Integer)
    commercial_date: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[dict] = mapped_column(JSONB)
    compact: Mapped[dict] = mapped_column(JSONB)
