"""Retained-data-only browse maintenance; never dispatch ingestion/research jobs."""

import argparse
import json
import logging
import time
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException

from gridlens.intelligence.saved_browse import (
    current_generation,
    maintain_once,
    rebuild,
    restore_generation,
)
from gridlens.persistence.database import SessionLocal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "rebuild", "maintain", "rollback"))
    parser.add_argument("--generation", type=UUID)
    args = parser.parse_args()
    if args.action == "rollback":
        if args.generation is None:
            parser.error("rollback requires --generation")
        result = restore_generation(SessionLocal, args.generation)
        print(json.dumps({"restored": result}))
        return 0 if result else 1
    if args.action == "rebuild":
        result = rebuild(SessionLocal)
        print(json.dumps(result))
        return 0 if result["status"] == "published" else 1
    while True:
        try:
            with SessionLocal() as session:
                generation = current_generation(session)
                result = {
                    "status": "current",
                    "generation_id": str(generation.id),
                    "input_revision": generation.input_revision,
                    "policy_version": generation.policy_version,
                    "built_at": generation.built_at.isoformat(),
                    "row_count": generation.row_count,
                    "valid_until": generation.valid_until.isoformat(),
                }
        except HTTPException:
            result = {"status": "pending"}
        if args.action == "status":
            print(json.dumps(result))
            return 0 if result["status"] == "current" else 1
        if (
            result["status"] == "pending"
            or (generation.valid_until - datetime.now(UTC)).total_seconds() <= 120
        ):
            try:
                maintenance = maintain_once(SessionLocal)
                if maintenance["status"] not in {"current", "ready"}:
                    print(json.dumps(maintenance), flush=True)
            except Exception:
                # Do not emit private SQL parameters in exception details.
                logging.error("Browse maintenance failed; freshness fences remain active")
        time.sleep(0.25)


if __name__ == "__main__":
    raise SystemExit(main())
