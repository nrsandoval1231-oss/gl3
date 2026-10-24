from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from gridlens.api import app as api
from gridlens.domain.opportunity_intelligence import (
    _source,
    assemble_card,
    compact_source_excerpt,
)
from gridlens.ingestion.adapters.project_asset_classification import classify_project_asset
from gridlens.intelligence.lifecycle_service import _rebuild_projection


def test_source_native_data_center_classification_does_not_claim_a_milestone():
    assert (
        classify_project_asset(
            "texas-tdlr-tabs-data-centers",
            "PECOS COUNTY DATA CENTER",
            "Scope: New data center building; developer-reported completion: unknown",
        )
        == "data_center"
    )
    assert classify_project_asset("other-source", "Data center permit", "") is None
    assert (
        classify_project_asset(
            "texas-tdlr-tabs-data-centers", "Project registration", "Scope: office renovation"
        )
        is None
    )
    assert (
        classify_project_asset(
            "texas-tdlr-tabs-data-centers", "Project", "Scope: not a data center"
        )
        is None
    )


class _ProjectionSession:
    def __init__(self, project, evidence, observation, interpretation, decisions):
        self.project = project
        self.evidence = evidence
        self.observation = observation
        self.interpretation = interpretation
        self.decisions = decisions
        self.scalar_calls = 0
        self.scalars_calls = 0

    def scalars(self, _statement):
        self.scalars_calls += 1
        if self.scalars_calls == 1:
            rows = []  # no achieved lifecycle event
        elif self.scalars_calls == 2:
            rows = [row for row in self.decisions if row.candidate_project_id == self.project.id]
        elif self.scalars_calls == 3:
            rows = self.decisions
        else:
            rows = []
        return SimpleNamespace(all=lambda: rows)

    def scalar(self, _statement):
        self.scalar_calls += 1
        return self.interpretation

    def get(self, model, _identifier):
        name = getattr(model, "__name__", "")
        if name == "Evidence":
            return self.evidence
        if name == "Observation":
            return self.observation
        return None  # no prior lifecycle projection

    def delete(self, _value):
        raise AssertionError("no lifecycle projection should be deleted")


def _asset_projection(
    decisions=None,
    *,
    title="PECOS COUNTY DATA CENTER",
    abstract="Scope: New data center building",
):
    project_id, observation_id, evidence_id = uuid4(), uuid4(), uuid4()
    project = SimpleNamespace(
        id=project_id,
        identity_key="tdlr:TABS1",
        name=title,
        asset_type="unknown",
        source_id="synthetic-project-source",
        external_id="TABS1",
    )
    observation = SimpleNamespace(
        id=observation_id, source_id="texas-tdlr-tabs-data-centers", content_hash="a" * 64
    )
    evidence = SimpleNamespace(
        id=evidence_id,
        observation_id=observation_id,
        content_hash="b" * 64,
        title=title,
        abstract=abstract,
        event_date=None,
        event_date_label=None,
        published_at=None,
        observed_at=datetime.now(UTC),
        url="https://example.test/source",
    )
    interpretation = SimpleNamespace(
        observation_id=observation_id,
        content_hash=observation.content_hash,
        status="accepted",
        assessment={
            "semantic_hash": observation.content_hash,
            "evidence_hash": evidence.content_hash,
            "evidence_id": str(evidence.id),
            "project_identity_key": project.identity_key,
            "decision": "accepted",
        },
    )
    now = datetime.now(UTC)
    matched = SimpleNamespace(
        observation_id=observation_id,
        candidate_project_id=project_id,
        evidence_id=evidence_id,
        decision="matched",
        decided_at=now,
        id=1,
    )
    session = _ProjectionSession(
        project, evidence, observation, interpretation, decisions or [matched]
    )
    return project, session, matched


def test_explicit_asset_type_survives_projection_without_achieved_event():
    project, session, _matched = _asset_projection()
    _rebuild_projection(session, project)
    assert project.asset_type == "data_center"
    assert session.scalars_calls == 3


def test_current_revision_and_retraction_remove_old_asset_classification():
    project, session, matched = _asset_projection(
        title="TABS project registration", abstract="Scope: office renovation"
    )
    _rebuild_projection(session, project)
    assert project.asset_type == "unknown"

    project, session, matched = _asset_projection()
    unmatched = SimpleNamespace(
        observation_id=matched.observation_id,
        candidate_project_id=None,
        evidence_id=matched.evidence_id,
        decision="unmatched",
        decided_at=matched.decided_at + timedelta(seconds=1),
        id=2,
    )
    session.decisions.append(unmatched)
    _rebuild_projection(session, project)
    assert project.asset_type == "unknown"


def test_compact_evidence_preserves_exact_quotes_and_drops_opaque_payload():
    quote = "Construction of Building B requires a temporary power package."
    readable = f"Project: PECOS COUNTY DATA CENTER\nScope: {quote}"
    raw = readable + "\nOpaque source bytes (base64): " + ("QUJD" * 900)
    excerpt = compact_source_excerpt(raw)
    assert excerpt == readable

    evidence = {
        "id": "ev-1",
        "abstract": raw,
        "content_hash": "c" * 64,
        "source_id": "texas-tdlr-tabs-data-centers",
        "title": "PECOS COUNTY DATA CENTER",
        "assessment_current": True,
    }
    source = _source(evidence)
    card = assemble_card(
        {
            "id": "need-1",
            "project_id": "project-1",
            "name": "Pecos County Data Center",
            "tier": "Signal",
            "activity": "construction",
            "location": "Fort Stockton, TX",
            "required_mw": "5 MW",
            "demand_quote": quote,
            "evidence": [evidence],
        },
        {},
        {},
        [],
        research_enabled=False,
    )
    demand = next(field for field in card.fields if field.key == "required_mw")
    assert demand.sources[0].passage == quote
    assert "base64" not in source.passage.casefold()
    assert "evidence_text" not in card.model_dump_json()


def test_default_evidence_payload_compacts_repeated_raw_passages():
    raw = "Readable permit summary.\nOpaque source bytes (base64): " + ("QUJD" * 990)
    original = [{"id": str(index), "abstract": raw} for index in range(6)]
    compacted = [_source(row).model_dump(mode="json") for row in original]
    original_bytes = len(json.dumps(original).encode())
    compacted_bytes = len(json.dumps(compacted).encode())
    assert original_bytes > 24_000
    assert compacted_bytes < 4_000
    assert compacted_bytes < original_bytes / 6


def test_raw_evidence_endpoint_returns_only_requested_bounded_chunk(monkeypatch):
    content = "raw permit source bytes " * 400
    evidence = SimpleNamespace(
        id=uuid4(), content_hash="d" * 64, url="https://example.test", abstract=content
    )

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _model, _identifier):
            return evidence

    monkeypatch.setattr(api, "SessionLocal", _Session)
    result = api.evidence_content(evidence.id, offset=10, limit=20)
    assert result["content"] == content[10:30]
    assert result["total_chars"] == len(content)
    assert result["next_offset"] == 30
    with pytest.raises(HTTPException) as error:
        api.evidence_content(evidence.id, offset=len(content) + 1, limit=20)
    assert error.value.status_code == 416
