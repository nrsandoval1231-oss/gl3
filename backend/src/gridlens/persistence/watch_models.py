"""Persistent, per-need monitoring intent and source cursors."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from gridlens.persistence.database import Base


class ProjectMonitorWatch(Base):
    __tablename__ = "project_monitor_watches"
    __table_args__ = (Index("ix_project_monitor_watches_due", "enabled", "updated_at"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    need_id: Mapped[UUID] = mapped_column(ForeignKey("power_needs.id"), nullable=False, unique=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    question_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    reprocess_revision: Mapped[str] = mapped_column(
        String(80), nullable=False, default="watch-policy-v1", server_default="watch-policy-v1"
    )
    revision_history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    unresolved_questions: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    last_good_facts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    last_good_evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="idle", server_default="idle"
    )
    checkpoint: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    fresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProjectMonitorWatchSource(Base):
    __tablename__ = "project_monitor_watch_sources"
    __table_args__ = (
        UniqueConstraint("watch_id", "source_id", name="uq_monitor_watch_source"),
        Index("ix_monitor_watch_source_due", "enabled", "next_due_at", "watch_id", "source_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    watch_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_monitor_watches.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    allowed_urls: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    record_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    applied_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cursor: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    etag: Mapped[str | None] = mapped_column(String(500))
    last_modified: Mapped[str | None] = mapped_column(String(500))
    next_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="idle", server_default="idle"
    )
    error_class: Mapped[str | None] = mapped_column(String(80))
    checkpoint: Mapped[str | None] = mapped_column(Text)
