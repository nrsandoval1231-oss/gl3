"""Strict advisory-only Jev response contracts; none of these types grants authority."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Choice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    choice: str


class AdvisoryContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    contract_id: str
    choices: tuple[str, ...]
    authority: Literal["ADVISORY_ONLY"] = "ADVISORY_ONLY"

    def validate_choice(self, result: Choice) -> Choice:
        if result.choice not in self.choices:
            raise ValueError(f"choice must be one of {', '.join(self.choices)}")
        return result


class PriorityChoice(StrEnum):
    VERY_LOW = "1"
    LOW = "2"
    MODERATE = "3"
    HIGH = "4"
    VERY_HIGH = "5"


SOURCE_RELEVANCE_V1 = AdvisoryContract(
    contract_id="SOURCE_RELEVANCE_V1", choices=("RELEVANT", "IRRELEVANT", "UNCERTAIN")
)
EVENT_CLASS_V1 = AdvisoryContract(
    contract_id="EVENT_CLASS_V1",
    choices=(
        "CONSTRUCTION",
        "COMMISSIONING",
        "FORMATION",
        "ENERGIZATION",
        "PROCUREMENT",
        "OTHER",
        "UNKNOWN",
    ),
)
MATCH_ADVISORY_V1 = AdvisoryContract(
    contract_id="MATCH_ADVISORY_V1", choices=("SAME", "DIFFERENT", "UNRESOLVED")
)
MATERIALITY_V1 = AdvisoryContract(
    contract_id="MATERIALITY_V1", choices=("MATERIAL", "ROUTINE", "UNKNOWN")
)
POWER_ACTIVITY_HINT_V1 = AdvisoryContract(
    contract_id="POWER_ACTIVITY_HINT_V1",
    choices=("CONSTRUCTION", "COMMISSIONING", "BRIDGE", "BTM", "OIL_GAS", "OTHER", "UNKNOWN"),
)
RESEARCH_PRIORITY_V1 = AdvisoryContract(
    contract_id="RESEARCH_PRIORITY_V1", choices=("1", "2", "3", "4", "5")
)
BUYER_ROLE_HINT_V1 = AdvisoryContract(
    contract_id="BUYER_ROLE_HINT_V1",
    choices=("OWNER", "DEVELOPER", "GC_EPC", "ENGINEER", "UTILITY", "VENDOR", "UNKNOWN"),
)
LLM_ROUTE_V1 = AdvisoryContract(
    contract_id="LLM_ROUTE_V1",
    choices=("NONE", "FAST_EXTRACT", "DEEP_RESEARCH", "HUMAN_REVIEW"),
)

CONTRACTS = {
    contract.contract_id: contract
    for contract in (
        SOURCE_RELEVANCE_V1,
        EVENT_CLASS_V1,
        MATCH_ADVISORY_V1,
        MATERIALITY_V1,
        POWER_ACTIVITY_HINT_V1,
        RESEARCH_PRIORITY_V1,
        BUYER_ROLE_HINT_V1,
        LLM_ROUTE_V1,
    )
}


class JevChoiceAnswer(BaseModel):
    """Validated local representation of TypeSafe's choice answer fields."""

    model_config = ConfigDict(extra="forbid", strict=True)
    choice: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    probabilities: dict[str, float] | None = None


def validate_answer(contract_id: str, payload: dict[str, object]) -> JevChoiceAnswer:
    try:
        contract = CONTRACTS[contract_id]
    except KeyError as exc:
        raise ValueError("unknown Jev contract") from exc
    answer = JevChoiceAnswer.model_validate(payload)
    contract.validate_choice(Choice(choice=answer.choice))
    if answer.probabilities is not None:
        if any(not 0 <= value <= 1 for value in answer.probabilities.values()):
            raise ValueError("probabilities must be in [0, 1]")
        if not 0.98 <= sum(answer.probabilities.values()) <= 1.02:
            raise ValueError("probabilities must approximately sum to one")
    return answer
