"""Vendor-neutral, zero-authority EvidenceJudge contract and strict result parser."""

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class Choice(StrEnum):
    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"


class Level(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class EventType(StrEnum):
    CONSTRUCTION = "construction"
    ELECTRICAL_CONSTRUCTION = "electrical_construction"
    COMMISSIONING = "commissioning"
    UTILITY = "utility"
    PROCUREMENT = "procurement"
    BUYER = "buyer"
    OTHER = "other"
    UNKNOWN = "UNKNOWN"


class Driver(StrEnum):
    """What drives the quoted equipment or load; a label, never a value."""

    ELECTRIC = "ELECTRIC"
    COMBUSTION = "COMBUSTION"
    BOTH = "BOTH"
    UNKNOWN = "UNKNOWN"


class Novelty(StrEnum):
    NEW = "NEW"
    EXISTING = "EXISTING"
    UNKNOWN = "UNKNOWN"


class Side(StrEnum):
    DEMAND = "DEMAND"
    SUPPLY = "SUPPLY"
    UNKNOWN = "UNKNOWN"


class LifecyclePhase(StrEnum):
    PLANNED = "planned"
    PERMITTED = "permitted"
    UNDER_CONSTRUCTION = "under_construction"
    COMMISSIONING = "commissioning"
    OPERATING = "operating"
    CANCELLED = "cancelled"
    UNKNOWN = "UNKNOWN"


class DocumentRoute(StrEnum):
    TABLE = "table"
    NARRATIVE = "narrative"
    SCAN = "scan"
    IRRELEVANT = "irrelevant"
    UNKNOWN = "UNKNOWN"


class Judgment(BaseModel):
    """Closed-vocabulary labels only. No field can carry a quantity, amount or value.

    ``temporary_power_hint`` is a legacy field: it is no longer asked, and exists only so
    results stored before the demand rewrite still validate. The newer demand labels
    default to UNKNOWN for the same reason.
    """

    model_config = ConfigDict(extra="forbid")
    relevant: Choice
    same_project: Choice
    event_type: EventType
    material_change: Choice
    power_relevance: Level
    needs_deep_enrichment: Choice
    temporary_power_hint: Choice = Choice.UNKNOWN
    driver: Driver = Driver.UNKNOWN
    novelty: Novelty = Novelty.UNKNOWN
    side: Side = Side.UNKNOWN
    lifecycle_phase: LifecyclePhase = LifecyclePhase.UNKNOWN
    new_large_load: Choice = Choice.UNKNOWN
    document_route: DocumentRoute = DocumentRoute.UNKNOWN


class EvidenceJudge(Protocol):
    def judge(
        self, state: dict, evidence: dict, candidates: list[dict]
    ) -> tuple[Judgment, dict]: ...


class InvalidJudgment(ValueError):
    pass
