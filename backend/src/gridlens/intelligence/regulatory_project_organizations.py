"""Bounded developer-role extraction backed by current SEC identity proof.

This module joins an already retrieved project source to an already retrieved
SEC filing. It performs no acquisition and never treats an SEC domain assertion
as proof of legal ownership or purchasing authority.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from gridlens.domain.buying_chain import Category
from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.intelligence.buying_chain_extraction import (
    Extracted,
    document_content_hash,
    document_key,
)
from gridlens.intelligence.company_domain_proof import parse_sec_domain_assertion
from gridlens.intelligence.regulatory_company_identity import official_domain_matches_url
from gridlens.persistence.models import Project

_MAX_SEC_OBSERVATION_AGE = timedelta(days=30)
_MAX_SEC_PUBLICATION_AGE = timedelta(days=400)
_COMPANY_NAME = r"[A-Z][A-Za-z0-9&.'’/-]*(?:[ \t]+[A-Z][A-Za-z0-9&.'’/-]*){0,5}?"
_LEGAL_SUFFIX = re.compile(
    r"(?:,\s*)?(?:corporation|corp\.?|incorporated|inc\.?|limited|ltd\.?|llc|"
    r"company|co\.?)$",
    re.I,
)
_LEGAL_SUFFIX_TAIL = (
    r"\s*,?\s*(?:corporation|corp\.?|incorporated|inc\.?|limited|ltd\.?|llc|company|co\.?)\b"
)
_PUBLISHER_FIELD = re.compile(
    rf"(?<!\S)::\s*(?P<issuer>{_COMPANY_NAME}\s+"
    rf"(?:corporation|corp\.?|incorporated|inc\.?|limited|ltd\.?|llc|company|co\.?))"
    r"\s*\((?P<ticker>[A-Z][A-Z0-9.-]{0,9})\)(?=\s|$)|"
    rf"^\s*Publisher:\s*(?P<labelled_issuer>{_COMPANY_NAME}\s+"
    rf"(?:corporation|corp\.?|incorporated|inc\.?|limited|ltd\.?|llc|company|co\.?))\s*$",
    re.I | re.M,
)
_AMBIGUOUS = re.compile(
    r"\b(?:may|might|could|possibly|proposed|proposes|planned|plans|rumou?red|"
    r"former|formerly|sold|divested|acquired|no\s+longer|not|never|alleged)\b",
    re.I,
)
_NON_DEVELOPER_CONTEXT = re.compile(
    r"\b(?:architect|design\s+consultant|engineering\s+consultant|agent|broker|"
    r"on\s+behalf\s+of|subsidiar(?:y|ies)|affiliate|parent\s+company|joint\s+venture)\b",
    re.I,
)
_SITE_ALIAS_TAIL = (
    r"(?=$|[,.;:!?]|\s+(?:for|in|at|to|with|across|through|over|under|as|"
    r"which|that|where|will|is|was|has|have|can)\b)"
)
_SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?](?=\s|$)|$)")


def _project_aliases(project: Project) -> list[str]:
    facts = project.identity_facts or {}
    candidates = [project.name, *(facts.get("project_aliases") or [])]
    aliases: dict[str, str] = {}
    full_names = [
        value.strip() for value in candidates if isinstance(value, str) and len(value.split()) >= 2
    ]
    location = str(getattr(project, "location", "") or "").casefold()
    for value in candidates:
        if not isinstance(value, str):
            continue
        alias = value.strip()
        if len(alias) > 180:
            continue
        if len(alias.split()) < 2:
            location_anchors_alias = any(
                full.casefold().startswith(alias.casefold() + " ")
                and re.match(re.escape(alias) + r"(?:$|[,\s])", location, re.I)
                for full in full_names
            )
            if not location_anchors_alias:
                continue
        if not alias:
            continue
        aliases.setdefault(alias.casefold(), alias)
    return sorted(aliases.values(), key=lambda item: (-len(item), item.casefold()))


def _sentences(text: str) -> Iterable[str]:
    for match in _SENTENCE.finditer(text):
        sentence = match.group(0).strip()
        if sentence:
            yield sentence


def _developer_assertions(
    sentence: str, aliases: list[str], expected_company: str
) -> list[tuple[str, str]]:
    """Return literal company and site names from a direct developer relation."""
    if _AMBIGUOUS.search(sentence) or _NON_DEVELOPER_CONTEXT.search(sentence):
        return []
    alias_pattern = "(?:" + "|".join(re.escape(value) for value in aliases) + ")"
    company_pattern = re.escape(expected_company)
    patterns = (
        re.compile(
            rf"^\s*(?P<company>{company_pattern})\s+(?:has\s+)?"
            rf"(?:designed|developed|is\s+developing|will\s+develop|"
            rf"is\s+building|will\s+build|is\s+constructing|will\s+construct)\s+"
            rf"(?P<site>{alias_pattern}){_SITE_ALIAS_TAIL}",
            re.I,
        ),
        re.compile(
            rf"^\s*(?P<site>{alias_pattern})\s+(?:is|was)\s+"
            rf"(?:(?:being|expected\s+to\s+be)\s+)?"
            rf"(?:designed|developed|built|constructed)\s+by\s+"
            rf"(?P<company>{company_pattern})(?!{_LEGAL_SUFFIX_TAIL})"
            rf"(?=$|[,.;:!?]|\s+(?:to|for|in|at|with)\b)",
            re.I,
        ),
    )
    assertions = []
    for pattern in patterns:
        match = pattern.search(sentence)
        if match:
            company = match.group("company").strip()
            site = match.group("site").strip()
            assertions.append((company, site))
    return list(dict.fromkeys(assertions))


def _short_alias_has_native_full_site_support(
    project: Project,
    text: str,
    company: str,
    short_alias: str,
    *,
    role_quote: str,
) -> bool:
    """Require native full-site alias and same-source possessive confirmation."""
    facts = project.identity_facts or {}
    full_aliases = [
        value.strip()
        for value in [project.name, *(facts.get("project_aliases") or [])]
        if isinstance(value, str)
        and len(value.split()) >= 2
        and value.casefold().startswith(short_alias.casefold() + " ")
    ]
    if len(full_aliases) != 1:
        return False
    paragraph = next(
        (value for value in re.split(r"\n\s*\n", text) if role_quote in value),
        "",
    )
    if not paragraph:
        return False
    possessive = re.compile(
        re.escape(company) + r"[’']s\s+(?:the\s+)?" + re.escape(full_aliases[0]) + _SITE_ALIAS_TAIL,
        re.I,
    )
    return bool(possessive.search(paragraph))


def _sec_source(document: PublicDocument) -> SimpleNamespace:
    return SimpleNamespace(
        url=document.url,
        excerpt=document.text,
        content_hash=document_content_hash(document),
    )


def _sec_is_current(document: PublicDocument, now: datetime) -> bool:
    observed = document.observed_at
    observed = observed.replace(tzinfo=UTC) if observed.tzinfo is None else observed.astimezone(UTC)
    instant = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    published = document.published_at
    return bool(
        observed <= instant + timedelta(minutes=5)
        and instant - observed <= _MAX_SEC_OBSERVATION_AGE
        and published is not None
        and published <= instant.date()
        and instant.date() - published <= _MAX_SEC_PUBLICATION_AGE
    )


def _publisher_identity(text: str) -> tuple[str, str] | None:
    matches = list(_PUBLISHER_FIELD.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    issuer = (match.group("issuer") or match.group("labelled_issuer") or "").strip()
    if not issuer:
        return None
    return issuer, match.group(0).strip()


def _bare_publisher_stem(issuer: str) -> str | None:
    stem = _LEGAL_SUFFIX.sub("", issuer).rstrip(" ,.").strip()
    return stem if stem and stem != issuer else None


def extract_regulatory_project_organizations(
    project: Project,
    project_document: PublicDocument,
    regulatory_documents: Iterable[PublicDocument],
    *,
    now: datetime,
) -> list[Extracted]:
    """Extract only SEC-proven organizations with a direct developer assertion.

    The exact legal publisher name must appear in a retained publisher field,
    its bare stem must appear as the direct developer subject, and the SEC
    parser must validate that legal name as the issuer. Both source quotes are
    retained. No short brand alias is created for global identity matching.
    """
    aliases = _project_aliases(project)
    if not aliases or not project_document.text:
        return []
    publisher = _publisher_identity(project_document.text)
    if publisher is None:
        return []
    legal_issuer, publisher_quote = publisher
    publisher_stem = _bare_publisher_stem(legal_issuer)
    if publisher_stem is None:
        return []

    sec_documents = [
        document for document in regulatory_documents if _sec_is_current(document, now)
    ]
    if not sec_documents:
        return []

    results: dict[tuple[str, str], Extracted] = {}
    for sentence in _sentences(project_document.text):
        for organization, site in _developer_assertions(sentence, aliases, publisher_stem):
            if organization.casefold() != publisher_stem.casefold():
                continue
            if len(site.split()) == 1 and not _short_alias_has_native_full_site_support(
                project,
                project_document.text,
                organization,
                site,
                role_quote=sentence,
            ):
                continue
            matching_proofs = []
            for sec_document in sec_documents:
                proof = parse_sec_domain_assertion(
                    _sec_source(sec_document), organization=legal_issuer, expected_ein=None
                )
                if proof is not None and official_domain_matches_url(
                    proof.domain, project_document.url
                ):
                    matching_proofs.append(proof)
            proof_identities = {
                (proof.issuer_name.casefold(), proof.ein, proof.domain) for proof in matching_proofs
            }
            if len(proof_identities) != 1:
                continue
            key = (organization.casefold(), site.casefold())
            results[key] = Extracted(
                organization=legal_issuer,
                category=Category.OWNER.value,
                organization_relationship="DIRECT",
                evidence_strength="High",
                reason=(
                    "The source explicitly reports this organization as developing the selected "
                    "site. This does not establish legal ownership, active construction, or "
                    "purchasing authority."
                ),
                citations=[
                    {
                        "url": project_document.url,
                        "quote": publisher_quote,
                        "supports": "project_organization",
                        "document_key": document_key(project_document),
                    },
                    {
                        "url": project_document.url,
                        "quote": sentence,
                        "supports": "project_organization",
                        "document_key": document_key(project_document),
                    },
                    {
                        "url": project_document.url,
                        "quote": sentence,
                        "supports": "organization_category",
                        "document_key": document_key(project_document),
                    },
                ],
            )
    return list(results.values())
