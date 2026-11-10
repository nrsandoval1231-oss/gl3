"""Disabled Apollo contact adapter seam.

Apollo API docs describe account/API-key endpoint access and credit-bearing
enrichment. This repository cannot verify a workspace license, endpoint
entitlement, credit balance, or permitted use, so this adapter deliberately
performs no network calls until an owner-authorized activation is implemented.
Public company-site research remains independent of this adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

APOLLO_ENABLED = False
ACTIVATION_BLOCKED_REASON = "apollo_access_and_license_not_verified"


@dataclass(frozen=True)
class ApolloContactRequest:
    """Stable, already company-bound person hint; never a raw name-only search."""

    company_domain: str
    person_name: str
    role: str


@dataclass(frozen=True)
class ApolloContactResult:
    status: Literal["activation_blocked", "no_result"]
    reason: str
    contacts: tuple[object, ...] = ()


def enrich_contact(request: ApolloContactRequest) -> ApolloContactResult:
    """Fail closed without secrets, HTTP clients, or assumed provider rights."""
    del request  # Request is intentionally not logged or sent anywhere.
    return ApolloContactResult("activation_blocked", ACTIVATION_BLOCKED_REASON)
