"""Context-local instant for read-only canonical projection preparation.

Defaults stay with each caller's original clock. This never changes system time,
other threads, write receipts, leases, authentication or publication fencing.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime

_instant: ContextVar[datetime | None] = ContextVar("canonical_evaluation_instant", default=None)


def evaluation_now(default: datetime) -> datetime:
    instant = _instant.get()
    if instant is None:
        return default
    if default.tzinfo is None:
        return instant.astimezone().replace(tzinfo=None)
    return instant.astimezone(default.tzinfo)


def evaluation_today(default: date) -> date:
    instant = _instant.get()
    return default if instant is None else instant.astimezone().date()


@contextmanager
def evaluate_at(instant: datetime):
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("canonical evaluation instant must be timezone-aware")
    token = _instant.set(instant.astimezone(UTC))
    try:
        yield
    finally:
        _instant.reset(token)
