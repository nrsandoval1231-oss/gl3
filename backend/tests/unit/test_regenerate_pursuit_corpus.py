"""Offline wrapper boundaries; no database or live acquisition."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "regenerate_pursuit_corpus",
    Path(__file__).resolve().parents[3] / "scripts" / "regenerate_pursuit_corpus.py",
)
assert SPEC and SPEC.loader
wrapper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wrapper)


@pytest.mark.parametrize(
    "name", ["gridlens", "gridlens_test", "postgres", "gl3_regen_x;DROP", "../x"]
)
def test_refuses_unsafe_database_names(name):
    with pytest.raises(ValueError):
        wrapper.database_name(name)


def test_selection_rejects_duplicates_unsupported_and_oversize():
    row = {"source_id": "austin-building-permits", "external_id": "123"}
    assert wrapper.selection_rows([row]) == [row]
    for rows in (
        [row, row],
        [row] * 41,
        [],
        [{**row, "source_id": "fake"}],
        [{**row, "source_id": "federal-register-eis", "external_id": "2026-12345"}],
        [{**row, "external_id": "x' OR 1=1"}],
    ):
        with pytest.raises(ValueError):
            wrapper.selection_rows(rows)


def test_artifacts_are_contained_and_write_once(tmp_path):
    out = tmp_path / ".artifacts" / "run"
    wrapper.fresh_directory(out)
    with pytest.raises(FileExistsError):
        wrapper.fresh_directory(out)
    with pytest.raises(ValueError):
        wrapper.fresh_directory(tmp_path / "public")
    for relative in ("../escape", "/tmp/escape", "sub/record.json"):
        with pytest.raises(ValueError):
            wrapper.child_file(out, relative)


def test_mocked_symlink_boundary_is_rejected_on_every_platform(tmp_path, monkeypatch):
    out = tmp_path / ".artifacts" / "run"
    wrapper.fresh_directory(out)
    link = out / "link"
    real_is_symlink = Path.is_symlink

    def mocked_is_symlink(path):
        return path == link or real_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", mocked_is_symlink)
    with pytest.raises(ValueError):
        wrapper.child_file(out, link.name)


def test_real_symlink_boundary_when_supported(tmp_path):
    out = tmp_path / ".artifacts" / "run"
    wrapper.fresh_directory(out)
    target = out / "target.json"
    target.write_text("{}")
    link = out / "link"
    try:
        link.symlink_to(target)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege is unavailable")
        raise
    with pytest.raises(ValueError):
        wrapper.child_file(out, link.name)


def test_collection_preserves_failure_and_rendered_record_receipts(tmp_path, monkeypatch):
    from gridlens.ingestion.adapters import pursuit_acquisition

    calls = []

    def acquire(source_id, external_id, **kwargs):
        calls.append(kwargs)
        kwargs["before_request"]("https://data.austintexas.gov/exact/" + external_id)
        if external_id == "bad":
            raise TimeoutError("secret must not appear")
        return {"id": source_id}, {"document_number": external_id}

    monkeypatch.setattr(pursuit_acquisition, "acquire_registered_record", acquire)
    monkeypatch.setattr(wrapper, "candidate_identity", lambda: {"commit": "offline"})
    selection = tmp_path / "selection.json"
    wrapper.write_once(
        selection,
        {
            "records": [
                {"source_id": "austin-building-permits", "external_id": value}
                for value in ("123", "bad")
            ]
        },
    )
    out = tmp_path / ".artifacts" / "collection"
    result = wrapper.collect(selection, out)
    assert [a["status"] for a in result["attempts"]] == ["collected", "failed"]
    assert result["attempts"][1]["error"] == "TimeoutError"
    assert "secret" not in (out / "collection.json").read_text()
    assert result["attempts"][0]["artifact_sha256"] == wrapper.file_hash(out / "record-00.json")
    assert "not raw response" in result["attempts"][0]["representation"]
    assert (out / "request-01.json").exists()
    assert all(call["max_bytes"] == 750_000 for call in calls)


def test_request_callbacks_keep_their_row_receipts_after_iteration(tmp_path, monkeypatch):
    from gridlens.ingestion.adapters import pursuit_acquisition

    callbacks = []

    def acquire(source_id, external_id, **kwargs):
        callbacks.append((external_id, kwargs["before_request"]))
        return {"id": source_id}, {"document_number": external_id}

    monkeypatch.setattr(pursuit_acquisition, "acquire_registered_record", acquire)
    monkeypatch.setattr(wrapper, "candidate_identity", lambda: {"commit": "offline"})
    selection = tmp_path / "selection.json"
    wrapper.write_once(
        selection,
        {
            "records": [
                {"source_id": "austin-building-permits", "external_id": value}
                for value in ("123", "456")
            ]
        },
    )
    out = tmp_path / ".artifacts" / "collection"
    result = wrapper.collect(selection, out)
    for external_id, callback in callbacks:
        callback("https://data.austintexas.gov/exact/" + external_id)

    assert result["attempts"][0]["requests"][0]["url"].endswith("/123")
    assert result["attempts"][1]["requests"][0]["url"].endswith("/456")
    assert (out / "request-00.json").exists()
    assert (out / "request-01.json").exists()


def test_ingestion_rejects_tampered_artifact_before_database_work(tmp_path, monkeypatch):
    from gridlens.ingestion import registry

    source = {"id": "austin-building-permits"}
    monkeypatch.setattr(registry, "load_registry", lambda: [source])
    artifact = tmp_path / "record.json"
    wrapper.write_once(artifact, {"source": source, "record": {"document_number": "123"}})
    collection = tmp_path / "collection.json"
    attempt = {
        "source_id": source["id"],
        "external_id": "123",
        "status": "collected",
        "artifact": artifact.name,
        "artifact_sha256": wrapper.file_hash(artifact),
    }
    wrapper.write_once(collection, {"attempts": [attempt]})
    assert len(wrapper.checked_collection(collection)) == 1
    artifact.write_text("{}")
    with pytest.raises(ValueError, match="hash mismatch"):
        wrapper.checked_collection(collection)


def partial_manifest():
    return {
        "schema_version": 1,
        "kind": "reingested",
        "corpus_id": "partial",
        "database_name": "gl3_regen_diagnostic",
        "isolated_database": True,
        "cases": [
            {
                "category": "chicago_conversion",
                "need_id": "00000000-0000-0000-0000-000000000001",
                "selection_reason": "Native cited permit conversion scope",
            }
        ],
    }


def test_partial_validation_cannot_admit_full_or_invalid_manifests():
    import copy

    manifest = partial_manifest()
    assert len(wrapper.validate_diagnostic(manifest)) == 4
    for field, value in (
        ("kind", "fixture"),
        ("database_name", "gridlens"),
        ("isolated_database", False),
        ("corpus_id", ""),
        ("cases", []),
        ("cases", manifest["cases"] * 5),
        ("cases", manifest["cases"] * 2),
    ):
        invalid = {**manifest, field: value}
        with pytest.raises(ValueError):
            wrapper.validate_diagnostic(invalid)
    for field, value in (
        ("category", "invented"),
        ("selection_reason", ""),
        ("need_id", "invalid"),
    ):
        invalid = copy.deepcopy(manifest)
        invalid["cases"][0][field] = value
        with pytest.raises(ValueError):
            wrapper.validate_diagnostic(invalid)


def test_partial_projection_never_claims_full_acceptance():
    original = {
        "mechanical_gates_passed": True,
        "retained_corpus_proof": True,
        "operator_attested_retained_corpus_validation": True,
        "full_five_cohort_acceptance": True,
        "questions": ["preserved"],
    }
    result = wrapper.diagnostic_projection(original, ["oil_and_gas"], {"error": "ValueError"}, True)
    assert result["scope"] == "partial_diagnostic"
    assert result["passed"] is True  # Successful diagnostic, never full acceptance.
    assert result["full_five_cohort_acceptance"] is False
    assert result["retained_corpus_proof"] is False
    assert result["operator_attested_retained_corpus_validation"] is False
    assert result["questions"] == ["preserved"]
    changed = wrapper.diagnostic_projection(original, [], {}, False)
    assert changed["mechanical_gates_passed"] is False
    assert changed["passed"] is False


def test_diagnostic_requires_both_flags_before_reading_files(tmp_path):
    for execute, allow in ((False, False), (True, False), (False, True)):
        with pytest.raises(ValueError, match="requires --execute"):
            wrapper.diagnostic(
                tmp_path / "absent.json", tmp_path, execute=execute, allow_public_research=allow
            )


def test_safe_acquisition_enum_but_not_arbitrary_exception_text():
    from gridlens.ingestion.adapters.bounded_http import AcquisitionFailure

    assert wrapper.safe_error(AcquisitionFailure("acquisition_process_failed")) == {
        "error": "AcquisitionFailure",
        "acquisition_error_code": "acquisition_process_failed",
    }
    assert "acquisition_error_code" not in wrapper.safe_error(ValueError("credential"))
    assert "acquisition_error_code" not in wrapper.safe_error(AcquisitionFailure("https://secret"))


def test_terminal_write_is_fenced_before_any_mutation(monkeypatch):
    from types import SimpleNamespace

    from gridlens.jobs import queue

    job = SimpleNamespace(status="running", error=None, lease_owner="new-worker", lease_until=123)

    def lost(*args):
        raise RuntimeError("Worker lease fence lost")

    monkeypatch.setattr(queue, "assert_fence", lost)
    for error in (None, "TimeoutError"):
        with pytest.raises(RuntimeError):
            wrapper.finish_ingestion_job(None, "id", 1, error=error)
        assert job.status == "running" and job.lease_owner == "new-worker"
    monkeypatch.setattr(queue, "assert_fence", lambda *args: job)
    wrapper.finish_ingestion_job(None, "id", 2)
    assert job.status == "succeeded" and job.lease_owner is None


def test_restore_inventory_detects_mutable_fields_and_duplicate_rows(monkeypatch):
    from types import SimpleNamespace

    import sqlalchemy

    rows = [{"id": "same", "status": "queued"}]
    connection = SimpleNamespace(
        dialect=SimpleNamespace(
            identifier_preparer=SimpleNamespace(quote=lambda name: '"' + name + '"')
        )
    )
    session = SimpleNamespace(connection=lambda: connection, scalars=lambda query: iter(rows))
    monkeypatch.setattr(
        sqlalchemy, "inspect", lambda conn: SimpleNamespace(get_table_names=lambda schema: ["jobs"])
    )
    before = wrapper.full_table_inventories(session)
    rows[0]["status"] = "failed"
    changed = wrapper.full_table_inventories(session)
    assert before["jobs"]["sha256"] != changed["jobs"]["sha256"]
    rows.append(dict(rows[0]))
    duplicated = wrapper.full_table_inventories(session)
    assert duplicated["jobs"]["count"] == 2
    assert duplicated["jobs"]["sha256"] != changed["jobs"]["sha256"]


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///gl3_regen_test",
        "postgresql+psycopg2://user:pass@localhost:5432/gl3_regen_test",
        "postgresql://user:pass@/gl3_regen_test",
        "postgresql://user:pass@localhost/gl3_regen_test",
        "postgresql://localhost:5432/gl3_regen_test",
        "postgresql://user:pass@localhost:5432/gl3_regen_test?host=/socket",
        "postgresql://user:pass@localhost:5432/gl3_regen_test?hostaddr=192.0.2.1",
        "postgresql://user:pass@localhost:5432/gl3_regen_test?service=alternate",
        "postgresql://user:pass@localhost:5432/gl3_regen_test?options=anything",
        "postgresql://user:pass@localhost:5432/gl3_regen_test?sslmode=require&sslmode=disable",
    ],
)
def test_connection_rejects_ambiguous_server_or_options(monkeypatch, url):
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ValueError):
        wrapper.configured_url()


@pytest.mark.parametrize("driver", ["postgresql", "postgresql+psycopg"])
def test_connection_accepts_explicit_postgresql_and_scalar_tls(monkeypatch, driver):
    monkeypatch.setenv(
        "DATABASE_URL",
        driver + "://user@localhost:5432/gl3_regen_test?sslmode=require&sslrootcert=/tmp/ca.pem",
    )
    url = wrapper.configured_url()
    assert url.host == "localhost" and url.port == 5432 and url.username == "user"
    assert url.password is None
    assert url.query["sslmode"] == "require"
