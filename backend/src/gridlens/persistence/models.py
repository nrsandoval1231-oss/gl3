from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
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
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
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
    published_at: Mapped[date] = mapped_column(Date)
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
    published_at: Mapped[date] = mapped_column(Date)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    extraction_location: Mapped[str] = mapped_column(String(100), default="title and abstract")
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    observation: Mapped[Observation] = relationship(back_populates="evidence")


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    identity_key: Mapped[str] = mapped_column(String(220), unique=True)
    name: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(String(200))


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
