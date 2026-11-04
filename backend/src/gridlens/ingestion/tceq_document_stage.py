"""Database glue for the TCEQ application-document stage.

The stage itself (``adapters/tceq_application_documents.py``) never touches the database. This
module reads the retained prior state for change detection and turns a stage report into the
counts the job records, so a failure is visible and an accepted state is never overwritten.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gridlens.ingestion.adapters.tceq_application_documents import StageReport
from gridlens.persistence.models import Evidence, Observation

STATE_KEY = "application_document"


def load_prior_states(session: Session, source_id: str) -> dict[str, dict[str, Any]]:
    """Latest retained document state per TCEQ project, from the newest evidence that has one."""
    rows = session.execute(
        select(Observation.external_id, Evidence.provenance)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .where(Observation.source_id == source_id, Evidence.provenance.op("?")(STATE_KEY))
        .distinct(Observation.external_id)
        .order_by(Observation.external_id, Evidence.observed_at.desc(), Evidence.id)
    ).all()
    states: dict[str, dict[str, Any]] = {}
    for external_id, provenance in rows:
        state = provenance.get(STATE_KEY) if isinstance(provenance, dict) else None
        project = external_id.removeprefix("TCEQ-")
        if isinstance(state, dict) and project.isdigit():
            states[project] = state
    return states


def merge_report(counts: dict[str, Any], report: StageReport) -> None:
    """Record the stage in the job counts. Failures make the run partial, never silent."""
    counts["application_documents"] = {**report.counts, "known_failed": len(report.known_failed)}
    failures = len(report.rejections)
    if failures:
        counts["partial"] = True
        counts["parse_failures"] = int(counts.get("parse_failures", 0)) + failures
        counts["attempt_rejected"] = int(counts.get("attempt_rejected", 0)) + failures
        counts["rejected_records"] = [*counts.get("rejected_records", []), *report.rejections][:50]
