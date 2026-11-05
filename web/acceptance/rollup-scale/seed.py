"""Seed one empty, dedicated loopback PostgreSQL database for real browser QA."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import MetaData, create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND / "tests" / "integration"))
sys.path.insert(0, str(BACKEND / "src"))

from rollup_scale_fixture import seed_scale_corpus  # noqa: E402
from gridlens.settings import get_settings  # noqa: E402


def checked_database_url(value: str) -> str:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Refusing to seed a non-loopback database host.")
    database = parsed.path.lstrip("/").lower()
    if "_rollup_scale_" not in database or not database.endswith("_test"):
        raise SystemExit("Refusing to seed a database unless its name contains _rollup_scale_ and ends in _test.")
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise SystemExit("The real-backend browser lane requires loopback PostgreSQL.")
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
            if revision != "0049_scoped_identity_browse":
                raise SystemExit("Refusing to seed unless the dedicated database is migrated to 0049_scoped_identity_browse.")
            for table in metadata.sorted_tables:
                if table.name == "alembic_version":
                    continue
                if table.name == "browse_state":
                    rows = connection.execute(select(table)).mappings().all()
                    if len(rows) != 1:
                        raise SystemExit("Refusing to seed unless browse_state contains only the migration-owned singleton.")
                    row = rows[0]
                    # At schema 0049 the pristine migration chain owns the
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
