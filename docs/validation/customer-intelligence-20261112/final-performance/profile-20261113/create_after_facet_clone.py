"""Create a controlled same-seed test clone for the facet follow-up phase."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(os.environ.get("PERF_SOURCE_ROOT", "/workspace/gl3-page-payload-opt-20261113")).resolve()
SRC = ROOT / "backend" / "src"
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))

from gridlens.intelligence.saved_browse import POLICY_VERSION  # noqa: E402

BASE_DB = "gl3_mission_rollup_scale_payload_20261113_test"
AFTER_DB = "gl3_mission_rollup_scale_payload_after_facet_20261113_test"
RECEIPT = OUT / "controlled_policy_binding_adjustment_after_facet.json"

SNAPSHOT_QUERIES = {
    "state": "select id,input_revision,generation_id,full_revision,structural_revision,prepared_generation_id,stale_since from browse_state where id=1",
    "generation": "select id,input_revision,policy_version,built_at,valid_from,valid_until,row_count,digest from browse_generations where id=(select generation_id from browse_state where id=1)",
    "projects": "select count(*) n, md5(coalesce(string_agg(md5(id::text||'|'||identity_key||'|'||name||'|'||coalesce(location,'')||'|'||source_id||'|'||external_id||'|'||asset_type||'|'||identity_facts::text), '' order by id::text),'')) h from projects",
    "browse_rows": "select count(*) n, md5(coalesce(string_agg(md5(project_id::text||'|'||need_id::text||'|'||generation_id::text||'|'||compact::text), '' order by project_id::text,need_id::text),'')) h from browse_rows",
    "memberships": "select count(*) n, md5(coalesce(string_agg(md5(generation_id::text||'|'||project_id::text||'|'||company_identity_id::text||'|'||role||'|'||organization_name), '' order by generation_id::text,project_id::text,company_identity_id::text,role),'')) h from browse_customer_memberships",
    "power_needs": "select count(*) n, md5(coalesce(string_agg(md5(id::text||'|'||project_id::text), '' order by id::text),'')) h from power_needs",
    "evidence": "select count(*) n, md5(coalesce(string_agg(md5(id::text||'|'||observation_id::text||'|'||content_hash), '' order by id::text),'')) h from evidence",
}


def snapshot(url):
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            result = {}
            for name, query in SNAPSHOT_QUERIES.items():
                row = connection.execute(text(query)).mappings().one()
                result[name] = {
                    key: value.isoformat() if hasattr(value, "isoformat") else str(value) if hasattr(value, "hex") else value
                    for key, value in row.items()
                }
            return result
    finally:
        engine.dispose()


def main() -> None:
    if RECEIPT.exists():
        raise SystemExit(f"Refusing to overwrite {RECEIPT}")
    base_url = make_url(os.environ["DATABASE_URL"])
    if base_url.host not in {"127.0.0.1", "localhost", "::1"} or base_url.query:
        raise SystemExit("Refusing non-loopback or routed database URLs")
    admin = create_engine(base_url.set(database="postgres"))
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            if connection.execute(text("select 1 from pg_database where datname=:name"), {"name": AFTER_DB}).first():
                raise SystemExit(f"Refusing existing database {AFTER_DB}")
            active = connection.execute(
                text("select count(*) from pg_stat_activity where datname=:name"), {"name": BASE_DB}
            ).scalar_one()
            if active:
                raise SystemExit(f"Refusing to clone a database with {active} active sessions")
            connection.exec_driver_sql(f"CREATE DATABASE {AFTER_DB} WITH TEMPLATE {BASE_DB}")
    finally:
        admin.dispose()

    base = snapshot(base_url.set(database=BASE_DB))
    clone_url = base_url.set(database=AFTER_DB)
    clone_before = snapshot(clone_url)
    if base != clone_before:
        raise SystemExit("Template-clone rows/UUID/content fingerprints differ from source")
    generation_id = base["state"]["generation_id"]
    old_policy = base["generation"]["policy_version"]
    if base["state"]["prepared_generation_id"] is not None:
        raise SystemExit("Refusing to rebind a prepared generation")
    engine = create_engine(clone_url)
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text("update browse_generations set policy_version=:new where id=:id and policy_version=:old"),
                {"new": POLICY_VERSION, "id": generation_id, "old": old_policy},
            )
            if result.rowcount != 1:
                raise SystemExit(f"Expected one metadata binding row, got {result.rowcount}")
    finally:
        engine.dispose()
    after = snapshot(clone_url)
    expected = {key: dict(value) for key, value in base.items()}
    expected["generation"]["policy_version"] = POLICY_VERSION
    if after != expected:
        raise SystemExit("The candidate clone differs beyond the single policy_version field")

    digest = hashlib.sha256()
    file_hashes = {}
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        file_hashes[rel] = content_hash
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(bytes.fromhex(content_hash))
    receipt = {
        "adjustment_type": "synthetic-test-only-policy-binding",
        "reason": "The canonical facet optimization changes customer_results.py, which participates in saved-browse policy fingerprinting. The full synthetic seed is cloned unchanged so before/after page and facet results refer to identical records.",
        "database": AFTER_DB,
        "source_database": BASE_DB,
        "source_head": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        "source_backend_src_manifest_sha256": digest.hexdigest(),
        "source_backend_src_py_file_sha256": file_hashes,
        "generation_id": generation_id,
        "old_policy_version": old_policy,
        "new_policy_version": POLICY_VERSION,
        "only_database_field_changed": "browse_generations.policy_version for browse_state.generation_id",
        "source_snapshot_before_clone": base,
        "clone_snapshot_before_rebind": clone_before,
        "candidate_snapshot_after_rebind": after,
        "snapshot_check": "Projects, browse rows, memberships, needs, evidence, generation id/revisions/digest/content hashes all match; only policy_version differs as listed.",
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "database": AFTER_DB,
        "generation_id": generation_id,
        "old_policy_version": old_policy,
        "new_policy_version": POLICY_VERSION,
        "source_manifest_sha256": digest.hexdigest(),
        "snapshot_equal_except_policy_version": True,
    }, indent=2))


if __name__ == "__main__":
    main()
