from gridlens.domain.signal_admission import admit_standalone


def test_news_cannot_admit_signal_even_when_copy_claims_procurement_terms():
    result = admit_standalone(
        source_id="news-rss",
        family="news",
        retrieval_method="publisher-rss",
        accepted=True,
        activity="temporary-power",
        title="Solicitation for temporary generator service",
        abstract="A project-specific request for proposal is open.",
        dated=True,
        citation_url="https://publisher.example/story",
        identified_project=True,
    )
    assert not result.admitted
    assert result.origin == "News context"


def test_accepted_official_permit_is_admitted_without_known_mw():
    result = admit_standalone(
        source_id="city-permits",
        family="construction-permits",
        retrieval_method="socrata-permits",
        accepted=True,
        activity="backup-power",
        title="New generator installation at a data center",
        abstract=None,
    )
    assert result.admitted
    assert result.origin == "Official permit"


def test_official_utility_policy_without_specific_dated_project_event_is_context():
    generic = admit_standalone(
        source_id="utility-docket",
        family="official-utility-filings",
        retrieval_method="utility-docket",
        accepted=True,
        activity="utility-service",
        title="Utility publishes large-load service policy",
        abstract="New procedures apply to future applications.",
        dated=True,
        citation_url="https://utility.example/policy",
        identified_project=False,
    )
    project_event = admit_standalone(
        source_id="utility-docket",
        family="official-utility-filings",
        retrieval_method="utility-docket",
        accepted=True,
        activity="utility-service",
        title="Commission approves service agreement for Atlas project substation",
        abstract="A dated filing identifies the physical project and site.",
        dated=True,
        citation_url="https://utility.example/docket/123",
        identified_project=True,
    )
    assert not generic.admitted
    assert project_event.admitted


def test_public_temporary_power_solicitation_requires_explicit_need_and_citation():
    result = admit_standalone(
        source_id="county-procurement",
        family="temporary-power-procurement",
        retrieval_method="public-procurement",
        accepted=True,
        activity="temporary-power",
        title="Request for proposal: temporary generator rental for Atlas site",
        abstract="Bid due October 18; delivery is required at the named project site.",
        dated=True,
        citation_url="https://county.example/bids/atlas",
        identified_project=True,
    )
    vague = admit_standalone(
        source_id="county-procurement",
        family="temporary-power-procurement",
        retrieval_method="public-procurement",
        accepted=True,
        activity="backup-power",
        title="Facilities equipment request",
        abstract="The county is exploring standby generation.",
        dated=True,
        citation_url="https://county.example/bids/other",
        identified_project=True,
    )
    assert result.admitted
    assert not vague.admitted


def test_planning_and_general_government_research_remain_context():
    for family, method in (
        ("municipal-planning-news", "taylor-newsflash"),
        ("economic-development-publication", "nc-commerce-html"),
        ("structured-government", "json-api"),
    ):
        result = admit_standalone(
            source_id="context-source",
            family=family,
            retrieval_method=method,
            accepted=True,
            activity="facility-expansion",
            title="Named facility project begins construction",
            abstract="A dated official update describes the site.",
            dated=True,
            citation_url="https://government.example/project",
            identified_project=True,
        )
        assert not result.admitted
