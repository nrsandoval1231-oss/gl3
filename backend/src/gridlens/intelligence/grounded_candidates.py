"""Strict advisory claims bound to exact retained source passages."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    original_value: str | None = Field(default=None, max_length=80)
    original_unit: Literal["kW", "MW"] | None = None
    precision: int | None = Field(default=None, ge=0, le=12)
    date_precision: Literal["day", "month", "quarter", "year"] | None = None
    evidence_id: UUID
    evidence_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    quote: str = Field(min_length=8, max_length=600)
    section: Literal["title", "abstract"]
    page: int | None = Field(default=None, ge=1)
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    publisher: str = Field(min_length=1, max_length=200)
    published_date: str | None = None
    speaker: str | None = Field(default=None, max_length=200)
    speaker_organization: str | None = Field(default=None, max_length=200)
    speaker_role: str | None = Field(default=None, max_length=160)
    support: Literal["direct", "inferred", "ambiguous"]
    status: Literal["candidate"] = "candidate"

    @model_validator(mode="after")
    def validate_claim(self) -> GroundedCandidate:
        if self.span_end - self.span_start != len(self.quote):
            raise ValueError("span offsets must exactly cover the quoted passage")
        if self.published_date is not None:
            try:
                date.fromisoformat(self.published_date)
            except ValueError as exc:
                raise ValueError("published date must be ISO date") from exc
        if self.field == "temporary_load_mw":
            if self.unit != "MW" or self.original_unit not in {"kW", "MW"}:
                raise ValueError(
                    "temporary load requires explicit original units and normalized MW"
                )
            pieces = re.fullmatch(
                r"\s*(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*",
                self.original_value or "",
                re.I,
            )
            if pieces:
                low, high = Decimal(pieces.group(1)), Decimal(pieces.group(2))
                if not low.is_finite() or not high.is_finite() or low <= 0 or high < low:
                    raise ValueError("temporary load range must be positive and finite")
                low_mw = _format_decimal(_to_mw(low, self.original_unit))
                high_mw = _format_decimal(_to_mw(high, self.original_unit))
                amount = f"{low_mw}-{high_mw}"
            else:
                try:
                    original = Decimal(self.original_value or "")
                except InvalidOperation as exc:
                    raise ValueError(
                        "temporary load must preserve explicit numeric source value"
                    ) from exc
                amount = _format_decimal(_to_mw(original, self.original_unit))
                if not original.is_finite() or original <= 0:
                    raise ValueError("temporary load must be positive and finite")
            if self.value != amount or self.precision != _source_precision(
                self.original_value or ""
            ):
                raise ValueError(
                    "temporary load normalization or precision does not match source value"
                )
            if not _quantity_in_quote(self.original_value or "", self.original_unit, self.quote):
                raise ValueError("original quantity and unit must appear together in quote")
            if _negated_claim(self.original_value or "", self.quote):
                raise ValueError("negated quantity cannot support a candidate")
        elif any((self.original_value, self.original_unit, self.precision)):
            raise ValueError("quantity provenance applies only to temporary load")
        if self.field in {"utility_online_date", "construction_start", "commissioning_window"}:
            precision = _date_precision(self.value)
            if (
                precision is None
                or self.date_precision != precision
                or self.value not in self.quote
            ):
                raise ValueError("date value must preserve explicit source precision")
            if _negated_claim(self.value, self.quote):
                raise ValueError("negated date claim cannot support a candidate")
        elif self.date_precision is not None:
            raise ValueError("date precision only applies to date claims")
        return self


def validate_grounded_candidates(
    payload: dict[str, Any], evidence: list[dict[str, Any]]
) -> dict[str, Any]:
    """Require each advisory candidate to cite its exact retained text and version."""
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
    limits = {
        "candidates": 20,
        "hypotheses": 8,
        "contradictions": 8,
        "unresolved_questions": 12,
        "candidate_orgs": 8,
        "proposed_queries": 8,
    }
    for key, limit in limits.items():
        value = payload[key]
        if not isinstance(value, list) or len(value) > limit:
            raise ValueError(f"invalid bounded {key}")
        if key != "candidates" and any(
            not isinstance(item, str) or not 1 <= len(item) <= 500 for item in value
        ):
            raise ValueError(f"invalid bounded {key}")
    if any(re.search(r"(?:https?://|www\.)", item, re.I) for item in payload["proposed_queries"]):
        raise ValueError("proposed queries are untrusted search text, not URLs")
    pursuit = payload["suggested_pursuit"]
    if pursuit is not None and (
        not isinstance(pursuit, dict)
        or set(pursuit) != {"title", "rationale"}
        or any(not isinstance(pursuit[k], str) or not 1 <= len(pursuit[k]) <= 400 for k in pursuit)
    ):
        raise ValueError("invalid bounded suggested pursuit")
    by_id = {str(row["id"]): row for row in evidence}
    accepted = []
    for raw in payload["candidates"]:
        candidate = GroundedCandidate.model_validate_json(json.dumps(raw))
        row = by_id.get(str(candidate.evidence_id))
        if row is None or row.get("content_hash") != candidate.evidence_hash:
            raise ValueError("candidate references evidence outside its bound context")
        title = row.get("title") or ""
        abstract = row.get("abstract") or ""
        text = title + ("\n" if title and abstract else "") + abstract
        if (
            candidate.span_end > len(text)
            or text[candidate.span_start : candidate.span_end] != candidate.quote
        ):
            raise ValueError("candidate span does not match retained evidence")
        title_end = len(title)
        abstract_start = title_end + (1 if title and abstract else 0)
        correct_section = (
            candidate.span_end <= title_end
            if candidate.section == "title"
            else candidate.span_start >= abstract_start
        )
        if not correct_section or not _page_matches(
            row, candidate.page, candidate.section, candidate.span_start, abstract_start
        ):
            raise ValueError("candidate section or page does not match retained evidence location")
        if (
            candidate.published_date != row.get("published_at")
            or candidate.publisher != row["publisher"]
        ):
            raise ValueError("candidate date or publisher does not match retained evidence")
        if any(
            value is not None and value not in candidate.quote
            for value in (
                candidate.speaker,
                candidate.speaker_organization,
                candidate.speaker_role,
            )
        ):
            raise ValueError("speaker attribution is unsupported by cited quote")
        quote = candidate.quote.casefold()
        if candidate.field == "temporary_load_mw" and any(
            term in quote for term in ("total capacity", "flare")
        ):
            raise ValueError("capacity or flaring does not establish temporary demand")
        if (
            candidate.field == "temporary_load_mw"
            and "campus" in quote
            and not any(term in quote for term in ("temporary", "bridge", "backup"))
        ):
            raise ValueError("campus demand does not establish temporary load")
        if candidate.field == "natural_gas_availability" and any(
            term in quote for term in ("flare", "flaring")
        ):
            raise ValueError("flaring does not establish available natural gas")
        if candidate.field == "direct_buyer_authority" and "applicant" in quote:
            raise ValueError("applicant status does not establish direct buyer authority")
        accepted.append(candidate.model_dump(mode="json"))
    if any(
        not isinstance(item, str) or not 1 <= len(item) <= 500 for item in payload["hypotheses"]
    ):
        raise ValueError("invalid bounded hypothesis")
    return {
        "schema_version": "grounded-candidates-v2",
        "candidates": accepted,
        "hypotheses": payload["hypotheses"],
        "contradictions": payload["contradictions"],
        "unresolved_questions": payload["unresolved_questions"],
        "candidate_orgs": payload["candidate_orgs"],
        "proposed_queries": payload["proposed_queries"],
        "suggested_pursuit": pursuit,
    }


def _to_mw(value: Decimal, unit: str) -> Decimal:
    return value / Decimal(1000) if unit == "kW" else value


def _format_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _source_precision(value: str) -> int:
    number = re.search(r"\d+(?:\.(\d+))?", value)
    return len(number.group(1)) if number and number.group(1) else 0


def _quantity_in_quote(value: str, unit: str, quote: str) -> bool:
    return (
        bool(re.search(rf"(?<![\d.]){re.escape(value)}\s*{unit}\b", quote, re.I))
        if "-" not in value and "to" not in value
        else all(
            _quantity_in_quote(part, unit, quote)
            for part in re.split(r"\s*(?:-|to)\s*", value, flags=re.I)
        )
    )


def _date_precision(value: str) -> str | None:
    if re.fullmatch(r"\d{4}", value):
        return "year"
    month = (
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    )
    if re.fullmatch(rf"\d{{4}}-\d{{2}}|{month}\s+\d{{4}}", value, re.I):
        return "month"
    if re.fullmatch(r"\d{4}-Q[1-4]|Q[1-4]\s+\d{4}", value, re.I):
        return "quarter"
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return "day"


def _negated_claim(value: str, quote: str) -> bool:
    for match in re.finditer(re.escape(value), quote, re.I):
        prefix = quote[max(0, match.start() - 48) : match.start()]
        if re.search(
            r"\b(?:no|not|never|without|denied|cancelled|canceled|not expected)\b",
            prefix,
            re.I,
        ):
            return True
    return False


def _page_matches(
    row: dict[str, Any], page: int | None, section: str, start: int, abstract_start: int
) -> bool:
    if section == "title":
        return page is None
    abstract_offset = start - abstract_start
    text = row.get("abstract") or ""
    location = row.get("extraction_location") or ""
    if page is None:
        return True
    if re.search(rf"\bpage\s+{page}\b", location, re.I) and not re.search(
        r"\bpages?\s+\d+\s*[-–]\s*\d+", location, re.I
    ):
        return True
    matches = list(re.finditer(r"(?:^|\n)\s*(?:\[)?Page\s+(\d+)(?:\])?\s*:?", text, re.I))
    for index, marker in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        if int(marker.group(1)) == page and marker.start() <= abstract_offset < end:
            return True
    return False
