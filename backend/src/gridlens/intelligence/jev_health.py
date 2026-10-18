"""Safe Jev diagnostics. No credential values, evidence writes or implicit provider calls."""

from __future__ import annotations

import argparse
import json
from uuid import uuid4

import httpx

from gridlens.settings import settings


def diagnostic(*, probe: bool = False) -> dict[str, object]:
    """Inspect this process, optionally making exactly one bounded provider request."""
    from gridlens.intelligence.signal_adjudication import (
        _jev_call,
        failure_status,
        validated_dimensions,
    )

    secret = settings.typesafe_api_key
    key = secret.get_secret_value().strip() if secret else ""
    result: dict[str, object] = {
        "provider": "TypeSafe Jev",
        "model": settings.intelligence_typesafe_model,
        "credential_present": bool(key),
        "status": "not_checked" if key else "missing_credentials",
        "provider_requests": 0,
        "scope": "this process only; source ingestion and qualification are independent",
    }
    if not key or not probe:
        return result
    from gridlens.integrations.legacy_calls import perform_legacy_call
    from gridlens.intelligence.intelligence_jobs import _enabled

    enabled, _provider, model, reason = _enabled("JEV_HEALTH_PROBE")
    if not enabled:
        result["status"] = f"blocked:{reason}"
        return result
    state = dict.fromkeys(
        [
            "title",
            "abstract",
            "url",
            "published_at",
            "source_id",
            "source_family",
            "publisher",
            "event_date",
            "event_date_label",
            "project_name",
            "location",
            "asset_type",
            "lifecycle_state",
        ],
        "Unknown",
    )
    state["title"] = "GL3 provider connectivity diagnostic"
    state["abstract"] = "Connectivity check only. No project or commercial facts are asserted."
    try:
        call = perform_legacy_call(
            task_type="JEV_HEALTH_PROBE",
            task_key=f"explicit-health-probe:{uuid4()}",
            payload={"state": state, "model": model, "contract": "health-probe-v1"},
            source_id=None,
            project_id=None,
            job_id=None,
            worker_id=None,
            fence_token=0,
            invoke=lambda: (
                _jev_call(state, key, model=model, max_attempts=1),
                None,
                None,
            ),
        )
        validated_dimensions(call.result, expected_model=model)
        result["provider_requests"] = 1
        result["status"] = "available"
    except (KeyError, TypeError, ValueError, RuntimeError, httpx.HTTPError) as exc:
        if isinstance(exc, RuntimeError) and str(exc).startswith(
            ("The shared policy", "SENT_OUTCOME_UNKNOWN", "COMPLETED_RESPONSE_UNAVAILABLE")
        ):
            result["provider_requests"] = 0
        else:
            result["provider_requests"] = 1
        result["status"] = failure_status(exc)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe", action="store_true", help="Make one authenticated request (12s timeout)"
    )
    args = parser.parse_args()
    result = diagnostic(probe=args.probe)
    print(json.dumps(result))
    raise SystemExit(0 if result["status"] in {"available", "not_checked"} else 1)


if __name__ == "__main__":
    main()
