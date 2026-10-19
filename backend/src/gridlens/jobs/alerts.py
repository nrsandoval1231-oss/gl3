"""Owner alerts: summarize source health and push it to the configured ntfy topic.

Run once or twice a day from the host scheduler. Every run sends a message, so a
missing morning message is itself a signal that collection or alerting stopped.
"""

import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from gridlens.settings import settings

PROBLEM_STATES = {"Failed", "Overdue", "RegistryUnavailable"}


FAILURE_WINDOW = timedelta(hours=48)


def processing_failures() -> dict[str, int]:
    """Count terminal failures that health() folds into its backlog totals."""
    from sqlalchemy import func, select

    from gridlens.persistence.database import SessionLocal
    from gridlens.persistence.models import Interpretation, Job, LogicalCall
    from gridlens.persistence.watch_models import ProjectMonitorWatch

    since = datetime.now(UTC) - FAILURE_WINDOW
    with SessionLocal() as session:
        jobs = session.execute(
            select(Job.kind, func.count())
            .where(Job.status == "failed", Job.created_at >= since)
            .group_by(Job.kind)
        ).all()
        interpretations = session.scalar(
            select(func.count())
            .select_from(Interpretation)
            .where(Interpretation.status == "failed")
        )
        uncertain = session.scalar(
            select(func.count())
            .select_from(LogicalCall)
            .where(LogicalCall.status == "SENT_OUTCOME_UNKNOWN")
        )
        old_queued = session.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.status == "queued", Job.created_at < datetime.now(UTC) - timedelta(hours=24))
        )
        quarantined = session.scalar(
            select(func.count())
            .select_from(ProjectMonitorWatch)
            .where(ProjectMonitorWatch.status == "quarantined")
        )
    counts = {f"{kind} jobs": int(count) for kind, count in jobs}
    if interpretations:
        counts["interpretations"] = int(interpretations)
    counts["uncertain logical calls"] = int(uncertain or 0)
    counts["old queued jobs"] = int(old_queued or 0)
    counts["monitor quarantines"] = int(quarantined or 0)
    return counts


def summarize(
    health: dict[str, Any], failures: dict[str, int] | None = None
) -> tuple[str, str, bool]:
    """Return (title, body, has_problems) from the health payload and failure counts."""
    enabled = [source for source in health["sources"] if source.get("enabled")]
    problems = [source for source in enabled if source.get("status") in PROBLEM_STATES]
    lines = [
        f"{source['id']}: {source['status']}"
        + (f" — {source['error']}" if source.get("error") else "")
        for source in problems
    ]
    if health.get("worker_liveness") != "LIVE":
        lines.append(f"Worker liveness: {health.get('worker_liveness')}")
    if health.get("collection_freshness") == "OVERDUE":
        lines.append("Daily collection is overdue for at least one source.")
    for label, count in sorted((failures or {}).items()):
        if count:
            lines.append(f"Failed {label}: {count}")
    ok = len(enabled) - len(problems)
    footer = (
        f"{ok}/{len(enabled)} enabled sources healthy · {health.get('backlog', 0)} jobs queued"
        f" · {health.get('pending_interpretations', 0)} interpretations waiting"
    )
    if lines:
        return f"GridLens: {len(lines)} problem(s)", "\n".join([*lines, "", footer]), True
    return "GridLens: collection healthy", footer, False


def send(title: str, body: str, urgent: bool, client: httpx.Client | None = None) -> None:
    if not settings.ntfy_url:
        raise RuntimeError("NTFY_URL is not configured")
    headers = {"Title": title, "Priority": "high" if urgent else "default"}
    if urgent:
        headers["Tags"] = "warning"
    if settings.ntfy_token:
        headers["Authorization"] = f"Bearer {settings.ntfy_token.get_secret_value()}"
    http = client or httpx.Client(timeout=15)
    try:
        http.post(settings.ntfy_url, content=body.encode(), headers=headers).raise_for_status()
    finally:
        if client is None:
            http.close()


def main() -> None:
    from gridlens.api.app import health

    try:
        title, body, urgent = summarize(health(), processing_failures())
    except Exception as exc:  # health itself failing is the most important alert
        title, body, urgent = "GridLens: health check failed", f"{type(exc).__name__}: {exc}", True
    send(title, body, urgent)
    print(title)
    sys.exit(0)


if __name__ == "__main__":
    main()
