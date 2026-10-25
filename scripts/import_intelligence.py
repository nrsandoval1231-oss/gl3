"""Preview, stage and reverse external intelligence without production mutation.

Reports can contain private source values: choose an ignored or protected output path.
No database connection is made for preview. Stage requires an exact loopback DB name.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["preview", "stage", "history", "rollback"])
    parser.add_argument("files", type=Path, nargs="*")
    parser.add_argument(
        "--mapping", type=Path, help="JSON source-header to canonical-field mapping"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-database-name")
    parser.add_argument("--batch-id")
    parser.add_argument("--actor", default="local-operator")
    args = parser.parse_args()
    if args.action in {"preview", "stage"} and not args.files:
        parser.error("preview/stage require at least one source file")
    mapping = json.loads(args.mapping.read_text(encoding="utf-8")) if args.mapping else None
    from gridlens.ingestion.workbook_import import read_workbook

    previews = [read_workbook(path, column_mapping=mapping) for path in args.files]
    if args.action == "preview":
        result = {"action": "preview", "files": [p.model_dump(mode="json") for p in previews]}
    else:
        from gridlens.intelligence.external_imports import (
            import_history,
            rollback_import,
            stage_import,
        )
        from gridlens.settings import settings
        from sqlalchemy import create_engine
        from sqlalchemy.engine import make_url
        from sqlalchemy.orm import Session

        url = make_url(settings.database_url)
        if not args.expected_database_name or url.database != args.expected_database_name:
            parser.error("database actions require the exact --expected-database-name")
        if url.host not in {"127.0.0.1", "localhost", "::1"}:
            parser.error("database actions require a loopback staging database")
        engine = create_engine(url)
        try:
            with Session(engine) as session, session.begin():
                if args.action == "stage":
                    result = {
                        "action": "stage",
                        "files": [stage_import(session, p, actor=args.actor) for p in previews],
                    }
                elif args.action == "rollback":
                    if not args.batch_id:
                        parser.error("rollback requires --batch-id")
                    result = rollback_import(session, args.batch_id, actor=args.actor)
                else:
                    result = {"action": "history", "batches": import_history(session)}
        finally:
            engine.dispose()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"{args.action} report written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
