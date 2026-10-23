import json
import pickle
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from gridlens.ingestion.adapters.bounded_http import AcquisitionFailure, _safe_acquisition_error
from gridlens.ingestion.adapters.diagnostics import (
    acquisition_diagnostics,
    acquisition_error_message,
    acquisition_stage,
)
from gridlens.ingestion.adapters.federal_register import SourceParseError


def test_http_status_and_stage_survive_wrapping_process_transfer_and_second_sanitization():
    request = httpx.Request("GET", "https://example.test/private?token=DO_NOT_RETAIN")
    response = httpx.Response(403, request=request, headers={"secret": "DO_NOT_RETAIN"})
    try:
        try:
            with acquisition_stage("georgia_document"):
                response.raise_for_status()
        except httpx.HTTPError as error:
            raise SourceParseError("wrapper DO_NOT_RETAIN") from error
    except SourceParseError as error:
        safe = _safe_acquisition_error(error)
    transferred = pickle.loads(pickle.dumps(safe))
    again = _safe_acquisition_error(transferred)
    assert acquisition_diagnostics(again) == {
        "error_code": "http_status_403",
        "http_status": 403,
        "error_stage": "georgia_document",
    }
    assert "DO_NOT_RETAIN" not in str(again)
    assert "example.test" not in str(again)
    assert "DO_NOT_RETAIN" not in json.dumps(again.__dict__)


@pytest.mark.parametrize("status", [302, 403, 429, 500])
def test_http_codes_are_retained_without_url_or_headers(status):
    request = httpx.Request("GET", "https://example.test/?secret=DO_NOT_RETAIN")
    error = httpx.HTTPStatusError(
        "DO_NOT_RETAIN", request=request, response=httpx.Response(status, request=request)
    )
    safe = _safe_acquisition_error(error)
    assert isinstance(safe, AcquisitionFailure)
    assert str(safe) == f"http_status_{status}"
    assert acquisition_diagnostics(safe)["http_status"] == status
    assert "DO_NOT_RETAIN" not in acquisition_error_message(safe)


def test_retry_after_seconds_survive_isolation_without_retaining_headers():
    request = httpx.Request("GET", "https://example.test/?token=DO_NOT_RETAIN")
    error = httpx.HTTPStatusError(
        "rate limited",
        request=request,
        response=httpx.Response(
            429,
            request=request,
            headers={"Retry-After": "321", "Secret": "DO_NOT_RETAIN"},
        ),
    )
    safe = _safe_acquisition_error(error)
    transferred = pickle.loads(pickle.dumps(safe))
    diagnostics = acquisition_diagnostics(_safe_acquisition_error(transferred))
    assert diagnostics["retry_after_seconds"] == 321
    assert diagnostics["http_status"] == 429
    assert "DO_NOT_RETAIN" not in str(safe)
    assert "DO_NOT_RETAIN" not in json.dumps(safe.__dict__)


def test_retry_after_http_date_is_parsed_and_over_bound_is_not_clamped_early():
    request = httpx.Request("GET", "https://example.test")
    retry_at = datetime.now(UTC) + timedelta(minutes=2)
    error = httpx.HTTPStatusError(
        "unavailable",
        request=request,
        response=httpx.Response(
            503, request=request, headers={"Retry-After": format_datetime(retry_at, usegmt=True)}
        ),
    )
    delay = acquisition_diagnostics(error)["retry_after_seconds"]
    assert 110 <= delay <= 120

    over_bound = httpx.HTTPStatusError(
        "unavailable",
        request=request,
        response=httpx.Response(503, request=request, headers={"Retry-After": "604801"}),
    )
    assert acquisition_diagnostics(over_bound)["retry_after_exceeds_bound"] == 1


@pytest.mark.parametrize(
    "error",
    [
        SourceParseError("DO_NOT_RETAIN token=abcd password=xyz"),
        AcquisitionFailure("arbitrary_secret_lowercase"),
        ValueError("DO_NOT_RETAIN"),
    ],
)
def test_arbitrary_messages_and_metadata_are_never_forwarded(error):
    error.acquisition_code = "arbitrary_secret_lowercase"
    error.acquisition_stage = "DO_NOT_RETAIN"
    safe = _safe_acquisition_error(error)
    result = acquisition_diagnostics(safe)
    assert result["error_code"] in {"source_parse_error", "acquisition_failed"}
    assert "error_stage" not in result
    assert "DO_NOT_RETAIN" not in str(safe)
    assert "arbitrary_secret" not in str(safe)


def test_known_parser_error_survives_as_reviewed_code_and_unknown_detail_does_not():
    safe = _safe_acquisition_error(
        SourceParseError("Boston permit rows have duplicate identity or bad order")
    )
    assert acquisition_diagnostics(safe)["error_code"] == "boston_row_order"
    unknown = _safe_acquisition_error(SourceParseError("Boston secret=DO_NOT_RETAIN"))
    assert acquisition_diagnostics(unknown)["error_code"] == "source_parse_error"


def test_publisher_staleness_stays_distinct_from_transport_or_parser_failure():
    safe = _safe_acquisition_error(
        SourceParseError(
            "Houston publisher has not posted a weekly report since 2026-09-07 (over 30 days)"
        )
    )
    assert isinstance(safe, SourceParseError)
    assert acquisition_diagnostics(safe)["error_code"] == "publisher_stale"


def test_cause_cycles_and_non_allowlisted_stages_are_bounded():
    error = SourceParseError("untrusted")
    error.__cause__ = error
    assert acquisition_diagnostics(error) == {"error_code": "source_parse_error"}
    with pytest.raises(ValueError, match="Unknown acquisition diagnostic stage"):
        with acquisition_stage("arbitrary stage"):
            pytest.fail("invalid stage was admitted")
