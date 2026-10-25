"""Append-only company relationship assertion ledger.

Contact assertions remain in the correction-aware buying-chain claims, and
imported contact data remains in external_import_rows.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
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


class CompanyRelationshipAssertion(Base):
    """Evidence-bound directional company relationship; history is immutable."""

    __tablename__ = "company_relationship_assertions"
    __table_args__ = (
        CheckConstraint(
            "relationship_type IN ('parent', 'subsidiary', 'developer', 'operator', "
            "'epc', 'gc', 'utility')",
            name="ck_company_relationship_type",
        ),
        CheckConstraint(
            "source_company_id <> target_company_id",
            name="ck_company_relationship_distinct",
        ),
        UniqueConstraint("idempotency_key", name="uq_company_relationship_idempotency"),
        Index("ix_company_relationship_source", "source_company_id", "created_at"),
        Index("ix_company_relationship_target", "target_company_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_company_id: Mapped[UUID] = mapped_column(ForeignKey("company_identities.id"))
    target_company_id: Mapped[UUID] = mapped_column(ForeignKey("company_identities.id"))
    relationship_type: Mapped[str] = mapped_column(String(20))
    source_evidence_id: Mapped[UUID] = mapped_column(ForeignKey("buying_chain_evidence.id"))
    source_version_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CompanyRelationshipCorrection(Base):
    """Append-only reversible correction to a relationship assertion."""

    __tablename__ = "company_relationship_corrections"
    __table_args__ = (
        CheckConstraint(
            "action IN ('retract', 'suppress', 'reinstate')",
            name="ck_company_relationship_correction_action",
        ),
        UniqueConstraint(
            "assertion_id",
            "idempotency_key",
            name="uq_company_relationship_correction_idempotency",
        ),
        UniqueConstraint(
            "assertion_id",
            "version",
            name="uq_company_relationship_correction_version",
        ),
        Index("ix_company_relationship_correction_history", "assertion_id", "version"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    assertion_id: Mapped[UUID] = mapped_column(ForeignKey("company_relationship_assertions.id"))
    expected_version: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
