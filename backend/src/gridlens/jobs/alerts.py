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


def spend_report() -> dict[str, Any]:
    """Near-cap and capped-out intelligence spend from the shared call ledger (read-only).

    Empty (no rows, no jobs) while intelligence is off or nothing has been reserved, so the
    default alert is unchanged.
    """
    from gridlens.intelligence.intelligence_jobs import _caps, provider_caps
    from gridlens.intelligence.spend_caps import (
        parse_provider_caps,
        recent_capped_out_jobs,
        spend_status,
    )
    from gridlens.persistence.database import SessionLocal

    base = _caps()
    providers = {
        "openai",
        "typesafe",
        "firecrawl",
        *parse_provider_caps(settings.intelligence_provider_caps),
    }
    with SessionLocal() as session:
        rows = spend_status(
            session,
            global_caps=base,
            provider_caps={name: provider_caps(name, base) for name in sorted(providers)},
            threshold=settings.intelligence_spend_alert_threshold,
            max_call_usd=settings.intelligence_max_call_usd,
        )
        jobs = recent_capped_out_jobs(session)
    return {"rows": rows, "capped_out_jobs": jobs}


def _spend_lines(spend: dict[str, Any] | None) -> list[str]:
    lines: list[str] = []
    for row in (spend or {}).get("rows", []):
        label = {"CAPPED_OUT": "CAPPED OUT", "LOW_HEADROOM": "low headroom"}.get(
            row["level"], "near cap"
        )
        unit = "USD" if row["metric"] == "usd" else "calls"
        lines.append(
            f"Spend {label}: {row['scope']} {row['period']} {unit} "
            f"{row['used']}/{row['cap']} ({row['fraction']:.0%})"
        )
    jobs = (spend or {}).get("capped_out_jobs", {})
    if jobs.get("jobs"):
        lines.append(f"Capped-out intelligence jobs in last {jobs['hours']}h: {jobs['jobs']}")
    return lines


def summarize(
    health: dict[str, Any],
    failures: dict[str, int] | None = None,
    spend: dict[str, Any] | None = None,
    documents: list[Any] | None = None,
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
    lines.extend(_spend_lines(spend))
    lines.extend(finding.line() for finding in documents or [])
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
        try:
            spend = spend_report()
        except Exception as exc:  # a broken spend read must not hide the health message
            spend = {"rows": [], "capped_out_jobs": {}, "error": type(exc).__name__}
        try:
            from gridlens.jobs.document_alerts import document_report

            documents: list[Any] = list(document_report())
        except Exception as exc:  # a broken document check must be visible, not fatal
            from gridlens.jobs.document_alerts import Finding

            documents = [Finding("document_check_failed", "all", type(exc).__name__)]
        title, body, urgent = summarize(health(), processing_failures(), spend, documents)
    except Exception as exc:  # health itself failing is the most important alert
        title, body, urgent = "GridLens: health check failed", type(exc).__name__, True
    send(title, body, urgent)
    print(title)
    sys.exit(0)


if __name__ == "__main__":
    main()
