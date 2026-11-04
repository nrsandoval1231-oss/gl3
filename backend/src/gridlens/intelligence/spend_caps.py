"""Per-provider spend caps, near-cap status and typed capped-out states.

The shared ledger applies each configured cap to every provider, model, source and project
alike, so a 90/10 OpenAI/TypeSafe split cannot be written with the five shared scopes.
``INTELLIGENCE_PROVIDER_CAPS`` adds per-provider values that are combined with the shared
provider-scope cap by taking the smaller number: an override can tighten a provider, never
loosen any existing cap.

Everything here is pure or read-only. Nothing in this module reserves, dispatches or settles
a call.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

PERIODS = ("daily", "monthly")
_CAP_KEYS = frozenset({"daily", "monthly", "daily_usd", "monthly_usd"})
_PROVIDER_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_MAX_CALLS = 1_000_000
_MAX_USD = Decimal("100000")
# Reasons produced by logical_calls.reserve_call and intelligence_jobs._dispatch_policy.
_CAP_REASON = re.compile(
    r"(?P<scope>GLOBAL|PROVIDER|MODEL|SOURCE|PROJECT)_(?P<period>DAILY|MONTHLY)_"
    r"(?:USD_)?CAP_(?P<kind>REACHED|ZERO|INVALID)\Z"
)
CAPPED_OUT = "CAPPED_OUT"
NEAR_CAP = "NEAR_CAP"


def parse_provider_caps(raw: str) -> dict[str, dict[str, int | Decimal]]:
    """Parse and validate the per-provider cap map. Empty text means no overrides."""
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw, parse_float=Decimal)
    except (ValueError, RecursionError) as exc:
        raise ValueError("INTELLIGENCE_PROVIDER_CAPS must be a JSON object") from exc
    if not isinstance(data, dict) or len(data) > 8:
        raise ValueError("INTELLIGENCE_PROVIDER_CAPS must be a JSON object of at most 8 providers")
    result: dict[str, dict[str, int | Decimal]] = {}
    for provider, limits in data.items():
        if not isinstance(provider, str) or _PROVIDER_NAME.fullmatch(provider) is None:
            raise ValueError("INTELLIGENCE_PROVIDER_CAPS provider names must be lowercase words")
        if not isinstance(limits, dict) or not limits or not set(limits) <= _CAP_KEYS:
            raise ValueError(f"INTELLIGENCE_PROVIDER_CAPS[{provider}] has unsupported keys")
        clean: dict[str, int | Decimal] = {}
        for key, value in limits.items():
            if isinstance(value, bool):
                raise ValueError(f"INTELLIGENCE_PROVIDER_CAPS[{provider}].{key} is invalid")
            if key.endswith("_usd"):
                try:
                    money = Decimal(str(value))
                except InvalidOperation as exc:
                    raise ValueError(
                        f"INTELLIGENCE_PROVIDER_CAPS[{provider}].{key} is invalid"
                    ) from exc
                if not money.is_finite() or not 0 <= money <= _MAX_USD:
                    raise ValueError(
                        f"INTELLIGENCE_PROVIDER_CAPS[{provider}].{key} is out of range"
                    )
                clean[key] = money
            else:
                if type(value) is not int or not 0 <= value <= _MAX_CALLS:
                    raise ValueError(f"INTELLIGENCE_PROVIDER_CAPS[{provider}].{key} is invalid")
                clean[key] = value
        result[provider] = clean
    return result


def tighten_provider_scope(
    caps: dict[str, dict[str, Any]], provider: str | None, overrides: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Copy of ``caps`` whose provider scope is min(shared cap, provider override).

    A provider with no override, or an unknown provider, gets the shared caps unchanged.
    A zero override stays zero and therefore blocks that provider (fail closed).
    """
    result = {scope: dict(limits) for scope, limits in caps.items()}
    override = overrides.get(provider or "")
    if not override or "provider" not in result:
        return result
    shared = result["provider"]
    for key, value in override.items():
        current = shared.get(key)
        shared[key] = value if current is None else min(current, value)
    return result


def cap_fields(reason: str | None) -> dict[str, Any]:
    """Typed capped-out marker for a job checkpoint/result, or ``{}`` for other reasons."""
    match = _CAP_REASON.fullmatch(reason or "")
    if match is None:
        return {}
    return {
        "capped_out": True,
        "cap_state": CAPPED_OUT,
        "cap_scope": match["scope"].lower(),
        "cap_period": match["period"].lower(),
        "cap_reason": reason,
    }


def is_cap_reason(reason: str | None) -> bool:
    return bool(cap_fields(reason))


def _ratio(used: Decimal, cap: Decimal) -> Decimal | None:
    return None if cap <= 0 else used / cap


def spend_status(
    session: Any,
    *,
    global_caps: dict[str, dict[str, Any]],
    provider_caps: dict[str, dict[str, dict[str, Any]]],
    threshold: float,
    max_call_usd: Decimal,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Rows for every global/provider scope at or above ``threshold`` of its USD or call cap.

    ``global_caps`` is the shared cap table; ``provider_caps`` maps provider name to the
    effective (tightened) cap table. Usage is the ledger's reserved ceiling, which is what the
    caps enforce, not settled spend. Read-only.
    """
    from sqlalchemy import select

    from gridlens.persistence.models import LogicalCallBudget

    moment = now or datetime.now(UTC)
    keys = {"daily": moment.date().isoformat(), "monthly": moment.strftime("%Y-%m")}
    wanted: dict[str, dict[str, Any]] = {"global:global": global_caps["global"]}
    for provider, table in provider_caps.items():
        wanted[f"provider:{provider}"] = table["provider"]
    rows = session.scalars(
        select(LogicalCallBudget).where(
            LogicalCallBudget.scope.in_(list(wanted)),
            LogicalCallBudget.period.in_(PERIODS),
        )
    ).all()
    status: list[dict[str, Any]] = []
    for row in rows:
        if row.period_key != keys.get(row.period):
            continue
        limits = wanted[row.scope]
        usd_cap = Decimal(str(limits.get(f"{row.period}_usd", 0)))
        call_cap = int(limits.get(row.period, 0))
        used = Decimal(str(row.cost_usd))
        for metric, used_value, cap_value in (
            ("usd", used, usd_cap),
            ("calls", Decimal(row.call_count), Decimal(call_cap)),
        ):
            ratio = _ratio(used_value, cap_value)
            if ratio is None:
                continue
            blocks_next = (
                metric == "usd" and max_call_usd > 0 and cap_value - used_value < max_call_usd
            )
            if ratio >= 1 or blocks_next:
                level = CAPPED_OUT
            elif ratio >= Decimal(str(threshold)):
                level = NEAR_CAP
            else:
                continue
            status.append(
                {
                    "scope": row.scope,
                    "period": row.period,
                    "metric": metric,
                    "used": str(used_value),
                    "cap": str(cap_value),
                    "fraction": round(float(ratio), 4),
                    "level": level,
                }
            )
    return sorted(status, key=lambda item: (item["scope"], item["period"], item["metric"]))


def recent_capped_out_jobs(session: Any, *, hours: int = 48) -> dict[str, Any]:
    """Count recent intelligence/OCR jobs that ended CAPPED_OUT, with reasons. Read-only."""
    from datetime import timedelta

    from sqlalchemy import func, select

    from gridlens.persistence.models import Job

    since = datetime.now(UTC) - timedelta(hours=hours)
    marker = Job.checkpoint.like('%"capped_out":true%')
    total = session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.kind == "intelligence_process", Job.created_at >= since, marker)
    )
    return {"hours": hours, "jobs": int(total or 0)}
