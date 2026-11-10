"""CLI regression for the nested Phase 2 capture receipt contract."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "phase2_metrics.py"
BASE_COMMIT = "bc433650ce4706dddfb5b30d78a502e3b528f54e"
FIXTURE_SHA = "a" * 64
EVALUATOR_SHA = "b" * 64


def _metrics_module():
    spec = importlib.util.spec_from_file_location("phase2_metrics", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _capture_receipt(mode: str, *, fixture_sha: str, evaluator_sha: str) -> dict:
    source_root = ROOT / "backend" / "src"
    module_path = source_root / "gridlens" / "__init__.py"
    module_sha = hashlib.sha256(module_path.read_bytes()).hexdigest()
    return {
        "mode": mode,
        "fixture_id": f"phase2-cross-lane-v3-{fixture_sha}",
        "source_commit": BASE_COMMIT if mode == "baseline" else "c" * 40,
        "imported_source_root": str(source_root),
        "source_modules": {
            "gridlens.domain.commercial_brief": {
                "path": str(module_path),
                "sha256": module_sha,
            }
        },
        "data_kind": "SYNTHETIC fixture only",
        "entities": {
            "canonical_account_ids": ["account-1"],
            "physical_project_ids": ["project-1"],
            "need_ids": ["need-1"],
        },
        # This mirrors capture()'s actual emission location; hashes are not
        # duplicated at the receipt top level.
        "commercial": {
            "fixture_input_sha256": fixture_sha,
            "evaluator_sha256": evaluator_sha,
            "useful_need_ids": ["need-1"],
            "amount_class_scope_counts": {},
            "named_contact_need_ids": [],
            "generic_contact_need_ids": [],
            "freshness_states": {},
            "conflict_count": 0,
            "structured_brief_need_ids": ["need-1"] if mode == "candidate" else [],
            "contact_counts": {},
        },
        "pipeline": {
            "provider_logical_requests": 0,
            "provider_cache_reuses": 0,
            "synthetic_mock_cost_usd": "0.000000",
            "scheduled_jobs": 1,
            "successful_jobs": 1,
            "failed_jobs": 0,
            "recovery_completed": True,
            "elapsed_ms": 10.0,
            "read_latency_ms": {"p50": 1.0, "p95": 2.0},
        },
    }


def _write_receipt(path: Path, receipt: dict) -> None:
    path.write_text(json.dumps(receipt), encoding="utf-8")


def _run_compare(baseline: Path, candidate: Path, output: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "compare",
            "--baseline",
            str(baseline),
            "--candidate",
            str(candidate),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_compare_cli_round_trips_capture_receipt_hashes(tmp_path: Path) -> None:
    baseline = _capture_receipt("baseline", fixture_sha=FIXTURE_SHA, evaluator_sha=EVALUATOR_SHA)
    candidate = _capture_receipt("candidate", fixture_sha=FIXTURE_SHA, evaluator_sha=EVALUATOR_SHA)
    assert "fixture_input_sha256" not in baseline
    assert "evaluator_sha256" not in baseline
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    output_path = tmp_path / "comparison.json"
    _write_receipt(baseline_path, baseline)
    _write_receipt(candidate_path, candidate)

    result = _run_compare(baseline_path, candidate_path, output_path)

    assert result.returncode == 0, result.stderr
    comparison = json.loads(output_path.read_text(encoding="utf-8"))
    assert comparison["fixture_input_sha256"] == FIXTURE_SHA
    assert comparison["evaluator_sha256"] == EVALUATOR_SHA
    assert comparison["candidate"]["structured_brief_need_count"] == 1
    assert output_path.with_suffix(".md").is_file()

    overwrite = _run_compare(baseline_path, candidate_path, output_path)
    assert overwrite.returncode == 2
    assert "Refusing to overwrite" in overwrite.stderr


@pytest.mark.parametrize(
    ("candidate_fixture_sha", "candidate_evaluator_sha", "message"),
    [
        ("d" * 64, EVALUATOR_SHA, "same fixture_id"),
        (FIXTURE_SHA, "e" * 64, "identical evaluator_sha256"),
    ],
)
def test_compare_cli_rejects_mismatched_fixture_or_evaluator_hash(
    tmp_path: Path,
    candidate_fixture_sha: str,
    candidate_evaluator_sha: str,
    message: str,
) -> None:
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    _write_receipt(
        baseline_path,
        _capture_receipt("baseline", fixture_sha=FIXTURE_SHA, evaluator_sha=EVALUATOR_SHA),
    )
    _write_receipt(
        candidate_path,
        _capture_receipt(
            "candidate",
            fixture_sha=candidate_fixture_sha,
            evaluator_sha=candidate_evaluator_sha,
        ),
    )

    result = _run_compare(baseline_path, candidate_path, tmp_path / "comparison.json")

    assert result.returncode == 2
    assert message in result.stderr


def _source_checkout(tmp_path: Path) -> Path:
    checkout = tmp_path / "checkout"
    source_root = checkout / "backend" / "src"
    source_package = source_root / "gridlens"
    source_package.mkdir(parents=True)
    (source_package / "__init__.py").write_text('"""Fixture package."""\n')
    (source_package / "module.py").write_text("VALUE = 1\n")
    test_file = checkout / "backend" / "tests" / "fixture.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("assert True\n")
    (checkout / ".gitignore").write_text("__pycache__/\n")
    subprocess.run(["git", "init", "--quiet", str(checkout)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "add",
            "backend/src",
            "backend/tests",
            ".gitignore",
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "user.name=Phase2 Test",
            "-c",
            "user.email=phase2@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "source fixture",
        ],
        check=True,
    )
    return source_root


def test_source_guard_rejects_tracked_and_untracked_python_changes(
    tmp_path: Path,
) -> None:
    metrics = _metrics_module()
    source_root = _source_checkout(tmp_path)
    source_file = source_root / "gridlens" / "module.py"
    source_file.write_text("VALUE = 2\n")
    with pytest.raises(ValueError, match="tracked changes"):
        metrics._assert_source_checkout_matches_head(source_root)

    checkout = source_root.parents[1]
    subprocess.run(
        ["git", "-C", str(checkout), "add", "backend/src/gridlens/module.py"],
        check=True,
    )
    with pytest.raises(ValueError, match="tracked changes"):
        metrics._assert_source_checkout_matches_head(source_root)
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "reset",
            "--quiet",
            "HEAD",
            "--",
            "backend/src/gridlens/module.py",
        ],
        check=True,
    )
    source_file.write_text("VALUE = 1\n")
    untracked_source = source_root / "gridlens" / "untracked.py"
    untracked_source.write_text("VALUE = 3\n")
    with pytest.raises(ValueError, match="untracked Python source"):
        metrics._assert_source_checkout_matches_head(source_root)


def test_source_guard_allows_tests_only_changes_and_ignored_pycache(
    tmp_path: Path,
) -> None:
    metrics = _metrics_module()
    source_root = _source_checkout(tmp_path)
    checkout = source_root.parents[1]
    tests_dir = checkout / "backend" / "tests"
    test_file = tests_dir / "fixture.py"
    test_file.write_text("assert 1 + 1 == 2\n")
    subprocess.run(
        ["git", "-C", str(checkout), "add", "backend/tests/fixture.py"],
        check=True,
    )
    (tests_dir / "new_test.py").write_text("assert True\n")
    pycache = source_root / "gridlens" / "__pycache__"
    pycache.mkdir()
    (pycache / "module.cpython-311.pyc").write_bytes(b"generated")

    assert metrics._assert_source_checkout_matches_head(source_root)
