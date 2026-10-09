"""Public RFI context only; never qualification, purchasing authority, or response access."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

VERSION = "ercot-impact-rfi-v1"
FAMILY = "ercot-impact-rfi"
FIELDS = {
    "project_name",
    "developer",
    "latitude",
    "longitude",
    "regional_water_planning_group",
    "peak_requested_load_mw",
    "ercot_region",
    "not_yet_energized",
    "substantiated_load",
    "medium_load_reported",
    "newly_substantiated",
    "batch_zero_classification",
    "grid_dependence",
    "onsite_generation",
    "ownership_control",
    "water",
    "cooling",
    "community_impacts",
    "public_financial_assistance",
}


class PublicClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: Any
    quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def nonempty_quote(self) -> "PublicClaim":
        if not self.quote.strip() or self.value is None:
            raise ValueError("A public claim requires a nonempty quote and value")
        return self


class RFIRecord(BaseModel):
    """Stored under Interpretation.assessment['ercot_impact_rfi']; evidence bound externally."""

    model_config = ConfigDict(extra="forbid")
    publication_state: Literal[
        "public_question_schema",
        "public_project_disclosure",
        "public_aggregate",
        "public_anonymized",
    ]
    project_identity_key: str | None = None
    evidence_id: UUID
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    claims: dict[str, PublicClaim] = Field(default_factory=dict)

    @model_validator(mode="after")
    def public_scope(self) -> "RFIRecord":
        if self.publication_state != "public_project_disclosure":
            if self.project_identity_key or self.claims:
                raise ValueError(
                    "Schema and aggregate/anonymized results cannot identify a project"
                )
        elif not self.project_identity_key:
            raise ValueError("A project disclosure requires an explicit site identity")
        if not self.claims.keys() <= FIELDS:
            raise ValueError("Unsupported RFI field")
        for name, claim in self.claims.items():
            value = claim.value
            if name == "batch_zero_classification" and not isinstance(value, str):
                raise ValueError("Batch Zero classification requires text")
            if name in {"latitude", "longitude", "peak_requested_load_mw"}:
                if type(value) not in {int, float}:
                    raise ValueError("Numeric RFI field requires a finite number")
                low, high = {
                    "latitude": (25.837401, 37),
                    "longitude": (-106.645632, -93.507837),
                    "peak_requested_load_mw": (0, float("inf")),
                }[name]
                if not low <= value <= high or value == float("inf"):
                    raise ValueError("RFI number outside permitted range")
            if (
                name
                in {
                    "ercot_region",
                    "not_yet_energized",
                    "substantiated_load",
                    "medium_load_reported",
                    "newly_substantiated",
                }
                and type(value) is not bool
            ):
                raise ValueError("RFI eligibility flag requires a boolean")
        return self


def classify_scope(
    *,
    peak_requested_load_mw: float | None = None,
    ercot_region: bool | None = None,
    not_yet_energized: bool | None = None,
    substantiated_load: bool | None = None,
    medium_load_reported: bool | None = None,
    newly_substantiated: bool | None = None,
    batch_zero_classification: str | None = None,
) -> str:
    """Advisory respondent category, never evidence of submission or §25.194 readiness."""
    if peak_requested_load_mw is not None and peak_requested_load_mw < 25:
        return "OUTSIDE"
    if ercot_region is False or not_yet_energized is False:
        return "OUTSIDE"
    if peak_requested_load_mw is None or ercot_region is not True or not_yet_energized is not True:
        return "UNKNOWN"
    if peak_requested_load_mw < 75:
        if substantiated_load is True and medium_load_reported is True:
            return "MEDIUM_REQUIRED"
        if (
            substantiated_load is True
            and medium_load_reported is False
            and newly_substantiated is True
        ):
            return "MEDIUM_VOLUNTARY"
        return "UNKNOWN"
    if batch_zero_classification in {"base_load", "studied_load"}:
        return "BATCH_ZERO_REQUIRED"
    return "UNKNOWN"
