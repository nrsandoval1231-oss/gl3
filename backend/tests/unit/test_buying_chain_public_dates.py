from datetime import date
from uuid import uuid4

import pytest

from gridlens.ingestion.adapters.buying_chain_public import parse_document
from gridlens.intelligence.buying_chain_extraction import Extracted, extract_people
from gridlens.persistence.models import Project

TODAY = date(2026, 9, 30)


def extracted_role(document):
    project = Project(
        id=uuid4(),
        identity_key="orion",
        name="Orion Data Center",
        location="Austin, TX",
        source_id="test",
        external_id="42",
        identity_facts={},
    )
    return extract_people(
        document,
        [Extracted("Acme", "general_contractor")],
        project,
        project_scoped=False,
        today=TODAY,
    )[0]


@pytest.mark.parametrize(
    "incidental_date",
    [
        '<aside>Conference <time datetime="2026-09-20">September 20</time></aside>',
        '<meta name="date" content="2026-09-20">',
        '<meta itemprop="dateModified" content="2026-09-20">',
    ],
)
def test_archived_role_is_not_refreshed_by_calendar_or_generic_date(incidental_date):
    document = parse_document(
        "https://acme.com/2019/alice",
        (
            "<html><head><title>Acme biography archive</title></head><body>"
            f"{incidental_date}"
            "<article>Alice Smith is Project Director at Acme.</article></body></html>"
        ).encode(),
        "text/html",
    )

    assert document.published_at is None
    role = extracted_role(document)
    assert role.person_organization_relationship == "UNKNOWN"
    assert role.person_project_relationship == "UNKNOWN"


@pytest.mark.parametrize(
    "publication",
    [
        '<meta property="article:published_time" content="2026-09-20T09:00:00Z">',
        '<meta itemprop="datePublished" content="2026-09-20">',
        '<time itemprop="datePublished" datetime="2026-09-20">September 20</time>',
    ],
)
def test_explicit_publication_date_supports_recent_role(publication):
    document = parse_document(
        "https://acme.com/news/project-director",
        (
            "<html><head><title>Acme announcement</title></head><body>"
            f"{publication}"
            "<article>Alice Smith is Project Director at Acme.</article></body></html>"
        ).encode(),
        "text/html",
    )

    assert document.published_at == date(2026, 9, 20)
    role = extracted_role(document)
    assert role.person_organization_relationship == "CURRENT"
    assert role.person_project_relationship == "ROLE_SUPPORTED"


def test_official_record_issue_date_is_not_publication_date():
    document = parse_document(
        "https://data.cityofchicago.org/resource/ydr8-5enu.json",
        b'[{"id":"42","issue_date":"2026-09-20"}]',
        "application/json",
    )
    assert document.published_at is None
