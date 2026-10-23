"""Prove Austin's current structured lanes fit the unchanged chain allowance."""

import json
import re
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion.registry import load_registry
from gridlens.ingestion.service import process_job
from gridlens.persistence.database import Base
from gridlens.persistence.models import Job, Source, SourceCollectionProgress
from gridlens.settings import settings


def _austin_row(row_id: int, day: str) -> dict[str, str]:
    return {
        "permit_number": f"BP{row_id:05d}",
        "issue_date": f"{day}T12:00:00.000",
        "statusdate": f"{day}T12:30:00.000",
        "description": "Commercial electrical construction",
        "permit_class_mapped": "Commercial",
        "work_class": "Electrical",
        "permit_type_desc": "Electrical Permit",
        "status_current": "Issued",
        "original_address1": "1 Main Street",
        "original_city": "Austin",
        "original_state": "TX",
        "link": "https://data.austintexas.gov/permits/1",
        "project_id": "p-1",
        "total_job_valuation": "10000",
        "total_new_add_sqft": "1000",
    }


def test_austin_recent_ranges_finish_within_eight_jobs_and_history_advances(monkeypatch):
    import gridlens.ingestion.service as service

    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    )
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(
        service,
        "process_records",
        lambda *_args, **_kwargs: {
            "new": 0,
            "changed": 0,
            "unchanged": 0,
            "signals": 0,
            "latest_publication_date": None,
            "parse_failures": 0,
        },
    )
    definition = next(
        source for source in load_registry() if source["id"] == "austin-building-permits"
    )
    today = datetime.now(UTC).date()
    rows = [_austin_row(1, today.isoformat())]
    dense_start = today - timedelta(days=6)
    rows.extend(
        _austin_row(index + 10, (dense_start + timedelta(days=index // 600)).isoformat())
        for index in range(1200)
    )

    with factory.begin() as session:
        session.add(
            Source(
                id=definition["id"],
                publisher=definition["publisher"],
                endpoint=definition["endpoint"],
                family=definition["family"],
                geography=definition["geography"],
                industries=definition["industries"],
                retrieval_method=definition["retrieval_method"],
                cadence_hours=definition["cadence_hours"],
                enabled=True,
                registry_enabled=True,
                health={"status": "Overdue"},
            )
        )

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        where = params["$where"]
        if params.get("$select") == "count(*) AS row_count":
            field = "statusdate" if "statusdate >= " in where else "issue_date"
            match = re.search(rf"{field} >= '(\d{{4}}-\d\d-\d\d)", where)
            upper = re.search(rf"{field} <= '(\d{{4}}-\d\d-\d\d)", where)
            start = datetime.fromisoformat(match.group(1)).date() if match else today
            end = datetime.fromisoformat(upper.group(1)).date() if upper else today
            matched = [
                row
                for row in rows
                if start <= datetime.fromisoformat(row[field].split("T")[0]).date() <= end
                and (field == "statusdate" or row["permit_number"] == "BP00001")
            ]
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=[{"row_count": len(matched)}],
            )
        field = "statusdate" if "statusdate >= " in where else "issue_date"
        match = re.search(rf"{field} >= '(\d{{4}}-\d\d-\d\d)", where)
        upper = re.search(rf"{field} <= '(\d{{4}}-\d\d-\d\d)", where)
        start = datetime.fromisoformat(match.group(1)).date() if match else today
        end = datetime.fromisoformat(upper.group(1)).date() if upper else today
        after = re.search(r"permit_number > '([^']+)'", where)
        matching = [
            row
            for row in rows
            if start <= datetime.fromisoformat(row[field].split("T")[0]).date() <= end
            and (field == "statusdate" or row["permit_number"] == "BP00001")
            and (after is None or row["permit_number"] > after.group(1))
        ]
        matching.sort(key=lambda row: (row[field], row["permit_number"]))
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=matching[:1000],
        )

    try:
        outcomes = []
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            for index in range(8):
                with factory.begin() as session:
                    job = Job(
                        source_id=definition["id"],
                        status="running",
                        lease_owner="austin-range-test",
                        fence=1,
                        lease_until=datetime.now(UTC) + timedelta(minutes=10),
                        checkpoint=json.dumps(
                            {
                                "collection_continuation": True,
                                "collection_jobs_remaining": 8 - index,
                            }
                        ),
                    )
                    session.add(job)
                    session.flush()
                    job_id = job.id
                with factory() as session:
                    outcomes.append(
                        process_job(session, job_id, "austin-range-test", 1, definition, client)
                    )

        with factory() as session:
            progress = session.scalars(
                select(SourceCollectionProgress).where(
                    SourceCollectionProgress.source_id == definition["id"]
                )
            ).all()
        by_lane = {item.lane: item for item in progress}
        assert by_lane["issue_recent"].status == "complete"
        assert by_lane["modified_recent"].status == "complete", [
            (item.lane, item.error_class, item.cursor) for item in progress
        ] + [
            (outcome.get("collection_error_code"), outcome.get("collection_error_stage"))
            for outcome in outcomes
        ]
        assert by_lane["issue_history"].completed_through is not None
        assert by_lane["issue_history"].completed_through.date() > (
            today - timedelta(days=int(definition["query"].get("window_days", 90)))
        )
        assert any(outcome["collection_current_complete"] for outcome in outcomes)
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
