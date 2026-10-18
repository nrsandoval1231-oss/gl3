from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from gridlens.domain.evaluation_clock import evaluate_at, evaluation_now, evaluation_today


def test_context_preserves_defaults_and_isolates_normal_threads():
    default = datetime(2026, 1, 1, tzinfo=UTC)
    future = datetime(2027, 1, 1, 0, tzinfo=UTC)
    assert evaluation_now(default) == default
    with evaluate_at(future):
        assert evaluation_now(default) == future
        chicago = evaluation_now(default.astimezone(ZoneInfo("America/Chicago")))
        assert chicago.date() == date(2026, 12, 31)
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(evaluation_now, default).result() == default
        with pytest.raises(RuntimeError), evaluate_at(default):
            assert evaluation_now(future) == default
            raise RuntimeError("synthetic")
        assert evaluation_now(default) == future
    assert evaluation_now(default) == default
    assert evaluation_today(date(2000, 1, 1)) == date(2000, 1, 1)
    with pytest.raises(ValueError), evaluate_at(datetime(2026, 1, 1)):
        pass


@pytest.mark.parametrize(
    "instant, chicago_day",
    [
        (datetime(2027, 1, 1, 0, tzinfo=UTC), date(2026, 12, 31)),
        (datetime(2026, 11, 1, 5, tzinfo=UTC), date(2026, 11, 1)),
        (datetime(2026, 11, 1, 7, tzinfo=UTC), date(2026, 11, 1)),
        (datetime(2026, 3, 8, 8, tzinfo=UTC), date(2026, 3, 8)),
    ],
)
def test_calendar_and_dst_clocks_preserve_their_own_zones(instant, chicago_day):
    from importlib import import_module

    api = import_module("gridlens.api.app")
    with evaluate_at(instant):
        assert api.chicago_today() == chicago_day
        assert evaluation_now(datetime.now(UTC)) == instant
        assert evaluation_today(date.today()) == instant.astimezone().date()
