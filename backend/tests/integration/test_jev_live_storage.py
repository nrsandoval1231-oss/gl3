"""WS2a: live Jev persistence against a disposable `_test` database. No paid provider is called."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from test_evidence_shadow_storage import FakeJudge, seed_accepted, shadow_db  # noqa: F401,F811
from test_intelligence_worker_integration import _enable_bounded_typesafe, _wire_worker

from gridlens.intelligence.evidence_judge import Judgment
from gridlens.intelligence.evidence_shadow import run_shadow
from gridlens.intelligence.jev_live import accepted_labels
from gridlens.persistence.models import (
    Evidence,
    EvidenceJudgeRun,
    Interpretation,
    Job,
    LogicalCall,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
)
from gridlens.settings import settings

MODEL = "jev-1.13.0"
LONG_PASSAGE = "The facility will add four electric chillers and two substations. " * 60


def _live(monkeypatch, *authorities):
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "jev_shadow_mode", True)
    monkeypatch.setattr(settings, "jev_live_mode", True)
    for authority in authorities:
        monkeypatch.setattr(settings, f"jev_live_{authority}", True)


class LiveJudge(FakeJudge):
    """A fake provider adapter: returns labels and per-label probabilities."""

    def judge(self, state, evidence, candidates):
        self.calls += 1
        judgment = Judgment(
            relevant="YES",
            same_project="UNKNOWN",
            event_type="electrical_construction",
            material_change="YES",
            power_relevance="HIGH",
            needs_deep_enrichment="NO",
            driver="ELECTRIC",
            novelty="NEW",
            side="DEMAND",
            lifecycle_phase="permitted",
            new_large_load="YES",
            document_route="narrative",
        )
        probabilities = {name: 0.97 for name in Judgment.model_fields}
        probabilities["driver"] = 0.5
        return judgment, {
            "model": MODEL,
            "latency_ms": 4,
            "input_tokens": 100,
            "output_tokens": 1,
            "probabilities": probabilities,
        }


def _snapshot(factory):
    """Every canonical row Jev must never alter, including value-bearing assessment JSON."""
    with factory() as session:
        return {
            "projects": [
                (p.id, p.identity_key, p.name, p.location, p.identity_facts, p.asset_type)
                for p in session.scalars(select(Project).order_by(Project.id))
            ],
            "needs": [
                (n.id, n.tier, n.activity_key, n.supply, n.active, n.admission_basis)
                for n in session.scalars(select(PowerNeed).order_by(PowerNeed.id))
            ],
            "observations": [
                (o.id, o.title, o.abstract, o.content_hash)
                for o in session.scalars(select(Observation).order_by(Observation.id))
            ],
            "evidence": [
                (e.id, e.title, e.abstract, e.content_hash, e.provenance)
                for e in session.scalars(select(Evidence).order_by(Evidence.id))
            ],
            "interpretations": [
                (i.id, i.status, i.content_hash, json.dumps(i.assessment, sort_keys=True))
                for i in session.scalars(select(Interpretation).order_by(Interpretation.id))
            ],
            "links": sorted(
                (str(n.need_id), str(n.observation_id))
                for n in session.scalars(select(NeedObservation))
            ),
        }


def _admit(factory):
    """Make the accepted record satisfy the worker's current-admitted-evidence recheck."""
    with factory.begin() as session:
        project = session.scalar(select(Project))
        interpretation = session.scalar(select(Interpretation))
        interpretation.assessment = {
            **interpretation.assessment,
            "semantic_hash": interpretation.content_hash,
            "project_identity_key": project.identity_key,
        }


def _add_equipment_values(factory):
    """Give the accepted record value-bearing fields that a live decision must not touch."""
    with factory.begin() as session:
        interpretation = session.scalar(select(Interpretation))
        interpretation.assessment = {
            **interpretation.assessment,
            "demand_mw": 25,
            "equipment": [{"unit": "chiller", "quantity": 4, "rating_kw": 1200}],
        }


def test_shadow_only_stores_no_live_record(shadow_db, monkeypatch):  # noqa: F811
    seed_accepted(shadow_db)
    monkeypatch.setattr(settings, "jev_enabled", True)
    monkeypatch.setattr(settings, "jev_shadow_mode", True)
    with shadow_db() as session:
        assert run_shadow(session, limit=1, judge=LiveJudge())["valid"] == 1
        run = session.scalar(select(EvidenceJudgeRun))
        assert "live" not in run.result and "live" not in run.deterministic
        # Probabilities and the passage actually seen are kept even without live mode.
        assert run.result["probabilities"]["relevant"] == pytest.approx(0.97)
        assert "passage_bounds" in run.result
        assert accepted_labels(run.result) == {}


def test_live_decision_records_labels_and_cannot_change_any_value(shadow_db, monkeypatch):  # noqa: F811
    seed_accepted(shadow_db)
    _add_equipment_values(shadow_db)
    _live(monkeypatch, "routing", "labels", "materiality", "triage", "matching")
    before = _snapshot(shadow_db)
    with shadow_db() as session:
        assert run_shadow(session, limit=1, judge=LiveJudge())["valid"] == 1
        run = session.scalar(select(EvidenceJudgeRun))
        live = run.result["live"]
        assert live["mode"] == "live" and live["model"] == MODEL and live["outcome"] == "decided"
        by_field = {item["field"]: item for item in live["labels"]}
        # Acts alone: routing, labels, materiality and triage.
        assert by_field["document_route"]["effective_value"] == "narrative"
        assert by_field["event_type"]["effective_value"] == "electrical_construction"
        assert by_field["material_change"]["effective_value"] == "YES"
        assert by_field["new_large_load"]["effective_value"] == "YES"
        # Below the abstain threshold: UNKNOWN, never a guess.
        assert by_field["driver"]["outcome"] == "abstained"
        assert by_field["driver"]["effective_value"] == "UNKNOWN"
        # Matching needs a deterministic key; this fixture has none and Jev said UNKNOWN anyway.
        assert by_field["same_project"]["effective_value"] == "UNKNOWN"
        # Model, probability and decision are stored on the record and the run.
        assert run.model == MODEL
        assert all(
            isinstance(item["probability"], float) and item["model"] == MODEL
            for item in live["labels"]
        )
        assert accepted_labels(run.result)["document_route"] == "narrative"
        assert "driver" not in accepted_labels(run.result)
    # Nothing canonical changed: no project, need, evidence, observation or value.
    after = _snapshot(shadow_db)
    assert after == before
    assert json.loads(after["interpretations"][0][3])["demand_mw"] == 25


class MatchJudge(LiveJudge):
    def judge(self, state, evidence, candidates):
        judgment, meta = super().judge(state, evidence, candidates)
        data = judgment.model_dump()
        data["same_project"] = "YES"
        meta["probabilities"]["same_project"] = 0.99
        return Judgment.model_validate(data), meta


def _seed_keys(factory, project_facts, assessment_facts):
    project_id = seed_accepted(factory)
    with factory.begin() as session:
        session.get(Project, project_id).identity_facts = project_facts
        interpretation = session.scalar(select(Interpretation))
        interpretation.assessment = {**interpretation.assessment, **assessment_facts}


def test_live_matching_acts_with_a_permit_number_key(shadow_db, monkeypatch):  # noqa: F811
    # The evidence side is Interpretation.assessment (deterministic interpretation output);
    # the project side is Project.identity_facts.
    _seed_keys(
        shadow_db,
        {"permit_number": "NSR-123456", "county": "Travis"},
        {"permit_number": "NSR-123456", "county": "Travis"},
    )
    _live(monkeypatch, "matching")
    with shadow_db() as session:
        run_shadow(session, limit=1, judge=MatchJudge())
        run = session.scalar(select(EvidenceJudgeRun))
        labels = {item["field"]: item for item in run.result["live"]["labels"]}
        assert set(labels) == {"same_project"}
        assert labels["same_project"]["outcome"] == "accepted"
        assert labels["same_project"]["corroboration"] == ["county", "permit_number"]
        assert accepted_labels(run.result) == {"same_project": "YES"}


def test_live_matching_never_acts_on_county_alone(shadow_db, monkeypatch):  # noqa: F811
    _seed_keys(shadow_db, {"county": "Travis"}, {"county": "Travis"})
    _live(monkeypatch, "matching")
    with shadow_db() as session:
        run_shadow(session, limit=1, judge=MatchJudge())
        run = session.scalar(select(EvidenceJudgeRun))
        label = run.result["live"]["labels"][0]
        assert label["outcome"] == "abstained"
        assert label["reason"] == "NO_DETERMINISTIC_KEY_AGREES"
        assert label["effective_value"] == "UNKNOWN"
        assert accepted_labels(run.result) == {}


def test_live_matching_is_inert_without_identity_fact_keys(shadow_db, monkeypatch):  # noqa: F811
    # Today's writers store project_name/site only, so no deterministic key can agree.
    _seed_keys(shadow_db, {"project_name": "Ambiguous Data Center", "site": "Austin, TX"}, {})
    _live(monkeypatch, "matching")
    with shadow_db() as session:
        run_shadow(session, limit=1, judge=MatchJudge())
        run = session.scalar(select(EvidenceJudgeRun))
        assert accepted_labels(run.result) == {}


@pytest.mark.parametrize(("outcome", "status"), [("timeout", "timeout"), ("invalid", "invalid")])
def test_live_provider_failure_abstains_visibly(shadow_db, monkeypatch, outcome, status):  # noqa: F811
    seed_accepted(shadow_db)
    _live(monkeypatch, "routing", "labels")
    with shadow_db() as session:
        result = run_shadow(session, limit=1, judge=FakeJudge(outcome))
        assert result["failed"] == 1
        run = session.scalar(select(EvidenceJudgeRun))
        assert run.status == status and run.result is None
        live = run.deterministic["live"]
        assert live["outcome"] == "abstained" and live["labels"] == []
        assert live["reason"].startswith("PROVIDER_")
        assert accepted_labels({"live": live}) == {}


def _enable_live_ledger(monkeypatch, *authorities):
    _enable_bounded_typesafe(monkeypatch)
    for name, value in {
        "intelligence_enabled_contracts": "EVIDENCE_SHADOW",
        "intelligence_typesafe_model": MODEL,
        "intelligence_typesafe_priced_model_id": MODEL,
        "intelligence_typesafe_billing_model_id": MODEL,
        "typesafe_api_key": SecretStr("fixture-only"),
        "intelligence_typesafe_input_usd_per_million": Decimal("0.042"),
        "jev_shadow_daily_limit": 20,
    }.items():
        monkeypatch.setattr(settings, name, value)
    _live(monkeypatch, *authorities)


def _provider_answers(model=MODEL):
    values = {
        "relevant": "YES",
        "same_project": "UNKNOWN",
        "event_type": "construction",
        "material_change": "YES",
        "power_relevance": "HIGH",
        "needs_deep_enrichment": "NO",
        "driver": "ELECTRIC",
        "novelty": "NEW",
        "side": "DEMAND",
        "lifecycle_phase": "permitted",
        "new_large_load": "YES",
        "document_route": "narrative",
    }
    answers = {
        name: {
            "type": "choice",
            "choice": value,
            "confidence": 0.9,
            "probabilities": {value: 0.9, "UNKNOWN": 0.1}
            if value != "UNKNOWN"
            else {"UNKNOWN": 1.0},
        }
        for name, value in values.items()
    }
    return {"model": model, "answers": answers, "usage": {"input_tokens": 700, "output_tokens": 0}}


def _run_worker(factory, monkeypatch, provider, before_worker=None):
    _admit(factory)
    from gridlens.integrations import intelligence_provider, legacy_calls

    worker = _wire_worker(factory, monkeypatch)
    monkeypatch.setattr(worker, "WORKER_ID", "fixture-live-worker")
    monkeypatch.setattr(legacy_calls, "SessionLocal", factory)
    monkeypatch.setattr(intelligence_provider, "call_typesafe", provider)
    with factory() as session:
        assert run_shadow(session, limit=1)["attempted"] == 1
        job = session.scalar(select(Job).where(Job.kind == "evidence_shadow"))
        job_id = job.id
    if before_worker:
        before_worker(factory, job_id)
    # This helper immediately invokes the leased worker, so make the newly-created
    # job explicitly due despite small DB/application clock skew.
    with factory.begin() as session:
        job = session.get(Job, job_id)
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    assert worker.run_one({}, job_ids=[job_id]) is True


def test_live_worker_path_uses_ledger_pin_full_passage_and_stores_decision(
    shadow_db,  # noqa: F811
    monkeypatch,
):
    seed_accepted(shadow_db)
    with shadow_db.begin() as session:
        for row in session.scalars(select(Evidence)):
            row.abstract = LONG_PASSAGE
    _enable_live_ledger(monkeypatch, "routing", "triage")
    sent = []

    def provider(**kwargs):
        sent.append(kwargs)
        return _provider_answers()

    _run_worker(shadow_db, monkeypatch, provider)
    assert len(sent) == 1
    assert sent[0]["model"] == MODEL
    passage = sent[0]["payload"]["state"]["evidence"]["abstract"]
    assert passage == LONG_PASSAGE and len(passage) > 1200  # not cut at 1,200 characters
    assert "temporary" not in json.dumps(sent[0]["payload"]["questions"]).casefold().replace(
        "temporary public event", ""
    )
    with shadow_db() as session:
        run = session.scalar(select(EvidenceJudgeRun))
        call = session.scalar(select(LogicalCall))
        assert run.status == "valid" and run.model == MODEL
        assert call and call.status == "COMPLETED"
        live = run.result["live"]
        fields = {item["field"]: item for item in live["labels"]}
        assert set(fields) == {"document_route", "new_large_load", "relevant"}
        assert fields["document_route"]["outcome"] == "accepted"
        assert fields["document_route"]["probability"] == pytest.approx(0.9)
        assert run.result["probabilities"]["document_route"] == pytest.approx(0.9)
        bounds = run.result["passage_bounds"]["abstract"]
        assert bounds["truncated"] is False and bounds["chars_total"] == len(LONG_PASSAGE)
        assert run.deterministic["passage_bounds"] == run.result["passage_bounds"]
        assert run.deterministic["contract_version"] == "evidence-judge-v2"


def test_live_worker_over_cap_job_is_visible_and_never_calls_the_provider(
    shadow_db,  # noqa: F811
    monkeypatch,
):
    seed_accepted(shadow_db)
    _enable_live_ledger(monkeypatch, "routing")
    # The per-call cap cannot cover the full verified input ceiling: ledger policy blocks.
    monkeypatch.setattr(settings, "intelligence_max_call_usd", Decimal("0.0000001"))
    provider_calls = []
    _run_worker(shadow_db, monkeypatch, lambda **kw: provider_calls.append(kw))
    assert provider_calls == []
    with shadow_db() as session:
        run = session.scalar(select(EvidenceJudgeRun))
        assert run.status == "failed" and run.result is None
        live = run.deterministic["live"]
        assert live["outcome"] == "abstained" and live["labels"] == []
        assert run.deterministic["failure_reason"]  # the cap/policy reason is recorded
        assert accepted_labels({"live": live}) == {}


def test_live_worker_provider_error_abstains(shadow_db, monkeypatch):  # noqa: F811
    seed_accepted(shadow_db)
    _enable_live_ledger(monkeypatch, "routing")

    def provider(**_kwargs):
        raise httpx.TimeoutException("fixture timeout")

    _run_worker(shadow_db, monkeypatch, provider)
    with shadow_db() as session:
        run = session.scalar(select(EvidenceJudgeRun))
        assert run.status == "failed" and run.result is None, run.error_class
        assert run.deterministic["live"]["outcome"] == "abstained"
        assert run.deterministic["live"]["labels"] == []
        # Class name only: provider/exception text is never persisted.
        assert "fixture timeout" not in json.dumps(run.deterministic)
        assert run.deterministic["failure_reason"].split(":")[0]


def test_live_worker_early_block_writes_an_abstained_record(shadow_db, monkeypatch):  # noqa: F811
    seed_accepted(shadow_db)
    _enable_live_ledger(monkeypatch, "routing")
    calls = []

    def disable(*_args):
        monkeypatch.setattr(settings, "intelligence_enabled_contracts", "")

    _run_worker(shadow_db, monkeypatch, lambda **kw: calls.append(kw), before_worker=disable)
    assert calls == []
    with shadow_db() as session:
        run = session.scalar(select(EvidenceJudgeRun))
        assert run.status == "failed" and run.error_class == "CONTRACT_DISABLED"
        assert run.deterministic["live"]["outcome"] == "abstained"
        assert run.deterministic["live"]["reason"] == "BLOCKED:CONTRACT_DISABLED"


def test_live_worker_does_not_replay_a_v1_contract_job(shadow_db, monkeypatch):  # noqa: F811
    seed_accepted(shadow_db)
    _enable_live_ledger(monkeypatch, "routing")
    calls = []

    def downgrade(factory, job_id):
        with factory.begin() as session:
            job = session.get(Job, job_id)
            checkpoint = json.loads(job.checkpoint)
            checkpoint["contract_version"] = "evidence-judge-v1"
            job.checkpoint = json.dumps(checkpoint)

    _run_worker(shadow_db, monkeypatch, lambda **kw: calls.append(kw), before_worker=downgrade)
    assert calls == []
    with shadow_db() as session:
        run = session.scalar(select(EvidenceJudgeRun))
        assert run.error_class == "LegacyContractReplayUnsupported"
        assert run.deterministic["contract_version"] == "evidence-judge-v1"
        assert run.deterministic["live"]["labels"] == []


def test_live_worker_unpinned_response_model_is_rejected(shadow_db, monkeypatch):  # noqa: F811
    seed_accepted(shadow_db)
    _enable_live_ledger(monkeypatch, "routing")
    _run_worker(shadow_db, monkeypatch, lambda **_kw: _provider_answers("jev-latest"))
    with shadow_db() as session:
        run = session.scalar(select(EvidenceJudgeRun))
        assert run.status == "failed" and run.result is None
        assert run.deterministic["live"]["labels"] == []
