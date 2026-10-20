"""Inspect the three proposed public intents in an isolated restored database.

This script never queues work, reserves funds, or invokes a provider. Run only in
the network-none test container with the existing restored rehearsal database.
"""
import hashlib
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select, text

from gridlens.intelligence import intelligence_jobs as policy
from gridlens.intelligence.signal_adjudication import _evidence_state, jev_request_payload
from gridlens.intelligence.titles import (
    _activity_options, _role_options, digest, title_input, title_request_payload, validate_title,
)
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import (
    Evidence, Interpretation, NeedObservation, Observation, PowerNeed, Project, Source,
)
from gridlens.settings import settings

scope = json.loads(Path(sys.argv[1]).read_text())
activation = json.loads(Path(sys.argv[2]).read_text())
assert scope["status"] == "PROPOSED_NOT_ACTIVATED" and len(scope["records"]) == 3
assert activation["status"] == "PROPOSED_NOT_AUTHORIZED_OR_APPLIED"
for key, value in {**activation["required_unchanged_controls"], **activation["runtime_changes"]}.items():
    name = key.lower()
    original = getattr(settings, name)
    if isinstance(original, bool):
        converted = value == "true"
    elif isinstance(original, Decimal):
        converted = Decimal(value)
    elif isinstance(original, int):
        converted = int(value)
    else:
        converted = value
    setattr(settings, name, converted)
settings.openai_api_key = SecretStr("synthetic-preflight-only")
settings.typesafe_api_key = SecretStr("synthetic-preflight-only")
settings.intelligence_openai_reasoning_max_output_tokens = 700

outputs = []
with SessionLocal() as session:
    session.execute(text("SET TRANSACTION READ ONLY"))
    database = session.scalar(text("SELECT current_database()"))
    assert database == "title02_retained_migration_20261019", "Isolated restored database only"
    for item in scope["records"]:
        observation = session.get(Observation, UUID(item["observation_id"]))
        evidence = session.get(Evidence, UUID(item["evidence_id"]))
        need = session.get(PowerNeed, UUID(item["need_id"]))
        project = session.get(Project, UUID(item["project_id"]))
        source = session.get(Source, item["source_id"])
        assert observation and evidence and need and project and source
        assert source.enabled and source.registry_enabled and need.active
        assert observation.source_id == source.id and evidence.observation_id == observation.id
        assert need.project_id == project.id
        assert observation.content_hash == evidence.content_hash == item["content_hash"]
        assert session.scalar(select(NeedObservation).where(
            NeedObservation.need_id == need.id, NeedObservation.observation_id == observation.id))
        interpretation = session.scalar(select(Interpretation).where(
            Interpretation.observation_id == observation.id))
        assert interpretation and interpretation.status == "accepted"
        assert interpretation.content_hash == item["content_hash"]
        assert interpretation.assessment.get("evidence_hash") == item["content_hash"]

        payload, title_evidence = title_input(session, need.id)
        roles, activities = _role_options(title_evidence), _activity_options(title_evidence)
        assert activities, "Selected record must support a complete source work clause"
        title_request = title_request_payload(payload, title_evidence, roles, activities)
        ledger_payload = {"title": payload, "evidence": title_evidence,
                          "roles": roles, "activities": activities}
        assert policy._enabled("POWER_NEED_TITLE")[0]
        title_reservation = policy._cost_bound("openai", "POWER_NEED_TITLE", ledger_payload)
        assert 0 < title_reservation <= Decimal("0.01")
        example_activity_id = next(iter(activities))
        example, citations = validate_title(
            {"role_option_id": None, "activity_option_id": example_activity_id},
            title_evidence, roles, activities, payload.get("title"))

        state = _evidence_state(session, observation, evidence)
        jev_payload = {"state": state, "model": "jev-1.13.0", "contract": "signal-display-v2",
                       "observation_id": str(observation.id), "evidence_id": str(evidence.id),
                       "evidence_hash": evidence.content_hash}
        enabled = policy._enabled("SIGNAL_ADJUDICATION", payload=jev_payload)
        assert enabled[0], enabled[3]
        jev_request = jev_request_payload(state, model="jev-1.13.0")
        jev_reservation = policy._cost_bound("typesafe", "SIGNAL_ADJUDICATION", jev_payload)
        assert jev_reservation == Decimal("0.01")
        outputs.append({"need_id": str(need.id), "observation_id": str(observation.id),
                        "evidence_id": str(evidence.id), "evidence_hash": evidence.content_hash,
                        "title_input_fingerprint": digest(payload),
                        "title_request_sha256": digest(title_request),
                        "title_request_bytes": policy._serialized_request_bytes(title_request),
                        "title_reservation_usd": str(title_reservation),
                        "role_option_count": len(roles), "activity_option_count": len(activities),
                        "source_rendered_example_not_llm": example["title"],
                        "example_citation_count": len(citations),
                        "jev_request_sha256": digest(jev_request),
                        "jev_request_bytes": policy._serialized_request_bytes(jev_request),
                        "jev_reservation_usd": str(jev_reservation), "cost_basis": "ESTIMATE"})
print(json.dumps({"checked_at": datetime.now(UTC).isoformat(), "read_only": True,
                  "database": database, "production_database_access": False,
                  "provider_calls": 0, "job_writes": 0, "reservations": 0,
                  "scope_sha256": hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest(),
                  "activation_sha256": hashlib.sha256(Path(sys.argv[2]).read_bytes()).hexdigest(),
                  "records": outputs}, default=str))
