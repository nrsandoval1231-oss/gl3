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


@pytest.mark.parametrize(
    ("error_code", "http_status", "expected"),
    [
        ("network_error", None, "TRANSIENT"),
        ("acquisition_timeout", None, "TRANSIENT"),
        ("http_status_429", 429, "TRANSIENT"),
        ("http_status_503", 503, "TRANSIENT"),
        ("http_status_403", 403, "PERMANENT"),
        ("source_parse_error", None, "PERMANENT"),
        ("unexpected", None, "BOUNDED_UNKNOWN"),
    ],
)
def test_acquisition_retry_classification_is_bounded_and_fail_closed(
    error_code, http_status, expected
):
    from gridlens.jobs.worker import _acquisition_retry_class

    diagnostics = {"error_code": error_code}
    if http_status is not None:
        diagnostics["http_status"] = http_status
    assert _acquisition_retry_class(RuntimeError("fixture"), diagnostics) == expected


@pytest.mark.parametrize(
    ("error", "diagnostics", "expected"),
    [
        ("timeout", {"error_code": "acquisition_timeout"}, "TRANSIENT"),
        ("parse_timeout", {"error_code": "acquisition_timeout"}, "TRANSIENT"),
        ("parse_503", {"http_status": 503, "error_code": "source_parse_error"}, "TRANSIENT"),
        ("parse_429", {"http_status": 429, "error_code": "source_parse_error"}, "TRANSIENT"),
        ("parse_403", {"http_status": 403, "error_code": "source_parse_error"}, "PERMANENT"),
        ("parse", {"error_code": "source_parse_error"}, "PERMANENT"),
        (
            "parse_503",
            {"http_status": 503, "retry_after_exceeds_bound": 1},
            "PERMANENT",
        ),
    ],
)
def test_wrapped_acquisition_failures_respect_trusted_retry_diagnostics(
    error, diagnostics, expected
):
    import httpx

    from gridlens.ingestion.adapters.federal_register import SourceParseError
    from gridlens.jobs.worker import _acquisition_retry_class

    request = httpx.Request("GET", "https://example.test")
    response = httpx.Response(503, request=request)
    errors = {
        "timeout": httpx.ReadTimeout("offline", request=request),
        "parse_timeout": SourceParseError("collection failed"),
        "parse_503": SourceParseError("collection failed"),
        "parse_429": SourceParseError("collection failed"),
        "parse_403": SourceParseError("collection failed"),
        "parse": SourceParseError("invalid schema"),
    }
    cause = (
        httpx.ReadTimeout("offline", request=request)
        if error == "parse_timeout"
        else httpx.HTTPStatusError("status", request=request, response=response)
        if error.startswith("parse_")
        else None
    )
    if cause:
        errors[error].__cause__ = cause
    assert _acquisition_retry_class(errors[error], diagnostics) == expected
