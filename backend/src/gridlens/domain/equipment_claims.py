"""Strict, non-authoritative structural validation for equipment claim candidates."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from gridlens.domain.equipment_evidence import (
    EvidenceContext,
    EvidenceReference,
    validate_evidence_reference,
)

EquipmentType = Literal["compressor", "pump", "unknown"]
DriveType = Literal["electric", "gas_engine", "diesel_engine", "steam", "unknown", "mixed"]
LifecycleStatus = Literal["existing", "proposed", "installed", "retired", "unknown"]
OperatingRole = Literal["duty", "standby", "redundant", "unknown"]
RatingUnit = Literal["kW", "MW", "hp", "kVA"]
RatingBasis = Literal["electrical_input", "mechanical_output", "generator_output", "unknown"]
ClaimState = Literal["reported", "unknown", "contradicted"]
PositiveCount = Annotated[int, Field(strict=True, gt=0)]
_DECIMAL_LEXEME = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z", re.ASCII)


def _strict_uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("must be a UUID or canonical UUID string") from exc
        if str(parsed) != value:
            raise ValueError("UUID string must use canonical lowercase hyphenated form")
        return parsed
    raise ValueError("must be a UUID or canonical UUID string")


class EquipmentRating(BaseModel):
    """An original equipment rating claim, retaining its value and unit verbatim."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )

    value: str = Field(max_length=100)
    unit: RatingUnit
    basis: RatingBasis

    @field_validator("value", mode="before")
    @classmethod
    def positive_finite_decimal_string(cls, value: object) -> str:
        if not isinstance(value, str) or len(value) > 100:
            raise ValueError("rating value must be a decimal string of at most 100 characters")
        if _DECIMAL_LEXEME.fullmatch(value) is None:
            raise ValueError(
                "rating value must use ASCII decimal digits and an optional decimal point"
            )
        try:
            decimal_value = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("rating value must be a decimal string") from exc
        if not decimal_value.is_finite() or decimal_value <= 0:
            raise ValueError("rating value must be finite and positive")
        return value


class EquipmentClaim(BaseModel):
    """Frozen equipment candidate; structural validity does not verify its claims."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )

    schema_version: Literal["equipment-claim-v1"]
    claim_id: UUID
    project_id: UUID
    need_id: UUID
    equipment_id: str = Field(max_length=200)
    equipment_type: EquipmentType
    drive_type: DriveType
    lifecycle_status: LifecycleStatus
    operating_role: OperatingRole
    count: PositiveCount | None
    rating: EquipmentRating | None
    evidence: EvidenceReference
    verification_state: Literal["UNVERIFIED"]
    claim_state: ClaimState

    @field_validator("claim_id", "project_id", "need_id", mode="before")
    @classmethod
    def accept_uuid_or_canonical_text(cls, value: object) -> UUID:
        return _strict_uuid(value)

    @field_validator("equipment_id")
    @classmethod
    def equipment_id_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("equipment_id must be nonblank")
        return value

    @field_validator("evidence", mode="before")
    @classmethod
    def parse_evidence_reference(cls, value: object) -> EvidenceReference:
        if isinstance(value, EvidenceReference):
            return value
        if isinstance(value, dict):
            try:
                return EvidenceReference(**value)
            except (TypeError, ValueError) as exc:
                raise ValueError("evidence must match the evidence reference schema") from exc
        raise ValueError("evidence must be an evidence reference mapping")


def validate_equipment_claim(value: dict, *, context: EvidenceContext) -> EquipmentClaim:
    """Validate shape, evidence binding, and exact project/need scope only.

    This function does not authenticate a database snapshot, verify source meaning,
    infer electrical demand, calculate MW/gap, or award commercial qualification.
    """
    if not isinstance(value, dict):
        raise ValueError("equipment claim must be an object")
    if not isinstance(context, EvidenceContext):
        raise ValueError("context must be an EvidenceContext")
    try:
        context = EvidenceContext.model_validate(context)
    except (ValidationError, ValueError, TypeError) as exc:
        raise ValueError("context is malformed") from exc
    claim_values = dict(value)
    if "evidence" in claim_values:
        claim_values["evidence"] = validate_evidence_reference(
            claim_values["evidence"], context=context
        )
    claim = EquipmentClaim.model_validate(claim_values)
    if claim.project_id != context.project_id or claim.need_id != context.need_id:
        raise ValueError("equipment claim scope must match the supplied evidence context")
    # Revalidate the nested evidence against the exact retained snapshot supplied by
    # the caller; the candidate's structural parse alone is not evidence verification.
    return claim
