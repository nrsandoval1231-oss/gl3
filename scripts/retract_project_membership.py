"""Preview or explicitly execute an audited exceptional membership retraction."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from sqlalchemy import text  # noqa: E402

from gridlens.intelligence.membership_corrections import (  # noqa: E402
    preview_membership_retraction,
    retract_project_membership,
)
from gridlens.persistence.database import SessionLocal  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--membership-id", required=True, type=UUID)
    parser.add_argument("--project-id", required=True, type=UUID)
    parser.add_argument("--company-id", required=True, type=UUID)
    parser.add_argument("--expected-version", required=True, type=int)
    parser.add_argument("--source-evidence-id", required=True, type=UUID)
    parser.add_argument("--source-hash", required=True)
    parser.add_argument("--expected-database-name", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument(
        "--execute", action="store_true", help="Explicitly apply the reviewed event"
    )
    args = parser.parse_args(argv)
    request = {
        "membership_id": args.membership_id,
        "project_id": args.project_id,
        "company_id": args.company_id,
        "expected_version": args.expected_version,
        "expected_source_evidence_id": args.source_evidence_id,
        "expected_source_hash": args.source_hash,
    }
    with SessionLocal() as session:
        if session.get_bind().url.database != args.expected_database_name:
            parser.error(
                "The connected database must exactly match --expected-database-name"
            )
        if args.execute:
            event = retract_project_membership(
                session,
                **request,
                actor=args.actor,
                reason=args.reason,
                idempotency_key=args.idempotency_key,
            )
            session.commit()
            result = {"status": "executed", "event_id": str(event.id)}
        else:
            session.execute(text("SET TRANSACTION READ ONLY"))
            result = {
                "status": "preview",
                **preview_membership_retraction(session, **request),
            }
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
