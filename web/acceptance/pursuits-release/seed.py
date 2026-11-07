"""Seed the explicitly named local UI pursuits browser database with test-only rows."""

from __future__ import annotations

import argparse
import json
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

from rollup_scale_fixture import seed_scale_corpus  # noqa: E402
from gridlens.settings import get_settings  # noqa: E402


def checked_database_url(value: str) -> str:
    parsed = make_url(value)
    if (parsed.host or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Refusing to seed a database outside loopback.")
    if parsed.port != 54973 or parsed.database != "ui_pursuits_real_test":
        raise SystemExit(
            "Refusing unexpected database; expected ui_pursuits_real_test on port 54973."
        )
    if parsed.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise SystemExit("Refusing non-PostgreSQL browser database.")
    return value


def main() -> None:
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
            if revision != "0050_commercial_pursuits":
                raise SystemExit("Refusing to seed unless schema 0050 is installed.")
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
    finally:
        engine.dispose()

    target = manifest["groups"]["de_central"]
    output = {
        "synthetic_fixture": True,
        "migration_revision": "0050_commercial_pursuits",
        "total_rows": manifest["total_rows"],
        "target_need_id": target["need_ids"][2],
        "target_project_id": target["project_ids"][2],
        "target_name": "STORMCHASER Synthetic Asset",
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
