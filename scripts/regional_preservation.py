"""Compare retained identities and immutable evidence in an isolated local proof DB.

The baseline is captured before migration/ingestion. Newly added evidence is
allowed; deletion or mutation of any retained evidence version fails the proof.
Application and test databases must be distinct. No production writes occur.
"""

import argparse
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url

from gridlens.persistence.database import SessionLocal
from gridlens.settings import settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = make_url(settings.database_url)
    if (
        target.host != "127.0.0.1"
        or not target.database
        or not target.database.endswith("_app")
    ):
        raise SystemExit("Requires an isolated loopback *_app database")
    before = json.loads(args.baseline.read_text(encoding="utf-8"))
    result = {"database_scope": "isolated local retained clone", "tables": {}}
    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        for table in (
            "evidence",
            "observations",
            "projects",
            "power_needs",
            "change_events",
        ):
            projection = table
            if table == "projects":
                projection = (
                    "(SELECT id,identity_key,name,location,source_id,external_id,"
                    "asset_type,identity_facts FROM projects)"
                )
            current = dict(
                session.execute(
                    text(
                        f"SELECT id::text, md5(row_to_json(t)::text) FROM {projection} t"
                    )
                ).all()
            )
            original = {row["id"]: row["digest"] for row in before[table]}
            missing = sorted(set(original) - set(current))
            changed = [
                key
                for key in original
                if key in current and original[key] != current[key]
            ]
            result["tables"][table] = {
                "before": len(original),
                "after": len(current),
                "missing": len(missing),
                "changed": len(changed),
            }
            if missing or (table in ("evidence", "change_events") and changed):
                raise AssertionError(f"Historical preservation failed: {table}")
        result["region_counts"] = [
            dict(row)
            for row in session.execute(
                text(
                    "SELECT region_status, region_state, count(*) AS projects FROM projects GROUP BY region_status,region_state ORDER BY region_status,region_state"
                )
            ).mappings()
        ]
        result["duplicate_observations"] = session.scalar(
            text(
                "SELECT count(*) FROM (SELECT source_id, external_id FROM observations GROUP BY source_id,external_id HAVING count(*)>1) d"
            )
        )
        result["duplicate_projects"] = session.scalar(
            text(
                "SELECT count(*) FROM (SELECT identity_key FROM projects GROUP BY identity_key HAVING count(*)>1) d"
            )
        )
        assert result["duplicate_observations"] == result["duplicate_projects"] == 0
    result["historical_evidence_preserved"] = True
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
