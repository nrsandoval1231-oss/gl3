"""Bounded diagnostics for the original PR87 GitHub Actions publication failure."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

TARGET = "tests/integration/test_power_need_briefs.py"
ORIGINAL_FAILING_TEST = (
    TARGET + "::test_authenticated_brief_request_and_worker_keep_saved_maps_current"
)
EXPECTED_TOTAL_COLLECTION = 2153
EXPECTED_PREFIX = 360
EXPECTED_TARGET_CASES = 4
MAX_REPEAT_COUNT = 20
MAX_FAILURE_LOG_BYTES = 262144
_URL_RE = re.compile(r"(?i)(?:postgres(?:ql)?(?:\+[^:/\s]+)?|https?)://[^\s\"'<>]+")


class RedactingStream:
    """Redact database/auth values and all URLs from pytest stdout/stderr."""

    def __init__(self, stream):
        self._stream = stream
        self._secrets = tuple(
            value for key in (
                "DATABASE_URL", "TEST_DATABASE_URL", "POSTGRES_PASSWORD",
                "SESSION_SECRET", "APP_PASSWORD_HASH",
            ) if (value := os.environ.get(key))
        )

    def write(self, value):
        for secret in self._secrets:
            value = value.replace(secret, "[REDACTED]")
        value = _URL_RE.sub("[REDACTED_URL]", value)
        return self._stream.write(value)

    def __getattr__(self, name):
        return getattr(self._stream, name)


sys.stdout = RedactingStream(sys.stdout)
sys.stderr = RedactingStream(sys.stderr)


def _mark(label: str, **fields: Any) -> None:
    entry = {
        "kind": label,
        "wall_utc": datetime.now(UTC).isoformat(),
        "monotonic": time.monotonic(),
        **fields,
    }
    line = json.dumps(entry, default=str)
    print(line, flush=True)
    if (label.endswith(("_exception", "_error")) or label in {
            "pytest_failure", "probe_install_error", "collection_counts",
            "repeat_collection_counts", "repeat_plan", "diagnostic_complete",
    }):
        sidecar = os.environ.get("DIAGNOSTIC_FAILURE_LOG")
        if sidecar:
            try:
                if not os.path.exists(sidecar) or os.path.getsize(sidecar) < MAX_FAILURE_LOG_BYTES:
                    with open(sidecar, "a", encoding="utf-8") as output:
                        output.write(line[:16000] + "\n")
            except OSError:
                pass


def _best_effort_mark(label: str, **fields: Any) -> None:
    try:
        _mark(label, **fields)
    except Exception:
        # Instrumentation must not replace the operation or its exception.
        pass


def _safe_error(exc: BaseException) -> dict[str, str | None]:
    original = getattr(exc, "orig", None)
    return {
        "exception_class": type(exc).__name__,
        "sqlstate": getattr(original, "sqlstate", None) or getattr(original, "pgcode", None),
    }


def _install_probe(item: Any, probe_errors: list[str]) -> tuple[Any, ...] | None:
    if not item.nodeid.startswith(ORIGINAL_FAILING_TEST):
        return None
    from sqlalchemy import event, select, text
    from gridlens.intelligence import saved_browse, worker_browse
    from gridlens.persistence.models import BrowseGeneration, BrowseState

    reader = saved_browse.current_generation
    refresher = saved_browse.refresh_project_changes
    hook = worker_browse._before_commit
    installer = worker_browse.install_worker_publication
    policy = saved_browse.POLICY_VERSION
    import logging

    def read_state(session, *, effective_now=None):
        with session.no_autoflush:
            rows = session.execute(text(
                "SELECT s.input_revision, s.full_revision, s.generation_id, "
                "g.input_revision AS published_revision, g.valid_from AS published_valid_from, "
                "g.valid_until AS published_valid_until, g.policy_version AS published_policy, "
                "s.prepared_generation_id, p.input_revision AS prepared_revision, "
                "p.valid_from AS prepared_valid_from, p.valid_until AS prepared_valid_until, "
                "p.policy_version AS prepared_policy FROM browse_state s "
                "LEFT JOIN browse_generations g ON g.id=s.generation_id "
                "LEFT JOIN browse_generations p ON p.id=s.prepared_generation_id WHERE s.id=1"
            )).mappings().all()
        safe_rows = []
        for row in rows:
            valid_from = row["published_valid_from"]
            valid_until = row["published_valid_until"]
            prepared_from = row["prepared_valid_from"]
            prepared_until = row["prepared_valid_until"]
            safe_rows.append({
                "input_revision": row["input_revision"],
                "full_revision": row["full_revision"],
                "published_revision": row["published_revision"],
                "generation_id_present": row["generation_id"] is not None,
                "prepared_generation_present": row["prepared_generation_id"] is not None,
                "valid_from": valid_from,
                "valid_until": valid_until,
                "policy_matches": row["published_policy"] == policy,
                "input_revision_matches": row["input_revision"] == row["published_revision"],
                "valid_from_le_now": effective_now is not None and valid_from is not None and valid_from <= effective_now,
                "valid_until_gt_now": effective_now is not None and valid_until is not None and valid_until > effective_now,
                "prepared_revision": row["prepared_revision"],
                "prepared_valid_from": prepared_from,
                "prepared_valid_until": prepared_until,
                "prepared_policy_matches": row["prepared_policy"] == policy,
                "prepared_input_revision_matches": row["input_revision"] == row["prepared_revision"],
                "prepared_valid_from_le_now": effective_now is not None and prepared_from is not None and prepared_from <= effective_now,
                "prepared_valid_until_gt_now": effective_now is not None and prepared_until is not None and prepared_until > effective_now,
            })
        return safe_rows

    def traced_reader(session, *, now=None):
        started = time.monotonic()
        _best_effort_mark("current_generation_enter", supplied_now=now)
        try:
            value = reader(session, now=now)
        except Exception as original_exc:
            exact_now = None
            tb = original_exc.__traceback__
            while tb:
                if tb.tb_frame.f_code.co_name == "current_generation":
                    exact_now = tb.tb_frame.f_locals.get("now")
                tb = tb.tb_next
            try:
                rows = read_state(session, effective_now=exact_now)
                _best_effort_mark("current_generation_exception", supplied_now=now,
                                  exact_frame_now=exact_now, failed_predicates=rows,
                                  elapsed_seconds=time.monotonic() - started,
                                  **_safe_error(original_exc))
            except Exception as probe_exc:
                _best_effort_mark("current_generation_failure_snapshot_error",
                                  **_safe_error(probe_exc))
            raise
        _best_effort_mark("current_generation_return", supplied_now=now,
                          generation_input_revision=value.input_revision,
                          policy_matches=value.policy_version == policy,
                          elapsed_seconds=time.monotonic() - started)
        return value

    def traced_refresh(session, **kwargs):
        started = time.monotonic()
        try:
            state = read_state(session)
            with session.no_autoflush:
                dirty = session.scalar(text("SELECT current_setting('gridlens.browse_dirty', true)")) == "1"
                eligibility_now = datetime.now(UTC)
                eligible = session.scalar(
                    select(BrowseState.id)
                    .join(BrowseGeneration, BrowseGeneration.id == BrowseState.generation_id)
                    .where(
                        BrowseState.id == 1,
                        BrowseState.input_revision != BrowseGeneration.input_revision,
                        BrowseState.full_revision <= BrowseGeneration.input_revision,
                        BrowseGeneration.policy_version == policy,
                        BrowseGeneration.valid_from <= eligibility_now,
                        BrowseGeneration.valid_until > eligibility_now,
                    )
                )
            _best_effort_mark("worker_refresh_enter", dirty=dirty, worker_eligible=eligible is not None,
                              eligibility_now=eligibility_now, state=state)
        except Exception as probe_exc:
            _best_effort_mark("worker_refresh_probe_read_error", **_safe_error(probe_exc))
        try:
            value = refresher(session, **kwargs)
        except Exception as original_exc:
            _best_effort_mark("worker_refresh_exception", elapsed_seconds=time.monotonic() - started,
                              **_safe_error(original_exc))
            raise
        _best_effort_mark("worker_refresh_return", refresh_return=value,
                          elapsed_seconds=time.monotonic() - started)
        return value

    def traced_hook(session):
        started = time.monotonic()
        _best_effort_mark("worker_before_commit_enter", nested=session.in_nested_transaction(),
                          refresh_in_progress=bool(session.info.get("worker_browse_refresh")))
        try:
            value = hook(session)
        except Exception as original_exc:
            _best_effort_mark("worker_before_commit_exception",
                              elapsed_seconds=time.monotonic() - started,
                              **_safe_error(original_exc))
            raise
        _best_effort_mark("worker_before_commit_return", elapsed_seconds=time.monotonic() - started)
        return value

    def traced_installer(factory):
        value = installer(factory)
        try:
            registered = event.contains(factory, "before_commit", traced_hook)
        except Exception as probe_exc:
            registered = None
            _best_effort_mark("worker_hook_registration_probe_error", **_safe_error(probe_exc))
        _best_effort_mark("worker_hook_registered", traced_hook_is_registered=registered)
        if registered is not True:
            probe_errors.append("worker before_commit hook wrapper was not registered")
            _best_effort_mark("probe_install_error", reason="worker hook wrapper registration failed")
        return value

    saved_browse.current_generation = traced_reader
    saved_browse.refresh_project_changes = traced_refresh
    worker_browse._before_commit = traced_hook
    worker_browse.install_worker_publication = traced_installer
    _best_effort_mark("target_test_setup", nodeid=item.nodeid,
                      worker_logger_disabled=worker_browse.logger.disabled,
                      root_handlers=[type(handler).__name__ for handler in logging.getLogger().handlers])
    return saved_browse, reader, refresher, worker_browse, hook, installer


class Probe:
    def __init__(self, mode: str):
        self.mode = mode
        self.selected_count = 0
        self.passed_cases = 0
        self.failed_cases = 0
        self.skipped_cases = 0
        self.executed_nodes: set[str] = set()
        self.failed_nodes: set[str] = set()
        self.probe_errors: list[str] = []

    def pytest_collection_modifyitems(self, config, items):
        target_indexes = [i for i, item in enumerate(items) if item.nodeid.startswith(TARGET)]
        target_cases = [item for item in items if item.nodeid.startswith(ORIGINAL_FAILING_TEST)]
        if self.mode == "full-prefix":
            prefix_size = target_indexes[-1] + 1 if target_indexes else 0
            _mark("collection_counts", expected_total=EXPECTED_TOTAL_COLLECTION,
                  actual_total=len(items), expected_prefix=EXPECTED_PREFIX,
                  actual_prefix=prefix_size, expected_target_cases=EXPECTED_TARGET_CASES,
                  actual_target_cases=len(target_cases))
            if (len(items) != EXPECTED_TOTAL_COLLECTION or prefix_size != EXPECTED_PREFIX
                    or len(target_cases) != EXPECTED_TARGET_CASES):
                raise pytest.UsageError("Original collection/prefix/target counts changed")
            removed = items[prefix_size:]
            del items[prefix_size:]
            self.selected_count = len(items)
            config.hook.pytest_deselected(items=removed)
            _mark("collection_prefix", collected=len(items), through=TARGET)
        elif self.mode == "repeat-parameters":
            _mark("repeat_collection_counts", expected_target_cases=EXPECTED_TARGET_CASES,
                  actual_target_cases=len(target_cases), actual_selected=len(items))
            if len(items) != EXPECTED_TARGET_CASES or len(target_cases) != EXPECTED_TARGET_CASES:
                raise pytest.UsageError("Expected exactly four original parameter cases")
            self.selected_count = len(items)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item):
        restore = None
        if item.nodeid.startswith(ORIGINAL_FAILING_TEST):
            try:
                restore = _install_probe(item, self.probe_errors)
            except Exception as probe_exc:
                self.probe_errors.append(type(probe_exc).__name__)
                _best_effort_mark("probe_install_error", **_safe_error(probe_exc))
        try:
            yield
        finally:
            if restore:
                saved_browse, reader, refresher, worker_browse, hook, installer = restore
                saved_browse.current_generation = reader
                saved_browse.refresh_project_changes = refresher
                worker_browse._before_commit = hook
                worker_browse.install_worker_publication = installer
                _best_effort_mark("probe_restored", nodeid=item.nodeid,
                                  reader_restored=saved_browse.current_generation is reader,
                                  refresh_restored=saved_browse.refresh_project_changes is refresher,
                                  hook_restored=worker_browse._before_commit is hook,
                                  installer_restored=worker_browse.install_worker_publication is installer)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        report = outcome.get_result()
        if report.when == "call":
            self.executed_nodes.add(item.nodeid)
            if report.passed:
                self.passed_cases += 1
            elif report.failed:
                self.failed_cases += 1
                self.failed_nodes.add(item.nodeid)
            elif report.skipped:
                self.skipped_cases += 1
        elif report.when == "setup" and report.failed:
            self.executed_nodes.add(item.nodeid)
            self.failed_nodes.add(item.nodeid)
            self.failed_cases += 1
        elif report.when == "setup" and report.skipped:
            self.executed_nodes.add(item.nodeid)
            self.skipped_cases += 1
        if report.failed:
            _best_effort_mark("pytest_failure", nodeid=item.nodeid, phase=report.when)

    def pytest_sessionfinish(self, session, exitstatus):
        if self.probe_errors and int(exitstatus) == int(pytest.ExitCode.OK):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
        _best_effort_mark("session_summary", selected_cases=self.selected_count,
                          passed_cases=self.passed_cases, failed_cases=self.failed_cases,
                          executed_cases=len(self.executed_nodes),
                          skipped_cases=self.skipped_cases,
                          probe_errors=self.probe_errors,
                          exit_status=int(session.exitstatus))


def run_one(selection: str, mode: str) -> int:
    args = (["tests", "-q", "-s", "--tb=no", "--maxfail=1",
             "-o", "cache_dir=/tmp/pr87-publication-pytest-cache"] if mode == "full-prefix"
            else [selection, "-q", "-s", "--tb=no", "--maxfail=1",
                  "-o", "cache_dir=/tmp/pr87-publication-pytest-cache"])
    _mark("pytest_start", selection=selection, mode=mode)
    result = pytest.main(args, plugins=[Probe(mode)])
    _mark("pytest_finish", selection=selection, exit_code=int(result))
    return int(result)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--single", action="store_true", help="Run one original four-case selection")
    parser.add_argument("--repeat-count", type=int, default=20)
    options = parser.parse_args()
    if options.repeat_count < 1 or options.repeat_count > MAX_REPEAT_COUNT:
        parser.error(f"repeat-count must be between 1 and {MAX_REPEAT_COUNT}")
    if options.single:
        return run_one(ORIGINAL_FAILING_TEST, "repeat-parameters")

    failures = int(run_one("full-prefix", "full-prefix") != 0)
    script = str(Path(__file__).resolve())
    total_expected = options.repeat_count * EXPECTED_TARGET_CASES
    cases_seen = 0
    _mark("repeat_plan", iterations=options.repeat_count,
          cases_per_iteration=EXPECTED_TARGET_CASES, expected_parameter_cases=total_expected)
    for iteration in range(1, options.repeat_count + 1):
        _mark("repeat_start", iteration=iteration, count=options.repeat_count,
              test=ORIGINAL_FAILING_TEST, expected_cases=EXPECTED_TARGET_CASES)
        process = subprocess.Popen([sys.executable, script, "--single"],
                                   env=os.environ.copy(), stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        actual_selected = 0
        actual_executed = 0
        actual_passed = 0
        actual_skipped = 0
        if process.stdout:
            for line in process.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                try:
                    event_record = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if event_record.get("kind") == "repeat_collection_counts":
                    actual_selected = int(event_record.get("actual_selected", 0))
                elif event_record.get("kind") == "session_summary":
                    actual_selected = int(event_record.get("selected_cases", actual_selected))
                    actual_executed = int(event_record.get("executed_cases", 0))
                    actual_passed = int(event_record.get("passed_cases", 0))
                    actual_skipped = int(event_record.get("skipped_cases", 0))
        result_code = process.wait()
        cases_seen += actual_executed
        _mark("repeat_finish", iteration=iteration, expected_cases=EXPECTED_TARGET_CASES,
              selected_cases=actual_selected, actual_executed_cases=actual_executed,
              passed_cases=actual_passed, skipped_cases=actual_skipped, exit_code=result_code)
        failures += (result_code != 0 or actual_selected != EXPECTED_TARGET_CASES
                     or actual_executed != EXPECTED_TARGET_CASES
                     or actual_passed != EXPECTED_TARGET_CASES or actual_skipped != 0)
    _mark("diagnostic_complete", failures=failures, expected_parameter_cases=total_expected,
          counted_parameter_cases=cases_seen)
    return int(failures > 0 or cases_seen != total_expected)


if __name__ == "__main__":
    raise SystemExit(main())
