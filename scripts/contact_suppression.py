#!/usr/bin/env python3
"""Internal CLI for audited contact privacy suppression; no public API surface."""

from __future__ import annotations

import argparse

from gridlens.intelligence.contact_suppressions import (
    company_suppression_key,
    method_suppression_key,
    person_suppression_key,
    record_contact_suppression,
)
from gridlens.persistence.database import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scope", choices=("company", "person", "method"))
    parser.add_argument("company_id")
    parser.add_argument("--name", default="")
    parser.add_argument("--kind", default="")
    parser.add_argument("--value", default="")
    parser.add_argument("--action", required=True, choices=("suppress", "reinstate"))
    parser.add_argument("--expected-version", required=True, type=int)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--idempotency-key", required=True)
    args = parser.parse_args()
    from uuid import UUID

    company_id = UUID(args.company_id)
    if args.scope == "company":
        key = company_suppression_key(company_id)
    elif args.scope == "person":
        if not args.name:
            parser.error("person scope requires --name")
        key = person_suppression_key(company_id, args.name)
    else:
        if not (args.name and args.kind and args.value):
            parser.error("method scope requires --name, --kind, and --value")
        key = method_suppression_key(company_id, args.name, args.kind, args.value)
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
        print(f"event={row.id} scope={row.scope} version={row.version} action={row.action}")


if __name__ == "__main__":
    main()
