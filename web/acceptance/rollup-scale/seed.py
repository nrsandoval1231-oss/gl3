"""Seed one empty, dedicated loopback PostgreSQL database for real browser QA."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import MetaData, create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND / "tests" / "integration"))
sys.path.insert(0, str(BACKEND / "src"))
sys.path.insert(0, str(REPO / "web" / "acceptance" / "rollup-scale"))

from rollup_scale_fixture import seed_scale_corpus  # noqa: E402
from account_fixture import seed_resolved_operator_accounts  # noqa: E402
from gridlens.settings import get_settings  # noqa: E402


def checked_database_url(value: str) -> str:
    parsed = make_url(value)
    routing_overrides = {
        "host", "hostaddr", "port", "dbname", "database", "user", "username",
        "password", "service", "servicefile", "options", "target_session_attrs",
    }
    if routing_overrides.intersection(parsed.query):
        raise SystemExit("Refusing database URL with connection-routing query overrides.")
    if any(os.environ.get(key) for key in (
        "PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGUSER", "PGOPTIONS",
        "PGSERVICE", "PGSERVICEFILE",
    )):
        raise SystemExit("Refusing inherited libpq connection-routing environment overrides.")
    if urlsplit(value).fragment:
        raise SystemExit("Refusing database URL fragments.")
    host = (parsed.host or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Refusing to seed a non-loopback database host.")
    if not isinstance(parsed.port, int) or not 1 <= parsed.port <= 65535:
        raise SystemExit("Refusing database URL without an explicit valid port.")
    database = (parsed.database or "").lower()
    if "_rollup_scale_" not in database or not database.endswith("_test"):
        raise SystemExit("Refusing to seed a database unless its name contains _rollup_scale_ and ends in _test.")
    if parsed.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise SystemExit("The real-backend browser lane requires loopback PostgreSQL.")
    from sqlalchemy.dialects.postgresql.psycopg import dialect

    args, effective = dialect().create_connect_args(parsed)
    if args or (effective.get("host") or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Refusing effective connection parameters outside loopback.")
    if effective.get("port") != parsed.port or effective.get("dbname") != parsed.database:
        raise SystemExit("Refusing effective connection parameters that differ from the pinned URL.")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-output", required=True, type=Path)
    parser.add_argument("--rows", type=int, default=2098)
    args = parser.parse_args()
    if args.rows < 2000:
        parser.error("--rows must be at least 2000")

    settings = get_settings()
    database_url = checked_database_url(settings.database_url)
    if not settings.test_database_url:
        raise SystemExit("TEST_DATABASE_URL must be configured separately from the browser database.")
    browser_db = urlsplit(database_url)
    unit_test_db = urlsplit(settings.test_database_url)
    if (browser_db.hostname, browser_db.port, browser_db.path) == (unit_test_db.hostname, unit_test_db.port, unit_test_db.path):
        raise SystemExit("Refusing to use the same database for DATABASE_URL and TEST_DATABASE_URL.")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        if "alembic_version" not in inspector.get_table_names():
            raise SystemExit("Refusing to seed a database without the expected migrated schema.")
        metadata = MetaData()
        metadata.reflect(bind=engine)
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
            if revision != "0053_browse_structural_fence":
                raise SystemExit("Refusing to seed unless the dedicated database is migrated to 0053_browse_structural_fence.")
            for table in metadata.sorted_tables:
                if table.name == "alembic_version":
                    continue
                if table.name == "browse_state":
                    rows = connection.execute(select(table)).mappings().all()
                    if len(rows) != 1:
                        raise SystemExit("Refusing to seed unless browse_state contains only the migration-owned singleton.")
                    row = rows[0]
                    # Schemas 0051-0053 add only canonical need aliases, lookup indexes and the identity fence after the
                    # pursuit tables and does not touch browse_state; the pristine migration chain owns the
                    # empty singleton: 0021 creates it; 0030, 0031, and 0034
                    # each force one full publication revision; 0032 bumps the
                    # title-policy input revision. No data table may be seeded
                    # before this exact state is checked.
                    expected_state = {
                        "id": 1,
                        "input_revision": 4,
                        "generation_id": None,
                        "full_revision": 4,
                        "prepared_generation_id": None,
                    }
                    if any(row.get(key) != value for key, value in expected_state.items()):
                        raise SystemExit("Refusing to seed because migration-owned browse_state differs from its pristine singleton.")
                    continue
                if connection.execute(select(table).limit(1)).first() is not None:
                    raise SystemExit(f"Refusing to seed nonempty table {table.name!r}.")
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        manifest = seed_scale_corpus(factory, total_rows=args.rows)
        seed_resolved_operator_accounts(engine, manifest)
    finally:
        engine.dispose()

    if not isinstance(manifest, dict):
        raise SystemExit("Shared synthetic fixture must return a sanitized manifest object.")
    if manifest.get("synthetic_fixture") is not True or manifest.get("total_rows") != args.rows:
        raise SystemExit("Shared fixture manifest did not confirm the requested synthetic row count.")
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"manifest_output": str(args.manifest_output.resolve()), "seeded_rows": args.rows, "database": re.sub(r"(?<=://)[^/@]+@", "<redacted>@", database_url)}))


if __name__ == "__main__":
    main()
