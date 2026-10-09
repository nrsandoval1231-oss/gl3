"""Enqueue due sources on the worker cadence or a managed local-day schedule."""


def enqueue_daily_sources() -> int:
    """Reconcile immutable scheduled occurrences through the worker's due ledger."""
    from gridlens.jobs.worker import refresh_due

    return refresh_due()


def main() -> None:
    enqueue_daily_sources()


if __name__ == "__main__":
    main()
