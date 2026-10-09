"""Read-only public RFI metadata using existing interpretation/evidence storage."""

from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.domain.ercot_impact_rfi import FAMILY, VERSION, RFIRecord, classify_scope
from gridlens.persistence.models import Evidence, Interpretation, Observation, Project, Source


def public_rfi_state(session: Session, project: Project) -> dict[str, Any]:
    rows = session.execute(
        select(Observation, Evidence, Interpretation, Source)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .join(Interpretation, Interpretation.observation_id == Observation.id)
        .join(Source, Source.id == Observation.source_id)
        .where(Source.family == FAMILY)
    )
    disclosures = []
    for observation, evidence, interpretation, source in rows:
        assessment = interpretation.assessment or {}
        if not (
            interpretation.status == "accepted"
            and interpretation.evaluator_version == VERSION
            and observation.content_hash == evidence.content_hash == interpretation.content_hash
            and assessment.get("evidence_hash") == evidence.content_hash
        ):
            continue
        try:
            record = RFIRecord.model_validate(assessment.get("ercot_impact_rfi"))
        except ValidationError:
            continue
        if not (
            record.publication_state == "public_project_disclosure"
            and source.retrieval_method == "ercot-impact-rfi-project"
            and record.project_identity_key == project.identity_key
            and record.evidence_id == evidence.id
            and record.evidence_hash == evidence.content_hash
            and evidence.url.startswith("https://")
            and (evidence.published_at or evidence.event_date)
            and all(c.quote in (evidence.abstract or "") for c in record.claims.values())
        ):
            continue
        facts = {k: c.value for k, c in record.claims.items()}
        scope_keys = {
            "peak_requested_load_mw",
            "ercot_region",
            "not_yet_energized",
            "substantiated_load",
            "medium_load_reported",
            "newly_substantiated",
            "batch_zero_classification",
        }
        disclosures.append(
            {
                "publication_state": record.publication_state,
                "claims": {k: c.model_dump() for k, c in record.claims.items()},
                "respondent_category": classify_scope(
                    **{k: v for k, v in facts.items() if k in scope_keys}
                ),
                "category_kind": "Derived",
                "evidence_id": str(evidence.id),
                "evidence_hash": evidence.content_hash,
                "url": evidence.url,
                "extraction_location": evidence.extraction_location,
                "published_at": evidence.published_at,
                "retrieved_at": evidence.observed_at,
                "event_date": evidence.event_date,
                "event_date_label": evidence.event_date_label,
            }
        )
    return {
        "status": "PUBLIC_DISCLOSURES" if disclosures else "UNKNOWN",
        "disclosures": disclosures,
        "disclosure": "Public project disclosures only; conflicting reports remain separate. "
        "RFI questions and aggregate/anonymized results are not project answers. "
        "No confidential responses, submission status, power gap or buying authority inferred.",
    }
