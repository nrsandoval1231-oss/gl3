"""Retained-data-only browse maintenance; never dispatch ingestion/research jobs."""

import argparse
import json
import logging
import time
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException

from gridlens.intelligence.saved_browse import (
    PREPARE_LEAD_SECONDS,
    current_generation,
    inspect_recovery_stage,
    maintain_once,
    publish_recovery_stage,
    rebuild,
    stage_recovery,
)
from gridlens.persistence.database import SessionLocal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "status",
            "rebuild",
            "maintain",
            "stage-recovery",
            "inspect-recovery",
            "publish-recovery",
        ),
    )
    parser.add_argument("--generation", type=UUID)
    args = parser.parse_args()
    if args.action in {"inspect-recovery", "publish-recovery"}:
        if args.generation is None:
            parser.error(f"{args.action} requires --generation")
    if args.action == "stage-recovery":
        result = stage_recovery(SessionLocal)
        print(json.dumps(result))
        return 0 if result["status"] == "staged" else 1
    if args.action == "inspect-recovery":
        result = inspect_recovery_stage(SessionLocal, args.generation)
        print(json.dumps(result))
        return 0 if result["status"] == "ready" else 1
    if args.action == "publish-recovery":
        result = publish_recovery_stage(SessionLocal, args.generation)
        print(json.dumps(result))
        return 0 if result["status"] in {"published", "already_published"} else 1
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
            or (generation.valid_until - datetime.now(UTC)).total_seconds() <= PREPARE_LEAD_SECONDS
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
