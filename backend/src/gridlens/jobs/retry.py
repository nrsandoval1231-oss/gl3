"""Deterministic bounded retry delay jitter for durable jobs."""

from __future__ import annotations

import hashlib


def jittered_delay_seconds(
    identity: str,
    attempt: int,
    base_seconds: int,
    *,
    ceiling_seconds: int,
    jitter_percent: int = 20,
) -> int:
    """Apply reproducible symmetric jitter and clamp a retry delay to its ceiling."""
    if not identity or attempt < 0 or base_seconds <= 0 or ceiling_seconds <= 0:
        raise ValueError("Retry identity, attempt, base, and ceiling must be valid")
    if not 0 <= jitter_percent <= 100:
        raise ValueError("jitter_percent must be between 0 and 100")
    base = min(base_seconds, ceiling_seconds)
    span = base * jitter_percent // 100
    if span == 0:
        return base
    digest = hashlib.sha256(f"{identity}:{attempt}".encode()).digest()
    offset = int.from_bytes(digest[:8], "big") % (2 * span + 1) - span
    return min(ceiling_seconds, max(1, base + offset))
