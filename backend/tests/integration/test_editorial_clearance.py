"""Disposable DB only. Historical source text with explicit synthetic test dates."""

import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.editorial_clearance import approved_feed, decide, queue
from gridlens.persistence.database import Base
from gridlens.persistence.models import EditorialDecision, Evidence, Observation, Source
from gridlens.settings import settings


def test_durable_clearance_rejection_and_version_revocation():
    engine = create_engine(settings.test_database_url)
    assert engine.url.database.endswith("_test")
    assert engine.url.database != create_engine(settings.database_url).url.database
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    review, (_, ev, src) = runpy.run_path(
        str(Path(__file__).parents[1] / "unit/test_editorial.py")
    )["example"]()
    observation_id, evidence_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    try:
        with factory.begin() as s:
            s.add(
                Source(
                    id=src.id,
                    publisher=src.publisher,
                    endpoint="https://taylortx.gov/",
                    family=src.family,
                    geography="United States",
                    industries=["infrastructure"],
                    retrieval_method="test",
                )
            )
            s.flush()
            s.add(
                Observation(
                    id=observation_id,
                    source_id=src.id,
                    external_id="synthetic-date-test",
                    title=ev.title,
                    url=ev.url,
                    content_hash=ev.content_hash,
                    published_at=now.date(),
                    first_seen_at=now,
                )
            )
            s.flush()
            s.add(
                Evidence(
                    id=evidence_id,
                    observation_id=observation_id,
                    title=ev.title,
                    abstract=ev.abstract,
                    url=ev.url,
                    content_hash=ev.content_hash,
                    published_at=now.date(),
                    observed_at=now,
                )
            )
        with factory.begin() as s:
            # Historical review volume must not hide a newly approved development.
            for number in range(205):
                old_id = uuid4()
                s.add(
                    Observation(
                        id=old_id,
                        source_id=src.id,
                        external_id=f"old-test-{number}",
                        title="Synthetic old review",
                        url=ev.url,
                        content_hash="c" * 64,
                        published_at=now.date() - timedelta(days=90),
                        first_seen_at=now - timedelta(days=90),
                    )
                )
                s.flush()
                old_evidence = Evidence(
                    observation_id=old_id,
                    title="Synthetic old review",
                    url=ev.url,
                    content_hash="c" * 64,
                    published_at=now.date() - timedelta(days=90),
                    observed_at=now - timedelta(days=90),
                )
                s.add(old_evidence)
                s.flush()
                s.add(
                    EditorialDecision(
                        observation_id=old_id,
                        evidence_id=old_evidence.id,
                        evidence_hash="c" * 64,
                        status="rejected",
                        reviewer="session:test",
                    )
                )
        with factory.begin() as s:
            assert queue(s)[0]["clearance"] == "pending"
            with pytest.raises(ValueError, match="evidence_changed"):
                decide(s, observation_id, "b" * 64, "approved", review, "session:test")
            result = decide(s, observation_id, ev.content_hash, "approved", review, "session:test")
            assert result["status"] == "approved"
            # All share transaction-start time: ordering must use insertion sequence.
            for _ in range(4):
                decide(s, observation_id, ev.content_hash, "rejected", None, "session:test")
                assert approved_feed(s)["feed"]["items"] == []
                decide(s, observation_id, ev.content_hash, "approved", review, "session:test")
        with factory.begin() as s:
            synced = approved_feed(s)
            assert len(synced["feed"]["items"]) == 1
            assert (
                synced["clearances"]["gridlens:" + str(observation_id)]["evidenceVersion"]
                == ev.content_hash
            )
            assert queue(s)[0]["reviewer"] == "session:test"
            decide(s, observation_id, ev.content_hash, "needs-evidence", None, "session:test")
        with factory.begin() as s:
            assert approved_feed(s)["feed"]["items"] == []
            decide(s, observation_id, ev.content_hash, "approved", review, "session:test")
        with factory.begin() as s:
            s.add(
                Evidence(
                    observation_id=observation_id,
                    title=ev.title,
                    abstract=ev.abstract,
                    url=ev.url,
                    content_hash="b" * 64,
                    published_at=now.date(),
                    observed_at=now + timedelta(seconds=1),
                )
            )
        with factory() as s:
            assert approved_feed(s)["feed"]["items"] == []
            assert queue(s)[0]["clearance"] == "evidence-changed"
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
