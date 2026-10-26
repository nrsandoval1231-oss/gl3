"""Append-only internal contact privacy suppression ledger."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from gridlens.persistence.database import Base


class ContactSuppression(Base):
    """Versioned suppression keyed by stable pseudonymous subject/method hashes."""

    __tablename__ = "contact_suppressions"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('company', 'person', 'method')", name="ck_contact_suppression_scope"
        ),
        CheckConstraint(
            "action IN ('suppress', 'reinstate')", name="ck_contact_suppression_action"
        ),
        CheckConstraint("version = expected_version + 1", name="ck_contact_suppression_version"),
        UniqueConstraint(
            "scope", "subject_key", "idempotency_key", name="uq_contact_suppression_idempotency"
        ),
        UniqueConstraint("scope", "subject_key", "version", name="uq_contact_suppression_version"),
        Index("ix_contact_suppression_subject", "scope", "subject_key", "version"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(String(12), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(12), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
