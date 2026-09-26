import re

_SPECIFIC_TITLE = re.compile(
    r"\b([A-Z][\w'-]+\s+){0,5}(Mine|Mining Project|Rare Earth Project|Mine Project)\b", re.I
)
_DEVELOPMENT = re.compile(
    r"\b(develop(?:ment|ing)?|construct(?:ion|ing)?|mine plan of operations|expansion)\b", re.I
)
_ACTIVITY = re.compile(r"\b(min(?:e|ing)|open-pit|tunnel|shaft|ore|dewater(?:ing)?)\b", re.I)
_EXCLUDED = re.compile(
    r"\b(policy|program(?:matic)?|rescission|cancel(?:led|ed)|withdrawn|"
    r"continued operation|license renewal|permit renewal)\b",
    re.I,
)
_FACILITY = re.compile(
    r"\b(facilit(?:y|ies)|plant|factory|manufactur\w*|production|operations|campus|building|site)\b",
    re.I,
)
_PHYSICAL_ACTION = re.compile(
    r"\b(expand\w*|construct\w*|build\w*|open\w*|establish\w*|add\w*)\b", re.I
)
_NC_NEGATIVE = re.compile(r"\b(cancel(?:led|ed)|withdrawn|rescinded|no longer proceeding)\b", re.I)
_NC_AGGREGATE = re.compile(
    r"\b(?:reports?\b|program(?:me)?\b|since the inception|communities\b|"
    r"building rehabilitations|year[- ]to[- ]date|fiscal year\s+\d{4})\b",
    re.I,
)
_NC_SITE_EVENT = re.compile(
    r"\b(?:company|manufacturer|business|firm|\w+(?:'s|’s)\s+\w+)\b.{0,220}"
    r"\b(?:will|plans? to|is planning to|announced plans to)\b.{0,180}"
    r"\b(?:invest|expand|construct|build|establish|open|add)\w*\b.{0,160}"
    r"\b(?:facility|plant|factory|campus|production|operations|manufacturing)\b",
    re.I,
)
_COUNTY = re.compile(r"\b([A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+){0,2}\s+County)\b")


def assess_signal(title: str, abstract: str | None) -> str | None:
    body = abstract or ""
    if (
        _SPECIFIC_TITLE.search(title)
        and _DEVELOPMENT.search(body)
        and _ACTIVITY.search(body)
        and not _EXCLUDED.search(f"{title} {body}")
    ):
        trigger = (
            "mine plan and mine development"
            if re.search(r"mine plan", body, re.I)
            else "proposed mine development"
        )
        return (
            f"The source describes {trigger}; construction or dewatering may need power. "
            "Activity-specific load, timing, duration, and suitable supply are unknown."
        )
    return None


def assess_nc_commerce_signal(title: str, excerpt: str | None) -> str | None:
    """Admit a dated public event only when a physical facility change is explicit."""
    body = excerpt or ""
    combined = f"{title} {body}"
    if _NC_NEGATIVE.search(combined) or _NC_AGGREGATE.search(combined):
        return None
    if not (_FACILITY.search(combined) and _PHYSICAL_ACTION.search(combined)):
        return None
    # A generic job count, grant or investment story is not a physical project.
    has_project_word = re.search(
        r"\b(expansion|expand\w*|new facility|new plant|new factory|manufacturing hub|"
        r"production campus|construct\w*|build\w*)\b",
        combined,
        re.I,
    )
    if not has_project_word:
        return None
    if not _NC_SITE_EVENT.search(combined):
        return None
    return (
        "The NC Commerce release describes a physical facility expansion or build, "
        "which can create construction or commissioning power needs. Activity-specific "
        "load, timing, duration, and suitable supply are unknown."
    )


def nc_commerce_location(excerpt: str | None) -> str | None:
    """Return only an explicitly named county; leave city/state parsing unknown."""
    match = _COUNTY.search(excerpt or "")
    return f"{match.group(1)}, North Carolina" if match else None
