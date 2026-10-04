"""Read-only research metrics; saved evaluations, never question pairs, count changes."""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import datetime
from decimal import Decimal
from typing import Any


def evaluation_events(pursuits: list, since: datetime | None = None) -> list[dict]:
    """A first saved state is a baseline, not a transition from a fabricated state."""
    events = []
    seen = set()
    for pursuit in pursuits:
        versions = (pursuit.snapshot or {}).get("commercial_triage", {}).get("versions", [])
        previous = None
        for version in sorted(versions, key=lambda item: item.get("version", 0)):
            identity = (str(pursuit.id), version.get("version"))
            if identity in seen:
                continue
            seen.add(identity)
            at = version.get("evaluated_at")
            current = version.get("saved_card") or {}
            eligible = since is None or (at is not None and datetime.fromisoformat(at) >= since)
            if previous is not None and eligible:
                prior = previous.get("saved_card") or {}
                before, after = previous.get("disposition"), version.get("disposition")
                old_tier, new_tier = prior.get("tier"), current.get("tier")
                changed = (
                    before != after
                    or old_tier != new_tier
                    or previous.get("input_hash") != version.get("input_hash")
                )
                if changed:

                    def source_key(source):
                        return tuple(source.get(key) for key in ("evidence_id", "url", "hash"))

                    old_sources = {source_key(source) for source in prior.get("sources", [])}
                    new_sources = []
                    added = set()
                    for source in current.get("sources", []):
                        key = source_key(source)
                        if key not in old_sources and key not in added:
                            added.add(key)
                            new_sources.append(
                                {
                                    field: source.get(field)
                                    for field in ("text", "evidence_id", "url", "hash", "date")
                                }
                            )
                    events.append(
                        {
                            "id": f"{pursuit.id}:{version['version']}",
                            "pursuit_id": str(pursuit.id),
                            "version": version["version"],
                            "need_id": current.get("id") or prior.get("id"),
                            "project_id": current.get("project_id") or prior.get("project_id"),
                            "evaluated_at": at,
                            "input_hash": version.get("input_hash"),
                            "name": current.get("name") or prior.get("name"),
                            "before": before,
                            "after": after,
                            "before_tier": old_tier,
                            "after_tier": new_tier,
                            "reason": current.get("reason"),
                            "next_action": current.get("next_action"),
                            "new_evidence": new_sources,
                        }
                    )
            previous = version
    return sorted(
        events, key=lambda event: (event["evaluated_at"] or "", event["id"]), reverse=True
    )


def evaluation_transitions(pursuits: list, since: datetime | None = None) -> list[dict]:
    changes = []
    for event in evaluation_events(pursuits, since):
        for kind, before, after in (
            ("commercial", event["before"], event["after"]),
            ("evidence_tier", event["before_tier"], event["after_tier"]),
        ):
            # Missing historical tier is unknown, never a promotion baseline.
            if before and after and before != after:
                changes.append(
                    {
                        "kind": kind,
                        "pursuit_id": event["pursuit_id"],
                        "need_id": event["need_id"],
                        "version": event["version"],
                        "before": before,
                        "after": after,
                        "evaluated_at": event["evaluated_at"],
                        "input_hash": event["input_hash"],
                    }
                )
    return changes


def metrics_report(
    cards: list[dict], rows: list, pursuits: list, since: datetime | None = None
) -> dict[str, Any]:
    def activity_time(row):
        times = [row.created_at]
        if row.completed_at is not None:
            times.append(row.completed_at)
        for key in ("latest_attempt_at", "started_at"):
            if row.receipt.get(key):
                times.append(datetime.fromisoformat(row.receipt[key]))
        return max(times)

    selected = [row for row in rows if since is None or activity_time(row) >= since]
    attempted = [row for row in selected if row.attempt_count]
    completed = [row for row in attempted if row.completed_at]
    transitions = evaluation_transitions(pursuits, since)
    latencies = [
        row.receipt["runtime_seconds"]
        for row in completed
        if row.receipt.get("runtime_seconds") is not None
    ]
    known_costs = [
        Decimal(row.receipt["cost_usd"])
        for row in attempted
        if row.receipt.get("cost_usd") is not None
    ]

    def average(key: str) -> float | None:
        return (
            sum(row.receipt.get(key, 0) for row in attempted) / len(attempted)
            if attempted
            else None
        )

    def transition_counts(kind: str) -> dict:
        return dict(
            Counter(
                f"{row['before']} → {row['after']}" for row in transitions if row["kind"] == kind
            )
        )

    return {
        "scope": "Configured database; current cohort capped at 50; not retained-corpus proof.",
        "since": since.isoformat() if since else None,
        "question_time_basis": "Latest creation, recorded attempt, or completion time; counters "
        "are cumulative for those selected questions, not provider billing in the time window.",
        "current_pursuits": dict(Counter(card["disposition"] for card in cards)),
        "automatically_investigated_pursuits": len(
            {
                r.pursuit_id
                for r in attempted
                if r.context.get("origin") in {"automatic", "follow_up"}
            }
        ),
        "investigated_pursuits": len({r.pursuit_id for r in attempted}),
        "attempted_question_origins": dict(
            Counter(r.context.get("origin", "unknown") for r in attempted)
        ),
        "blockers_attempted": len(attempted),
        "blocker_statuses": dict(Counter(row.status for row in selected)),
        "commercial_transitions": transition_counts("commercial"),
        "evidence_tier_transitions": transition_counts("evidence_tier"),
        "transition_receipts": transitions,
        "average_searches_per_attempted_blocker": average("searches"),
        "average_retrieval_attempts_per_blocker": average("retrieval_attempts"),
        "average_unique_checked_urls_per_blocker": (
            sum(
                len({c["url"] for c in r.receipt.get("source_checks", []) if c.get("url")})
                for r in attempted
            )
            / len(attempted)
            if attempted
            else None
        ),
        "model_calls": sum(r.receipt.get("model_calls", 0) for r in attempted),
        "known_actual_cost_usd": str(sum(known_costs, Decimal(0))),
        "attempts_with_unknown_actual_cost": len(attempted) - len(known_costs),
        "average_actual_cost_per_pursuit_usd": (
            str(sum(known_costs, Decimal(0)) / len({r.pursuit_id for r in attempted}))
            if attempted and len(known_costs) == len(attempted)
            else None
        ),
        "reserved_cost_usd": str(
            sum((Decimal(r.receipt.get("reserved_cost_usd", "0")) for r in attempted), Decimal(0))
        ),
        "duplicate_work_avoided": sum(
            r.receipt.get("duplicate_work_avoided", 0) for r in attempted
        ),
        "failure_rate": (
            sum(r.status == "FAILED" for r in completed) / len(completed) if completed else None
        ),
        "median_research_latency_seconds": statistics.median(latencies) if latencies else None,
    }


def research_overview(
    cards: list[dict], rows: list, pursuits: list, since: datetime | None = None
) -> dict:
    """One morning item per evaluation; question IDs denote correlation, not causation."""
    items = evaluation_events(pursuits, since)
    for item in items:
        item["question_ids"] = sorted(
            {
                str(row.id)
                for row in rows
                if str(row.pursuit_id) == item["pursuit_id"]
                and row.receipt.get("after_input_hash") == item["input_hash"]
                and row.completed_at is not None
                and item["evaluated_at"] is not None
                and row.created_at
                <= datetime.fromisoformat(item["evaluated_at"])
                <= row.completed_at
            }
        )
    items = [item for item in items if item["question_ids"]]
    summary = metrics_report(cards, rows, pursuits, since)
    summary.pop("transition_receipts")
    for key, before, after in (
        ("commercial_transitions", "before", "after"),
        ("evidence_tier_transitions", "before_tier", "after_tier"),
    ):
        summary[key] = dict(
            Counter(
                f"{item[before]} → {item[after]}"
                for item in items
                if item[before] and item[after] and item[before] != item[after]
            )
        )
    return {"since": since.isoformat() if since else None, "summary": summary, "items": items}
