"""Regression coverage for the populated standalone-admission backfill."""

import importlib.util
import json
import uuid
from datetime import date
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from gridlens.persistence import models as _models  # noqa: F401
from gridlens.persistence.database import Base
from gridlens.settings import settings


@pytest.fixture
def migration_engine():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and target.database.endswith("_test")
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    ), "Refusing to reset application database"
    engine = create_engine(settings.test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_populated_backfill_closes_news_but_preserves_permit_and_history(migration_engine):
    migration_path = (
        Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0009_signal_admission.py"
    )
    spec = importlib.util.spec_from_file_location("gl3_018_signal_admission", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    with migration_engine.begin() as connection:
        connection.execute(text("ALTER TABLE power_needs DROP COLUMN admission_basis"))
        legacy_rows = []
        for source_id, family, method, digest in (
            (
                "migration-permit-source",
                "construction-permits",
                "socrata-permits",
                "a" * 64,
            ),
            ("migration-news-source", "news", "publisher-rss", "b" * 64),
        ):
            project_id, observation_id, need_id, evidence_id = (str(uuid.uuid4()) for _ in range(4))
            project_key = f"{source_id}:atlas"
            url = f"https://authority.example/{source_id}/record"
            title = "Atlas project data center permit"
            abstract = "Atlas project at Denver, CO; an official dated project record."
            assessment = {
                "decision": "accepted",
                "tier": "Signal",
                "subject": "Atlas",
                "location": "Denver, CO",
                "reason": "Historical assessment retained by the backfill.",
                "power_activity": "facility-expansion",
                "activity_key": "facility-expansion",
                "project_identity_key": project_key,
                "semantic_hash": digest,
                "evidence_hash": digest,
            }
            connection.execute(
                text(
                    "INSERT INTO sources "
                    "(id,publisher,endpoint,family,geography,industries,retrieval_method,"
                    "cadence_hours,enabled,health) VALUES "
                    "(:id,'Migration test',:endpoint,:family,'US','[\"data centers\"]',"
                    ":method,24,true,'{}'::jsonb)"
                ),
                {
                    "id": source_id,
                    "endpoint": f"https://authority.example/{source_id}",
                    "family": family,
                    "method": method,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id,identity_key,name,location,source_id,external_id,asset_type,"
                    "identity_facts) "
                    "VALUES (:id,:identity,'Atlas project','Denver, CO',:source,:external,"
                    "'data_center','{}'::jsonb)"
                ),
                {
                    "id": project_id,
                    "identity": project_key,
                    "source": source_id,
                    "external": source_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO observations "
                    "(id,source_id,external_id,title,abstract,published_at,url,content_hash) "
                    "VALUES (:id,:source,:external,:title,:abstract,:published,:url,:hash)"
                ),
                {
                    "id": observation_id,
                    "source": source_id,
                    "external": source_id,
                    "title": title,
                    "abstract": abstract,
                    "published": date(2026, 9, 20),
                    "url": url,
                    "hash": digest,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO evidence "
                    "(id,observation_id,content_hash,title,abstract,url,published_at,"
                    "extraction_location) VALUES (:id,:observation,:hash,:title,:abstract,"
                    ":url,:published,'migration regression fixture')"
                ),
                {
                    "id": evidence_id,
                    "observation": observation_id,
                    "hash": digest,
                    "title": title,
                    "abstract": abstract,
                    "url": url,
                    "published": date(2026, 9, 20),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO interpretations "
                    "(observation_id,content_hash,status,attempts,evaluator_version,assessment) "
                    "VALUES (:observation,:hash,'accepted',1,'migration-test',"
                    "CAST(:assessment AS jsonb))"
                ),
                {
                    "observation": observation_id,
                    "hash": digest,
                    "assessment": json.dumps(assessment),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO power_needs "
                    "(id,project_id,activity_key,tier,rationale,required_mw,supply,active) "
                    "VALUES (:id,:project,'facility-expansion','Signal',"
                    "'Historical rationale',NULL,'Unknown',true)"
                ),
                {"id": need_id, "project": project_id},
            )
            connection.execute(
                text(
                    "INSERT INTO need_observations (need_id,observation_id) "
                    "VALUES (:need,:observation)"
                ),
                {"need": need_id, "observation": observation_id},
            )
            legacy_rows.append((source_id, need_id, observation_id))

        assert "admission_basis" not in {
            column["name"] for column in inspect(connection).get_columns("power_needs")
        }
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        needs = (
            connection.execute(
                text(
                    "SELECT need.id, need.active, need.tier, need.admission_basis, "
                    "source.id AS source_id "
                    "FROM power_needs AS need "
                    "JOIN projects AS project ON project.id=need.project_id "
                    "JOIN sources AS source ON source.id=project.source_id"
                )
            )
            .mappings()
            .all()
        )
        by_source = {row["source_id"]: row for row in needs}
        permit = by_source["migration-permit-source"]
        news = by_source["migration-news-source"]
        assert permit["active"] is True and permit["tier"] == "Signal"
        assert permit["admission_basis"]["origin"] == "Official permit"
        assert news["active"] is False and news["tier"] == "Signal"
        assert news["admission_basis"]["prior_active"] is True
        assert news["admission_basis"]["prior_tier"] == "Signal"
        assert news["admission_basis"]["origin"] == "Research context"
        assert news["admission_basis"]["reason"]
        assert connection.scalar(text("SELECT count(*) FROM evidence")) == 2
        assert connection.scalar(text("SELECT count(*) FROM need_observations")) == 2
        assert connection.scalar(text("SELECT count(*) FROM observations")) == 2
