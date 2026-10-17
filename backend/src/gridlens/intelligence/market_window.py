"""Select the trailing-week evidence window for the power-market newsletter.

Deterministic and model-free: eligible retained evidence is classified by region and
topic in code, then grouped under fixed caps. The result is hashed so an unchanged
window can be served from cache without any provider call.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, aliased

from gridlens.domain.editorial import canonical_url
from gridlens.domain.market import classify, group_items, normalize_title
from gridlens.intelligence.editorial_clearance import eligibility
from gridlens.persistence.models import Evidence, Observation, Source

POLICY_VERSION = "power-market-window-v1"
WINDOW_DAYS = 7
MAX_ITEMS_PER_GROUP = 8
MAX_ITEMS_TOTAL = 60
MAX_TITLE = 500
MAX_TEXT = 1_200
NEWS_FAMILIES = ("news", "structured-government")


@dataclass
class MarketWindow:
    start: date
    end: date
    items: dict[str, dict[str, Any]] = field(default_factory=dict)
    groups: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    fingerprint: str = ""


def today_central(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(ZoneInfo("America/Chicago")).date()


def window_fingerprint(items: dict[str, dict[str, Any]], groups: list[dict[str, Any]]) -> str:
    payload = {
        "policy_version": POLICY_VERSION,
        "items": [
            [item["id"], item["content_hash"], item["region"], item["topic"]]
            for item in sorted(items.values(), key=lambda i: i["id"])
        ],
        "groups": [[g["key"], g["item_ids"]] for g in groups],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def build_window(session: Session, now: datetime | None = None) -> MarketWindow:
    end = today_central(now)
    start = end - timedelta(days=WINDOW_DAYS)
    newer = aliased(Evidence)
    rows = session.execute(
        select(Observation, Evidence, Source)
        .join(Evidence, Evidence.observation_id == Observation.id)
        .join(Source, Source.id == Observation.source_id)
        .where(
            Source.family.in_(NEWS_FAMILIES),
            Evidence.published_at >= start,
            Evidence.published_at <= end,
            # Only the latest retained version of each observation.
            ~exists().where(
                newer.observation_id == Evidence.observation_id,
                newer.id != Evidence.id,
                (newer.observed_at > Evidence.observed_at)
                | ((newer.observed_at == Evidence.observed_at) & (newer.id > Evidence.id)),
            ),
        )
        .order_by(Evidence.published_at.desc(), Source.id, Evidence.id.desc())
        .limit(2_000)
    ).all()
    excluded: Counter[str] = Counter()
    seen_titles: set[str] = set()
    seen_urls: set[str] = set()
    items: dict[str, dict[str, Any]] = {}
    for observation, evidence, source in rows:
        reason = eligibility(observation, evidence, source, now=end)
        if reason:
            excluded[reason] += 1
            continue
        placement = classify(evidence.title, evidence.abstract, source.geography)
        if placement is None:
            excluded["not_power_market"] += 1
            continue
        try:
            url = canonical_url(evidence.url)
        except (ValueError, TypeError):
            excluded["unsafe_source_url"] += 1
            continue
        title_key = normalize_title(evidence.title)
        if url in seen_urls or title_key in seen_titles:
            excluded["duplicate"] += 1
            continue
        seen_urls.add(url)
        seen_titles.add(title_key)
        items[str(evidence.id)] = {
            "id": str(evidence.id),
            "observation_id": str(observation.id),
            "content_hash": evidence.content_hash,
            "title": evidence.title[:MAX_TITLE],
            "excerpt": (evidence.abstract or "")[:MAX_TEXT],
            "published_at": evidence.published_at.isoformat(),
            "url": url,
            "publisher": source.publisher,
            "source_id": source.id,
            **placement,
        }
    groups = group_items(
        list(items.values()), max_per_group=MAX_ITEMS_PER_GROUP, max_total=MAX_ITEMS_TOTAL
    )
    kept_ids = {item_id for group in groups for item_id in group["item_ids"]}
    omitted = len(items) - len(kept_ids)
    items = {item_id: item for item_id, item in items.items() if item_id in kept_ids}
    coverage = {
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "eligible_items": len(kept_ids) + omitted,
        "included_items": len(kept_ids),
        "omitted_by_caps": omitted,
        "excluded": dict(sorted(excluded.items())),
        "by_source": dict(sorted(Counter(i["source_id"] for i in items.values()).items())),
        "by_region": dict(sorted(Counter(i["region"] for i in items.values()).items())),
        "by_topic": dict(sorted(Counter(i["topic"] for i in items.values()).items())),
    }
    return MarketWindow(
        start=start,
        end=end,
        items=items,
        groups=groups,
        coverage=coverage,
        fingerprint=window_fingerprint(items, groups),
    )
