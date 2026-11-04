"""Shared value types for deterministic permit-document extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

Route = Literal["table", "narrative", "scan", "irrelevant"]
Origin = Literal["table", "narrative"]
Role = Literal["demand_claim", "supply_other"]

REQUIRED_FIELDS = ("id", "type", "rating", "unit")
OPTIONAL_FIELDS = ("count", "drive", "state")


@dataclass(frozen=True, slots=True)
class FieldEvidence:
    """One extracted value with its verbatim quote and canonical-text span."""

    field: str
    value: str
    quote: str
    start: int
    end: int
    page: int


@dataclass(frozen=True, slots=True)
class ExtractedRow:
    """A candidate equipment row. Not trusted until the verifier accepts it."""

    origin: Origin
    equipment_id: str
    equipment_type: str
    drive: str
    rating: Decimal
    unit: str
    count: int | None
    state: str
    evidence: dict[str, FieldEvidence] = field(default_factory=dict)
    group: str = ""
    stitched: bool = False
    linked_to: tuple[str, ...] = ()
    link_hint: str = ""
