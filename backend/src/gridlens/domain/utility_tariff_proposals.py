"""Source-linked proposal metadata, never operative tariff or project obligations.

Validate a reviewed record with:
python -m gridlens.domain.utility_tariff_proposals path/to/proposal.json

No matching, billing, qualification, network access or database writes occur.
"""

from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Source(Record):
    id: Text
    kind: Literal["regulatory_filing", "regulatory_order", "utility_announcement"]
    url: HttpUrl
    published_date: date
    retrieved_date: date


class Citation(Record):
    source_id: Text
    location: Text


class Applicability(Record):
    territory: Text
    threshold_mw: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)] | None
    threshold_basis: Text
    conditions: Text
    citation: Citation


class ProposedTerm(Record):
    key: Text
    stage: Literal["proposed_tariff", "future_rate_case_intent", "utility_announcement"]
    summary: Text
    citation: Citation


class TariffProposal(Record):
    schema_version: Literal[1]
    proposal_id: Text
    utility: Text
    regulator: Text
    docket: Text
    status: Literal["proposed_pending"]
    as_of_date: date
    filing_date: date | None
    announcement_date: date | None
    proposed_effective_date: date | None
    sources: Annotated[tuple[Source, ...], Field(min_length=1)]
    status_citation: Citation
    applicability: Applicability | None
    terms: Annotated[tuple[ProposedTerm, ...], Field(min_length=1)]
    limitations: Annotated[tuple[Text, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        sources = {source.id: source for source in self.sources}
        if len(sources) != len(self.sources):
            raise ValueError("duplicate source IDs")
        if len({term.key for term in self.terms}) != len(self.terms):
            raise ValueError("duplicate term keys")
        citations = [self.status_citation, *(term.citation for term in self.terms)]
        if self.applicability is not None:
            citations.append(self.applicability.citation)
        if any(citation.source_id not in sources for citation in citations):
            raise ValueError("citation must reference a retained source")
        if self.applicability is not None:
            source = sources[self.applicability.citation.source_id]
            if source.kind != "regulatory_filing":
                raise ValueError("applicability requires a verified regulatory filing citation")
        for term in self.terms:
            source = sources[term.citation.source_id]
            if term.stage != "utility_announcement" and source.kind != "regulatory_filing":
                raise ValueError(
                    "proposed tariff and future rate-case terms require filing citations"
                )
        for source in self.sources:
            if not source.published_date <= source.retrieved_date <= self.as_of_date:
                raise ValueError("source dates must precede the proposal review date")
        # A requested effective date is intentionally NOT an activation condition.
        return self


def load_proposal(path: Path) -> TariffProposal:
    """Fail visibly on invalid records; preserve unknowns and proposal-only status."""
    return TariffProposal.model_validate_json(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(load_proposal(args.path).model_dump_json(indent=2))
