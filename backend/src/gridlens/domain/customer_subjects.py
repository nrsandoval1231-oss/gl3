"""Source-local subject binding for retained customer facts.

This module binds an already extracted claim to native project names in the
original source. It does not infer identities from company names, locations, or
nearby numerical values.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass

_CLAUSE_BREAK = re.compile(r"(?<=[.!?])\s+|[\n;]+")
_ANAPHORA = re.compile(
    r"^(?:the\s+(?:(?:phase\s+(?:[0-9]+|[ivx]+)\s+)?design\s+of\s+the\s+site|"
    r"deal|facility|project|campus|site|data\s+center|"
    r"(?:\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:MW|megawatts?)\s+)?"
    r"(?:data\s+center\s+)?expansion)|"
    r"this\s+(?:facility|project|campus|site|data\s+center|expansion)|it)\b",
    re.I,
)
_SITE_NOUN = r"(?:campus|data\s+cent(?:er|re)|facility|site|project|plant|station)"
_NAMED_SITE = re.compile(rf"(?:[A-Z][\w’'-]+\s+){{1,5}}(?i:{_SITE_NOUN})\b")
_LEADING_SITE_SUBJECT = re.compile(
    rf"^\s*(?:the\s+)?(?:[\w’'-]+\s+){{0,5}}(?i:{_SITE_NOUN})\b", re.I
)
_COMPETING_SITE = re.compile(
    rf"\b(?:and|while|whereas|versus|but|compared\s+with)\s+"
    rf"(?:the\s+)?(?:[A-Z][\w’'-]+\s+){{1,5}}(?i:{_SITE_NOUN})\b|"
    rf"(?i:\b(?:and|while|whereas|versus|but|compared\s+with)\s+(?:the\s+)?)"
    rf"(?:(?!(?:to|for|with|from|of|at|in|on|by|support|build|serve|develop|house|land)\b)"
    rf"[\w’'-]+\s+){{1,3}}(?i:{_SITE_NOUN})\b|"
    rf"\b(?:other|another)\s+(?:[\w’'-]+\s+){{0,4}}(?i:{_SITE_NOUN})\b"
)
_FOREIGN_SITE_RELATION = re.compile(
    rf"(?i:\b(?:at|in|near|on|within|adjacent\s+to|next\s+to|access\s+to)\s+(?:the\s+)?)"
    rf"(?:[\w’'-]+\s+){{1,5}}(?i:{_SITE_NOUN})\b"
)
_FOREIGN_SITE_OWNS_PREDICATE = re.compile(
    rf"(?i:\b(?:at|in|near|on|within|adjacent\s+to|next\s+to|access\s+to)\s+(?:the\s+)?)"
    rf"(?:[\w’'-]+\s+){{1,5}}(?i:{_SITE_NOUN})\s+"
    rf"(?:(?:which|that)\s+)?(?:has|is|will|can|provides|features|offers|with)\b"
)
_NAMED_FOREIGN_SITE_RELATION = re.compile(
    rf"(?i:\b(?:at|in|near|on|within|adjacent\s+to|next\s+to|access\s+to)\s+(?:the\s+)?)"
    rf"(?:[A-Z][\w’'-]*\s+){{1,5}}(?i:{_SITE_NOUN})\b"
)
_FOREIGN_SITE_REFERENCE = re.compile(
    rf"(?i:\b(?:adjacent\s+to|alongside|next\s+to|near|access\s+to|uses?|"
    rf"smaller\s+than|larger\s+than|higher\s+than|lower\s+than|separate\s+from)\s+"
    rf"(?:the\s+)?)"
    rf"(?:[\w’'-]+\s+){{1,4}}(?i:{_SITE_NOUN})\b"
    rf"(?:\s*(?:,\s*)?(?:whose|which|that)\b|\s+[’']s\b)?|"
    rf"(?i:\b(?:whose|which|that)\s+(?:IT\s+)?(?:load|capacity|power)\b)"
)

_OWNED_CAPACITY_PREFIX = re.compile(
    r"^\s*(?:(?:phase\s+(?:[0-9]+|[ivx]+)|"
    r"(?:initial|first|second|third|fourth)\s+phase)\s+)?"
    r"(?:(?:has|have|had|will\s+have|features?|includes?|hosts?|will\s+host|"
    r"will\s+accommodate|can\s+deliver|will\s+deliver|is\s+capable\s+of\s+delivering)\s*|"
    r"(?:(?:is|was|will\s+be)\s+)?(?:designed|intended|planned)\s+to\s+"
    r"(?:host|support|accommodate|deliver|provide|scale\s+to)\s*|"
    r"(?:is\s+designed\s+for|has\s+a\s+capacity\s+of)\s+)"
    r"(?:(?:up\s+to|about|approximately|around|a\s+total\s+of|totaling|over|at\s+least)\s+)*\s*$",
    re.I,
)
_ELECTRICAL_AMOUNT = re.compile(
    r"(?i)(?<![\w.])(?:\d{1,3}(?:,\d{3})*(?:\.\d+)?|"
    r"one|two|three|four|five|six|seven|eight|nine|ten)\s*"
    r"(?:MW|megawatts?|GW|gigawatts?|kW|kilowatts?)\b"
)
_DIRECT_TIMELINE_PREDICATE = re.compile(
    r"^\s*(?:construction\s+(?:(?:is|was|will)\s+)?"
    r"(?:(?:expected|scheduled|planned|targeted)\s+to\s+)?"
    r"(?:began|started|commenced|start|begin|commence|begins|starts)|"
    r"(?:began|started|commenced)\s+construction|"
    r"(?:is|was|will\s+be)?\s*(?:expected|scheduled|planned|targeted)?\s*"
    r"to\s+be\s+energized|(?:first\s+)?energization\s+"
    r"(?:(?:is|was)\s+)?(?:(?:expected|scheduled|planned|targeted)\s+)?"
    r"(?:on|in|for)|(?:full\s+)?operations?\s+"
    r"(?:(?:is|are)\s+)?(?:(?:expected|scheduled|planned|targeted)\s+)?"
    r"(?:on|in|for)|ready\s+for\s+service\s+|"
    r"(?:is|was|will\s+be)\s+(?:(?:expected|scheduled|planned|targeted)\s+)?"
    r"(?:ready\s+for\s+service|operational\s+(?:by|in))|"
    r"(?:(?:is|was|will\s+be)\s+)?(?:expected|scheduled|planned|targeted)\s+to\s+be\s+"
    r"(?:energized\s+in|operational\s+(?:by|in)))",
    re.I,
)


@dataclass(frozen=True)
class ClauseSpan:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class SubjectBinding:
    alias: str
    subject_kind: str
    predicate: str
    quote_span: tuple[int, int]
    subject_span: tuple[int, int]
    predicate_span: tuple[int, int]
    antecedent_span: tuple[int, int] | None = None

    def as_json(self, *, source_hash: str | None = None) -> dict:
        return {
            **asdict(self),
            "quote_span": list(self.quote_span),
            "subject_span": list(self.subject_span),
            "predicate_span": list(self.predicate_span),
            "antecedent_span": list(self.antecedent_span)
            if self.antecedent_span is not None
            else None,
            "source_hash": source_hash,
        }


def clause_spans(text: str) -> list[ClauseSpan]:
    """Split text into clauses with half-open Unicode codepoint offsets."""
    spans = []
    start = 0
    for boundary in _CLAUSE_BREAK.finditer(text):
        end = boundary.start()
        if text[start:end].strip():
            left = start + len(text[start:end]) - len(text[start:end].lstrip())
            right = start + len(text[start:end].rstrip())
            spans.append(ClauseSpan(left, right, text[left:right]))
        start = boundary.end()
    if text[start:].strip():
        left = start + len(text[start:]) - len(text[start:].lstrip())
        right = len(text.rstrip())
        spans.append(ClauseSpan(left, right, text[left:right]))
    return spans


def _safe_aliases(values: Iterable[str], *, allow_single: bool = False) -> list[str]:
    unique = {}
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if (len(cleaned.split()) < 2 and not allow_single) or len(cleaned) > 180:
            continue
        unique[cleaned.casefold()] = cleaned
    return sorted(unique.values(), key=lambda value: (-len(value), value.casefold()))


def _alias_pattern(aliases: list[str]) -> str:
    return "(?:" + "|".join(re.escape(value) for value in aliases) + ")"


def _has_competing_physical_site(text: str) -> bool:
    """Ignore generic market/sector mentions while retaining named-site holds."""
    for match in _COMPETING_SITE.finditer(text):
        generic_data_center = re.fullmatch(
            r"(?:and|while|whereas|versus|but|compared\s+with)\s+(?:the\s+)?"
            r"(?:(?:largest|most|desired)\s+)*data\s+cent(?:er|re)",
            match.group(),
            re.I,
        )
        market_suffix = re.match(r"\s*(?:markets?|industry|sector)\b", text[match.end() :], re.I)
        if generic_data_center is None or market_suffix is None:
            return True
    return False


def _direct_binding(
    clause: ClauseSpan,
    *,
    aliases: list[str],
    owner_names: list[str],
    quote_span: tuple[int, int],
) -> SubjectBinding | None:
    alias_re = _alias_pattern(aliases)
    direct = re.match(rf"\s*(?:the\s+)?(?P<alias>{alias_re})(?=\b|\s)", clause.text, re.I)
    kind = "native_site_alias"
    subject_start = clause.start + (direct.start("alias") if direct else 0)
    subject_end = clause.start + (direct.end("alias") if direct else 0)
    if direct is None:
        owners = _safe_aliases(owner_names)
        if not owners:
            return None
        owner_re = _alias_pattern(owners)
        possessive = re.match(
            rf"\s*(?P<owner>{owner_re})[’']s\s+(?:the\s+)?(?P<alias>{alias_re})(?=\b|\s)",
            clause.text,
            re.I,
        )
        if possessive is None:
            return None
        direct = possessive
        kind = "verified_owner_possessive"
        subject_start = clause.start + direct.start("alias")
        subject_end = clause.start + direct.end("alias")
    predicate = clause.text[direct.end() :].strip()
    if not predicate:
        return None
    predicate_left = clause.start + len(clause.text[: direct.end()])
    predicate_left += len(clause.text[direct.end() :]) - len(clause.text[direct.end() :].lstrip())
    return SubjectBinding(
        alias=direct.group("alias"),
        subject_kind=kind,
        predicate=predicate,
        quote_span=quote_span,
        subject_span=(subject_start, subject_end),
        predicate_span=(predicate_left, clause.end),
    )


def _introduced_binding(
    clause: ClauseSpan,
    *,
    aliases: list[str],
    owner_names: list[str],
    quote_span: tuple[int, int],
) -> SubjectBinding | None:
    """Find a site alias in an explicit service/build relation, never a company alone."""
    alias_re = _alias_pattern(aliases)
    owners = _safe_aliases(owner_names)
    owner_re = _alias_pattern(owners) if owners else r"(?!)"
    # Introductions are restricted to a service object or an explicit site
    # naming construction. Loose "for" or "at" mentions can describe another
    # facility's customer or location.
    patterns = (
        re.compile(
            rf"\bto\s+serve\s+(?:a|an|the)?\s*"
            rf"(?:(?P<owner>{owner_re})[’']s\s+)?"
            rf"(?P<alias>{alias_re})(?=\b|\s)",
            re.I,
        ),
        re.compile(
            rf"\bhome\s+to\s+(?:(?:a|an|the)\s+)?(?:new\s+)?"
            rf"[\"“‘']?(?P<alias>{alias_re})(?=\b|\s)",
            re.I,
        ),
    )
    matches = [match for pattern in patterns for match in pattern.finditer(clause.text)]
    if len(matches) != 1:
        return None
    match = matches[0]
    prefix = clause.text[: match.start()]
    if _NAMED_SITE.search(prefix) or _LEADING_SITE_SUBJECT.search(clause.text):
        return None
    owner_name = match.groupdict().get("owner")
    if owner_name and owner_name.casefold() not in {name.casefold() for name in owners}:
        return None
    relation_tail = clause.text[match.end() :]
    if _COMPETING_SITE.search(relation_tail) or _FOREIGN_SITE_OWNS_PREDICATE.search(relation_tail):
        return None
    start = clause.start + match.start("alias")
    end = clause.start + match.end("alias")
    return SubjectBinding(
        alias=match["alias"],
        subject_kind="native_site_relation",
        predicate=clause.text,
        quote_span=quote_span,
        subject_span=(start, end),
        predicate_span=(clause.start, clause.end),
    )


def _named_site_alias_binding(
    clause: ClauseSpan,
    *,
    aliases: list[str],
    quote_span: tuple[int, int],
) -> SubjectBinding | None:
    """Bind a source-native alias used as a site's locality suffix.

    This is limited to a unique alias in an explicit ``site noun in/at/near
    locality, alias`` construction. It does not derive aliases from owner names,
    locations, or reference labels.
    """
    alias_re = _alias_pattern(aliases)
    matches = list(
        re.finditer(
            rf"(?<!\w){alias_re}(?!\w)"
            rf"(?=$|[.,;:!?](?=\s|$)|\s+(?:is|was|are|were|has|had|will)\b)",
            clause.text,
            re.I,
        )
    )
    if len(matches) != 1:
        return None
    match = matches[0]
    prefix = clause.text[: match.start()]
    site_location = re.search(
        r"(?i:\b(?:campus|data\s+center|facility|site|project|plant|station)\s+"
        r"(?:in|at|near|within)\s+)"
        r"(?:[A-Z][\w’'-]*\s+){0,2}[A-Z][\w’'-]*,?\s*$",
        prefix,
    )
    if (
        site_location is None
        or re.search(
            r"\b(?:and|or|versus|compared\s+with)\b",
            prefix[site_location.start() :] if site_location else "",
            re.I,
        )
        or _has_competing_physical_site(clause.text)
        or _NAMED_FOREIGN_SITE_RELATION.search(clause.text)
    ):
        return None
    start = clause.start + match.start()
    end = clause.start + match.end()
    return SubjectBinding(
        alias=match.group(),
        subject_kind="native_site_location_alias",
        predicate=clause.text,
        quote_span=quote_span,
        subject_span=(start, end),
        predicate_span=(clause.start, clause.end),
    )


def resolve_claim_subject(
    source_text: str,
    quote: str,
    *,
    project_name: str,
    project_aliases: Iterable[str] = (),
    trusted_owner_names: Iterable[str] = (),
    source_hash: str | None = None,
) -> dict | None:
    """Resolve every exact occurrence of a claim quote or abstain on ambiguity.

    Exact source offsets are used instead of ``str.find`` so duplicated passages
    under different headings cannot silently select the first context. The
    adjacent-anaphora rule uses only the immediately preceding source clause.
    """
    if not isinstance(source_text, str) or not isinstance(quote, str) or not quote:
        return None
    aliases = _safe_aliases([project_name])
    aliases.extend(
        value
        for value in _safe_aliases(project_aliases, allow_single=True)
        if value.casefold() not in {alias.casefold() for alias in aliases}
    )
    aliases.sort(key=lambda value: (-len(value), value.casefold()))
    owners = _safe_aliases(trusted_owner_names, allow_single=True)
    if not aliases:
        return None
    spans = clause_spans(source_text)
    occurrences = [match.span() for match in re.finditer(re.escape(quote), source_text)]
    if not occurrences:
        return None
    resolutions = []
    for occurrence in occurrences:
        index = next(
            (
                position
                for position, span in enumerate(spans)
                if span.start <= occurrence[0] and occurrence[1] <= span.end
            ),
            None,
        )
        if index is None:
            return None
        current = spans[index]
        binding = _direct_binding(
            current,
            aliases=aliases,
            owner_names=owners,
            quote_span=occurrence,
        )
        if binding is None and _ANAPHORA.match(current.text):
            if _NAMED_FOREIGN_SITE_RELATION.search(current.text) or _has_competing_physical_site(
                current.text
            ):
                return None
            if index == 0:
                return None
            previous = spans[index - 1]
            antecedent = (
                _direct_binding(
                    previous,
                    aliases=aliases,
                    owner_names=owners,
                    quote_span=(previous.start, previous.end),
                )
                or _introduced_binding(
                    previous,
                    aliases=aliases,
                    owner_names=owners,
                    quote_span=(previous.start, previous.end),
                )
                or _named_site_alias_binding(
                    previous,
                    aliases=aliases,
                    quote_span=(previous.start, previous.end),
                )
            )
            if antecedent is None:
                return None
            previous = spans[index - 1]
            foreign = _NAMED_FOREIGN_SITE_RELATION.search(previous.text)
            if foreign and not (
                previous.start + foreign.start() >= antecedent.subject_span[0]
                and previous.start + foreign.end() <= antecedent.subject_span[1]
            ):
                return None
            binding = SubjectBinding(
                alias=antecedent.alias,
                subject_kind="adjacent_anaphora",
                predicate=current.text,
                quote_span=occurrence,
                subject_span=antecedent.subject_span,
                predicate_span=(current.start, current.end),
                antecedent_span=(previous.start, previous.end),
            )
        if binding is None:
            return None
        resolutions.append(binding)
    identities = {(item.alias.casefold(), item.subject_kind) for item in resolutions}
    if len(identities) != 1:
        return None
    first = resolutions[0]
    return {
        "alias": first.alias,
        "subject_kind": first.subject_kind,
        "predicate": first.predicate,
        "source_hash": source_hash,
        "occurrences": [item.as_json(source_hash=source_hash) for item in resolutions],
    }


def _same_extracted_claim(candidate: dict, claim: dict, field: str) -> bool:
    fields = (
        ("basis", "value_mw", "qualifier", "scope_id", "phase_id", "includes_scope_ids")
        if field == "capacity_claims"
        else (
            "event_type",
            "label",
            "precision",
            "qualifier",
            "scope_id",
            "start",
            "end",
            "earliest",
            "latest",
        )
    )
    return all(candidate.get(key) == claim.get(key) for key in fields)


def _claim_in_owned_prefix(binding: dict, claim: dict, field: str, predicate_prefix: str) -> bool:
    from gridlens.domain.customer_intelligence import extract_customer_facts

    alias = binding.get("alias")
    if not isinstance(alias, str) or not alias:
        return False
    source = claim.get("source")
    extracted = extract_customer_facts(
        f"{alias} {predicate_prefix}",
        project_id=str(claim.get("project_id") or ""),
        source=source if isinstance(source, dict) else {},
    )
    key = "capacity_claims" if field == "capacity_claims" else "timeline_claims"
    return any(
        _same_extracted_claim(candidate, claim, field) for candidate in extracted.get(key, [])
    )


def _predicate_after_project_location(predicate: str, project_location: str) -> str | None:
    location = project_location.strip()
    if not location:
        return None
    match = re.match(
        r"^\s*(?:at|in)\s+" + re.escape(location) + r"(?:\s+|,)(?P<rest>.+)$",
        predicate,
        re.I,
    )
    return match.group("rest") if match else None


def claim_has_owned_predicate(
    binding: dict, claim: dict, field: str, *, project_location: str = ""
) -> bool:
    """Require a bounded owned predicate after source-local subject binding.

    This deliberately recognizes a small positive grammar. A selected site
    appearing before a comparison or neighboring-site relation is not enough to
    assign a later amount or date to that site.
    """
    predicate = binding.get("predicate")
    subject_kind = binding.get("subject_kind")
    if not isinstance(predicate, str) or subject_kind not in {
        "native_site_alias",
        "verified_owner_possessive",
        "adjacent_anaphora",
    }:
        return False
    if subject_kind == "adjacent_anaphora" and (
        _has_competing_physical_site(predicate) or _FOREIGN_SITE_REFERENCE.search(predicate)
    ):
        return False

    if subject_kind == "adjacent_anaphora":
        if field == "capacity_claims":
            phase_site = re.match(
                r"^\s*the\s+phase\s+(?:[0-9]+|[ivx]+)\s+design\s+of\s+the\s+site\b",
                predicate,
                re.I,
            )
            expansion = re.match(
                r"^\s*the\s+(?:\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*"
                r"(?:MW|megawatts?)\s+)?data\s+center\s+expansion\b",
                predicate,
                re.I,
            )
            if expansion:
                return bool(
                    claim.get("basis") == "campus_development"
                    and claim.get("scope_id", "").endswith(":expansion")
                    and _claim_in_owned_prefix(binding, claim, field, predicate)
                )
            return bool(
                phase_site
                and re.search(
                    r"\b(?:can|will)\s+deliver\s+(?:up\s+to\s+)?\d[\d,.]*\s*"
                    r"(?:MW|megawatts?|GW|gigawatts?)\b[^.!?]{0,200}?"
                    r"(?:critical\s+IT\s+(?:power|load)|IT\s+(?:power|load))",
                    predicate,
                    re.I,
                )
                and (
                    re.search(
                        r"\bfor\s+a\s+total\s+of\s+\d[\d,.]*\s*"
                        r"(?:MW|megawatts?|GW|gigawatts?)\b[^.!?]{0,100}?\b across\s+all\b",
                        predicate,
                        re.I,
                    )
                    or re.search(
                        r"\b(?:can|will)\s+deliver\s+(?:up\s+to\s+)?\d[\d,.]*\s*"
                        r"(?:MW|megawatts?|GW|gigawatts?)\b",
                        predicate,
                        re.I,
                    )
                )
            )
        return bool(
            claim.get("event_type") == "operational_target"
            and re.match(r"^\s*the\s+deal\b", predicate, re.I)
            and re.search(
                r"\bto\s+support\s+a\s+new\s+"
                r"(?:(?:state\s+of\s+the\s+art|state-of-the-art)\s+)?"
                r"(?:facility|data\s+center)\b",
                predicate,
                re.I,
            )
            and re.search(r"\bexpected\s+to\s+be\s+operational\s+by\b", predicate, re.I)
        )

    if field == "capacity_claims":
        location_tail = _predicate_after_project_location(predicate, project_location)
        owned_lead = predicate if location_tail is None else location_tail
        if not isinstance(owned_lead, str):
            return False
        # Existing comparative clauses remain wholly ambiguous. A neighboring
        # site introduced through a later prepositional relation is checked at
        # each extractor match span below, so an earlier fully owned amount can
        # survive while the neighbor's later amount cannot.
        if _COMPETING_SITE.search(predicate):
            return False
        from gridlens.domain.customer_intelligence import _CAPACITY_PATTERNS

        matches = sorted(
            {
                (match.start(), match.end())
                for _, pattern in _CAPACITY_PATTERNS
                for match in pattern.finditer(predicate)
            }
        )
        for start, end in matches:
            lead = owned_lead[: max(0, start - (len(predicate) - len(owned_lead)))]
            if not _OWNED_CAPACITY_PREFIX.fullmatch(lead):
                continue
            prefix = predicate[:end]
            if _COMPETING_SITE.search(prefix) or _FOREIGN_SITE_REFERENCE.search(prefix):
                continue
            from gridlens.domain.customer_intelligence import extract_customer_facts

            alias = binding.get("alias")
            source = claim.get("source")
            if not isinstance(alias, str) or not alias:
                return False
            extracted = extract_customer_facts(
                f"{alias} {prefix}",
                project_id=str(claim.get("project_id") or ""),
                source=source if isinstance(source, dict) else {},
            )
            candidates = extracted.get("capacity_claims", [])
            if candidates:
                return any(
                    _same_extracted_claim(candidate, claim, field) for candidate in candidates
                )
        return False

    location_tail = _predicate_after_project_location(predicate, project_location)
    timeline_lead = predicate if _DIRECT_TIMELINE_PREDICATE.match(predicate) else location_tail
    if not isinstance(timeline_lead, str) or not _DIRECT_TIMELINE_PREDICATE.match(timeline_lead):
        return False
    from gridlens.domain.customer_intelligence import _TIMELINE_PATTERNS

    events: list[tuple[int, str]] = []
    offset = len(predicate) - len(timeline_lead)
    for event_type, pattern in _TIMELINE_PATTERNS:
        events.extend(
            (offset + match.end(), event_type) for match in pattern.finditer(timeline_lead)
        )
    ordered_events = sorted(set(events))
    if not ordered_events:
        return False
    # Without a fresh explicit subject, a later event/date cannot inherit the
    # first event's project binding. This bounded grammar intentionally keeps
    # only the first event in a clause; separately stated clauses bind anew.
    end, event_type = ordered_events[0]
    prefix = predicate[:end]
    return bool(
        event_type == claim.get("event_type")
        and not _COMPETING_SITE.search(prefix)
        and not _FOREIGN_SITE_REFERENCE.search(prefix)
        and _claim_in_owned_prefix(binding, claim, field, prefix)
    )
