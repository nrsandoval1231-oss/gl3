"""Bounded organization claims from admitted retained project announcements.

This module is a producer for the existing buying-chain pipeline. It does not
create identities, reconcile companies globally, or treat a publisher as a
project participant merely because it published an announcement.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from gridlens.domain.signal_admission import admitted_from_source
from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.ingestion.adapters.retained_company_projects import (
    FAMILY,
    RETRIEVAL_METHOD,
    SOURCE_ID,
    interpret_retained_company_project,
    retained_record_hash,
)
from gridlens.intelligence.buying_chain_extraction import Extracted, _citation

_TITLE_DEVELOPER = re.compile(
    r"^(?P<organization>[A-Z][A-Za-z0-9&'’.-]*(?:\s+[A-Z][A-Za-z0-9&'’.-]*){0,4})"
    r"\s+develops\s+(?P<capacity>\d+(?:\.\d+)?)\s*MW\s+"
    r"(?P<market>[A-Z][A-Za-z'’.-]*(?:\s+[A-Z][A-Za-z'’.-]*){0,2})"
    r"\s+data\s+campus$",
    re.I,
)
_ORG_TOKEN = r"[A-Z][A-Za-z0-9&'’.-]*(?:\s+[A-Z][A-Za-z0-9&'’.-]*){0,4}"


def _planned_native_developer_claim(
    document: PublicDocument, context: dict[str, Any], body: str
) -> Extracted | None:
    """Bind a publisher actor to an immediately announced site's planned build."""
    native_name = context.get("project_name")
    location_quote = context.get("location_quote")
    aliases = context.get("project_aliases")
    alias_quotes = context.get("alias_quotes")
    alias_spans = context.get("alias_spans")
    sections = context.get("section_ranges")
    publisher_host = context.get("publisher_host")
    if (
        not isinstance(native_name, str)
        or not native_name
        or not isinstance(location_quote, str)
        or not location_quote
        or not isinstance(aliases, list)
        or len(aliases) != 1
        or not isinstance(aliases[0], str)
        or not isinstance(alias_quotes, dict)
        or not isinstance(alias_spans, dict)
        or not isinstance(sections, list)
        or not isinstance(publisher_host, str)
    ):
        return None

    alias = aliases[0]
    alias_quote = alias_quotes.get(alias)
    alias_span = alias_spans.get(alias)
    if (
        not isinstance(alias_quote, str)
        or not isinstance(alias_span, list)
        or len(alias_span) != 2
        or body[alias_span[0] : alias_span[1]] != alias_quote
        or alias not in alias_quote
    ):
        return None

    # The source-defined actor must be linked from the same exact publisher host.
    # A name-only or suffix-based company match is deliberately insufficient.
    try:
        document_host = (urlsplit(document.url).hostname or "").casefold()
    except ValueError:
        return None
    publisher_host = publisher_host.casefold()
    if not document_host or document_host != publisher_host:
        return None
    publisher_link = re.compile(
        r"\[(?P<actor>[^\]\n]{1,80})\]\((?P<url>https://[^)\s]{1,300})\)"
    ).search(body)
    if publisher_link is None:
        return None
    try:
        linked_host = (urlsplit(publisher_link.group("url")).hostname or "").casefold()
    except ValueError:
        return None
    actor = publisher_link.group("actor").strip()
    if not actor or linked_host != publisher_host:
        return None

    definition = re.compile(rf"\([\"“”']{re.escape(actor)}[\"“”']\)").search(
        body, publisher_link.end()
    )
    if definition is None:
        return None

    # Require a finite announcement by the defined publisher actor, followed
    # immediately by a land-purchase construction sentence for that same actor.
    announcement_pattern = re.compile(
        r"(?:,\s*(?:the|a)\s+[^,.!?\n]{1,80},)?\s*"
        rf"today announced the primary location of its\s+"
        rf"{re.escape(native_name)}\b[^.!?\n]*\."
    )
    announcement_tail = announcement_pattern.search(body, definition.end())
    if announcement_tail is None:
        return None
    announcement_quote = body[publisher_link.start() : announcement_tail.end()]

    action_pattern = re.compile(
        rf"\s*The land purchase agreement\b[^.!?\n]{{1,180}}?\bwill allow\s+"
        rf"{re.escape(actor)}\s+to construct\b(?:[^.!?\n]|\d\.\d){{0,300}}?"
        rf"{re.escape(location_quote)}\b[^.!?\n]*\."
    )
    action = action_pattern.match(body, announcement_tail.end())
    if action is None:
        return None

    project_stem_match = re.fullmatch(
        r"(?P<stem>.+?)\s+(?:data\s+center\s+)?campus", native_name, re.I
    )
    if project_stem_match is None:
        return None
    project_stem = project_stem_match.group("stem")
    alias_sentence_pattern = re.compile(
        rf"\s*The\s+{re.escape(project_stem)}\s+campus\s+will be called\s+"
        rf"{re.escape(alias_quote)}"
    )
    alias_sentence = alias_sentence_pattern.match(body, action.end())
    if alias_sentence is None:
        return None

    # All three clauses must belong to one unbroken retained source section.
    if not any(
        isinstance(section, dict)
        and isinstance(section.get("start"), int)
        and isinstance(section.get("end"), int)
        and section["start"] <= publisher_link.start()
        and alias_sentence.end() <= section["end"]
        and body[section["start"] : section["end"]].strip()
        for section in sections
    ):
        return None

    return Extracted(
        organization=actor,
        category="owner_developer",
        evidence_strength="High",
        reason=(
            "The retained source reports this organization as the planned developer "
            "of the named project. This does not establish legal ownership, completed "
            "construction, current status, or purchasing authority."
        ),
        citations=[
            _citation(document, announcement_quote, "organization_category"),
            _citation(document, action.group(0).strip(), "project_organization"),
            _citation(document, alias_sentence.group(0).strip(), "project_name"),
        ],
    )


def _corroborated_native_build_claim(
    document: PublicDocument, context: dict[str, Any], body: str
) -> Extracted | None:
    """Bind a named actor's announced campus project to source-reported build work."""
    native_name = context.get("project_name")
    location_quote = context.get("location_quote")
    sections = context.get("section_ranges")
    if (
        not isinstance(native_name, str)
        or not native_name
        or not isinstance(location_quote, str)
        or not location_quote
        or not isinstance(sections, list)
    ):
        return None

    locality = re.fullmatch(
        r"in\s+(?P<city>[A-Z][A-Za-z.'’\-]*(?:\s+[A-Z][A-Za-z.'’\-]*){0,2}),"
        r"\s*[A-Z][A-Za-z.'’\- ]+",
        location_quote,
    )
    if locality is None:
        return None
    actor_link = (
        r"\[(?P<actor>[A-Z][A-Za-z0-9&'’.-]*(?:\s+[A-Z][A-Za-z0-9&'’.-]*){0,4})\]"
        r"\(https://[^)\s]{1,300}\)"
    )
    native_site_link = rf"\[{re.escape(native_name)}\]\(https://[^)\s]{{1,300}}\)"
    native_site_text = rf"(?:{native_site_link}|{re.escape(native_name)})"
    announcement = re.compile(
        rf"{actor_link}(?:,\s*(?P<appositive>(?:the|a|an)\s+[^,.!?\n]{{1,100}}),)?\s*"
        r"announced construction has begun on the next phase of its AI data center at\s+(?:the\s+)?"
        rf"{native_site_link}\s+{re.escape(location_quote)}\."
    )
    sentence_start = r"(?:^|[.!?]\s+)"
    site_build = re.compile(
        rf"{sentence_start}(?P<quote>Designed and built by\s+(?P<actor>{_ORG_TOKEN})"
        rf"\s+at\s+(?:the\s+)?{native_site_text}(?=\s*[,.;!?]))"
    )
    adverse = re.compile(
        r"\b(?:not|never|no\s+longer|cannot|can't|hypothetical(?:ly)?|possibly|allegedly|"
        r"reported(?:ly)?|cancelled|canceled|abandoned|withdrawn|terminated|"
        r"only\s+as\s+(?:a\s+)?(?:general\s+)?contractor|(?:general\s+)?contractor\s+for|"
        r"contractor\s+only|client(?:'s)?|on\s+behalf\s+of)\b",
        re.I,
    )

    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        start, end = section.get("start"), section.get("end")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or not 0 <= start < end <= len(body)
        ):
            continue
        text = body[start:end]
        announcement_match = announcement.search(text)
        if announcement_match is None or (
            announcement_match.group("appositive")
            and (
                re.search(
                    r"\[[^]]+\]\(|\b(?:said|says|claimed|claims|reported|reports|according|"
                    r"not|never|hypothetical(?:ly)?|possibly|allegedly)\b",
                    announcement_match.group("appositive"),
                    re.I,
                )
                or re.search(r"\b[A-Z][a-z]+\b", announcement_match.group("appositive"))
            )
        ):
            continue
        actor = announcement_match.group("actor")
        actor_build = re.compile(
            rf"{sentence_start}(?P<quote>{re.escape(actor)} began constructing the AI data "
            rf"center in {re.escape(locality.group('city'))}\b[^.!?\n]{{0,100}}\.)"
        )
        for build_index in (index, index + 1):
            if build_index >= len(sections):
                continue
            build_section = sections[build_index]
            if not isinstance(build_section, dict):
                continue
            build_start, build_end = build_section.get("start"), build_section.get("end")
            if (
                not isinstance(build_start, int)
                or not isinstance(build_end, int)
                or not 0 <= build_start < build_end <= len(body)
            ):
                continue
            if build_index != index and (
                build_section.get("source_files") != section.get("source_files")
                or body[end:build_start] != "\n\n"
            ):
                continue
            build_text = body[build_start:build_end]
            if adverse.search(text) or adverse.search(build_text):
                continue
            actor_build_match = actor_build.search(build_text)
            site_build_match = site_build.search(build_text)
            if (
                actor_build_match is None
                or site_build_match is None
                or site_build_match.group("actor").casefold() != actor.casefold()
            ):
                continue
            return Extracted(
                organization=actor,
                category="owner_developer",
                evidence_strength="High",
                reason=(
                    f"The retained source identifies {actor}'s announced AI data center at "
                    "this campus and corroborates the same actor designed and built there. "
                    "This is historical source-reported developer involvement, not legal "
                    "ownership, current status, or purchasing authority."
                ),
                citations=[
                    _citation(document, announcement_match.group(0), "organization_category"),
                    _citation(document, actor_build_match.group("quote"), "project_organization"),
                    _citation(document, site_build_match.group("quote"), "project_name"),
                ],
            )
    return None


def _fresh_native_context(
    document: PublicDocument,
    *,
    project: Any,
    source: Any,
    observation: Any,
    evidence: Any,
    interpretation: Any,
) -> tuple[dict[str, Any], str] | None:
    """Require the persisted source, native assessment, and project to agree."""
    if (
        source is None
        or observation is None
        or evidence is None
        or interpretation is None
        or project is None
        or source.id != SOURCE_ID
        or source.family != FAMILY
        or source.retrieval_method != RETRIEVAL_METHOD
    ):
        return None
    if (
        evidence.observation_id != observation.id
        or observation.source_id != source.id
        or observation.title != evidence.title
        or observation.url != evidence.url
        or observation.abstract != evidence.abstract
        or observation.published_at != evidence.published_at
        or interpretation.observation_id != observation.id
        or interpretation.content_hash != observation.content_hash
        or interpretation.status != "accepted"
        or document.title != evidence.title
        or document.url != evidence.url
        or document.published_at != evidence.published_at
        or document.retained_version != evidence.content_hash
        or document.text != f"{evidence.title}\n{evidence.abstract or ''}"
    ):
        return None
    assessment = interpretation.assessment
    if not isinstance(assessment, dict):
        return None
    if (
        project.source_id != source.id
        or project.external_id != observation.external_id
        or assessment.get("project_identity_key") != project.identity_key
        or assessment.get("evidence_hash") != evidence.content_hash
        or assessment.get("semantic_hash") != observation.content_hash
    ):
        return None
    # The source adapter re-parses the exact retained body, hashes, site relation,
    # project/activity spans, and source-native aliases before any claim is emitted.
    context = (evidence.provenance or {}).get("retained_company_project")
    if not isinstance(context, dict):
        return None
    body = evidence.abstract or ""
    body_hash = context.get("body_hash")
    record = {
        "document_number": observation.external_id,
        "title": evidence.title,
        "abstract": body,
        "html_url": evidence.url,
        "publication_date": evidence.published_at.isoformat() if evidence.published_at else None,
        "publication_date_metadata": context.get("publication_date_metadata"),
        "observation_date": evidence.observed_at.date().isoformat()
        if evidence.observed_at
        else None,
        "source_body_hash": body_hash,
        "publication_date_precision": context.get("publication_date_precision"),
        "source_hash": evidence.content_hash,
        "retained_company_project": context,
    }
    source_hash = retained_record_hash(record)
    native = interpret_retained_company_project(record)
    if (
        native is None
        or source_hash != evidence.content_hash
        or assessment.get("subject") != native.get("name")
        or assessment.get("location") != native.get("location")
        or assessment.get("power_activity") != native.get("activity_key")
        or project.name != native.get("name")
        or project.location != native.get("location")
    ):
        return None
    aliases = (project.identity_facts or {}).get("project_aliases", [])
    if not isinstance(aliases, list) or any(
        alias not in aliases for alias in context.get("project_aliases", [])
    ):
        return None
    if not admitted_from_source(source, assessment, evidence).admitted:
        return None
    return context, body


def extract_retained_project_organizations(
    document: PublicDocument,
    *,
    project: Any,
    source: Any,
    observation: Any,
    evidence: Any,
    interpretation: Any,
) -> list[Extracted]:
    """Extract source-reported roles for two exact, admitted native projects.

    Results are ordinary ``Extracted`` claims, allowing the existing freshness,
    suppression, project-scoped identity, and account projection rules to apply.
    """
    validated = _fresh_native_context(
        document,
        project=project,
        source=source,
        observation=observation,
        evidence=evidence,
        interpretation=interpretation,
    )
    if validated is None:
        return []
    context, body = validated
    claims: list[Extracted] = []

    planned_developer = _planned_native_developer_claim(document, context, body)
    if planned_developer is not None:
        claims.append(planned_developer)

    corroborated_build = _corroborated_native_build_claim(document, context, body)
    if corroborated_build is not None:
        claims.append(corroborated_build)

    title_match = _TITLE_DEVELOPER.fullmatch(document.title.strip())
    if title_match:
        organization = title_match.group("organization")
        capacity = title_match.group("capacity")
        market = title_match.group("market")
        location_quote = str(context.get("location_quote") or "")
        org_pattern = re.escape(organization)
        body_pattern = re.compile(
            rf"(?:\[{org_pattern}\]\([^)]*\)|\b{org_pattern}\b),?"
            rf"[^.!?\n]{{0,300}}?\b(?:announced|announces)\s+"
            rf"(?:the\s+)?development\s+of\s+a\s+{re.escape(capacity)}\s*MW\s+"
            rf"data\s+center\s+campus[^.!?\n]{{0,180}}?{re.escape(location_quote)}\b",
            re.I,
        )
        body_match = body_pattern.search(body) if location_quote else None
        alias_spans = context.get("alias_spans")
        alias_quotes = context.get("alias_quotes")
        aliases_in_context = context.get("project_aliases")
        if (
            body_match
            and isinstance(alias_spans, dict)
            and isinstance(alias_quotes, dict)
            and isinstance(aliases_in_context, list)
            and len(aliases_in_context) == 1
            and isinstance(aliases_in_context[0], str)
            and alias_spans.get(aliases_in_context[0])
            and alias_quotes.get(aliases_in_context[0])
        ):
            alias = aliases_in_context[0]
            span = alias_spans[alias]
            if (
                isinstance(span, list)
                and len(span) == 2
                and body[span[0] : span[1]] == alias_quotes[alias]
                and alias in alias_quotes[alias]
            ):
                title_quote = document.title.strip()
                body_quote = body_match.group(0)
                alias_pattern = re.compile(
                    rf"\bThe\s+{re.escape(market)}\s+land\s+will\s+become\s+home\s+"
                    rf"to\s+the\s+new\s+[\"“]{re.escape(alias)}[\"”]",
                    re.I,
                )
                alias_sentence = alias_pattern.search(body)
                alias_quote = alias_sentence.group(0) if alias_sentence else ""
                if not alias_quote:
                    return claims
                claims.append(
                    Extracted(
                        organization=organization,
                        category="owner_developer",
                        evidence_strength="High",
                        reason=(
                            "The retained announcement reports this organization "
                            "developing the source-named campus; this is historical "
                            "reported involvement, not a finding of current legal ownership."
                        ),
                        citations=[
                            _citation(document, title_quote, "organization_category"),
                            _citation(document, body_quote, "project_organization"),
                            _citation(document, alias_quote, "project_name"),
                        ],
                    )
                )

    native_name = str(context.get("project_name") or "")
    location_quote = str(context.get("location_quote") or "")
    if native_name and location_quote:
        customer_pattern = re.compile(
            rf"\b(?:agreement|deal)\s+with\s+(?:[A-Z][a-z]+\s+based\s+)?"
            rf"(?P<organization>{_ORG_TOKEN}),\s+(?:a\s+)?[^.!?\n]{{0,120}}?"
            rf"\b(?:data\s+center\s+)?(?:developer|operator)\b[^.!?\n]{{0,40}}?,\s+"
            rf"to\s+serve\s+(?:a\s+)?{re.escape(native_name)}\s+"
            rf"{re.escape(location_quote)}\b",
            re.I,
        )
        customer_match = customer_pattern.search(body)
        if customer_match:
            organization = customer_match.group("organization")
            claims.append(
                Extracted(
                    organization=organization,
                    category="project_customer",
                    evidence_strength="High",
                    reason=(
                        f"The retained announcement names {organization} as the direct "
                        "counterparty for service to this data center; it does not "
                        "establish legal ownership or current purchasing authority."
                    ),
                    citations=[
                        _citation(document, customer_match.group(0), "project_organization")
                    ],
                )
            )
    return claims
