"""Deterministic region/topic classification and grouping for power-market items.

No model is involved. Classification is keyword evidence over the retained title and
abstract only, so every assignment can be reproduced and explained.
"""

import re
from typing import Any

REGIONS: dict[str, tuple[str, ...]] = {
    "ercot": (r"ercot", r"texas", r"houston", r"dallas", r"austin", r"oncor", r"puct"),
    "pjm": (
        r"pjm",
        r"pennsylvania",
        r"virginia",
        r"ohio",
        r"new jersey",
        r"maryland",
        r"dominion",
        r"delaware",
    ),
    "caiso": (r"caiso", r"california", r"pg&e", r"sce\b", r"cpuc"),
    "miso": (
        r"miso",
        r"midcontinent",
        r"louisiana",
        r"michigan",
        r"indiana",
        r"minnesota",
        r"wisconsin",
        r"entergy",
    ),
    "spp": (r"\bspp\b", r"southwest power pool", r"oklahoma", r"kansas", r"nebraska"),
    "nyiso": (r"nyiso", r"new york", r"con ?ed", r"nypa"),
    "iso-ne": (r"iso[- ]new england", r"iso-ne", r"new england", r"massachusetts", r"connecticut"),
    "southeast": (
        r"georgia",
        r"carolina",
        r"florida",
        r"tennessee",
        r"alabama",
        r"\btva\b",
        r"duke energy",
        r"southern company",
    ),
    "west": (
        r"arizona",
        r"nevada",
        r"oregon",
        r"utah",
        r"colorado",
        r"idaho",
        r"montana",
        r"wecc",
        r"\bbpa\b",
        r"pacific northwest",
    ),
    "international": (
        r"europe",
        r"\buk\b",
        r"united kingdom",
        r"ireland",
        r"germany",
        r"china",
        r"india",
        r"japan",
        r"australia",
        r"singapore",
        r"netherlands",
        r"canada",
    ),
}
DEFAULT_REGION = "national"
REGION_LABELS = {
    "ercot": "ERCOT / Texas",
    "pjm": "PJM / Mid-Atlantic",
    "caiso": "CAISO / California",
    "miso": "MISO / Midcontinent",
    "spp": "SPP / Southwest Power Pool",
    "nyiso": "NYISO / New York",
    "iso-ne": "ISO-NE / New England",
    "southeast": "Southeast",
    "west": "West",
    "international": "International",
    "national": "National and multi-region",
}
SOURCE_GEOGRAPHY_REGION = {"texas": "ercot", "california": "caiso"}

TOPICS: dict[str, tuple[str, ...]] = {
    "load-growth": (
        r"data cent(?:er|re)s?",
        r"large loads?",
        r"load growth",
        r"hyperscal\w*",
        r"demand growth",
        r"electrification",
        r"\bai\b",
        r"artificial intelligence",
    ),
    "interconnection": (r"interconnect\w*", r"queue", r"study process", r"cluster stud\w*"),
    "generation": (
        r"solar",
        r"wind",
        r"nuclear",
        r"reactor",
        r"gas[- ]fired",
        r"natural gas",
        r"battery",
        r"storage",
        r"coal",
        r"geothermal",
        r"hydro\w*",
        r"power plants?",
        r"generat\w+",
        r"turbines?",
        r"capacity addition",
    ),
    "transmission": (
        r"transmission",
        r"substations?",
        r"transformers?",
        r"distribution",
        r"grid",
        r"high[- ]voltage",
        r"\bkv\b",
    ),
    "policy-tariffs": (
        r"tariffs?",
        r"rate cases?",
        r"ferc",
        r"commission",
        r"regulat\w+",
        r"legislat\w+",
        r"\bbill\b",
        r"\brule\b",
        r"\bdoe\b",
        r"\bepa\b",
        r"permit\w*",
        r"environmental impact",
    ),
    "prices-markets": (
        r"wholesale",
        r"capacity (?:auction|market|price)s?",
        r"\blmp\b",
        r"electricity prices?",
        r"power prices?",
        r"energy prices?",
        r"spot prices?",
        r"price spikes?",
        r"ratepayers?",
        r"auctions?",
        r"prices?",
        r"market",
    ),
}
TOPIC_LABELS = {
    "load-growth": "Load growth and data centers",
    "interconnection": "Interconnection",
    "generation": "Generation and storage",
    "transmission": "Transmission and grid",
    "policy-tariffs": "Policy, regulation and tariffs",
    "prices-markets": "Prices and markets",
}
# An item must be about power at all before topic keywords can place it.
POWER_GATE = re.compile(
    r"\b(?:power|electric\w*|grid|utilit(?:y|ies)|energy|megawatts?|gigawatts?|\d+\s?(?:mw|gw)"
    r"|kilowatts?|transmission|generation|interconnection|ratepayers?|substations?)\b",
    re.I,
)


def _hits(patterns: tuple[str, ...], title: str, abstract: str) -> int:
    score = 0
    for pattern in patterns:
        rx = re.compile(
            rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])" if r"\b" not in pattern else pattern, re.I
        )
        score += 2 * len(rx.findall(title)) + len(rx.findall(abstract))
    return score


def best(table: dict[str, tuple[str, ...]], title: str, abstract: str) -> str | None:
    """Highest keyword score; ties resolve by the table's fixed order. None if no hit."""
    top_key, top_score = None, 0
    for key, patterns in table.items():
        score = _hits(patterns, title, abstract)
        if score > top_score:
            top_key, top_score = key, score
    return top_key


def classify(title: str, abstract: str | None, source_geography: str = "") -> dict[str, Any] | None:
    """Return {region, topic} or None when the item is not demonstrably about power."""
    abstract = abstract or ""
    if not POWER_GATE.search(f"{title}\n{abstract}"):
        return None
    topic = best(TOPICS, title, abstract)
    if topic is None:
        return None
    region = best(REGIONS, title, abstract)
    if region is None:
        region = SOURCE_GEOGRAPHY_REGION.get(source_geography.strip().casefold(), DEFAULT_REGION)
    return {"region": region, "topic": topic}


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()


def group_items(
    items: list[dict[str, Any]], max_per_group: int = 8, max_total: int = 60
) -> list[dict[str, Any]]:
    """Group classified items; deterministic order and caps.

    Items are expected to carry region, topic, published_at (ISO date) and id. Larger
    groups come first (ties by key); within a group newest first (ties by id). Items
    over the per-group or total cap are counted, never silently dropped.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        buckets.setdefault(f"{item['region']}:{item['topic']}", []).append(item)
    order = sorted(buckets, key=lambda key: (-len(buckets[key]), key))
    groups, used = [], 0
    for key in order:
        members = sorted(buckets[key], key=lambda i: (i["published_at"], i["id"]), reverse=True)
        room = max(0, min(max_per_group, max_total - used))
        kept = members[:room]
        if not kept:
            continue
        used += len(kept)
        region, topic = key.split(":")
        groups.append(
            {
                "key": key,
                "region": region,
                "topic": topic,
                "label": f"{REGION_LABELS[region]}: {TOPIC_LABELS[topic]}",
                "item_ids": [i["id"] for i in kept],
                "total_items": len(members),
                "omitted_items": len(members) - len(kept),
            }
        )
    return groups
