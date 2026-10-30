"""Strict, database-free validation for retained evidence references."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

_HASH = re.compile(r"^[0-9a-fA-F]{64}$")
_FIELDS = frozenset(
    {
        "source_id",
        "observation_id",
        "evidence_id",
        "evidence_hash",
        "source_url",
        "observed_at",
        "retrieved_at",
        "published_at",
        "extraction_location",
        "extractor_version",
        "quote",
    }
)


class EvidenceReference(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )

    source_id: str = Field(min_length=1, max_length=200)
    observation_id: UUID
    evidence_id: UUID
    evidence_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    source_url: str = Field(min_length=1, max_length=4096)
    observed_at: datetime
    retrieved_at: datetime
    published_at: date | None
    extraction_location: str = Field(min_length=1, max_length=2000)
    extractor_version: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=20000)

    @model_validator(mode="after")
    def validate_source_metadata(self) -> EvidenceReference:
        for field_name in ("source_id", "source_url", "extraction_location", "extractor_version"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must be nonblank")
        if not self.quote.strip():
            raise ValueError("quote must be nonblank")
        for field_name in ("observed_at", "retrieved_at"):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.observed_at > self.retrieved_at:
            raise ValueError("observed_at cannot be after retrieved_at")
        if self.published_at is not None and self.published_at > self.observed_at.date():
            raise ValueError("published_at cannot be after observed_at")
        parsed_url = urlsplit(self.source_url)
        if (
            parsed_url.scheme.lower() not in {"http", "https"}
            or not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
        ):
            raise ValueError("source_url must be an HTTP(S) URL without credentials")
        return self


class EvidenceContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )

    project_id: UUID
    need_id: UUID
    reference: EvidenceReference
    source_text: str


def _canonical_uuid(value: Any, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            parsed = UUID(value)
        except ValueError:
            pass
        else:
            if str(parsed) == value:
                return parsed
    raise ValueError(f"{field_name} must be a UUID or canonical lowercase UUID string")


def _aware_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{field_name} must be an exact ISO-8601 datetime") from None
        if not (
            parsed.isoformat() == value
            or (value.endswith("Z") and parsed.isoformat() == value[:-1] + "+00:00")
        ):
            raise ValueError(f"{field_name} must be an exact ISO-8601 datetime")
    else:
        raise ValueError(f"{field_name} must be a datetime or ISO-8601 string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def _published_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        raise ValueError("published_at must be a date or null")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            parsed = None
        if parsed is not None and parsed.isoformat() == value:
            return parsed
    raise ValueError("published_at must be a date, ISO date string or null")


def _reference_values(value: Any) -> dict[str, Any]:
    if isinstance(value, EvidenceReference):
        # Reparse even model instances: model_construct() can bypass validation.
        values = value.model_dump(mode="python")
    elif isinstance(value, dict):
        values = value
    else:
        raise ValueError("Evidence reference must be a strict mapping or EvidenceReference")
    if set(values) != _FIELDS:
        raise ValueError("Evidence reference fields are missing or unsupported")

    normalized = dict(values)
    normalized["observation_id"] = _canonical_uuid(values["observation_id"], "observation_id")
    normalized["evidence_id"] = _canonical_uuid(values["evidence_id"], "evidence_id")
    normalized["observed_at"] = _aware_datetime(values["observed_at"], "observed_at")
    normalized["retrieved_at"] = _aware_datetime(values["retrieved_at"], "retrieved_at")
    normalized["published_at"] = _published_date(values["published_at"])
    return normalized


def _context_model(context: Any) -> EvidenceContext:
    if not isinstance(context, EvidenceContext):
        raise ValueError("context must be an EvidenceContext")
    try:
        values = context.model_dump(mode="python")
    except Exception as exc:
        raise ValueError("context is malformed") from exc
    reference = EvidenceReference.model_validate(_reference_values(values.get("reference")))
    source_text = values.get("source_text")
    if not isinstance(source_text, str):
        raise ValueError("context source_text must be text")
    return EvidenceContext(
        project_id=_canonical_uuid(values.get("project_id"), "project_id"),
        need_id=_canonical_uuid(values.get("need_id"), "need_id"),
        reference=reference,
        source_text=source_text,
    )


def validate_evidence_reference(
    value: EvidenceReference | dict[str, Any], *, context: EvidenceContext
) -> EvidenceReference:
    """Validate exact binding to the caller-supplied retained snapshot.

    This checks structure and byte-for-byte quote containment only. It does not
    authenticate the snapshot, establish source authority, or verify claim meaning.
    """
    validated_context = _context_model(context)
    candidate = EvidenceReference.model_validate(_reference_values(value))
    if candidate != validated_context.reference:
        raise ValueError("evidence reference does not match the retained snapshot")
    if candidate.quote not in validated_context.source_text:
        raise ValueError("quote must be an exact substring of retained source text")
    return candidate
