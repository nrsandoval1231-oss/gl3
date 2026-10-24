"""Shared finite-deadline and nonblocking PostgreSQL acquisition admission."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.engine import Engine

GLOBAL_PUBLIC_LOCK_KEY = "gridlens:public-acquisition:global:v1"
ACQUISITION_SETTLEMENT_GRACE_SECONDS = 5


def acquisition_deadline(
    lease_until: datetime,
    *,
    now_utc: datetime | None = None,
    monotonic_now: float | None = None,
) -> float:
    """Translate one absolute database lease expiry to one monotonic deadline."""
    if lease_until.tzinfo is None or lease_until.utcoffset() is None:
        raise ValueError("Acquisition lease expiry must be timezone-aware")
    wall_now = now_utc or datetime.now(UTC)
    if wall_now.tzinfo is None or wall_now.utcoffset() is None:
        raise ValueError("Acquisition clock must be timezone-aware")
    remaining = max(0.0, (lease_until - wall_now).total_seconds())
    return (time.monotonic() if monotonic_now is None else monotonic_now) + remaining


def remaining_seconds(deadline: float | None) -> float | None:
    """Return remaining time for an absolute monotonic acquisition deadline."""
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Public-source research deadline exhausted")
    return remaining


class FencedLeaseRenewer:
    """Renew a running job in short sessions, never past its original deadline."""

    def __init__(
        self,
        session_factory: Any,
        job_id: Any,
        worker_id: str,
        fence: int,
        lease_until: datetime,
        *,
        interval_seconds: float = 1.0,
        lease_seconds: float = 90.0,
    ) -> None:
        if lease_until.tzinfo is None or lease_until.utcoffset() is None:
            raise ValueError("Lease renewal requires an aware lease expiry")
        self.session_factory = session_factory
        self.job_id = job_id
        self.worker_id = worker_id
        self.fence = fence
        self.deadline = lease_until
        self.settlement_until = lease_until + timedelta(
            seconds=ACQUISITION_SETTLEMENT_GRACE_SECONDS
        )
        self.interval_seconds = interval_seconds
        self.lease_seconds = lease_seconds
        self._stop = Event()
        self._thread = Thread(target=self._run, name="gridlens-acquisition-lease", daemon=True)

    def start(self) -> FencedLeaseRenewer:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=max(1.0, self.interval_seconds + 0.25))

    def _run(self) -> None:
        from gridlens.persistence.models import Job

        while not self._stop.wait(self.interval_seconds):
            now = datetime.now(UTC)
            if now >= self.settlement_until:
                return
            try:
                with self.session_factory.begin() as session:
                    session.execute(text("SET LOCAL statement_timeout = '750ms'"))
                    session.execute(text("SET LOCAL lock_timeout = '250ms'"))
                    job = session.scalar(
                        select(Job).where(Job.id == self.job_id).with_for_update(skip_locked=True)
                    )
                    if job is None:
                        # A competing short checkpoint/status transaction may own
                        # this row for one tick. Keep the bounded renewal loop alive;
                        # an actually missing job ends the renewal immediately.
                        exists = session.scalar(
                            select(Job.id).where(Job.id == self.job_id).limit(1)
                        )
                        if exists is None:
                            return
                        continue
                    if (
                        job.status != "running"
                        or job.lease_owner != self.worker_id
                        or job.fence != self.fence
                        or job.lease_until is None
                        or job.lease_until <= now
                    ):
                        return
                    next_expiry = min(
                        now + timedelta(seconds=self.lease_seconds), self.settlement_until
                    )
                    if next_expiry > job.lease_until:
                        job.lease_until = next_expiry
            except Exception:
                # Lock contention, cancellation, or database trouble fail closed.
                return


@contextmanager
def try_public_acquisition_admission(engine: Engine, source_id: str) -> Iterator[bool]:
    """Try the shared public slot and source lock without waiting for either.

    The global session advisory lock serializes different discovered hosts too.
    The source key matches the legacy ingestion dispatch lock so registry/source
    operators and older workers continue to share that same exclusion boundary.
    The connection is held outside transactions and always closed on exit.
    """
    connection = engine.connect()
    global_locked = False
    source_locked = False
    try:
        global_locked = bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"),
                {"key": GLOBAL_PUBLIC_LOCK_KEY},
            ).scalar_one()
        )
        connection.commit()
        if not global_locked:
            yield False
            return
        source_locked = bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(hashtextextended(:source_id, 0))"),
                {"source_id": source_id},
            ).scalar_one()
        )
        connection.commit()
        if not source_locked:
            yield False
            return
        yield True
    finally:
        try:
            if source_locked:
                connection.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:source_id, 0))"),
                    {"source_id": source_id},
                )
                connection.commit()
            if global_locked:
                connection.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
                    {"key": GLOBAL_PUBLIC_LOCK_KEY},
                )
                connection.commit()
        finally:
            connection.close()
