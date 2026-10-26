"""Native source cohort query keeps site selection read-only and source-bound."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from gridlens.persistence.models import (  # noqa: E402
    Evidence,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from scripts.freeze_native_cohort import (  # noqa: E402
    _read_native_candidates,
    select_frozen_candidates,
)

pytest_plugins = ["test_saved_browse"]


def test_read_only_freezer_selects_only_source_cited_native_project(saved_db):
    source_id = "native-cohort-fixture"
    project_id, need_id, observation_id, evidence_id = (uuid4() for _ in range(4))
    with saved_db.begin() as session:
        session.add(
            Source(
                id=source_id,
                publisher="Fixture municipal publisher",
                endpoint="https://public.example.gov/permits",
                family="municipal-permits",
                geography="Texas",
                industries=["data centers"],
                retrieval_method="municipal-api",
                health={},
            )
        )
        session.flush()
        session.add(
            Project(
                id=project_id,
                identity_key=f"native-cohort-{project_id}",
                name="Published compute campus",
                location="Dallas, TX",
                source_id=source_id,
                external_id="permit-123",
                asset_type="data_center",
            )
        )
        session.add(
            Observation(
                id=observation_id,
                source_id=source_id,
                external_id="permit-123",
                title="Compute campus permit",
                abstract="Official permit record for a compute campus in Dallas, Texas.",
                url="https://public.example.gov/permits/123",
                content_hash="a" * 64,
            )
        )
        session.flush()
        session.add(
            Evidence(
                id=evidence_id,
                observation_id=observation_id,
                content_hash="b" * 64,
                title="Compute campus permit",
                abstract="Official permit record for a compute campus in Dallas, Texas.",
                url="https://public.example.gov/permits/123",
                extraction_location="record detail",
                provenance={},
            )
        )
        session.add(
            PowerNeed(
                id=need_id,
                project_id=project_id,
                activity_key="temporary-power",
                tier="Signal",
                rationale="Load and dates remain unknown.",
                admission_basis={"evidence_hash": "b" * 64},
                supply="Unknown",
                active=True,
            )
        )
        session.flush()
        session.add(NeedObservation(need_id=need_id, observation_id=observation_id))

    with saved_db() as session:
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        session.execute(text("SET TRANSACTION READ ONLY"))
        candidates, counts = _read_native_candidates(session)
        selected = select_frozen_candidates(candidates, limit=25)
        assert counts == {
            "eligible_territory_projects": 1,
            "cited_project_candidates": 1,
        }
        assert len(selected) == 1
        candidate = selected[0]
        assert candidate["project_id"] == str(project_id)
        assert candidate["source_evidence"][0]["url"] == "https://public.example.gov/permits/123"
        assert candidate["source_evidence"][0]["observation_hash"] == "a" * 64
        assert candidate["source_evidence"][0]["evidence_hash"] == "b" * 64
        assert candidate["baseline_status"]["power_floor_300kw"] == (
            "UNKNOWN_OR_UNSUPPORTED_NEED_POWER_BASIS"
        )
        assert candidate["baseline_status"]["temporary_power_activity"] == (
            "UNKNOWN_OR_UNSUPPORTED_ACTIVITY"
        )
        assert session.scalar(select(func.count()).select_from(Project)) == 1
