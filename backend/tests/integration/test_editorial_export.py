"""Isolated DB projection test; business text comes from retained Taylor fixture."""

import json
import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.editorial import export_editorial
from gridlens.persistence.database import Base
from gridlens.persistence.models import Evidence, Observation, Source
from gridlens.settings import settings


def test_export_revokes_clearance_after_a_new_evidence_version(tmp_path, monkeypatch):
    engine = create_engine(settings.test_database_url)
    assert engine.url.database.endswith("_test")
    assert engine.url.database != create_engine(settings.database_url).url.database
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    example = runpy.run_path(str(Path(__file__).parents[1] / "unit/test_editorial.py"))["example"]
    review, (obs, ev, src) = example()
    observation_id, evidence_id = uuid4(), uuid4()
    review["evidenceId"] = str(evidence_id)
    path = tmp_path / "reviews.json"
    path.write_text(
        json.dumps({"version": "2g-editorial-review/1", "reviews": [review], "recentIds": []})
    )
    from gridlens.domain.editorial import evaluate_feed

    monkeypatch.setattr(
        "gridlens.intelligence.editorial.evaluate_feed",
        lambda *args, **kw: evaluate_feed(*args, now=datetime(2026, 8, 20).date(), **kw),
    )
    factory = sessionmaker(engine)
    try:
        with factory.begin() as session:
            session.add(
                Source(
                    id=src.id,
                    publisher=src.publisher,
                    endpoint="https://taylortx.gov/",
                    family=src.family,
                    geography="United States",
                    industries=[],
                    retrieval_method="test",
                )
            )
            session.flush()
            session.add(
                Observation(
                    id=observation_id,
                    source_id=src.id,
                    external_id="real-fixture",
                    title=ev.title,
                    url=ev.url,
                    content_hash=ev.content_hash,
                    published_at=ev.published_at,
                    first_seen_at=obs.first_seen_at,
                )
            )
            session.flush()
            session.add(
                Evidence(
                    id=evidence_id,
                    observation_id=observation_id,
                    content_hash=ev.content_hash,
                    title=ev.title,
                    abstract=ev.abstract,
                    url=ev.url,
                    published_at=ev.published_at,
                    observed_at=datetime(2026, 8, 15, tzinfo=UTC),
                )
            )
        with factory() as session:
            assert len(export_editorial(session, path)["items"]) == 1
            assert not session.new and not session.dirty and not session.deleted
        with factory.begin() as session:
            session.add(
                Evidence(
                    observation_id=observation_id,
                    content_hash="b" * 64,
                    title=ev.title,
                    abstract=ev.abstract,
                    url=ev.url,
                    published_at=ev.published_at,
                    observed_at=datetime(2026, 8, 15, tzinfo=UTC) + timedelta(hours=1),
                )
            )
        with factory() as session:
            assert export_editorial(session, path)["items"] == []
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
