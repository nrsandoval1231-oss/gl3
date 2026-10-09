"""Reviewed jurisdiction context; never a project denial or qualification input.

Validate and project a reviewed JSON record with:
python -m gridlens.domain.jurisdiction_policy record.json --on YYYY-MM-DD
"""

from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PolicyEvidence(Record):
    id: Text
    url: HttpUrl
    observed_on: date
    location: Text
    kind: Literal[
        "official_record", "draft_minutes", "staff_report", "reported_vote",
        "enactment_record", "effective_clause",
    ]
    summary: Text


class StatusObservation(Record):
    source_id: Text
    status: Text
    event_date: date | None = None


class Enactment(Record):
    date: date
    source_id: Text


class EffectiveInterval(Record):
    start: date
    end_exclusive: date
    source_id: Text


class PolicyRecord(Record):
    schema_version: Literal[1]
    policy_id: Text
    jurisdiction: Text
    kind: Literal["land_use_moratorium", "utility_intake_constraint", "policy_development"]
    scope: Text
    as_of_date: date
    duration_days: Annotated[int, Field(strict=True, gt=0)] | None = None
    reported_start: Text | None = None
    anticipated_completion: Text | None = None
    evidence: Annotated[tuple[PolicyEvidence, ...], Field(min_length=1)]
    observations: Annotated[tuple[StatusObservation, ...], Field(min_length=1)]
    enactment: Enactment | None = None
    effective_interval: EffectiveInterval | None = None
    limitations: Annotated[tuple[Text, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        sources = {source.id: source for source in self.evidence}
        if len(sources) != len(self.evidence):
            raise ValueError("duplicate evidence IDs")
        if any(source.observed_on > self.as_of_date for source in self.evidence):
            raise ValueError("future evidence cannot support this snapshot")
        for observation in self.observations:
            if observation.source_id not in sources:
                raise ValueError("unknown observation source")
            if observation.event_date and observation.event_date > self.as_of_date:
                raise ValueError("observed event cannot be in the future")
        if self.kind != "land_use_moratorium" and (
            self.enactment or self.effective_interval or self.duration_days is not None
        ):
            raise ValueError("non-moratorium context cannot carry moratorium enactment or duration")
        if self.enactment:
            source = sources.get(self.enactment.source_id)
            if source is None or source.kind != "enactment_record":
                raise ValueError("enactment requires authoritative enactment evidence")
            if self.enactment.date > source.observed_on:
                raise ValueError("enactment must already have occurred when observed")
        interval = self.effective_interval
        if interval:
            source = sources.get(interval.source_id)
            if not self.enactment or source is None or source.kind != "effective_clause":
                raise ValueError(
                    "effective interval requires enactment and effective-clause evidence"
                )
            if not self.enactment.date <= interval.start < interval.end_exclusive:
                raise ValueError("invalid effective interval")
        return self

    def state_on(self, on: date) -> str:
        """Project only the retained interval, not later extensions or repeals.

        A duration or a Passed label never supplies a missing effective date.
        End is exclusive and must be verified during source review, not guessed.
        """
        if on < self.as_of_date:
            raise ValueError("use an earlier snapshot for historical knowledge")
        if self.kind != "land_use_moratorium" and on > self.as_of_date:
            return "requires_refresh"
        if self.kind == "utility_intake_constraint":
            return "reported_constraint"
        if self.kind == "policy_development":
            return "in_development"
        if not self.enactment or not self.effective_interval:
            return "pending_verification"
        if on < self.effective_interval.start:
            return "enacted_not_effective"
        if on >= self.effective_interval.end_exclusive:
            return "expired"
        return "operative"


def load_policy(path: Path) -> PolicyRecord:
    return PolicyRecord.model_validate_json(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--on", type=date.fromisoformat)
    args = parser.parse_args()
    record = load_policy(args.path)
    print(json.dumps({"record": record.model_dump(mode="json"),
                      "state": record.state_on(args.on or record.as_of_date)}, indent=2))
