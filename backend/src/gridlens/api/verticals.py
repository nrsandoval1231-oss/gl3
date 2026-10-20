"""Inbox filter groups over source-level industry tags."""

VERTICAL_TAGS = {
    "data-centers": ("data centers",),
    "energy-and-utilities": ("utilities", "energy"),
    "oil-and-gas": ("oil and gas",),
    "industrial-and-manufacturing": ("manufacturing", "industrial facilities"),
    "construction-and-facilities": (
        "construction",
        "commercial construction",
        "commercial facilities",
    ),
    "healthcare": ("healthcare",),
    "cannabis": ("cannabis", "cannabis cultivation"),
    "mining": ("mining",),
    "infrastructure": ("infrastructure",),
}

VERTICAL_ALIASES = {
    alias: group for group, tags in VERTICAL_TAGS.items() for alias in (group, *tags)
}


def vertical_source_tags(value: str) -> tuple[str, ...]:
    """Return source tags for a canonical group or a retained legacy URL tag."""
    normalized = value.strip().lower()
    group = VERTICAL_ALIASES.get(normalized)
    return VERTICAL_TAGS[group] if group else (value,)
