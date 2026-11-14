"""Bounded source-local binding for project activity predicates.

Callers supply spans already selected from one source sentence. This module
only accepts a small set of direct grammatical links; it does not resolve site
identity or carry subjects across sentences.
"""

from __future__ import annotations

import re

_NEGATED_OR_HYPOTHETICAL = re.compile(
    r"\b(?:not|never|no\s+longer|cannot|can't|could\s+not|may|might|could|"
    r"possibly|hypothetical(?:ly)?|for\s+example|for\s+instance|e\.g\.|"
    r"cancelled|canceled|abandoned|withdrawn|terminated)\b",
    re.I,
)
_STATUS_ACTIVITY = re.compile(
    r"(?:(?:is|are|was|were|currently)\s+)?under\s+construction|"
    r"construction\s+(?:has\s+)?(?:begun|started|commenced)|"
    r"broke\s+ground|groundbreaking|(?:has\s+)?(?:begun|started|commenced)\s+"
    r"(?:construction|development)",
    re.I,
)
_DEVELOPMENT_ACTIVITY = re.compile(
    r"(?:(?:plans?\s+to|planned\s+to|will|to)\s+)?(?:develop|build|construct)|"
    r"(?:planned\s+)?development\s+of",
    re.I,
)
_DIRECT_STATUS_GAP = re.compile(
    r"\s*(?:(?:,|and)\s*)?(?:(?:that|which)\s+)?"
    r"(?:(?:is|are|was|were|has|have|had|will|remains|continues)\s+)?"
    r"(?:(?:currently|now|still|actively|already|just|yet)\s+)*$",
    re.I,
)
_LOCATION_RELATION = re.compile(
    r"\s*(?:(?:on\s+\d[\d,.]*\s+acres?\s+of\s+land\s+)?"
    r"(?:in|at|near|within|inside|on|adjacent\s+to|next\s+to)\s+)"
    r"(?:the\s+)?[A-Z0-9][\w’'. ,/-]{0,90}$",
    re.I,
)
_OBJECT_LINK = re.compile(
    r"\s*(?:(?:a|an|the|its|their|this|new|planned|proposed|first|second|third|"
    r"fourth|initial|phase|over|up|to|million|billion|square|feet|of|highly|"
    r"resilient|hyperscale|AI|HPC|mega-scale|state-of-the-art|data|center|centre|"
    r"campus|facility|site|Tier|\d[\d,.]*(?:\s*(?:MW|megawatts?|GW|gigawatts?|"
    r"kW|kilowatts?))?|[IVX]+|\d+(?:®|™)?)(?:\s+|$)){0,14}$",
    re.I,
)


def _valid_span(text: str, span: tuple[int, int]) -> bool:
    return (
        isinstance(span, tuple)
        and len(span) == 2
        and isinstance(span[0], int)
        and isinstance(span[1], int)
        and 0 <= span[0] < span[1] <= len(text)
    )


def _status_is_direct(
    text: str,
    subject_span: tuple[int, int],
    activity_span: tuple[int, int],
    site_span: tuple[int, int],
) -> bool:
    subject_start, subject_end = subject_span
    activity_start, activity_end = activity_span
    site_start, site_end = site_span
    if activity_end <= subject_start and subject_end <= site_start:
        # A verb-first status can identify a named physical site only when it
        # directly governs the site through an at/on phrase and the site is
        # immediately followed by its explicit locality.
        return bool(
            not text[:activity_start].strip()
            and re.fullmatch(r"\s+(?:at|on)\s+(?:the\s+)?", text[activity_end:subject_start], re.I)
            and re.fullmatch(r"\s+", text[subject_end:site_start])
            and re.match(r"\s*in\s+", text[site_start:site_end], re.I)
            and _LOCATION_RELATION.fullmatch(text[site_start:site_end])
        )
    if subject_end > activity_start:
        return False
    if site_span == subject_span:
        return bool(_DIRECT_STATUS_GAP.fullmatch(text[subject_end:activity_start]))
    # A locality phrase may sit between the physical subject and its status,
    # but only through an explicit locative connector and a direct copula.
    if subject_end <= site_start and site_end <= activity_start:
        if not _LOCATION_RELATION.fullmatch(text[subject_end:site_end]):
            return False
        return bool(_DIRECT_STATUS_GAP.fullmatch(text[site_end:activity_start]))
    if site_start >= activity_start or site_end <= subject_start:
        # Locality can precede a directly named subject in a sentence.
        if site_end <= subject_start:
            return bool(
                _LOCATION_RELATION.fullmatch(text[site_end:subject_start])
                and _DIRECT_STATUS_GAP.fullmatch(text[subject_end:activity_start])
            )
    return False


def _development_object_is_direct(
    text: str,
    subject_span: tuple[int, int],
    activity_span: tuple[int, int],
    site_span: tuple[int, int],
) -> bool:
    activity_start, activity_end = activity_span
    subject_start, subject_end = subject_span
    site_start, site_end = site_span
    if activity_end > subject_start or subject_end > site_start:
        return False
    # The development verb must govern the selected physical object directly;
    # unrelated prose or a different facility in between fails closed.
    if not _OBJECT_LINK.fullmatch(text[activity_end:subject_start]):
        return False
    return bool(_LOCATION_RELATION.fullmatch(text[subject_end:site_end]))


def activity_is_bound_to_project(
    text: str,
    *,
    subject_span: tuple[int, int],
    activity_span: tuple[int, int],
    site_span: tuple[int, int],
) -> bool:
    """Return whether one activity match is grammatically bound to a site.

    All spans are half-open character offsets relative to the same sentence.
    `subject_span` identifies the selected physical site or a caller-resolved
    anaphor; `site_span` identifies its explicit locality/relation, or may equal
    the subject span for a resolved local subject without a separate locality.
    Unsupported wording, negation, hypothetical language, and competing site
    predicates abstain.
    """
    spans = (subject_span, activity_span, site_span)
    if any(not _valid_span(text, span) for span in spans):
        return False
    activity = text[slice(*activity_span)]
    prefix = text[: activity_span[0]]
    if _NEGATED_OR_HYPOTHETICAL.search(prefix) or _NEGATED_OR_HYPOTHETICAL.search(
        text[activity_span[1] :]
    ):
        return False
    if _STATUS_ACTIVITY.fullmatch(activity):
        return _status_is_direct(text, subject_span, activity_span, site_span)
    if _DEVELOPMENT_ACTIVITY.fullmatch(activity):
        return _development_object_is_direct(text, subject_span, activity_span, site_span)
    return False
