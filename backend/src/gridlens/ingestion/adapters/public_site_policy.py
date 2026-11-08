"""Fail-closed exact-host permission and conservative robots policy.

Terms-review references are human attestations supplied by configuration; this
module does not determine or certify legal permission.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

from gridlens.settings import settings

PolicyMode = Literal["direct", "firecrawl"]


@dataclass(frozen=True)
class HostApproval:
    hostname: str
    terms_review_ref: str
    reviewed_at: datetime
    expires_at: datetime
    modes: frozenset[str]
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    hostname: str
    resolved_ip: str | None = None


def _host(value: str) -> str | None:
    normalized = value.casefold().rstrip(".")
    if (
        not normalized
        or "*" in normalized
        or len(normalized) > 253
        or not re.fullmatch(r"[a-z0-9.-]+", normalized)
        or any(
            not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
            for label in normalized.split(".")
        )
    ):
        return None
    return normalized


def _aware(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _approval_record(value: object) -> HostApproval | None:
    if not isinstance(value, dict):
        return None
    if set(value) - {
        "hostname",
        "terms_review_ref",
        "reviewed_at",
        "expires_at",
        "modes",
        "revoked_at",
    }:
        return None
    hostname = value.get("hostname")
    reference = value.get("terms_review_ref")
    reviewed = _aware(value.get("reviewed_at"))
    expires = _aware(value.get("expires_at"))
    revoked_raw = value.get("revoked_at")
    revoked = None if revoked_raw is None else _aware(revoked_raw)
    modes = value.get("modes")
    if (
        not isinstance(hostname, str)
        or _host(hostname) != hostname.casefold().rstrip(".")
        or not isinstance(reference, str)
        or not reference.strip()
        or len(reference) > 200
        or reviewed is None
        or expires is None
        or expires <= reviewed
        or (revoked_raw is not None and revoked is None)
        or not isinstance(modes, list)
        or not modes
        or any(not isinstance(mode, str) for mode in modes)
        or len(set(modes)) != len(modes)
        or any(mode not in {"direct", "firecrawl"} for mode in modes)
    ):
        return None
    return HostApproval(
        hostname=hostname.casefold().rstrip("."),
        terms_review_ref=reference.strip(),
        reviewed_at=reviewed,
        expires_at=expires,
        modes=frozenset(modes),
        revoked_at=revoked,
    )


def load_host_approval(
    url: str, *, mode: PolicyMode, now: datetime | None = None
) -> HostApproval | None:
    """Load one valid, active, exact-host approval; malformed config denies."""
    try:
        parts = urlsplit(url)
        target = _host(parts.hostname or "")
        if parts.scheme != "https" or parts.port not in (None, 443) or target is None:
            return None
    except ValueError:
        return None
    try:
        rows = json.loads(settings.public_research_site_permissions)
    except (AttributeError, TypeError, ValueError):
        return None
    if not isinstance(rows, list):
        return None
    approvals = [_approval_record(row) for row in rows]
    if any(approval is None for approval in approvals):
        return None
    matches = [approval for approval in approvals if approval and approval.hostname == target]
    if len(matches) != 1:
        return None
    approval = matches[0]
    instant = now or datetime.now(UTC)
    instant = instant.replace(tzinfo=UTC) if instant.tzinfo is None else instant.astimezone(UTC)
    if (
        mode not in {"direct", "firecrawl"}
        or mode not in approval.modes
        or approval.reviewed_at > instant
        or approval.expires_at <= instant
        or approval.revoked_at is not None
    ):
        return None
    return approval


def evaluate_host_approval(
    url: str,
    approval: HostApproval | None,
    *,
    mode: PolicyMode,
    now: datetime | None = None,
) -> PolicyDecision:
    try:
        parts = urlsplit(url)
        hostname = _host(parts.hostname or "") or ""
        valid_url = (
            parts.scheme == "https"
            and parts.username is None
            and parts.password is None
            and parts.port in (None, 443)
            and bool(hostname)
        )
    except ValueError:
        hostname, valid_url = "", False
    instant = now or datetime.now(UTC)
    instant = instant.replace(tzinfo=UTC) if instant.tzinfo is None else instant.astimezone(UTC)
    if not valid_url:
        return PolicyDecision(False, "unsupported_url", hostname)
    if approval is None:
        return PolicyDecision(False, "host_not_approved", hostname)
    if (
        not isinstance(approval.hostname, str)
        or _host(approval.hostname) != approval.hostname
        or not isinstance(approval.terms_review_ref, str)
        or not approval.terms_review_ref.strip()
        or len(approval.terms_review_ref) > 200
        or not isinstance(approval.reviewed_at, datetime)
        or not isinstance(approval.expires_at, datetime)
        or approval.reviewed_at.tzinfo is None
        or approval.expires_at.tzinfo is None
        or approval.expires_at <= approval.reviewed_at
        or not approval.modes
        or any(item not in {"direct", "firecrawl"} for item in approval.modes)
        or (
            approval.revoked_at is not None
            and (
                not isinstance(approval.revoked_at, datetime) or approval.revoked_at.tzinfo is None
            )
        )
    ):
        return PolicyDecision(False, "approval_invalid", hostname)
    if approval.hostname != hostname:
        return PolicyDecision(False, "host_mismatch", hostname)
    if mode not in approval.modes:
        return PolicyDecision(False, "mode_not_approved", hostname)
    if approval.revoked_at is not None:
        return PolicyDecision(False, "approval_revoked", hostname)
    if approval.reviewed_at > instant or approval.expires_at <= instant:
        return PolicyDecision(False, "approval_expired_or_not_yet_valid", hostname)
    return PolicyDecision(True, "host_approved", hostname)


def evaluate_robots_policy(
    robots_txt: str | None,
    target_url: str,
    *,
    user_agent: str = "GridLens",
    robots_status: int = 200,
) -> PolicyDecision:
    """Apply a deliberately limited path-prefix robots grammar; unknown syntax denies."""
    try:
        host = _host(urlsplit(target_url).hostname or "") or ""
    except ValueError:
        host = ""
    if not host:
        return PolicyDecision(False, "unsupported_url", host)
    target = urlsplit(target_url)
    path = target.path or "/"
    if (
        target.query
        or "%" in path
        or "\\" in path
        or "//" in path
        or any(part in {".", ".."} for part in path.split("/"))
    ):
        return PolicyDecision(False, "robots_ambiguous_target_path", host)
    if robots_status in {404, 410}:
        return PolicyDecision(True, "robots_absent", host)
    if robots_status != 200 or robots_txt is None:
        return PolicyDecision(False, "robots_unavailable", host)
    try:
        if len(robots_txt.encode("utf-8", errors="strict")) > 65_536:
            return PolicyDecision(False, "robots_too_large", host)
    except UnicodeError:
        return PolicyDecision(False, "robots_invalid_encoding", host)
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    saw_rule = False

    def flush() -> None:
        nonlocal agents, rules, saw_rule
        if agents:
            groups.append((agents, rules))
        agents, rules, saw_rule = [], [], False

    for raw in robots_txt.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            if agents and saw_rule:
                flush()
            continue
        if ":" not in line:
            return PolicyDecision(False, "robots_unsupported_syntax", host)
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.casefold()
        if key == "user-agent":
            if saw_rule:
                flush()
            if not re.fullmatch(r"[A-Za-z0-9*._-]{1,100}", value):
                return PolicyDecision(False, "robots_unsupported_user_agent", host)
            agents.append(value.casefold())
            continue
        if key not in {"allow", "disallow"} or not agents:
            return PolicyDecision(False, "robots_unsupported_directive", host)
        if any(token in value for token in ("*", "$", "%", "\\")) or "//" in value:
            return PolicyDecision(False, "robots_unsupported_pattern", host)
        if value and (not value.startswith("/") or len(value) > 1024):
            return PolicyDecision(False, "robots_unsupported_pattern", host)
        if any(part in {".", ".."} for part in value.split("/")):
            return PolicyDecision(False, "robots_unsupported_pattern", host)
        if value:
            rules.append((key, value))
        saw_rule = True
    flush()
    agent = user_agent.casefold()
    matched_agents = [
        (len(name), group) for group in groups for name in group[0] if name != "*" and name in agent
    ]
    if matched_agents:
        specificity = max(length for length, _ in matched_agents)
        selected = [group for length, group in matched_agents if length == specificity]
    else:
        selected = [group for group in groups if "*" in group[0]]
    matches = [
        (len(pattern), directive == "allow")
        for _, ruleset in selected
        for directive, pattern in ruleset
        if path.startswith(pattern)
    ]
    if not matches:
        return PolicyDecision(True, "robots_allowed", host)
    specificity = max(length for length, _ in matches)
    allowed = any(is_allowed for length, is_allowed in matches if length == specificity)
    return PolicyDecision(allowed, "robots_allowed" if allowed else "robots_disallowed", host)


def resolve_site_policy(
    url: str,
    *,
    mode: PolicyMode,
    approval: HostApproval | None = None,
    robots_txt: str | None,
    robots_status: int = 200,
    now: datetime | None = None,
) -> PolicyDecision:
    """Combine the exact-host approval with a previously checked robots result."""
    host_decision = evaluate_host_approval(url, approval, mode=mode, now=now)
    if not host_decision.allowed:
        return host_decision
    return evaluate_robots_policy(robots_txt, url, robots_status=robots_status)
