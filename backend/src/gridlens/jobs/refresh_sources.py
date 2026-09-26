"""Enqueue due sources on the worker cadence or a managed local-day schedule."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from gridlens.jobs.queue import enqueue
from gridlens.jobs.worker import sync_registry
from gridlens.persistence.database import SessionLocal
from gridlens.persistence.models import Source

CHICAGO = ZoneInfo("America/Chicago")


def enqueue_daily_sources() -> int:
    """Queue each enabled source at most once per Chicago calendar day."""
    definitions = sync_registry()
    today = datetime.now(UTC).astimezone(CHICAGO).date().isoformat()
    count = 0
    with SessionLocal.begin() as session:
        for definition in definitions:
            source = session.scalar(
                select(Source).where(Source.id == definition["id"]).with_for_update()
            )
            if source is None or not source.enabled or source.health.get("scheduled_day") == today:
                continue
            enqueue(session, source.id)
            source.health = {**source.health, "scheduled_day": today}
            count += 1
    return count


def main() -> None:
    enqueue_daily_sources()


if __name__ == "__main__":
    main()
