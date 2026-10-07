"""Offline fixture mechanics; these tests never claim retained-corpus validation."""

import copy
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "validate_pursuit_research", ROOT / "scripts" / "validate_pursuit_research.py"
)
assert SPEC and SPEC.loader
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)
BROWSER_SPEC = importlib.util.spec_from_file_location(
    "seeded_browser_acceptance", ROOT / "scripts" / "seeded_browser_acceptance.py"
)
assert BROWSER_SPEC and BROWSER_SPEC.loader
browser_harness = importlib.util.module_from_spec(BROWSER_SPEC)
BROWSER_SPEC.loader.exec_module(browser_harness)


def manifest():
    return {
        "schema_version": 1,
        "kind": "fixture",
        "corpus_id": "offline-mechanics-only",
        "database_name": "gl3_isolated_harness_fixture",
        "isolated_database": True,
        "cases": [
            {
                "category": category,
                "need_id": str(uuid4()),
                "selection_reason": "Explicit controlled fixture",
            }
            for category in sorted(harness.CATEGORIES)
        ],
    }


def snapshot():
    return {
        "database_name": "gl3_isolated_harness_fixture",
        "alembic_revision": "0014",
        "immutable_tables": {
            "evidence": {"count": 1, "sha256": "baseline", "rows": {"old": "unchanged-hash"}},
            "pursuit_call_notes": {"count": 0, "sha256": "empty", "rows": {}},
        },
        "identities": {"projects": ["project"], "power_needs": ["need"]},
    }


def test_manifest_requires_all_five_categories_and_explicit_distinct_ids(tmp_path):
    value = manifest()
    assert harness.validate_manifest(value, tmp_path)["retained_provenance_verified"] is False
    value["cases"][1]["need_id"] = value["cases"][0]["need_id"]
    with pytest.raises(ValueError, match="distinct"):
        harness.validate_manifest(value, tmp_path)
    value = manifest()
    value["cases"][0]["category"] = "synthetic_substitute"
    with pytest.raises(ValueError, match="five required"):
        harness.validate_manifest(value, tmp_path)


@pytest.mark.parametrize(
    ("windows", "expected"), [(True, "npm.cmd"), (False, "npm")]
)
def test_browser_runner_resolves_platform_npm_executable(monkeypatch, windows, expected):
    requested = []

    def resolve(name):
        requested.append(name)
        return f"C:/tools/{name}"

    monkeypatch.setattr(browser_harness.shutil, "which", resolve)
    assert browser_harness.npm_command(["--prefix", "web", "test"], windows=windows) == [
        f"C:/tools/{expected}",
        "--prefix",
        "web",
        "test",
    ]
    assert requested == [expected]


def no_question_case(category="austin_data_center"):
    from uuid import uuid4

    quote = (
        "New construction of modular data center foundation."
        if category == "austin_data_center"
        else "Temporary service for construction power."
    )
    card = {
        "input_hash": "same-evaluation",
        "disposition": "ACTION NOW",
        "tier": "Signal",
        "sources": [
            {
                "evidence_id": "11111111-1111-4111-8111-111111111111",
                "url": "https://abc.austintexas.gov/web/permit/public-search-other?id=1",
                "hash": "source-content-hash",
                "text": quote,
            }
        ],
    }
    return {
        "category": category,
        "need_id": str(uuid4()),
        "project_id": str(uuid4()),
        "source_id": "austin-building-permits",
        "card": copy.deepcopy(card),
        "category_source_evidence": harness.category_source_evidence(
            card, category, "austin-building-permits"
        ),
        "planned_questions": [],
    }


@pytest.mark.parametrize(
    "category", ["austin_data_center", "austin_temporary_power"]
)
def test_owner_no_question_exception_requires_unchanged_source_linked_austin_case(category):
    before = no_question_case(category)
    after = copy.deepcopy(before)
    assert before["category_source_evidence"]
    assert harness.owner_accepted_no_question_case(before, after, [])


@pytest.mark.parametrize(
    "category",
    ["chicago_conversion", "oil_and_gas", "low_quality"],
)
def test_owner_no_question_exception_never_bypasses_other_categories(category):
    before = no_question_case(category)
    after = copy.deepcopy(before)
    after["category_source_evidence"] = [{"evidence_id": "other-category"}]
    assert not harness.owner_accepted_no_question_case(before, after, [])


def test_category_citation_uses_exact_linked_austin_evidence_abstract():
    card = {
        "sources": [
            {
                "evidence_id": "11111111-1111-4111-8111-111111111111",
                "url": "https://abc.austintexas.gov/web/permit/public-search-other?id=1",
                "hash": "source-content-hash",
                "text": "Austin building permit 2026-036762 BP — Building Permit",
            }
        ]
    }
    row = SimpleNamespace(
        id="11111111-1111-4111-8111-111111111111",
        url=card["sources"][0]["url"],
        content_hash="source-content-hash",
        abstract=(
            "description: New Construction of Exterior Pad for Modular Data Center Foundation."
        ),
    )

    class EvidenceSession:
        def scalars(self, statement):
            return [row]

    citations = harness.category_source_evidence(
        card,
        "austin_data_center",
        "austin-building-permits",
        session=EvidenceSession(),
    )
    assert len(citations) == 1
    assert citations[0]["evidence_id"] == row.id
    assert citations[0]["content_hash"] == row.content_hash
    assert "Modular Data Center Foundation" in citations[0]["quote"]

    row.content_hash = "different-version"
    assert not harness.category_source_evidence(
        card,
        "austin_data_center",
        "austin-building-permits",
        session=EvidenceSession(),
    )


@pytest.mark.parametrize("mismatch", ["missing", "hash", "url"])
def test_runtime_category_citation_never_falls_back_to_card_text(mismatch):
    card = {
        "sources": [
            {
                "evidence_id": "11111111-1111-4111-8111-111111111111",
                "url": "https://abc.austintexas.gov/web/permit/public-search-other?id=1",
                "hash": "source-content-hash",
                "text": "New construction of modular data center foundation.",
            }
        ]
    }
    row = SimpleNamespace(
        id="11111111-1111-4111-8111-111111111111",
        url=card["sources"][0]["url"],
        content_hash=card["sources"][0]["hash"],
        abstract="An unrelated permit summary.",
    )
    if mismatch == "missing":
        rows = []
    else:
        if mismatch == "hash":
            row.content_hash = "different-version"
        else:
            row.url = "https://abc.austintexas.gov/web/permit/different?id=1"
        rows = [row]

    class EvidenceSession:
        def scalars(self, statement):
            return rows

    assert not harness.category_source_evidence(
        card,
        "austin_data_center",
        "austin-building-permits",
        session=EvidenceSession(),
    )


def test_sessionless_fixture_category_citation_uses_card_text():
    category = "austin_data_center"
    before = no_question_case(category)
    assert before["category_source_evidence"]
    assert "data center" in before["category_source_evidence"][0]["quote"].lower()


@pytest.mark.parametrize(
    "failure",
    [
        "no_citation",
        "wrong_source",
        "changed_identity",
        "questions_planned",
        "attempt",
        "evaluation",
        "disposition",
        "before_not_action_now",
        "tier",
        "evidence",
    ],
)
def test_owner_no_question_exception_fails_closed_on_missing_proof_or_change(failure):
    before = no_question_case()
    after = copy.deepcopy(before)
    attempts = []
    if failure == "no_citation":
        before["category_source_evidence"] = []
    elif failure == "wrong_source":
        after["source_id"] = "unrelated-source"
    elif failure == "changed_identity":
        after["project_id"] = "different-project"
    elif failure == "questions_planned":
        after["planned_questions"] = [{"category": "power_need"}]
    elif failure == "attempt":
        attempts = [{"status": "FAILED"}]
    elif failure == "evaluation":
        after["card"]["input_hash"] = "changed-evaluation"
    elif failure == "disposition":
        after["card"]["disposition"] = "RESEARCH"
    elif failure == "before_not_action_now":
        before["card"]["disposition"] = "WATCH"
    elif failure == "tier":
        after["card"]["tier"] = "Prospect"
    elif failure == "evidence":
        after["card"]["sources"][0]["hash"] = "changed-source-hash"
    assert not harness.owner_accepted_no_question_case(before, after, attempts)


@pytest.mark.parametrize("database", ["gridlens", "gridlens_test", "postgres"])
def test_runtime_and_shared_test_databases_cannot_be_validation_targets(tmp_path, database):
    value = manifest()
    value["database_name"] = database
    with pytest.raises(ValueError, match="isolated"):
        harness.validate_manifest(value, tmp_path)


def test_retained_label_requires_actual_original_backup_hash(tmp_path):
    backup = tmp_path / "substitute.dump"
    backup.write_bytes(b"fixture is not the original retained database")
    value = manifest()
    value["kind"] = "retained_pr23"
    value["provenance"] = {"backup_path": backup.name, "backup_sha256": harness.PR23_BACKUP}
    with pytest.raises(ValueError, match="backup hash"):
        harness.validate_manifest(value, tmp_path)


def test_baseline_files_cannot_be_silently_replaced(tmp_path):
    path = tmp_path / "baseline.json"
    harness.write_once(path, {"immutable": "baseline"})
    with pytest.raises(FileExistsError):
        harness.write_once(path, {"immutable": "overwritten"})
    assert "baseline" in path.read_text()


def test_preservation_allows_additions_but_detects_historical_mutation_or_missing_identity():
    before = snapshot()
    after = copy.deepcopy(before)
    after["immutable_tables"]["evidence"]["rows"]["new"] = "new-hash"
    assert harness.preservation(before, after)["passed"]
    after["immutable_tables"]["evidence"]["rows"]["old"] = "mutated"
    assert not harness.preservation(before, after)["passed"]
    after = copy.deepcopy(before)
    after["identities"]["projects"] = []
    assert not harness.preservation(before, after)["passed"]


@pytest.mark.parametrize(
    (
        "max_jobs",
        "deadline",
        "clock",
        "runner",
        "expected_stop",
        "expected_jobs",
        "expected_calls",
    ),
    [
        (2, 100, [0, 0, 0, 0], True, "max_jobs", 2, 2),
        (5, 100, [0], False, "runner_unavailable", 0, 1),
        (5, 1, [0], True, "wall_clock", 0, 0),
        (3, 100, [0] * 6, True, "max_jobs", 3, 3),
    ],
)
def test_cohort_drain_stops_at_job_time_runner_and_no_progress_bounds(
    max_jobs, deadline, clock, runner, expected_stop, expected_jobs, expected_calls
):
    pending = ["same-job"]
    calls = []

    def run_job(job_ids):
        calls.append(list(job_ids))
        return runner

    jobs, stop = harness.drain_cohort_jobs(
        lambda: pending,
        run_job,
        jobs_executed=0,
        max_jobs=max_jobs,
        deadline=deadline,
        per_question_timeout=2,
        monotonic=lambda: clock.pop(0),
    )
    assert jobs == expected_jobs
    assert stop == expected_stop
    assert len(calls) == expected_calls


@pytest.mark.parametrize("bad_replay", [False, True])
@pytest.mark.parametrize("changed_input", [False, True])
def test_full_harness_offline_fixture_receipts_and_duplicate_replay_failure(
    monkeypatch, bad_replay, changed_input
):
    from gridlens.ingestion import registry
    from gridlens.intelligence import commercial_evaluation, pursuit_questions
    from gridlens.jobs import worker
    from gridlens.persistence import database
    from gridlens.persistence.models import Job, Pursuit, PursuitResearchQuestion

    value = manifest()
    cases = [
        {
            **case,
            "source_id": "fixture-source",
            "project_id": "fixture-project",
            "category_source_evidence": [],
            "planned_questions": [],
            "card": {
                "id": case["need_id"],
                "disposition": "RESEARCH",
                "tier": "Signal",
                "input_hash": "same",
            },
        }
        for case in value["cases"]
    ]
    store = {"questions": [], "jobs": []}
    plan_count_by_need = {}
    changed_need_id = cases[0]["need_id"]
    changed_once = False

    class Session:
        def __enter__(self):
            self.saved = copy.deepcopy(store)
            return self

        def __exit__(self, *_):
            return False

        def flush(self):
            pass

        def rollback(self):
            store.update(copy.deepcopy(self.saved))

        def scalars(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            if entity is Job:
                return [job.id for job in store["jobs"] if job.status == "queued"]
            if entity is PursuitResearchQuestion:
                return store["questions"]
            assert entity is Pursuit
            return []

    class Sessions:
        def __call__(self):
            return Session()

        def begin(self):
            return Session()

    def schedule(_session, cards, **kwargs):
        nonlocal changed_once
        assert kwargs["origin"] == "validation"
        rows = []
        for card in cards:
            need_id = card["id"]
            plan_count_by_need[need_id] = plan_count_by_need.get(need_id, 0) + 1
            plan_count = plan_count_by_need[need_id]
            initial = plan_count == 1
            replacement = (
                changed_input
                and need_id == changed_need_id
                and plan_count == 2
                and card["input_hash"] == "changed"
            )
            duplicate = bad_replay and plan_count >= 3
            if not (initial or replacement or duplicate):
                continue
            qid = uuid4()
            row = SimpleNamespace(
                id=qid,
                need_id=need_id,
                pursuit_id=uuid4(),
                created_at=datetime.now(UTC),
                completed_at=None,
                attempt_count=0,
                status="QUEUED",
                category="activity",
                evidence_fingerprint=card["input_hash"],
                context={
                    "origin": "validation",
                    "before": {"input_hash": card["input_hash"]},
                },
                receipt={},
            )
            rows.append(row)
            store["questions"].append(row)
            store["jobs"].append(
                SimpleNamespace(id=uuid4(), target_id=qid, status="queued")
            )
        return rows

    def run(_definitions, *, job_ids):
        nonlocal changed_once
        assert set(job_ids) <= {job.id for job in store["jobs"]}
        job = next(item for item in store["jobs"] if item.id in job_ids and item.status == "queued")
        row = next(item for item in store["questions"] if item.id == job.target_id)
        row.attempt_count, row.completed_at = 1, datetime.now(UTC)
        if changed_input and row.need_id == changed_need_id and not changed_once:
            row.status = "FAILED"
            row.receipt = {"error": "input_changed_before_research", "source_checks": []}
            next(case for case in cases if case["need_id"] == changed_need_id)["card"][
                "input_hash"
            ] = "changed"
            changed_once = True
        else:
            row.status = "UNRESOLVED"
            row.receipt = {
                "cost_usd": "0",
                "runtime_seconds": 0.1,
                "source_checks": [
                    {
                        "url": "https://fixture.invalid/document",
                        "disposition": "UNRESOLVED",
                        "retrieved_at": datetime.now(UTC).isoformat(),
                    }
                ],
            }
        job.status = "succeeded"
        return True

    def replay(_session):
        return {"questions": sorted(str(row.id) for row in store["questions"])}

    monkeypatch.setattr(database, "SessionLocal", Sessions())
    monkeypatch.setattr(registry, "load_registry", lambda: [])
    monkeypatch.setattr(pursuit_questions, "schedule_questions", schedule)
    monkeypatch.setattr(
        pursuit_questions,
        "question_view",
        lambda row: {
            "id": str(row.id),
            "need_id": row.need_id,
            "category": row.category,
            "evidence_fingerprint": row.evidence_fingerprint,
            "context": row.context,
            "status": row.status,
            "receipt": row.receipt,
        },
    )
    monkeypatch.setattr(
        commercial_evaluation,
        "evaluate_target",
        lambda _s, need: next(case["card"] for case in cases if case["need_id"] == str(need)),
    )
    monkeypatch.setattr(worker, "run_one", run)
    monkeypatch.setattr(harness, "database_snapshot", lambda _session: snapshot())
    monkeypatch.setattr(harness, "selected_cases", lambda *_, **__: cases)
    monkeypatch.setattr(harness, "replay_state", replay)
    monkeypatch.setattr(harness, "candidate_identity", lambda: {"commit": "fixture"})
    baseline = {
        "snapshot": snapshot(),
        "execution_limits": harness.execution_limits(value),
        "replay_state": replay(None),
        "cases": cases,
        "provenance": {"retained_provenance_verified": False},
    }
    report = harness.execute_cases(value, baseline)
    assert report["mechanical_gates_passed"] is not (bad_replay or changed_input)
    assert report["retained_corpus_proof"] is False
    assert len(report["cases"]) == 5
    if changed_input:
        attempts = report["cases"][0]["questions"]
        assert len(attempts) == 2
        assert attempts[0]["status"] == "FAILED"
        assert attempts[0]["receipt"]["error"] == "input_changed_before_research"
        assert attempts[1]["status"] == "UNRESOLVED"
        assert report["cases"][0]["bounded_investigation_completed"] is False
        assert report["replay"]["passed"] is not bad_replay
    elif bad_replay:
        assert len(store["questions"]) == 5  # Strict dry replay rolled back its duplicates.
        assert not report["replay"]["passed"]
    else:
        assert len(store["questions"]) == 5
    assert report["metrics"]["attempted_question_origins"] == {
        "validation": len(store["questions"])
    }
    assert report["preservation"]["passed"]


def test_old_evaluation_versions_must_survive_research_unchanged():
    before = {"evaluations": {"pursuit": {"versions": [{"version": 1, "input_hash": "old"}]}}}
    after = copy.deepcopy(before)
    after["evaluations"]["pursuit"]["versions"].append({"version": 2, "input_hash": "new"})
    assert harness.evaluation_history_preserved(before, after)
    after["evaluations"]["pursuit"]["versions"][0]["input_hash"] = "rewritten"
    assert not harness.evaluation_history_preserved(before, after)


@pytest.mark.parametrize("disposition", ["FAILED", "SKIPPED", "UNAVAILABLE", "UNRESOLVED"])
def test_route_selection_or_failure_without_retrieval_cannot_pass_investigation(disposition):
    assert not harness.investigation_completed(
        {
            "status": "UNRESOLVED",
            "receipt": {
                "source_checks": [
                    {"url": "https://fixture.invalid/doc", "disposition": disposition}
                ]
            },
        }
    )


def test_completed_zero_result_discovery_is_bounded_unresolved_proof():
    assert harness.investigation_completed(
        {"status": "UNRESOLVED", "receipt": {"queries_searched": ['"Exact project" contractor']}}
    )
    assert not harness.investigation_completed(
        {"status": "UNRESOLVED", "receipt": {"queries_attempted": ['"Exact project" contractor']}}
    )


def test_aggregate_budget_requires_explicit_paid_cohort_ceiling(monkeypatch):
    from decimal import Decimal

    from gridlens.settings import settings

    value = manifest()
    monkeypatch.setattr(settings, "autonomous_research_max_cost_usd", Decimal("0.10"))
    with pytest.raises(ValueError, match="cost bound"):
        harness.execution_limits(value)
    value["run_budget"] = {"max_total_cost_usd": "2", "max_wall_clock_seconds": 3600}
    limits = harness.execution_limits(value)
    assert limits["configured_reserved_cost_bound_usd"] == "2.00"
    value["run_budget"]["max_total_cost_usd"] = "NaN"
    with pytest.raises(ValueError, match="Run budget"):
        harness.execution_limits(value)
