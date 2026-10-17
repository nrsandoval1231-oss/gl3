"""Safe Jev diagnostics. No credential values, evidence writes or implicit provider calls."""

from __future__ import annotations

import argparse
import json

import httpx

from gridlens.settings import settings


def diagnostic(*, probe: bool = False) -> dict[str, object]:
    """Inspect this process, optionally making exactly one bounded provider request."""
    from gridlens.intelligence.signal_adjudication import (
        MODEL,
        _jev_call,
        failure_status,
        validated_dimensions,
    )

    secret = settings.typesafe_api_key
    key = secret.get_secret_value().strip() if secret else ""
    result: dict[str, object] = {
        "provider": "TypeSafe Jev",
        "model": MODEL,
        "credential_present": bool(key),
        "status": "not_checked" if key else "missing_credentials",
        "provider_requests": 0,
        "scope": "this process only; source ingestion and qualification are independent",
    }
    if not key or not probe:
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
    result["provider_requests"] = 1
    try:
        validated_dimensions(_jev_call(state, key, max_attempts=1))
        result["status"] = "available"
    except (KeyError, TypeError, ValueError, RuntimeError, httpx.HTTPError) as exc:
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
