from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
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
    health: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'ingestion' AND source_id IS NOT NULL) "
            "OR (kind = 'research' AND source_id IS NULL)",
            name="ck_jobs_kind_source",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(20), default="ingestion", server_default="ingestion")
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
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


class ResearchJob(Base):
    __tablename__ = "research_jobs"
    __table_args__ = (
        UniqueConstraint("need_id", "target_fact", name="uq_research_need_fact"),
        CheckConstraint(
            "max_sources = 1 AND max_requests = 1 AND max_seconds BETWEEN 1 AND 20 "
            "AND max_spend_cents = 0",
            name="ck_research_job_limits",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'unresolved')",
            name="ck_research_job_status",
        ),
    )
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    need_id: Mapped[UUID] = mapped_column(ForeignKey("power_needs.id"))
    target_fact: Mapped[str] = mapped_column(String(60))
    question: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    max_sources: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    max_requests: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    max_seconds: Mapped[int] = mapped_column(Integer, default=20, server_default="20")
    max_spend_cents: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(20), default="queued", server_default="queued")
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    history: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    unresolved_reason: Mapped[str | None] = mapped_column(Text)
    next_action: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchEvidence(Base):
    __tablename__ = "research_evidence"
    __table_args__ = (
        UniqueConstraint("job_id", "content_hash", name="uq_research_evidence_version"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("research_jobs.job_id"))
    source_url: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(String(200))
    source_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    excerpt: Mapped[str] = mapped_column(Text)
    extraction_location: Mapped[str] = mapped_column(String(200))
    content_hash: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(20))
    basis: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(20))
    relationship: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(300), unique=True)


class ProjectRole(Base):
    __tablename__ = "project_roles"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "need_id",
            "organization_id",
            "role",
            "evidence_id",
            name="uq_project_role_evidence",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    need_id: Mapped[UUID] = mapped_column(ForeignKey("power_needs.id"))
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"))
    role: Mapped[str] = mapped_column(String(40))
    evidence_id: Mapped[UUID] = mapped_column(ForeignKey("research_evidence.id"))
    basis: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(20))
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)


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
    required_mw: Mapped[str | None] = mapped_column(String(100))
    start_window: Mapped[str | None] = mapped_column(String(100))
    duration: Mapped[str | None] = mapped_column(String(100))
    supply: Mapped[str] = mapped_column(String(30), default="Unknown")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NeedObservation(Base):
    __tablename__ = "need_observations"
    __table_args__ = (UniqueConstraint("need_id", "observation_id", name="uq_need_observation"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    need_id: Mapped[UUID] = mapped_column(ForeignKey("power_needs.id"))
    observation_id: Mapped[UUID] = mapped_column(ForeignKey("observations.id"))


class ChangeEvent(Base):
    __tablename__ = "change_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observation_id: Mapped[UUID] = mapped_column(ForeignKey("observations.id"))
    content_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
