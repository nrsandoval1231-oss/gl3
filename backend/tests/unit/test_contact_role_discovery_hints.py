"""Unverified named roles can guide bounded research, never contact acceptance."""

from datetime import UTC, date, datetime, timedelta

import pytest

from gridlens.ingestion.adapters.buying_chain_public import PublicDocument
from gridlens.intelligence.company_contact_discovery import _named_role_discovery_hints
from gridlens.persistence.models import Project

NOW = datetime(2026, 11, 12, 12, tzinfo=UTC)


def hints(
    text, *, url="https://acme.example/team", published_at=None, project=True, observed_at=NOW
):
    document = PublicDocument(
        url,
        "Acme Energy leadership",
        text,
        observed_at=observed_at,
        published_at=published_at,
    )
    selected = Project(name="North Campus", location="Austin, TX", identity_facts={})
    return _named_role_discovery_hints(document, "Acme Energy", selected if project else None, NOW)


def test_concrete_role_is_only_a_discovery_hint_and_deduplicates_urls():
    text = "Acme Energy\nJordan Smith\nVP, Construction\n© 2026 Acme Energy."
    first = hints(text)
    assert len(first) == 1
    assert hints(text, url="https://acme.example/leadership") == first
    assert all(len(key) == 2 for key in first)


@pytest.mark.parametrize(
    "text,published_at",
    [
        ("Acme Energy information. Email: info@acme.example.", None),
        ("Jordan Smith\nFormer VP, Construction", None),
        ("Jordan Smith is no longer VP, Construction at Acme Energy.", None),
        ("Jordan Smith is VP, Construction at Acme Energy.", date(2023, 1, 1)),
    ],
)
def test_empty_generic_historical_or_denied_pages_do_not_extend_depth(text, published_at):
    assert hints(text, published_at=published_at) == set()


def test_missing_project_anchor_cannot_extend_depth():
    assert hints("Jordan Smith\nVP, Construction", project=False) == set()


@pytest.mark.parametrize("days", [-1, 31])
def test_stale_or_future_roster_observation_is_not_a_new_hint(days):
    assert hints("Jordan Smith\nVP, Construction", observed_at=NOW - timedelta(days=days)) == set()
