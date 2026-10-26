"""Regional evidence retention and retry scheduling on a disposable DB."""

import hashlib
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from sqlalchemy import func, select

from gridlens.ingestion.service import process_records
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    Job,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    ProjectMatchDecision,
    Source,
)

pytest_plugins = ["test_saved_browse"]


def _permit(external_id: str, *, city: str, state: str, address: str) -> dict:
    title = f"Synthetic construction permit {external_id}"
    abstract = f"Construction of a new data center at {address}, {city}, {state}."
    return {
        "document_number": external_id,
        "title": title,
        "abstract": abstract,
        "publication_date": "2026-10-20",
        "event_date": "2026-10-20",
        "html_url": f"https://example.test/permit/{external_id}",
        "permit": {
            "row_id": external_id,
            "description": "Construction of a new data center.",
            "status": "Active",
            "address": address,
            "city": city,
            "state": state,
            "project": f"{external_id} data center",
            "source_fields": {},
        },
    }


def test_regional_permit_evidence_and_need_links_replay_without_duplicates(saved_db):
    from gridlens.ingestion.registry import load_registry

    definition = next(row for row in load_registry() if row["id"] == "austin-building-permits")
    source_id = definition["id"]
    rows = [
        _permit("TX-CROSSBORDER-1", city="Austin", state="TX", address="100 Main Street"),
        _permit("OUTREGION-1", city="San Jose", state="CA", address="200 Market Street"),
    ]
    rows[0]["permit"]["project"] = "Atlas Mesa data center"
    with saved_db.begin() as session:
        session.add(
            Source(
                id=source_id,
                publisher=definition["publisher"],
                endpoint=definition["endpoint"],
                family=definition["family"],
                geography="Austin, TX",
                industries=["data centers"],
                retrieval_method=definition["retrieval_method"],
                cadence_hours=definition["cadence_hours"],
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=source_id,
            status="running",
            lease_owner="regional-evidence-test",
            fence=1,
            lease_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    def run_once():
        with saved_db() as session:
            return process_records(
                session,
                job_id,
                "regional-evidence-test",
                1,
                definition,
                rows,
            )

    first = run_once()
    assert first["new"] == 2
    assert first["regional_excluded"] == 1
    with saved_db() as session:
        tx_project = session.scalar(
            select(Project).where(Project.external_id == "TX-CROSSBORDER-1")
        )
        ca_project = session.scalar(select(Project).where(Project.external_id == "OUTREGION-1"))
        assert tx_project is not None and tx_project.region_status == "ELIGIBLE"
        assert ca_project is not None and ca_project.region_status == "EXCLUDED"
        tx_need = session.scalar(
            select(PowerNeed).where(
                PowerNeed.project_id == tx_project.id, PowerNeed.active.is_(True)
            )
        )
        assert tx_need is not None
        assert (
            session.scalar(
                select(func.count())
                .select_from(NeedObservation)
                .join(Observation, Observation.id == NeedObservation.observation_id)
                .where(
                    NeedObservation.need_id == tx_need.id,
                    Observation.external_id == "TX-CROSSBORDER-1",
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(Evidence)
                .join(Observation, Observation.id == Evidence.observation_id)
                .where(Observation.external_id == "TX-CROSSBORDER-1")
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(PowerNeed)
                .where(PowerNeed.project_id == ca_project.id, PowerNeed.active.is_(True))
            )
            == 0
        )

    replay = run_once()
    assert replay["unchanged"] == 2
    with saved_db() as session:
        assert session.scalar(select(func.count()).select_from(Observation)) == 2
        assert session.scalar(select(func.count()).select_from(Evidence)) == 2
        assert session.scalar(select(func.count()).select_from(NeedObservation)) == 1
        assert (
            session.scalar(
                select(func.count()).select_from(PowerNeed).where(PowerNeed.active.is_(True))
            )
            == 1
        )

    from gridlens.ingestion.registry import load_registry
    from gridlens.ingestion.service import assess_retained_news

    news_sources = {
        item["id"]: item
        for item in load_registry()
        if item["id"] in {"dcd-news", "utility-dive-news"}
    }

    def add_news(session, source_id: str, external_id: str, title: str, abstract: str):
        definition = news_sources[source_id]
        if session.get(Source, source_id) is None:
            session.add(
                Source(
                    id=source_id,
                    publisher=definition["publisher"],
                    endpoint=definition["endpoint"],
                    family=definition["family"],
                    geography=definition["geography"],
                    industries=definition["industries"],
                    retrieval_method=definition["retrieval_method"],
                    cadence_hours=definition["cadence_hours"],
                    health={},
                )
            )
            session.flush()
        url = f"https://{source_id}.example/news/{external_id}"
        digest = hashlib.sha256(f"{title}|{abstract}".encode()).hexdigest()
        observation = Observation(
            source_id=source_id,
            external_id=external_id,
            title=title,
            abstract=abstract,
            published_at=date(2026, 10, 20),
            url=url,
            content_hash=digest,
        )
        session.add(observation)
        session.flush()
        evidence = Evidence(
            observation_id=observation.id,
            content_hash=digest,
            title=title,
            abstract=abstract,
            url=url,
            published_at=date(2026, 10, 20),
            extraction_location="RSS item title and description/summary",
        )
        session.add(evidence)
        session.flush()
        assert assess_retained_news(session, observation, evidence)
        return observation, evidence

    with saved_db.begin() as session:
        national_tx_observation, national_tx_evidence = add_news(
            session,
            "dcd-news",
            "national-tx-article",
            "Atlas begins construction at Atlas Mesa data center in Austin, Texas",
            "Atlas Mesa data center construction is underway. "
            "Site address: 100 Main Street, Austin, TX.",
        )
        crossborder_observation, crossborder_evidence = add_news(
            session,
            "utility-dive-news",
            "crossborder-ca-article",
            "Atlas begins construction at Atlas Mesa data center in San Jose, California",
            "Atlas Mesa data center construction is underway. "
            "Site address: 200 Market Street, San Jose, CA.",
        )
    with saved_db() as session:
        tx_project = session.scalar(
            select(Project).where(Project.external_id == "TX-CROSSBORDER-1")
        )
        assert tx_project is not None
        tx_need = session.scalar(
            select(PowerNeed).where(
                PowerNeed.project_id == tx_project.id, PowerNeed.active.is_(True)
            )
        )
        assert tx_need is not None
        match = session.scalar(
            select(ProjectMatchDecision).where(
                ProjectMatchDecision.observation_id == national_tx_observation.id,
                ProjectMatchDecision.candidate_project_id == tx_project.id,
            )
        )
        assert match is not None and match.decision == "matched"
        assert (
            session.scalar(
                select(func.count())
                .select_from(Evidence)
                .where(Evidence.observation_id == national_tx_observation.id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(NeedObservation)
                .where(
                    NeedObservation.need_id == tx_need.id,
                    NeedObservation.observation_id == national_tx_observation.id,
                )
            )
            == 1
        )
        crossborder_interpretation = session.scalar(
            select(Interpretation).where(
                Interpretation.observation_id == crossborder_observation.id
            )
        )
        assert crossborder_interpretation is not None
        assert crossborder_interpretation.assessment["regional_scope"]["status"] == "EXCLUDED"
        ca_project = session.scalar(
            select(Project).where(
                Project.identity_key
                == crossborder_interpretation.assessment["project_identity_key"]
            )
        )
        assert ca_project is not None and ca_project.region_status == "EXCLUDED"
        assert crossborder_evidence.observation_id == crossborder_observation.id
        assert (
            session.scalar(
                select(func.count())
                .select_from(PowerNeed)
                .where(PowerNeed.project_id == ca_project.id, PowerNeed.active.is_(True))
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(NeedObservation)
                .where(NeedObservation.observation_id == crossborder_observation.id)
            )
            == 0
        )


def test_active_api_projection_requires_persisted_in_region_site(saved_db):
    from test_saved_browse import seed

    from gridlens.api import app as api

    need_ids = seed(saved_db, count=8, histories=1)
    locations = (
        "Austin, TX",
        "Tulsa, OK",
        "Albuquerque, NM",
        "San Jose, CA",
        "Atlanta, GA",
        None,
        "Austin, TX / Tulsa, OK",
        "Dallas, TX",
    )
    with saved_db.begin() as session:
        for need_id, location in zip(need_ids, locations, strict=True):
            need = session.get(PowerNeed, need_id)
            project = session.get(Project, need.project_id)
            project.location = location
            if location == "Dallas, TX":
                project.identity_facts = {**project.identity_facts, "headquarters": "Atlanta, GA"}

    visible = api.opportunities(tier="Signal", limit=50, offset=0, cohort=None)
    assert {item["id"] for item in visible} == set(need_ids[:3] + [need_ids[7]])


def _retry_error(retry_after: str) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test/records")
    response = httpx.Response(429, request=request, headers={"Retry-After": retry_after})
    return httpx.HTTPStatusError("rate limited", request=request, response=response)


@pytest.mark.parametrize("retry_kind", ["numeric", "date", "oversized", "unrepresentable"])
def test_worker_respects_retry_after_and_does_not_lease_early_or_duplicate(
    saved_db, monkeypatch, retry_kind
):
    from gridlens.jobs import worker

    source_id = f"retry-proof-{retry_kind}"
    definition = {
        "id": source_id,
        "publisher": "Synthetic",
        "endpoint": "https://example.test/records",
        "family": "synthetic",
        "geography": "US",
        "industries": [],
        "retrieval_method": "json-api",
        "cadence_hours": 24,
        "enabled": True,
    }
    retry_at = datetime.now(UTC) + timedelta(minutes=2)
    retry_value = {
        "numeric": "120",
        "date": format_datetime(retry_at, usegmt=True),
        "oversized": "604801",
        "unrepresentable": "9" * 128,
    }[retry_kind]
    failure = _retry_error(retry_value)
    with saved_db.begin() as session:
        session.add(
            Source(
                id=source_id,
                publisher="Synthetic",
                endpoint=definition["endpoint"],
                family="synthetic",
                geography="US",
                industries=[],
                retrieval_method="json-api",
                enabled=True,
                registry_enabled=True,
                health={},
            )
        )
        session.flush()
        job = Job(
            source_id=source_id,
            status="queued",
            available_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add(job)
        session.flush()
        job_id = job.id

    class Admitted:
        def __enter__(self):
            return True

        def __exit__(self, *_args):
            return False

    class NoopRenewer:
        def __init__(self, *_args):
            pass

        def start(self):
            return self

        def stop(self):
            pass

    def fail_processing(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(worker, "SessionLocal", saved_db)
    monkeypatch.setattr(worker, "WORKER_ID", "regional-retry-test")
    monkeypatch.setattr(worker, "load_registry", lambda: [definition])
    monkeypatch.setattr(worker, "_park_if_disabled", lambda *_args: False)
    monkeypatch.setattr(worker, "try_public_acquisition_admission", lambda *_args: Admitted())
    monkeypatch.setattr(worker, "FencedLeaseRenewer", NoopRenewer)
    monkeypatch.setattr(worker, "process_job", fail_processing)

    assert worker.run_one({source_id: definition}, job_ids=[job_id])
    with saved_db() as session:
        scheduled = session.get(Job, job_id)
        assert scheduled is not None
        source_jobs = list(session.scalars(select(Job).where(Job.source_id == source_id)))
        assert len(source_jobs) == 1
        assert scheduled.status == ("failed" if retry_kind == "unrepresentable" else "queued")
        if retry_kind == "numeric":
            assert scheduled.available_at >= datetime.now(UTC) + timedelta(seconds=118)
        elif retry_kind == "oversized":
            assert scheduled.available_at >= datetime.now(UTC) + timedelta(seconds=604799)
        elif retry_kind == "unrepresentable":
            assert scheduled.status == "failed"
            source = session.get(Source, source_id)
            assert source and source.health["retry_state"] == "retry_after_unrepresentable"
        else:
            # The HTTP-date header has one-second resolution. The scheduled
            # instant still has to fall on or after that second.
            assert scheduled.available_at >= retry_at.replace(microsecond=0)

    with saved_db.begin() as session:
        scheduled = session.get(Job, job_id)
        assert scheduled is not None
        scheduled.available_at = datetime.now(UTC) - timedelta(minutes=1)
    assert worker.run_one({source_id: definition}, job_ids=[job_id]) is False
    from gridlens.jobs.queue import enqueue, lease_one

    with saved_db() as session:
        assert (
            session.scalar(select(func.count()).select_from(Job).where(Job.source_id == source_id))
            == 1
        )
    with saved_db.begin() as session:
        prior = session.get(Job, job_id)
        assert prior is not None
        prior.status = "failed"
        new_job_id = enqueue(session, source_id)
        created = session.get(Job, new_job_id)
        assert created is not None
        if retry_kind == "unrepresentable":
            assert created.available_at.year == 9999
        elif retry_kind == "oversized":
            assert created.available_at >= datetime.now(UTC) + timedelta(seconds=604799)
        elif retry_kind == "date":
            assert created.available_at >= retry_at.replace(microsecond=0)
        else:
            assert created.available_at >= retry_at
    with saved_db.begin() as session:
        assert lease_one(session, "new-national-job-test") is None


@pytest.mark.parametrize(
    ("health", "should_lease"),
    [
        ({}, True),
        ({"retry_state": "scheduled", "retry_at": "2099-10-22T12:00:20.500-05:00"}, False),
        ({"retry_state": "scheduled", "retry_at": "not-a-timestamp"}, False),
        ({"retry_state": "scheduled"}, False),
        ({"retry_state": "operator_review"}, False),
        ({"retry_state": "terminal"}, True),
        ({"retry_state": "retry_after_unrepresentable"}, False),
        ({"retry_state": "scheduled", "retry_at": "2000-10-22T12:00:20.500-05:00"}, True),
    ],
)
def test_source_retry_window_is_source_wide_and_legacy_safe(saved_db, health, should_lease):
    from gridlens.jobs.queue import enqueue, lease_one

    source_id = f"retry-window-{hashlib.sha256(repr(health).encode()).hexdigest()[:8]}"
    with saved_db.begin() as session:
        session.add(
            Source(
                id=source_id,
                publisher="Synthetic",
                endpoint="https://example.test/records",
                family="synthetic",
                geography="US",
                industries=[],
                retrieval_method="json-api",
                enabled=True,
                registry_enabled=True,
                health=health,
            )
        )
        session.flush()
        enqueue(session, source_id)
        job = Job(
            source_id=source_id,
            status="queued",
            available_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        session.add(job)
        session.flush()
        assert job.available_at < datetime.now(UTC)
    with saved_db.begin() as session:
        result = lease_one(session, "legacy-safe-test")
        assert (result is not None) is should_lease
