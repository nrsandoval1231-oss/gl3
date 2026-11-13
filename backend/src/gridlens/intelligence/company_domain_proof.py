"""Conservative SEC-filing proof for a canonical company's own domain.

This module is deliberately pure: callers provide already-retrieved SEC text
and canonical identity rows. It neither fetches sources nor treats a company's
own website as proof of the binding.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast
from urllib.parse import urlsplit
from uuid import UUID

if TYPE_CHECKING:
    from gridlens.persistence.models import (
        BuyingChainEvidence,
        CompanyIdentity,
        IdentityIdentifier,
    )

_SEC_FILING_PATH = re.compile(
    r"^/Archives/edgar/data/(?P<cik>[0-9]{1,10})/(?P<accession>[0-9]{18})/(?P<file>[A-Za-z0-9][A-Za-z0-9._-]*)$"
)
_ISSUER_LABELS = re.compile(
    r"(?im)^\s*(?:COMPANY\s+CONFORMED\s+NAME|REGISTRANT(?:'S)?\s+NAME|ISSUER\s+NAME|COMPANY\s+NAME)\s*:\s*(?P<name>[^\r\n]{2,240}?)\s*$"
)
_EIN_LABELS = re.compile(
    r"(?im)^\s*(?:IRS(?:\s+EMPLOYER)?(?:\s+IDENTIFICATION)?\s+(?:NUMBER|NO\.?|ID)|EMPLOYER\s+IDENTIFICATION\s+NUMBER|EIN)\s*:\s*(?P<ein>(?:\d[\s-]*){9})\s*$"
)
_WEBSITE_FIELD = re.compile(
    r"(?im)^\s*(?P<name>[^\r\n:]{2,240}?)\s+website\s*:\s*(?P<url>[^\s\r\n<>\"']+)\s*$"
)
_OUR_WEBSITE = re.compile(
    r"(?:\bOur\s+(?:(?:principal\s+)?website(?:\s+address)?|Internet\s+address)"
    r"(?:\s+(?:is|can\s+be\s+found\s+at|is\s+located\s+at)\s*|,\s*)"
    r"|\bYou\s+may\s+also\s+obtain\b[^.!?\n]{0,600}?\bon\s+our\s+website,\s*)"
    r"(?P<url>(?:https?://|www\.)[^\s<>\"']+)",
    re.IGNORECASE,
)
_DOMAIN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.IGNORECASE)


@dataclass(frozen=True)
class CompanyDomainProof:
    """One unambiguous, issuer-attributed domain statement in a SEC filing."""

    company_identity_id: UUID | None
    issuer_name: str
    ein: str
    domain: str
    quote: str
    start_offset: int
    end_offset: int
    source_url: str
    source_hash: str


class DomainProofSource(Protocol):
    url: str
    excerpt: str
    content_hash: str


def _canonical_name(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", value.casefold())
    equivalents = {
        "inc": "incorporated",
        "incorporated": "incorporated",
        "corp": "corporation",
        "corporation": "corporation",
        "ltd": "limited",
        "limited": "limited",
    }
    if words and words[-1] in equivalents:
        words[-1] = equivalents[words[-1]]
    return " ".join(words)


def _issuer_name_matches(text: str, organization: str, issuer: str) -> bool:
    expected = _canonical_name(organization)
    if _canonical_name(issuer) == expected:
        return True
    quoted_aliases = re.finditer(
        re.escape(issuer)
        + r"\s*(?:\(\s*(?:the\s+)?|,?\s+(?:is\s+)?(?:also known as|doing business as|"
        r"hereafter|hereinafter|referred to as)\s+)['\"“](?P<alias>[^'\"”]{2,160})['\"”]",
        text,
        re.IGNORECASE,
    )
    return any(_canonical_name(match.group("alias")) == expected for match in quoted_aliases)


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _sec_filing_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        # Reject even explicit :443, userinfo, queries and fragments. The
        # filing URL is a provenance check, not a general safe-URL validator.
        if (
            parsed.scheme != "https"
            or parsed.hostname not in {"sec.gov", "www.sec.gov"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.query
            or parsed.fragment
            or parsed.netloc.casefold() not in {"sec.gov", "www.sec.gov"}
        ):
            return False
    except (TypeError, ValueError):
        return False
    return bool(_SEC_FILING_PATH.fullmatch(parsed.path))


def _domain_from_url(value: str) -> str | None:
    candidate = value.rstrip(".,;:)").strip()
    try:
        parsed = urlsplit(candidate if "://" in candidate else f"https://{candidate}")
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
            return None
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            return None
        host = (parsed.hostname or "").casefold().rstrip(".")
    except ValueError:
        return None
    if not _DOMAIN.fullmatch(host) or host in {"sec.gov", "www.sec.gov"}:
        return None
    return host.removeprefix("www.")


def _canonical_eins(
    identity: CompanyIdentity, identifiers: Sequence[IdentityIdentifier]
) -> set[str]:
    values: set[str] = set()
    for row in identifiers:
        if (
            row.entity_type != "company"
            or row.identifier_type.casefold() != "ein"
            or row.company_identity_id != identity.id
            or row.person_identity_id is not None
        ):
            continue
        digits = _digits(row.normalized_value)
        if len(digits) == 9:
            values.add(digits)
    return values


def extract_company_domain_proof(
    source: BuyingChainEvidence,
    *,
    identity: CompanyIdentity,
    organization: str,
    identifiers: Sequence[IdentityIdentifier],
) -> CompanyDomainProof | None:
    """Return proof only for the exact canonical issuer's explicit SEC domain.

    `source.excerpt` is the exact retrieved content available to the caller;
    offsets and quote therefore refer to this immutable evidence snapshot.
    Ambiguity is intentionally represented as `None`.
    """
    canonical_eins = _canonical_eins(identity, identifiers)
    if len(canonical_eins) != 1:
        return None
    expected_ein = next(iter(canonical_eins))
    proof = parse_sec_domain_assertion(
        cast(DomainProofSource, source),
        organization=organization,
        expected_ein=expected_ein,
    )
    if proof is None:
        return None
    return CompanyDomainProof(
        company_identity_id=identity.id,
        issuer_name=proof.issuer_name,
        ein=proof.ein,
        domain=proof.domain,
        quote=proof.quote,
        start_offset=proof.start_offset,
        end_offset=proof.end_offset,
        source_url=proof.source_url,
        source_hash=proof.source_hash,
    )


def parse_sec_domain_assertion(
    source: DomainProofSource,
    *,
    organization: str,
    expected_ein: str | None = None,
) -> CompanyDomainProof | None:
    """Validate a standalone issuer/EIN/domain statement in one SEC filing.

    The expected EIN is supplied by the caller. This lower-level parser also
    supports guarded bootstrap before an `IdentityIdentifier` row exists.
    """
    if not _sec_filing_url(source.url):
        return None
    if not isinstance(source.excerpt, str) or not source.excerpt.strip():
        return None
    expected_digits = _digits(expected_ein) if expected_ein is not None else None
    if expected_digits is not None and len(expected_digits) != 9:
        return None

    issuer_rows = [match.group("name").strip() for match in _ISSUER_LABELS.finditer(source.excerpt)]
    # SEC cover-page form: "Name (Exact name of registrant as specified in
    # its charter)". Only the exact-label format is treated as an issuer field.
    for match in re.finditer(
        r"(?im)^\s*(?P<name>[^\r\n()]{2,240}?)\s*"
        r"\(Exact name of registrant as specified in its charter\)",
        source.excerpt,
    ):
        issuer_rows.append(match.group("name").strip())
    lines = source.excerpt.splitlines()
    for index, line in enumerate(lines):
        if not re.search(r"\bCommission\s+File\s+Number\b", line, re.I):
            continue
        for heading in lines[index + 1 : index + 7]:
            candidate = heading.strip().strip("|").strip()
            if not candidate or re.fullmatch(r"[0-9-]+", candidate):
                continue
            if (
                candidate.upper() == candidate
                and re.search(r"[A-Z]{2,}", candidate)
                and not any(mark in candidate for mark in ("|", ":"))
            ):
                issuer_rows.append(candidate)
                break
    issuer_names = {_canonical_name(value) for value in issuer_rows}
    if len(issuer_names) != 1 or not _issuer_name_matches(
        source.excerpt, organization, issuer_rows[0]
    ):
        return None
    issuer_name = issuer_rows[0]

    filing_eins = {_digits(match.group("ein")) for match in _EIN_LABELS.finditer(source.excerpt)}
    for match in re.finditer(
        r"(?im)\b(?:I\.?R\.?S\.?\s+)?"
        r"(?:Employer\s+Identification\s+No\.?|Employer\s+ID\s+No\.?)"
        r"\s*\)?\s*[:.]?\s*(?:\r?\n\s*)?(?P<ein>\d{2}[- ]?\d{7})",
        source.excerpt,
    ):
        filing_eins.add(_digits(match.group("ein")))
    lines = source.excerpt.splitlines()
    for index, line in enumerate(lines):
        if not re.search(r"\bI\.?R\.?S\.?\s+(?:ID|Employer|Identification|No\b)", line, re.I):
            continue
        if re.search(r"\d{2}[- ]?\d{7}", line):
            continue
        # SEC cover-page tables may put the EIN in the previous cell row and
        # the typed '(I.R.S. ID)' label directly below it. Accept only the
        # nearest preceding Markdown table row containing one EIN token.
        previous_table_rows = [
            row
            for row in lines[max(0, index - 3) : index]
            if row.lstrip().startswith("|") and re.search(r"\d{2}[- ]?\d{7}", row)
        ]
        if previous_table_rows:
            nearest = previous_table_rows[-1]
            row_eins = re.findall(r"\b\d{2}[- ]?\d{7}\b", nearest)
            if len(row_eins) == 1:
                filing_eins.add(_digits(row_eins[0]))
    if len(filing_eins) != 1 or (expected_digits is not None and filing_eins != {expected_digits}):
        return None
    ein = next(iter(filing_eins))

    authorities: list[tuple[str, re.Match[str]]] = []
    issuer_key = _canonical_name(organization)
    for match in _WEBSITE_FIELD.finditer(source.excerpt):
        if _canonical_name(match.group("name")) == issuer_key:
            authorities.append((match.group("url"), match))
    for match in _OUR_WEBSITE.finditer(source.excerpt):
        # Only a first-person assertion at sentence start is treated as the
        # issuer speaking. This rejects quoted subsidiary/customer statements.
        sentence_start = (
            max(
                source.excerpt.rfind(".", 0, match.start()),
                source.excerpt.rfind("!", 0, match.start()),
                source.excerpt.rfind("?", 0, match.start()),
                source.excerpt.rfind("\n", 0, match.start()),
            )
            + 1
        )
        prefix = source.excerpt[sentence_start : match.start()].casefold()
        paragraph_start = source.excerpt.rfind("\n\n", 0, match.start())
        preceding_context = source.excerpt[paragraph_start + 1 : sentence_start].strip()
        prior_paragraph = source.excerpt[max(0, paragraph_start - 400) : paragraph_start].strip()
        last_context_line = (
            (preceding_context or prior_paragraph).splitlines()[-1].strip()
            if (preceding_context or prior_paragraph)
            else ""
        )
        quote_prefix = source.excerpt[max(0, match.start() - 1) : match.start()]
        if (
            prefix.strip()
            or quote_prefix in {'"', "'", "“", "‘"}
            or last_context_line.endswith(":")
            or re.search(
                r"\b(?:reports|reported|says|said|states|stated|writes|wrote)\s*:\s*$",
                preceding_context,
                re.I,
            )
            or (
                re.search(
                    r"\b(?:LLC|L\.L\.C\.|INCORPORATED|INC\.?|CORPORATION|CORP\.?|LIMITED|LTD\.?)\b",
                    last_context_line,
                    re.I,
                )
                and _canonical_name(issuer_name) not in _canonical_name(last_context_line)
            )
        ):
            continue
        raw_url = match.group("url")
        clean_url = raw_url.rstrip(".,;:)")
        trailing = raw_url[len(clean_url) :]
        if trailing.startswith((".", "!", "?")):
            statement_tail = ""
        else:
            tail = source.excerpt[match.start("url") + len(clean_url) :]
            sentence_end = re.search(r"[.!?\n]", tail)
            statement_tail = tail[: sentence_end.start()] if sentence_end else tail
        # A correction often follows the assertion in a separate paragraph.
        # Check a short bounded tail for anaphoric website/domain retractions.
        following_context = source.excerpt[match.end() : match.end() + 400]
        if re.search(
            r"(?:\b(?:no longer|formerly|previously|ceased|discontinued)\b"
            r"[^.!?\n]{0,100}\b(?:our|the)?\s*(?:official|current|correct)?\s*"
            r"(?:website|internet address|domain|url)\b|"
            r"\bnot\s+(?:our|the)\s+(?:official|current|correct)\s*"
            r"(?:website|internet address|domain|url)\b|"
            r"\b(?:website|domain)\s+(?:is|was)\s+not\s+(?:ours|our\s+current)\b)",
            statement_tail + " " + following_context,
            re.IGNORECASE,
        ):
            continue
        authorities.append((match.group("url"), match))
    if not authorities:
        return None

    domains = {_domain_from_url(value) for value, _ in authorities}
    if None in domains or len(domains) != 1:
        return None
    # More than one assertion is accepted only if each exact issuer statement
    # independently identifies the same domain. Duplicate references within
    # one sentence are not separate authorities because the regex captures one.
    domain = next(iter(domains))
    assert isinstance(domain, str)
    statements: list[tuple[str, int, int]] = []
    for value, match in authorities:
        assert _domain_from_url(value) == domain
        start = match.start()
        end = match.end()
        quote = source.excerpt[start:end].strip()
        # Keep offsets aligned after trimming leading spaces on field rows.
        leading = len(source.excerpt[start:end]) - len(source.excerpt[start:end].lstrip())
        statements.append((quote, start + leading, start + leading + len(quote)))
    if len({statement[0] for statement in statements}) != len(statements):
        statements = list(dict.fromkeys(statements))
    if len(statements) != 1:
        return None
    quote, start_offset, end_offset = statements[0]
    if not isinstance(source.content_hash, str) or not source.content_hash:
        return None
    return CompanyDomainProof(
        company_identity_id=None,
        issuer_name=issuer_name,
        ein=ein,
        domain=domain,
        quote=quote,
        start_offset=start_offset,
        end_offset=end_offset,
        source_url=source.url,
        source_hash=source.content_hash,
    )
