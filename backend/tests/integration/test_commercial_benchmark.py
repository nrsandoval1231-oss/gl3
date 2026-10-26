"""Benchmark selection must match a usable snapshot and distinct physical projects."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from gridlens.intelligence.saved_browse import current_generation, rebuild
from gridlens.persistence.models import BrowseGeneration, BrowseRow

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.benchmark_intelligence import benchmark, select_projects  # noqa: E402

pytest_plugins = ["test_saved_browse"]


def test_benchmark_limits_distinct_projects_not_need_rows(saved_db):
    from test_saved_browse import seed

    seed(saved_db, count=30, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db.begin() as session:
        generation = current_generation(session)
        row = session.scalar(select(BrowseRow).where(BrowseRow.generation_id == generation.id))
        # Model a published multi-activity project: many need rows share its site.
        values = {column.name: getattr(row, column.name) for column in BrowseRow.__table__.columns}
        row.rank_score = 100
        for _ in range(30):
            session.add(BrowseRow(**{**values, "need_id": uuid4(), "rank_score": 100}))
    with saved_db() as session:
        projects, _, status = select_projects(session, limit=25)
        assert status == "CURRENT"
        assert len(projects) == len({project.id for project in projects}) == 25


def test_benchmark_ignores_newer_unpublished_generation(saved_db):
    from test_saved_browse import seed

    seed(saved_db, count=3, histories=1)
    assert rebuild(saved_db)["status"] == "published"
    with saved_db.begin() as session:
        current = current_generation(session)
        current_id = current.id
        values = {
            column.name: getattr(current, column.name)
            for column in BrowseGeneration.__table__.columns
        }
        session.add(
            BrowseGeneration(
                **{
                    **values,
                    "id": uuid4(),
                    "built_at": datetime.now(UTC) + timedelta(days=1),
                    "row_count": 0,
                }
            )
        )
    with saved_db() as session:
        result = benchmark(session, limit=25, dataset_kind="synthetic", source_reference="test")
        assert result["generation_id"] == str(current_id)
        assert result["projects_measured"] == 3
        assert result["cohort_complete"] is False
        assert result["commercial_acceptance"] == "NOT_TESTED"
        assert result["dataset_kind"] == "synthetic"
        assert result["company_match_accuracy"].startswith("UNKNOWN")
        assert result["api_performance"].startswith("NOT_TESTED")


def test_benchmark_reports_unavailable_snapshot_without_claiming_empty_market(saved_db):
    from test_saved_browse import seed

    seed(saved_db, count=3, histories=1)
    with saved_db() as session:
        result = benchmark(session, source_reference="synthetic test", dataset_kind="synthetic")
        assert result["selection_status"] == "QUALIFICATION_PENDING"
        assert result["projects_measured"] == 0
        assert result["cohort_complete"] is False
        assert result["commercial_acceptance"] == "NOT_TESTED"
