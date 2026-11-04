"""Bounded full-passage input for Jev requests.

Jev requests used to cut evidence at 1,200 or 1,500 characters. At the vendor's input price a
full relevant passage is nearly free, but the TypeSafe finite-billing policy
(`typesafe-total-input-ceiling-v1`) still requires every request to stay under the verified
total-input ceiling. The rule here is conservative and deterministic:

* one UTF-8 byte is counted as one billable token (tokens never exceed bytes);
* the request overhead (questions, state, JSON structure) is measured, not guessed;
* a fixed reserve covers opaque provider wrapper tokens;
* the passage budget is the smallest of the configured passage cap, the remaining headroom
  under the verified ceiling, and (when the narrow estimate policy is selected) the estimate
  policy's request-size limit.

A passage that does not fit is cut at a paragraph or sentence boundary and the cut is reported
to the caller so the record shows that the model saw a partial passage. Nothing is silently
dropped.
"""

from __future__ import annotations

import json
from typing import Any

from gridlens.settings import settings

# Reserve for provider wrapper tokens that client-side serialization cannot see.
WRAPPER_RESERVE_BYTES = 2_048


def request_bytes(request: Any) -> int:
    return len(json.dumps(request, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))


def passage_budget_bytes(overhead_bytes: int, *, hard_cap_bytes: int | None = None) -> int:
    """Return the bytes available for passage text; never negative."""
    budget = settings.jev_passage_max_bytes
    ceiling = settings.intelligence_typesafe_max_total_billable_input_tokens
    if ceiling > 0:
        budget = min(budget, ceiling - overhead_bytes - WRAPPER_RESERVE_BYTES)
    if hard_cap_bytes is not None:
        budget = min(budget, hard_cap_bytes - overhead_bytes)
    return max(0, budget)


def bound_passage(text: str, budget_bytes: int) -> tuple[str, dict[str, Any]]:
    """Return the longest boundary-aligned prefix of ``text`` that fits ``budget_bytes``.

    The returned metadata always reports the full size so a cut is visible.
    """
    total_chars = len(text)
    # json escaping can expand a byte (quotes, control characters, non-ASCII), so measure
    # the escaped size the request will actually carry.
    def escaped(value: str) -> int:
        return len(json.dumps(value, ensure_ascii=True).encode("utf-8")) - 2

    meta: dict[str, Any] = {"chars_total": total_chars, "truncated": False}
    if escaped(text) <= budget_bytes:
        meta["chars_sent"] = total_chars
        return text, meta
    low, high = 0, total_chars
    while low < high:
        middle = (low + high + 1) // 2
        if escaped(text[:middle]) <= budget_bytes:
            low = middle
        else:
            high = middle - 1
    cut = text[:low]
    for separator in ("\n\n", "\n", ". ", " "):
        position = cut.rfind(separator)
        if position >= low // 2:
            cut = cut[: position + len(separator)]
            break
    meta.update(chars_sent=len(cut), truncated=True)
    return cut, meta
