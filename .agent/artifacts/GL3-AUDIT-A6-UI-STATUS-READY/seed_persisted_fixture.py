"""Append one wholly synthetic, source-backed exact-Need fixture to an approved disposable UI database.

Run only under a guarded provider-off wrapper. This script refuses all databases except
explicitly named builder/root persisted-test targets on loopback port 55437.
"""
import hashlib
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import make_url

from gridlens.settings import settings

allowed_databases = {
    "gl3audit_a6_ui_builder_migration",
    "gl3audit_a6_ui_root_persisted_test",
}
expected_database = os.environ.get("A6_UI_FIXTURE_DATABASE_NAME")
url = make_url(settings.database_url)
if (
    expected_database not in allowed_databases
    or url.database != expected_database
    or url.host not in {"127.0.0.1", "localhost"}
    or url.port != 55437
    or url.username != "gl3audit"
):
    raise RuntimeError("Refusing fixture seed outside an explicitly approved disposable UI database")
receipt_value = os.environ.get("A6_UI_FIXTURE_RECEIPT")
if not receipt_value:
    raise RuntimeError("A6_UI_FIXTURE_RECEIPT must name a new receipt path")
receipt_path = Path(receipt_value).resolve()
if receipt_path.exists():
    raise RuntimeError("Refusing to overwrite an existing fixture receipt")

from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (
    Evidence,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)

source_id = f"a6-ui-sourcebacked-{uuid4()}"
fixture_key = f"a6-ui-permit-{uuid4()}"
with SessionLocal.begin() as session:
    source = Source(
        id=source_id,
        publisher="Synthetic UI Test",
        endpoint="https://example.test/ui",
        family="construction-permits",
        geography="Test City",
        industries=["construction"],
        retrieval_method="socrata-permits",
        health={},
    )
    session.add(source)
    session.flush()
    project = Project(
        identity_key=fixture_key,
        name=f"Synthetic UI Facility {fixture_key[-8:]}",
        location="Test City",
        source_id=source_id,
        external_id=fixture_key,
        asset_type="construction",
    )
    session.add(project)
    session.flush()
    need = PowerNeed(
        project_id=project.id,
        activity_key="construction",
        tier="Signal",
        rationale="Synthetic current support unavailable; persisted UI workflow fixture.",
        supply="Unknown",
        active=True,
    )
    session.add(need)
    session.flush()
    content_hash = hashlib.sha256(fixture_key.encode("utf-8")).hexdigest()
    title = f"Synthetic construction permit for {project.name}"
    abstract = (
        f"Current permit filing for {project.name} in Test City. "
        "No verified power supply or qualified Lead claim."
    )
    evidence_url = f"https://example.test/synthetic-permit/{fixture_key}"
    observation = Observation(
        source_id=source_id,
        external_id=fixture_key,
        title=title,
        abstract=abstract,
        published_at=date(2026, 10, 8),
        url=evidence_url,
        content_hash=content_hash,
    )
    session.add(observation)
    session.flush()
    evidence = Evidence(
        observation_id=observation.id,
        content_hash=content_hash,
        title=title,
        abstract=abstract,
        url=evidence_url,
        published_at=observation.published_at,
        observed_at=datetime.now(UTC),
        extraction_location="title and abstract",
    )
    session.add(evidence)
    session.flush()
    assessment = {
        "decision": "accepted",
        "semantic_hash": content_hash,
        "evidence_hash": content_hash,
        "project_identity_key": project.identity_key,
        "power_activity": "construction",
        "tier": "Signal",
        "reason": "Synthetic current permit context; no verified power supply or Lead claim.",
        "subject": project.name,
        "location": project.location,
        "evidence": {"id": str(evidence.id), "url": evidence_url},
    }
    session.add(
        Interpretation(
            observation_id=observation.id,
            content_hash=content_hash,
            status="accepted",
            assessment=assessment,
        )
    )
    session.add(NeedObservation(need_id=need.id, observation_id=observation.id))
    receipt = {
        "need_id": str(need.id),
        "project_id": str(project.id),
        "name": project.name,
        "evidence_id": str(evidence.id),
        "content_hash": content_hash,
        "source_id": source_id,
        "fixture_only": True,
    }
receipt_path.parent.mkdir(parents=True, exist_ok=True)
receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
print(json.dumps(receipt, sort_keys=True))
