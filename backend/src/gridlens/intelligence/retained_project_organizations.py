"""Bounded organization claims from admitted retained project announcements.

This module is a producer for the existing buying-chain pipeline. It does not
create identities, reconcile companies globally, or treat a publisher as a
project participant merely because it published an announcement.
"""

from __future__ import annotations

import re
from typing import Any

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
