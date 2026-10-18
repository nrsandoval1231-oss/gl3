"""Strict advisory candidate schema and exact-retained-span validation."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GroundedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    field: Literal[
        "utility_online_date",
        "temporary_load_mw",
        "construction_start",
        "commissioning_window",
        "natural_gas_availability",
        "direct_buyer_authority",
    ]
    value: str = Field(min_length=1, max_length=240)
    unit: str | None = Field(default=None, max_length=24)
    evidence_id: UUID
    evidence_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    quote: str = Field(min_length=8, max_length=600)
    section: Literal["title", "abstract"]
    page: int | None = Field(default=None, ge=1)
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    publisher: str = Field(min_length=1, max_length=200)
    published_date: str | None = None
    support: Literal["direct", "inferred", "ambiguous"]
    status: Literal["candidate"] = "candidate"

    @field_validator("value")
    @classmethod
    def normalized_value(cls, value: str) -> str:
        return value.strip()

    @field_validator("published_date")
    @classmethod
    def valid_date(cls, value: str | None) -> str | None:
        if value is not None:
            date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def valid_units_and_span(self) -> GroundedCandidate:
        if self.field == "temporary_load_mw" and self.unit != "MW":
            raise ValueError("temporary load candidates must be explicitly expressed in MW")
        if self.field != "temporary_load_mw" and self.unit is not None:
            raise ValueError("units are only accepted for temporary load")
        if self.span_end - self.span_start != len(self.quote):
            raise ValueError("span offsets must exactly cover the quoted passage")
        if self.field == "temporary_load_mw":
            try:
                amount = Decimal(self.value)
            except InvalidOperation as exc:
                raise ValueError("temporary load must be a decimal value") from exc
            if not amount.is_finite() or amount <= 0:
                raise ValueError("temporary load must be positive and finite")
            if not re.search(
                rf"(?<![0-9.]){re.escape(self.value)}\s*MW\b", self.quote, re.IGNORECASE
            ):
                raise ValueError("temporary MW value and unit must appear together in the quote")
        if self.field in {"utility_online_date", "construction_start"}:
            date.fromisoformat(self.value)
            if self.value not in self.quote:
                raise ValueError("claim date must appear exactly in the quote")
        if self.field == "commissioning_window" and not (
            _iso_date(self.value) or re.fullmatch(r"\d{4}-(?:Q[1-4]|0[1-9]|1[0-2])", self.value)
        ):
            raise ValueError("commissioning window must have explicit date precision")
        if self.field == "commissioning_window" and self.value not in self.quote:
            raise ValueError("commissioning window must appear exactly in the quote")
        return self


def validate_grounded_candidates(
    payload: dict[str, Any], evidence: list[dict[str, Any]]
) -> dict[str, Any]:
    """Require every candidate to cite its exact retained passage and version."""
    required = {
        "candidates",
        "hypotheses",
        "contradictions",
        "unresolved_questions",
        "candidate_orgs",
        "proposed_queries",
        "suggested_pursuit",
    }
    if set(payload) != required:
        raise ValueError("grounded result keys mismatch")
    if not isinstance(payload["candidates"], list) or len(payload["candidates"]) > 20:
        raise ValueError("candidate count exceeds bound")
    if not isinstance(payload["hypotheses"], list) or len(payload["hypotheses"]) > 8:
        raise ValueError("hypothesis count exceeds bound")
    for key, limit in (
        ("contradictions", 8),
        ("unresolved_questions", 12),
        ("candidate_orgs", 8),
        ("proposed_queries", 8),
    ):
        values = payload[key]
        if (
            not isinstance(values, list)
            or len(values) > limit
            or any(not isinstance(item, str) or not 1 <= len(item) <= 400 for item in values)
        ):
            raise ValueError(f"invalid bounded {key}")
        if key == "proposed_queries" and any(
            re.search(r"(?:https?://|www\.)", item, re.I) for item in values
        ):
            raise ValueError("proposed queries are untrusted search text, not URLs")
    pursuit = payload["suggested_pursuit"]
    if pursuit is not None and (
        not isinstance(pursuit, dict)
        or set(pursuit) != {"title", "rationale"}
        or any(not isinstance(pursuit[k], str) or not 1 <= len(pursuit[k]) <= 400 for k in pursuit)
    ):
        raise ValueError("invalid bounded suggested pursuit")
    by_id = {str(row["id"]): row for row in evidence}
    accepted: list[dict[str, Any]] = []
    for raw in payload["candidates"]:
        candidate = GroundedCandidate.model_validate_json(json.dumps(raw))
        row = by_id.get(str(candidate.evidence_id))
        if row is None or row["content_hash"] != candidate.evidence_hash:
            raise ValueError("candidate references evidence outside its bound context")
        text = "\n".join(part for part in (row.get("title"), row.get("abstract")) if part)
        if (
            candidate.span_end > len(text)
            or text[candidate.span_start : candidate.span_end] != candidate.quote
        ):
            raise ValueError("candidate span does not match retained evidence")
        title_end = len(row.get("title") or "")
        abstract_start = title_end + (1 if row.get("title") and row.get("abstract") else 0)
        if candidate.section == "title":
            section_matches = candidate.span_start >= 0 and candidate.span_end <= title_end
        else:
            section_matches = candidate.span_start >= abstract_start and candidate.span_end <= len(
                text
            )
        if not section_matches or candidate.page != row.get("page"):
            raise ValueError("candidate section or page does not match retained evidence location")
        candidate_data = candidate.model_dump(mode="json")
        if candidate.published_date != row.get("published_at"):
            raise ValueError("candidate date does not match retained evidence")
        if candidate.publisher != row["publisher"]:
            raise ValueError("candidate publisher does not match evidence source")
        if candidate.field == "temporary_load_mw" and any(
            token in candidate.quote.casefold() for token in ("total capacity", "flare")
        ):
            raise ValueError("campus capacity does not establish temporary demand")
        if (
            candidate.field == "temporary_load_mw"
            and "campus" in candidate.quote.casefold()
            and not any(
                token in candidate.quote.casefold() for token in ("temporary", "bridge", "backup")
            )
        ):
            raise ValueError("campus demand does not establish temporary load")
        if candidate.field == "natural_gas_availability" and any(
            token in candidate.quote.casefold() for token in ("flare", "flaring")
        ):
            raise ValueError("flaring does not establish available natural gas")
        if (
            candidate.field == "direct_buyer_authority"
            and "applicant" in candidate.quote.casefold()
        ):
            raise ValueError("applicant status does not establish direct buyer authority")
        accepted.append(candidate_data)
    hypotheses = payload["hypotheses"]
    if any(not isinstance(item, str) or not 1 <= len(item) <= 500 for item in hypotheses):
        raise ValueError("invalid bounded hypothesis")
    return {
        "schema_version": "grounded-candidates-v1",
        "candidates": accepted,
        "hypotheses": hypotheses,
        "contradictions": payload["contradictions"],
        "unresolved_questions": payload["unresolved_questions"],
        "candidate_orgs": payload["candidate_orgs"],
        "proposed_queries": payload["proposed_queries"],
        "suggested_pursuit": pursuit,
    }


def _iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True
