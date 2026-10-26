#!/usr/bin/env python3
"""Internal CLI for audited contact privacy suppression; no public API surface."""

from __future__ import annotations

import argparse
import os

from gridlens.intelligence.contact_suppressions import (
    company_suppression_key,
    global_method_suppression_key,
    global_person_suppression_key,
    method_suppression_key,
    person_suppression_key,
    record_contact_suppression,
)
from gridlens.persistence.database import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scope", choices=("company", "person", "method"))
    parser.add_argument("company_id", nargs="?")
    parser.add_argument("--name", default="")
    parser.add_argument("--kind", default="")
    parser.add_argument("--value", default="")
    parser.add_argument(
        "--global-scope",
        action="store_true",
        help="Apply person or method rule across companies",
    )
    parser.add_argument(
        "--person-id", help="Stable canonical person UUID for global person scope"
    )
    parser.add_argument("--action", required=True, choices=("suppress", "reinstate"))
    parser.add_argument("--expected-version", required=True, type=int)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Append the event; default is review only",
    )
    parser.add_argument(
        "--confirm-database",
        help="Exact configured database name required with --execute",
    )
    args = parser.parse_args()
    from uuid import UUID

    company_id = UUID(args.company_id) if args.company_id else None
    if args.scope == "company":
        if args.global_scope:
            parser.error(
                "company scope is already global to the canonical company identity"
            )
        if company_id is None:
            parser.error("company scope requires company_id")
        key = company_suppression_key(company_id)
    elif args.scope == "person":
        if args.global_scope:
            if not args.person_id:
                parser.error("global person scope requires --person-id")
            key = global_person_suppression_key(UUID(args.person_id))
        else:
            if company_id is None or not args.name:
                parser.error(
                    "company-scoped person suppression requires company_id and --name"
                )
            key = person_suppression_key(company_id, args.name)
    else:
        if not (args.kind and args.value):
            parser.error("method scope requires --kind and --value")
        if args.global_scope:
            key = global_method_suppression_key(args.kind, args.value)
        else:
            if company_id is None or not args.name:
                parser.error(
                    "company-scoped method suppression requires company_id and --name"
                )
            key = method_suppression_key(company_id, args.name, args.kind, args.value)
    from sqlalchemy.engine import make_url
    from gridlens.settings import settings

    configured_database = make_url(settings.database_url).database
    if not args.execute:
        print(
            f"DRY RUN database={configured_database} scope={args.scope} action={args.action} key={key} "
            f"expected_version={args.expected_version} actor={args.actor!r}"
        )
        return
    if not args.confirm_database or args.confirm_database != configured_database:
        parser.error(
            "--execute requires --confirm-database to exactly match configured DATABASE_URL"
        )
    if os.environ.get("GRIDLENS_DISABLE_PRIVACY_WRITES", "").casefold() in {
        "1",
        "true",
        "yes",
    }:
        parser.error("privacy ledger writes are disabled by runtime configuration")
    with SessionLocal() as session:
        row = record_contact_suppression(
            session,
            scope=args.scope,
            subject_key=key,
            action=args.action,
            expected_version=args.expected_version,
            reason=args.reason,
            actor=args.actor,
            idempotency_key=args.idempotency_key,
        )
        session.commit()
        print(
            f"event={row.id} scope={row.scope} version={row.version} action={row.action}"
        )


if __name__ == "__main__":
    main()
