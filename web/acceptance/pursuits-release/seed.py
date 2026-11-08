"""Seed the explicitly named local UI pursuits browser database with test-only rows."""

from __future__ import annotations

import argparse
import json
import os
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
    """Require the one authorized loopback disposable database for this seed."""
    parsed = make_url(value)
    # libpq accepts connection parameters in the query string; these can take
    # precedence over URL authority fields when SQLAlchemy opens the connection.
    # Keep this seed pinned to the explicitly authorized local socket target.
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
    if (parsed.host or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Refusing to seed a database outside loopback.")
    if not isinstance(parsed.port, int) or not 1 <= parsed.port <= 65535:
        raise SystemExit("Refusing database URL without an explicit valid port.")
    if parsed.database not in {
        "ui_pursuits_real_test",
        "ui_pursuits_real_slice1n_test",
    }:
        raise SystemExit("Refusing unexpected database; expected an explicitly named disposable pursuits test database.")
    if parsed.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise SystemExit("Refusing non-PostgreSQL browser database.")
    from sqlalchemy.dialects.postgresql.psycopg import dialect

    args, effective = dialect().create_connect_args(parsed)
    if args or (effective.get("host") or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Refusing effective connection parameters outside loopback.")
    if effective.get("port") != parsed.port or effective.get("dbname") != parsed.database:
        raise SystemExit("Refusing effective connection parameters that differ from the pinned URL.")
    return value


def main() -> None:
    """Validate a pristine migrated database, seed marked test data, and write its manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-output", required=True, type=Path)
    args = parser.parse_args()

    settings = get_settings()
    database_url = checked_database_url(settings.database_url)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names(schema="public"))
        if "alembic_version" not in table_names:
            raise SystemExit("Refusing to seed a database without the migrated schema.")
        metadata = MetaData()
        metadata.reflect(bind=engine, schema="public")
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one_or_none()
            if revision != "0051_canonical_need_aliases":
                raise SystemExit("Refusing to seed unless schema 0051 is installed.")
            for table in metadata.sorted_tables:
                if table.name == "alembic_version":
                    continue
                if table.name == "browse_state":
                    rows = connection.execute(select(table)).mappings().all()
                    if len(rows) != 1:
                        raise SystemExit(
                            "Refusing unless browse_state has its pristine singleton."
                        )
                    row = rows[0]
                    expected = {
                        "id": 1,
                        "input_revision": 4,
                        "generation_id": None,
                        "full_revision": 4,
                        "prepared_generation_id": None,
                    }
                    if any(row.get(key) != value for key, value in expected.items()):
                        raise SystemExit(
                            "Refusing because migration-owned browse state is not pristine."
                        )
                    continue
                if connection.execute(select(table).limit(1)).first() is not None:
                    raise SystemExit(f"Refusing to seed nonempty table {table.name!r}.")
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        manifest = seed_scale_corpus(factory, total_rows=2098)
        # The rollup scale fixture bypasses retained-data builds. Supply clearly
        # synthetic account-preview metadata so the real Research route exercises
        # its normal account workspace API instead of correctly failing closed.
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE public.browse_rows
                    SET compact = compact || CAST(:fixture AS jsonb)
                    WHERE generation_id = CAST(:generation AS uuid)
                    """
                ),
                {
                    "generation": manifest["generation_id"],
                    "fixture": json.dumps(
                        {
                            "rationale": "Synthetic browser fixture only.",
                            "required_mw": None,
                            "start_window": None,
                            "duration": None,
                            "supply": "Not established in this synthetic fixture.",
                            "next_action": "No action; synthetic fixture only.",
                            "conflict_state": "unknown",
                            "evidence": [],
                            "commercial_preview": {
                                "disposition": "RESEARCH",
                                "reason": "Synthetic browser fixture only; no commercial conclusion.",
                                "next_question": "Synthetic test question.",
                                "next_action": "Synthetic test action.",
                                "organization": None,
                                "synthetic_fixture": True,
                            },
                        }
                    ),
                },
            )
        seed_resolved_operator_accounts(engine, manifest)
    finally:
        engine.dispose()

    target = manifest["groups"]["de_central"]
    output = {
        "synthetic_fixture": True,
        "migration_revision": "0051_canonical_need_aliases",
        "total_rows": manifest["total_rows"],
        "target_need_id": target["need_ids"][2],
        "target_project_id": target["project_ids"][2],
        "target_name": "STORMCHASER Synthetic Asset",
        "second_page_need_id": target["need_ids"][25],
        "second_page_project_id": target["project_ids"][25],
        "contact_project_id": target["project_ids"][0],
        "account_name": target["name"],
        "target_group_id": target["id"],
        "target_group_name": target["name"],
    }
    if manifest.get("synthetic_fixture") is not True:
        raise SystemExit("The shared fixture did not mark the data synthetic.")
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    parsed = urlsplit(database_url)
    print(
        json.dumps(
            {
                "status": "SEEDED_SYNTHETIC_TEST_DATA",
                "rows": manifest["total_rows"],
                "database": f"{parsed.hostname}:{parsed.port}/{parsed.path.lstrip('/')}",
            }
        )
    )


if __name__ == "__main__":
    main()
