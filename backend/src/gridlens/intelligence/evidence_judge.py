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


class Judgment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relevant: Choice
    same_project: Choice
    event_type: EventType
    material_change: Choice
    power_relevance: Level
    temporary_power_hint: Choice
    needs_deep_enrichment: Choice


class EvidenceJudge(Protocol):
    def judge(
        self, state: dict, evidence: dict, candidates: list[dict]
    ) -> tuple[Judgment, dict]: ...


class InvalidJudgment(ValueError):
    pass
