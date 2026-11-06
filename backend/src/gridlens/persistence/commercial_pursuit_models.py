"""Owner-managed commercial pursuits linked to an existing power need.

Distinct from the autonomous research ``pursuits`` table: these rows record the
user's own execution state (stage, follow-ups, manually confirmed activity) and
never alter evidence, qualification or provenance.
"""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from gridlens.persistence.database import Base

STAGES = ("New", "Contacted", "Engaged", "Proposal", "Won", "Lost")
CLOSED_STAGES = ("Won", "Lost")
ACTIVITY_KINDS = ("call", "email", "meeting", "note", "stage_change", "task_completed", "created")
USER_ACTIVITY_KINDS = ("call", "email", "meeting", "note")


class CommercialPursuit(Base):
    __tablename__ = "commercial_pursuits"
    __table_args__ = (UniqueConstraint("need_id", name="uq_commercial_pursuit_need"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    need_id: Mapped[UUID] = mapped_column(ForeignKey("power_needs.id"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    stage: Mapped[str] = mapped_column(String(20), default="New", server_default="New")
    owner: Mapped[str | None] = mapped_column(String(100))
    stage_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PursuitTask(Base):
    __tablename__ = "pursuit_tasks"
    __table_args__ = (Index("ix_pursuit_tasks_pursuit_open", "pursuit_id", "completed_at"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    pursuit_id: Mapped[UUID] = mapped_column(
        ForeignKey("commercial_pursuits.id", ondelete="CASCADE")
    )
    description: Mapped[str] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PursuitActivity(Base):
    __tablename__ = "pursuit_activity"
    __table_args__ = (
        UniqueConstraint("pursuit_id", "client_id", name="uq_pursuit_activity_client"),
        Index("ix_pursuit_activity_pursuit_time", "pursuit_id", "occurred_at"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    pursuit_id: Mapped[UUID] = mapped_column(
        ForeignKey("commercial_pursuits.id", ondelete="CASCADE")
    )
    client_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
