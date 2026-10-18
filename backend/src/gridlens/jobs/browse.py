"""Retained-data-only browse maintenance; never dispatch ingestion/research jobs."""

import argparse
import json
import logging
import time
from uuid import UUID

from fastapi import HTTPException

from gridlens.intelligence.saved_browse import current_generation, rebuild, restore_generation
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
                    "row_count": generation.row_count,
                    "valid_until": generation.valid_until.isoformat(),
                }
        except HTTPException:
            result = {"status": "pending"}
        if args.action == "status":
            print(json.dumps(result))
            return 0 if result["status"] == "current" else 1
        if result["status"] == "pending":
            try:
                print(json.dumps(rebuild(SessionLocal)), flush=True)
            except Exception:
                # Do not emit DB exception details, which can include private input parameters.
                logging.error("Browse rebuild failed; qualification remains pending")
        time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
