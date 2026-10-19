import pytest

from gridlens.jobs.retry import jittered_delay_seconds


def test_retry_jitter_is_repeatable_bounded_and_separates_identities():
    first = jittered_delay_seconds("job-a", 2, 600, ceiling_seconds=3600)
    assert first == jittered_delay_seconds("job-a", 2, 600, ceiling_seconds=3600)
    assert 480 <= first <= 720
    assert jittered_delay_seconds("job-b", 2, 600, ceiling_seconds=3600) != first


def test_retry_jitter_clamps_ceiling_and_rejects_invalid_inputs():
    assert jittered_delay_seconds("job", 1, 9000, ceiling_seconds=3600) <= 3600
    with pytest.raises(ValueError):
        jittered_delay_seconds("", 1, 10, ceiling_seconds=20)
    with pytest.raises(ValueError):
        jittered_delay_seconds("job", 1, 10, ceiling_seconds=20, jitter_percent=101)
