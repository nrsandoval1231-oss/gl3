#!/usr/bin/env python3
"""Host-only dry-run/apply tool for explicit logical-call settlement."""

from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from gridlens.integrations.logical_calls import reconcile_call, settle_call
from gridlens.persistence.models import LogicalCall, LogicalCallBudget
from gridlens.settings import settings


def _request(args: argparse.Namespace) -> dict[str, object]:
    return {
        "call_id": str(args.call_id),
        "action": args.action,
        "actor": args.actor,
        "receipt_ref": args.receipt_ref,
        "expected_status": args.expected_status,
        "outcome_proof": args.outcome_proof,
        "actual_cost_usd": args.actual_cost_usd,
        "input_tokens": args.input_tokens,
        "output_tokens": args.output_tokens,
    }


def _identity(session: Session, call: LogicalCall) -> dict[str, object]:
    scopes = call.budget_scopes or []
    budgets = session.scalars(
        select(LogicalCallBudget)
        .where(
            LogicalCallBudget.scope.in_([item["scope"] for item in scopes]),
            LogicalCallBudget.period.in_(["daily", "monthly", "active"]),
            LogicalCallBudget.period_key.in_([item["period_key"] for item in scopes]),
        )
        .order_by(LogicalCallBudget.id)
    ).all()
    return {
        "id": str(call.id),
        "fingerprint": call.fingerprint,
        "status": call.status,
        "fence_token": call.fence_token,
        "actual_cost_usd": str(call.actual_cost_usd) if call.actual_cost_usd is not None else None,
        "input_tokens": call.input_tokens,
        "output_tokens": call.output_tokens,
        "finished_at": call.finished_at.isoformat() if call.finished_at else None,
        "result_digest": call.result_digest,
        "active_count": sum(int(row.active_count) for row in budgets if row.period == "active"),
        "budgets": [
            [
                row.scope,
                row.period,
                row.period_key,
                int(row.call_count),
                str(row.cost_usd),
                int(row.active_count),
            ]
            for row in budgets
        ],
    }


def _digest(identity: dict[str, object], request: dict[str, object]) -> str:
    raw = json.dumps([identity, request], sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("call_id", type=UUID)
    parser.add_argument("--action", choices=("settle", "outcome"), required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--receipt-ref", required=True)
    parser.add_argument("--expected-status", required=True)
    parser.add_argument("--actual-cost-usd", type=Decimal)
    parser.add_argument("--input-tokens", type=int)
    parser.add_argument("--output-tokens", type=int)
    parser.add_argument(
        "--outcome-proof", help="conclusive external evidence reference for outcome action"
    )
    parser.add_argument(
        "--apply", action="store_true", help="apply after preview digest verification"
    )
    parser.add_argument("--expect-digest", help="digest emitted by an earlier dry run")
    args = parser.parse_args()
    if args.action == "settle" and args.outcome_proof:
        parser.error("--outcome-proof is only valid for outcome action")
    if args.action == "outcome" and (
        not args.outcome_proof
        or any(
            value is not None
            for value in (args.actual_cost_usd, args.input_tokens, args.output_tokens)
        )
    ):
        parser.error("outcome action requires --outcome-proof and no measurement fields")
    if args.apply and not args.expect_digest:
        parser.error("--apply requires --expect-digest from a dry run")
    database_url = settings.database_url
    if not database_url:
        parser.error("database URL is missing")
    if not make_url(database_url).database:
        parser.error("database URL must identify a database")
    from sqlalchemy import create_engine

    engine = create_engine(database_url)
    request = _request(args)
    try:
        with Session(engine, expire_on_commit=False) as session:
            stmt = select(LogicalCall).where(LogicalCall.id == args.call_id)
            if args.apply:
                stmt = stmt.with_for_update()
            call = session.scalar(stmt)
            if call is None:
                parser.error("logical call not found")
            if call.status != args.expected_status:
                parser.error("logical call status differs from --expected-status")
            identity = _identity(session, call)
            digest = _digest(identity, request)
            if args.apply and digest != args.expect_digest:
                session.rollback()
                parser.error("preview is stale; no changes applied")
            if not args.apply:
                session.rollback()
                print(
                    json.dumps(
                        {"mode": "dry_run", "digest": digest, "identity": identity},
                        sort_keys=True,
                    )
                )
                return 0
            if args.action == "settle":
                receipt, replayed = settle_call(
                    session,
                    args.call_id,
                    actor=args.actor,
                    receipt_ref=args.receipt_ref,
                    actual_cost_usd=args.actual_cost_usd,
                    input_tokens=args.input_tokens,
                    output_tokens=args.output_tokens,
                )
                result = {
                    "mode": "applied",
                    "action": "settle",
                    "call_id": str(args.call_id),
                    "receipt_id": str(receipt.id),
                    "receipt_ref": receipt.receipt_ref,
                    "replayed": replayed,
                    "status": call.status,
                    "actual_cost_usd": (
                        str(call.actual_cost_usd) if call.actual_cost_usd is not None else None
                    ),
                    "input_tokens": call.input_tokens,
                    "output_tokens": call.output_tokens,
                }
            else:
                outcome = reconcile_call(
                    session,
                    args.call_id,
                    fence_token=call.fence_token,
                    reconciliation_actor=args.actor,
                    reconciliation_ref=args.outcome_proof,
                )
                if outcome.status != "RECONCILED":
                    parser.error(f"outcome reconciliation rejected: {outcome.blocked_reason}")
                result = {
                    "mode": "applied",
                    "action": "outcome",
                    "call_id": str(args.call_id),
                    "status": outcome.status,
                    "evidence_ref": args.outcome_proof,
                    "receipt_ref": args.receipt_ref,
                }
            print(json.dumps(result, sort_keys=True))
            return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
