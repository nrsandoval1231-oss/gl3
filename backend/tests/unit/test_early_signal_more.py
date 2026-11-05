"""WS4b sources: Comptroller registry, OCC notices, county agendas, TCEQ water rights.

No network: HTTP is an httpx.MockTransport with DNS pinned to a public address. Fixtures are short
excerpts of the public pages read live on 2026-11-04 (see ``_early_more_fixtures``).
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from _early_more_fixtures import (
    AGENDA_PAGES,
    DC_MULTI_ROW,
    DC_ROW,
    GOOGLE_FORM_PAGES,
    GOOGLE_LABEL,
    HASKELL_AGENDA,
    HASKELL_SCAN,
    HASKELL_URL,
    LD_ROW,
    LD_SHORT_ROW,
    NO_NUMBER_ROW,
    NOTICE_PAGES,
    OCC_EMERALD,
    OCC_GOOGLE,
    OCC_URL,
    REGISTRY_URL,
    TCEQ_NOTICE,
    TCEQ_URL,
    haskell_origin,
    occ_html,
    occ_links,
    occ_origin,
    pdf,
    registry_html,
    registry_origin,
    registry_row,
    tceq_html,
    tceq_origin,
    water_row,
)

import gridlens.ingestion.adapters.comptroller_dc_registry as cr
import gridlens.ingestion.adapters.county_abatement_agendas as ca
import gridlens.ingestion.adapters.early_signal_more as more
import gridlens.ingestion.adapters.ok_occ_dc_notices as oc
import gridlens.ingestion.adapters.tceq_water_rights as tw
from gridlens.ingestion.adapters.early_signal_http import EarlyFetcher
from gridlens.ingestion.adapters.early_signal_stage import StageConfig
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.tceq_application_documents import DocumentFailure
from gridlens.ingestion.registry import load_registry

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
TODAY = date(2026, 11, 4)
CONFIG = StageConfig(max_downloads=6, max_checks=20, extract_seconds=120.0, isolate=False)
MODULES = [cr, oc, ca, tw]


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr("gridlens.ingestion.adapters.tceq_http._public_ip", lambda _host: "8.8.8.8")


def source_of(module, **documents):
    definition = next(r for r in load_registry() if r["id"] == module.SOURCE_ID)
    definition = {**definition, "query": {**definition["query"]}}
    if documents:
        definition["query"]["documents"] = {**definition["query"]["documents"], **documents}
    return definition


def listing(module, origin):
    return module.retrieve(source_of(module), origin.client(), pacer=lambda: None, today=TODAY)


def stage(module, origin, records, *, prior=None, index=None, now=NOW, config=CONFIG):
    return module.run_stage(
        records,
        prior or {},
        client=origin.client(),
        config=config,
        index=index,
        pacer=lambda: None,
        now=lambda: now,
    )


def states_of(records):
    return {
        r["state_key"]: r["early_signal"]
        for r in records
        if r.get("state_key") and "early_signal" in r
    }


# --------------------------------------------------------------------------- ships off / registry


@pytest.mark.parametrize("module", MODULES)
def test_ships_off_and_the_registry_validates(module):
    definition = source_of(module)
    assert definition["enabled"] is False
    assert module.valid_query(definition["query"])
    documents = definition["query"].get("documents")
    if documents is not None:
        assert documents["enabled"] is False and documents["seed_urls"] == []
        assert module.config_from_source(definition) is None
    assert definition["retrieval_method"] == module.RETRIEVAL_METHOD
    assert definition["credential_reference"] is None


@pytest.mark.parametrize("module", MODULES)
def test_query_shape_is_exact(module):
    query = source_of(module)["query"]
    assert not module.valid_query({**query, "extra": 1})
    assert not module.valid_query({k: v for k, v in query.items() if k != "max_records"})
    assert not module.valid_query({**query, "max_records": 0})
    assert not module.valid_query({**query, "max_response_bytes": 10**9})
    assert not module.valid_query("nope")


def test_documents_config_rejects_seed_urls_and_bad_budgets():
    for module in (oc, ca, tw):
        query = source_of(module)["query"]
        docs = query["documents"]
        assert not module.valid_query({**query, "documents": {**docs, "seed_urls": [OCC_GOOGLE]}})
        assert not module.valid_query({**query, "documents": {**docs, "max_downloads": 99}})
        assert not module.valid_query({**query, "documents": {**docs, "extract_seconds": 1}})
    assert not ca.valid_query({**source_of(ca)["query"], "counties": ["haskell", "milam"]})


def test_listing_refuses_a_different_source_or_endpoint():
    for module in MODULES:
        definition = source_of(module)
        with pytest.raises(SourceParseError):
            module.retrieve({**definition, "id": "other"}, httpx.Client())
        with pytest.raises(SourceParseError):
            module.retrieve({**definition, "endpoint": "https://evil.example/"}, httpx.Client())


# --------------------------------------------------------------------------- URL policy

GOOD_PDF_PATHS = {
    oc: [OCC_URL, OCC_GOOGLE, OCC_EMERALD],
    ca: [
        HASKELL_URL,
        HASKELL_AGENDA,
        "https://www.haskellcountytx.gov/upload/page/7690/Agenda.pdf",
    ],
    tw: [TCEQ_URL, TCEQ_NOTICE],
    cr: [cr.ENDPOINT],
}


@pytest.mark.parametrize("module", MODULES)
def test_url_policy_accepts_reviewed_shapes(module):
    for url in GOOD_PDF_PATHS[module]:
        assert module.url_ok(url), url


BAD_URLS = [
    "",
    None,
    7,
    "http://oklahoma.gov/occ/x.pdf",
    "https://oklahoma.gov.evil.example/content/dam/ok/en/occ/documents/pu/data-center-act/"
    "notice-of-intent-submissions/a.pdf",
    "https://user@oklahoma.gov/content/dam/ok/en/occ/documents/pu/data-center-act/"
    "notice-of-intent-submissions/a.pdf",
    "https://oklahoma.gov:8443/content/dam/ok/en/occ/documents/pu/data-center-act/"
    "notice-of-intent-submissions/a.pdf",
    "https://oklahoma.gov/content/dam/ok/en/occ/documents/pu/data-center-act/"
    "notice-of-intent-submissions/../../secret.pdf",
    "https://oklahoma.gov/content/dam/ok/en/occ/documents/pu/data-center-act/"
    "notice-of-intent-submissions/a.pdf?x=1",
    "https://oklahoma.gov/content/dam/ok/en/occ/documents/pu/data-center-act/"
    "notice-of-intent-submissions/a.pdf#frag",
    "https://oklahoma.gov/content/dam/ok/en/occ/documents/pu/other/a.pdf",
    "https://oklahoma.gov/content/dam/ok/en/occ/documents/pu/data-center-act/"
    "notice-of-intent-submissions/a.exe",
    "https://www.haskellcountytx.gov/upload/page/7690/a.exe",
    "https://www.haskellcountytx.gov/upload/page/7690/../9220/a.pdf",
    "https://www.haskellcountytx.gov/upload/page/9220/docs/Agenda.pdf",
    "https://www.haskellcountytx.gov/upload/page/7690/a.pdf?x=1",
    "https://www.haskellcountytx.gov.evil.example/upload/page/7690/a.pdf",
    "https://www.tceq.texas.gov/downloads/permitting/water-rights/pending/application/a.pdf",
    "https://www.tceq.texas.gov/downloads/permitting/water-rights/pending/notice/a.pdf?x=1",
    "https://www.tceq.texas.gov/downloads/permitting/water-rights/pending/notice/a.xlsx",
    "https://www.tceq.texas.gov/downloads/permitting/water-rights/pending/notice/../a.pdf",
    "https://www.tceq.texas.gov/search",
    "https://comptroller.texas.gov/taxes/data-centers/data-center-lists.php?x=1",
    "https://comptroller.texas.gov/taxes/data-centers/",
    "https://comptroller.texas.gov/robots.txt",
    "https://evil.example/taxes/data-centers/data-center-lists.php",
    "https://oklahoma.gov/content/dam/ok/en/occ/documents/pu/data-center-act/"
    "notice-of-intent-submissions/" + "a" * 600 + ".pdf",
]


@pytest.mark.parametrize("module", MODULES)
def test_url_policy_rejects(module):
    for url in BAD_URLS:
        assert not module.url_ok(url), url


def test_fetcher_refuses_outside_policy_without_a_request():
    origin = occ_origin()
    fetcher = EarlyFetcher(origin.client(), lambda: None, oc.url_ok)
    for url in ("https://oklahoma.gov/robots.txt", "https://www.tceq.texas.gov/search"):
        with pytest.raises(DocumentFailure) as caught:
            fetcher.get(url, max_bytes=1000, media_types=frozenset({"text/html"}))
        assert caught.value.code == "url_policy"
    assert origin.log == []


def test_fetcher_refuses_a_host_not_on_the_shared_list_even_if_the_policy_accepts_it():
    origin = occ_origin()
    fetcher = EarlyFetcher(origin.client(), lambda: None, lambda _url: True)
    with pytest.raises(DocumentFailure):
        fetcher.get("https://example.com/a", max_bytes=10, media_types=frozenset({"text/html"}))
    assert origin.log == []


def test_redirects_are_not_followed_and_private_dns_is_refused(monkeypatch):
    origin = occ_origin()
    origin.put(OCC_URL, b"", status=302)
    fetcher = EarlyFetcher(origin.client(), lambda: None, oc.url_ok)
    with pytest.raises(DocumentFailure) as caught:
        fetcher.get(OCC_URL, max_bytes=1000, media_types=frozenset({"text/html"}))
    assert caught.value.code == "redirect_not_followed" and len(origin.log) == 1
    monkeypatch.setattr(
        "gridlens.ingestion.adapters.tceq_http._public_ip",
        lambda _h: (_ for _ in ()).throw(DocumentFailure("private_address")),
    )
    with pytest.raises(DocumentFailure):
        fetcher.get(OCC_URL, max_bytes=1000, media_types=frozenset({"text/html"}))


# --------------------------------------------------------------------------- listing behaviour


@pytest.mark.parametrize(
    ("module", "origin_factory", "pages"),
    [
        (cr, registry_origin, 1),
        (oc, occ_origin, 1),
        (ca, haskell_origin, 1),
        (tw, tceq_origin, 1),
    ],
)
def test_listing_makes_exactly_one_request_and_is_stable(module, origin_factory, pages):
    origin = origin_factory()
    first = listing(module, origin)
    assert len(origin.log) == pages and first
    again = listing(module, origin_factory())
    assert [(r["document_number"], r["source_hash"], r["abstract"]) for r in first] == [
        (r["document_number"], r["source_hash"], r["abstract"]) for r in again
    ]


@pytest.mark.parametrize(
    ("module", "origin_factory"),
    [(cr, registry_origin), (oc, occ_origin), (ca, haskell_origin), (tw, tceq_origin)],
)
def test_listing_429_is_typed_with_retry_after_and_503_without(module, origin_factory):
    origin = origin_factory()
    origin.force = lambda url: httpx.Response(429, headers={"retry-after": "900"})
    with pytest.raises(SourceParseError) as caught:
        listing(module, origin)
    assert caught.value.acquisition_code == "http_status_429"
    assert caught.value.acquisition_retry_after_seconds == 900
    origin.force = lambda url: httpx.Response(503)
    with pytest.raises(SourceParseError) as caught:
        listing(module, origin)
    assert caught.value.acquisition_code == "http_status_503"


@pytest.mark.parametrize(
    ("module", "origin_factory", "url"),
    [
        (cr, registry_origin, REGISTRY_URL),
        (oc, occ_origin, OCC_URL),
        (ca, haskell_origin, HASKELL_URL),
        (tw, tceq_origin, TCEQ_URL),
    ],
)
def test_listing_js_shell_and_layout_change_fail_loudly(module, origin_factory, url):
    origin = origin_factory()
    origin.put(url, b"<html><body><div id='app'></div></body></html>")
    with pytest.raises(SourceParseError):
        listing(module, origin)
    origin.put(url, b"%PDF-1.4", ctype="application/pdf")
    with pytest.raises(SourceParseError):
        listing(module, origin)


def test_listing_size_cap_by_header_is_a_typed_listing_error():
    origin = registry_origin()
    fetcher = EarlyFetcher(origin.client(), lambda: None, cr.url_ok)
    with pytest.raises(SourceParseError, match="oversize"):
        more.fetch_page(fetcher, REGISTRY_URL, 50, None, "Comptroller")


# --------------------------------------------------------------------------- Comptroller


def test_registry_rows_are_parsed_with_kind_names_numbers_and_dates():
    records = listing(cr, registry_origin())
    by_number = {r["document_number"]: r for r in records}
    assert set(by_number) == {
        "TXCOMP-DC046706",
        "TXCOMP-DC481494",
        "TXCOMP-LD549949",
        "TXCOMP-LD547974",
    }
    ale = by_number["TXCOMP-DC046706"]
    assert "Owner: COPT San Antonio LP" in ale["abstract"]
    assert "Occupant: Amazon Data Services Inc." in ale["abstract"]
    assert "qualifying data center" in ale["title"] and ale["event_date"] == "2021-01-01"
    assert ale["publication_date"] is None  # the page lists no publication date
    assert ale["event_date_label"] == "registration effective"
    large = by_number["TXCOMP-LD549949"]
    assert "qualifying large data center project" in large["title"]
    assert "Exemption end date (as listed): 10/19/2036" in large["abstract"]
    multi = by_number["TXCOMP-DC481494"]
    assert "Owner: not listed" in multi["abstract"]
    assert "Core Scientific, Inc.; Coreweave Compute Acquisition Co. II. LLC" in multi["abstract"]
    assert "DC481494-OP2" in multi["abstract"]
    # A row that omits the trailing cell has no end date: unknown, not an invented one.
    short = by_number["TXCOMP-LD547974"]
    assert "Exemption end date (as listed): not listed" in short["abstract"]


def test_registry_row_without_a_registration_number_is_skipped():
    rows, skipped = cr.parse_registry(
        registry_html([DC_ROW, DC_MULTI_ROW], [LD_ROW, LD_SHORT_ROW, NO_NUMBER_ROW])
    )
    assert len(rows) == 4 and skipped["no_registration"] == 1 and skipped["tables"] == 2


def test_registry_row_with_two_registration_roots_is_not_an_identity():
    mixed = registry_row(
        "Mixed", "01/01/2025", "A LLC", "DC111111-OW1", "B LLC", "DC222222-OC1", "C", "DC111111-OP1"
    )
    rows, skipped = cr.parse_registry(registry_html([mixed], [LD_ROW]))
    assert [r["root"] for r in rows] == ["LD549949"] and skipped["no_registration"] == 1


def test_registry_no_county_address_or_mw_is_claimed():
    for record in listing(cr, registry_origin()):
        assert "no county, address or MW" in record["abstract"]
        assert not re.search(r"\bMW\b: \d", record["abstract"])


def test_registry_withholds_detected_personal_names_and_addresses():
    row = registry_row(
        "Example Data Center",
        "01/01/2025",
        "John Smith, a property owner",
        "DC123456-OW1",
        "Acme Compute LLC",
        "DC123456-OC1",
        "123 County Road 5",
        "DC123456-OP1",
    )
    rows, _skipped = cr.parse_registry(registry_html([row], []))
    record = cr.record_for(rows[0], "2026-11-05")
    retained = repr(record)
    assert "John Smith" not in retained
    assert "123 County Road 5" not in retained
    assert "individual name withheld" in record["abstract"]
    assert record["source_hash"] != hashlib.sha256(cr._canonical(rows[0]).encode()).hexdigest()


def test_registry_changed_row_changes_only_its_hash():
    first = {r["document_number"]: r["source_hash"] for r in listing(cr, registry_origin())}
    changed = registry_row(
        "ALE60 Data Center",
        "01/01/2021",
        "COPT San Antonio LP",
        "DC046706-OW1",
        "Amazon Data Services Inc.",
        "DC046706-OC1",
        "Some New Operator LLC",
        "DC046706-OP1",
    )
    second = {
        r["document_number"]: r["source_hash"]
        for r in listing(cr, registry_origin(dc_rows=[changed, DC_MULTI_ROW]))
    }
    assert second["TXCOMP-DC046706"] != first["TXCOMP-DC046706"]
    assert all(second[k] == first[k] for k in first if k != "TXCOMP-DC046706")


def test_registry_duplicate_registration_root_keeps_the_first():
    rows, skipped = cr.parse_registry(registry_html([DC_ROW, DC_ROW], [LD_ROW]))
    assert len(rows) == 2 and skipped["duplicate"] == 1


def test_registry_no_document_stage_and_apply_prior_is_a_noop():
    records = listing(cr, registry_origin())
    before = [dict(r) for r in records]
    cr.apply_prior_states(records, {})
    assert records == before and cr.config_from_source(source_of(cr)) is None


# --------------------------------------------------------------------------- OCC


def test_occ_listing_parses_label_fields_from_the_heading_list_only():
    records = listing(oc, occ_origin())
    assert len(records) == 2
    google = next(r for r in records if r["doc_url"] == OCC_GOOGLE)
    assert "Company (per link text): Google, LLC" in google["abstract"]
    assert "County (per link text): Tulsa" in google["abstract"]
    assert google["publication_date"] is None and google["event_date"] == "2026-10-15"
    assert google["event_date_label"] == "date in link text"
    emerald = next(r for r in records if r["doc_url"] == OCC_EMERALD)
    assert "Project (per link text): Battles 112" in emerald["abstract"]
    assert "County (per link text): Pittsburg" in emerald["abstract"]
    assert "no MW is stated" in google["abstract"]
    assert google["state_key"] == OCC_GOOGLE and google["doc_kind"] == "occ_notice"


def test_occ_label_parsing_keeps_unknown_when_the_shape_does_not_match():
    assert oc.parse_label(GOOGLE_LABEL) == {
        "company": "Google, LLC",
        "county": "Tulsa",
        "date": "2026-10-15",
    }
    assert oc.parse_label("Mystery filing") == {}
    assert oc.parse_label("A - B County - Notadate 99, 2026") == {}
    assert oc.parse_label("A - B - October 15, 2026") == {}


def test_occ_foreign_and_off_policy_links_are_dropped():
    links = [
        *occ_links(),
        ("https://evil.example/x.pdf", "Evil - Tulsa County - October 1, 2026"),
        (
            "/content/dam/ok/en/occ/documents/pu/other/x.pdf",
            "Other - Tulsa County - October 1, 2026",
        ),
    ]
    origin = occ_origin()
    origin.put(OCC_URL, occ_html(links))
    assert len(listing(oc, origin)) == 2


def test_occ_missing_heading_or_list_is_a_layout_failure():
    for body in (b"<html>nothing</html>", b"<h2>Notice of Intent Submissions</h2><p>none</p>"):
        origin = occ_origin()
        origin.put(OCC_URL, body)
        with pytest.raises(SourceParseError):
            listing(oc, origin)


def test_occ_form_fields_each_reproduce_from_their_own_quote():
    origin = occ_origin()
    records = listing(oc, origin)
    report = stage(oc, origin, records)
    state = states_of(records)[OCC_GOOGLE]
    fields = state["document"]["extraction"]["fields"]
    assert {k: v["value"] for k, v in fields.items()} == {
        "company": "Google LLC",
        "land_purchase_date": "2026-08-21",
        "county": "Tulsa County",
        "planned_utility": "Public Service Company of Oklahoma (PSO)",
    }
    for name, item in fields.items():
        assert item["basis"] == "documented" and item["page"] == 1
        found = oc._FIELDS[name].search(item["quote"])
        assert found is not None and oc._value(name, found) == item["value"]
    assert report.counts["new"] == 1
    google = next(r for r in records if r["doc_url"] == OCC_GOOGLE)
    assert "Land purchase date (form): 2026-08-21 [page 1]" in google["abstract"]
    assert "Source document SHA-256:" in google["abstract"]


def test_occ_never_stores_the_attestant_or_adjacent_owners():
    origin = occ_origin()
    records = listing(oc, origin)
    stage(oc, origin, records)
    blob = repr(records)
    assert "McGarry" not in blob and "Landowner" not in blob and "Senior Director" not in blob


def test_occ_scanned_form_is_an_abstention_and_the_listing_record_stands():
    origin = occ_origin()
    records = listing(oc, origin)
    report = stage(oc, origin, records)
    assert any(
        r["error_code"].startswith("text_layer_") or r["error_code"] == "empty_text_layer"
        for r in report.rejections
    )
    emerald = next(r for r in records if r["doc_url"] == OCC_EMERALD)
    assert "early_signal" not in emerald and "Battles 112" in emerald["abstract"]
    # Remembered as a permanent failure: not asked again inside the recheck window.
    n = len(origin.log)
    again = stage(oc, origin, listing(oc, origin), index=report.index, now=NOW + timedelta(days=1))
    assert again.counts.get("known_failed", 0) >= 1
    assert OCC_EMERALD not in origin.urls()[n + 1 :]


def test_occ_form_pages_beyond_the_form_are_not_read_for_fields():
    pages = [[*GOOGLE_FORM_PAGES[0][:1]], [], [], GOOGLE_FORM_PAGES[0][1:]]
    pages[3] = ["Large Load Customer Company Name: Hidden Corp Land Purchase Date: 1/1/2026"]
    extraction = oc.extract_form([" ".join(p) for p in pages], [])
    assert extraction["fields"] == {} and extraction["abstain"]["note"] == "Abstention, not zero."


def test_occ_unchanged_rerun_is_idempotent_and_changed_bytes_keep_first_seen():
    origin = occ_origin()
    records = listing(oc, origin)
    stage(oc, origin, records)
    prior = states_of(records)
    first = {r["document_number"]: (r["source_hash"], r["abstract"]) for r in records}
    n = len(origin.log)
    again = listing(oc, origin)
    report = stage(
        oc,
        origin,
        again,
        prior=prior,
        index={"urls": {k: {"status": "document", "at": NOW.isoformat()} for k in prior}},
    )
    assert report.counts.get("fresh_skipped", 0) >= 1 and report.counts.get("new", 0) == 0
    assert OCC_GOOGLE not in origin.urls()[n:]
    assert {r["document_number"]: (r["source_hash"], r["abstract"]) for r in again} == first
    # Changed bytes after the recheck window: a new state; first_seen_at never rewritten.
    changed = occ_origin(form=pdf([[*GOOGLE_FORM_PAGES[0][:2], "Land Purchase Date: 8/22/2026"]]))
    later = NOW + timedelta(days=30)
    refreshed = listing(oc, changed)
    stage(oc, changed, refreshed, prior=prior, index={"urls": {}}, now=later)
    new_state = states_of(refreshed)[OCC_GOOGLE]
    assert new_state["first_seen_at"] == prior[OCC_GOOGLE]["first_seen_at"] == NOW.isoformat()
    assert new_state["document"]["replaced_sha256"] == [prior[OCC_GOOGLE]["document"]["sha256"]]
    record = next(r for r in refreshed if r["doc_url"] == OCC_GOOGLE)
    assert record["source_hash"] != first[record["document_number"]][0]


def test_occ_oversize_document_is_a_typed_failure(monkeypatch):
    origin = occ_origin()
    monkeypatch.setattr(oc, "MAX_PDF_BYTES", 300)
    records = listing(oc, origin)
    report = stage(oc, origin, records)
    assert report.counts.get("failure_oversize", 0) >= 1
    assert all("early_signal" not in r for r in records)


def test_occ_html_in_place_of_a_pdf_is_js_shell_and_wrong_signature_is_rejected():
    origin = occ_origin()
    origin.put(OCC_GOOGLE, b"<html>app</html>", ctype="text/html")
    report = stage(oc, origin, listing(oc, origin))
    assert report.counts.get("failure_js_shell") == 1
    origin.put(OCC_GOOGLE, b"MZ not a pdf", ctype="application/pdf")
    report = stage(oc, origin, listing(oc, origin))
    assert report.counts.get("failure_not_pdf_signature") == 1


# --------------------------------------------------------------------------- county agendas


def test_haskell_listing_keeps_only_policy_pdfs_newest_first_and_skips_cancellations():
    records = listing(ca, haskell_origin())
    assert [r["doc_url"] for r in records] == [HASKELL_SCAN, HASKELL_AGENDA]
    assert [r["event_date"] for r in records] == ["2026-06-23", "2026-05-12"]
    assert records[0]["publication_date"] is None
    assert all(r["doc_kind"] == "county_agenda" for r in records)


def test_haskell_listing_respects_max_agendas():
    definition = source_of(ca)
    definition["query"]["max_agendas"] = 1
    records = ca.retrieve(definition, haskell_origin().client(), pacer=lambda: None, today=TODAY)
    assert [r["doc_url"] for r in records] == [HASKELL_SCAN]


def test_agenda_items_are_verbatim_quotes_and_fields_reproduce_from_their_quotes():
    origin = haskell_origin()
    records = listing(ca, origin)
    stage(ca, origin, records)
    state = states_of(records)[HASKELL_AGENDA]
    items = state["document"]["extraction"]["items"]
    assert [i["value"]["agenda_item"] for i in items] == [
        "7",
        "9",
    ]  # item 8 is a nuisance abatement
    page = " ".join(" ".join(AGENDA_PAGES[0]).split())
    for item in items:
        assert item["quote"] in page
        assert page[item["span"][0] : item["span"][1]] == item["quote"]
        for name, field in item["fields"].items():
            again = ca._scalar(name, field["quote"])
            assert again is not None and again[0] == field["value"], name
            assert field["quote"] in page
    abatement, data_center = items
    assert abatement["value"]["names_abatement"] is True
    # The item names an abatement but not a data center: its quote only, no fields.
    assert abatement["fields"] == {} and abatement["value"]["names_data_center"] is False
    fields = data_center["fields"]
    assert data_center["value"]["names_data_center"] is True
    assert fields["stated_mw"]["value"] == 300 and fields["acres"]["value"] == 1200
    assert fields["investment_usd"]["value"] == 2_500_000_000
    assert fields["investment_usd"]["basis"] == "calculated"
    assert fields["location"]["value"] == "County Road 12"
    assert "entity" not in fields  # the item names no company: unknown, never guessed


def test_agenda_without_a_match_is_an_abstention_not_a_denial():
    origin = haskell_origin(
        agenda=pdf(
            [
                [
                    "1. Call to Order and welcome of the public to the regular meeting.",
                    "2. Prayer and Pledge of Allegiance to the flag of the United States.",
                    "3. Approval of minutes and payment of bills as listed in the consent items.",
                    "4. Adjourn the meeting of the Commissioners Court until the next date.",
                ]
            ]
        )
    )
    records = listing(ca, origin)
    stage(ca, origin, records)
    state = states_of(records)[HASKELL_AGENDA]
    extraction = state["document"]["extraction"]
    assert extraction["items"] == [] and extraction["abstain"]["note"] == "Abstention, not zero."
    record = next(r for r in records if r["doc_url"] == HASKELL_AGENDA)
    assert "not a statement that none was discussed" in record["abstract"]


def test_agenda_scan_is_withheld_not_stored_empty():
    origin = haskell_origin()
    records = listing(ca, origin)
    report = stage(ca, origin, records)
    assert [r["doc_url"] for r in records] == [HASKELL_AGENDA]
    assert report.counts["withheld_unread"] == 1
    assert any(
        r["error_code"].startswith("text_layer_") or r["error_code"] == "empty_text_layer"
        for r in report.rejections
    )


def test_agenda_item_investment_and_mw_shapes_are_exact():
    text = (
        "9. Consider an abatement agreement with Alpha Data LLC for a 1.5 GW data center on a "
        "10-acre site."
    )
    fields = ca.extract_agenda([text], [])["items"][0]["fields"]
    assert fields["stated_mw"]["value"] == 1500 and fields["stated_mw"]["basis"] == "calculated"
    assert fields["acres"]["value"] == 10 and fields["entity"]["value"] == "Alpha Data LLC"
    plain = "9. Consider a data center abatement with a $750,000,000 investment."
    investment = ca.extract_agenda([plain], [])["items"][0]["fields"]["investment_usd"]
    assert investment["value"] == 750_000_000 and investment["basis"] == "documented"


def test_two_different_amounts_in_one_item_are_unknown_not_chosen():
    text = (
        "9. Consider a data center abatement with a $750,000,000 investment and a $12.5 million "
        "road fund for 100 MW and 200 MW."
    )
    fields = ca.extract_agenda([text], [])["items"][0]["fields"]
    assert "investment_usd" not in fields and "stated_mw" not in fields


def test_agenda_items_are_capped():
    page = " ".join(f"{n}. Consider a tax abatement for project {n}." for n in range(1, 40))
    assert len(ca.extract_items([page])) == ca.MAX_ITEMS


# --------------------------------------------------------------------------- TCEQ water rights


def test_water_listing_rows_and_notice_links():
    records = listing(tw, tceq_origin())
    by_number = {r["document_number"]: r for r in records}
    assert set(by_number) == {"TCEQWR-12-4013D", "TCEQWR-23-2653C"}
    plain = by_number["TCEQWR-12-4013D"]
    assert plain["doc_url"] is None and plain["state_key"] is None
    assert plain["event_date"] == "2026-09-25" and plain["publication_date"] is None
    assert "The listing states no volume or use" in plain["abstract"]
    noticed = by_number["TCEQWR-23-2653C"]
    assert noticed["doc_url"] == TCEQ_NOTICE and noticed["publication_date"] == "2026-09-01"
    assert "Notice issued (as listed): 9/1/2026" in noticed["abstract"]


def test_water_listing_ignores_tables_with_other_headers_and_bad_wr_numbers():
    html = tceq_html(
        [water_row("A", "12-1", "x", "1/1/2026"), water_row("B", "12-4013D", "Brazos", "1/2/2026")]
    )
    rows = tw.parse_listing(html)
    assert [r["wr_no"] for r in rows] == ["12-4013D"]


def test_water_notice_volumes_are_quoted_with_roles_and_never_summed():
    origin = tceq_origin()
    records = listing(tw, origin)
    report = stage(tw, origin, records)
    state = states_of(records)[TCEQ_NOTICE]
    extraction = state["document"]["extraction"]
    volumes = extraction["volumes"]
    assert [(v["value"], v["role"]) for v in volumes] == [
        ("27.75", "existing_authorization"),
        (1000, "requested"),
    ]
    page = " ".join(" ".join(NOTICE_PAGES[0]).split())
    for v in volumes:
        assert page[v["span"][0] : v["span"][1]] == v["quote"] and v["unit"] == "acre-feet"
        again = tw._ACRE_FEET.search(v["quote"])
        assert again is not None and tw._acre_feet(again["n"]) == v["value"]
    assert "total" not in repr(extraction).lower()
    assert extraction["applicant_named"]["value"] == "Ingram Readymix No. 87, L.L.C"
    assert {p["value"] for p in extraction["purposes"]} >= {"mining", "agricultural"}
    assert extraction["data_center"] is None
    assert report.counts["new"] == 1
    record = next(r for r in records if r["doc_url"] == TCEQ_NOTICE)
    assert "Acre-feet stated (page 1, requested): 1000" in record["abstract"]


def test_water_notice_naming_a_data_center_is_quoted_only_when_stated():
    pages = [[*NOTICE_PAGES[0], "The applicant plans a data center cooling supply."]]
    extraction = tw.extract_notice([" ".join(pages[0])], [], "Ingram Readymix No. 87, L.L.C")
    assert extraction["data_center"]["quote"].count("data center") == 1
    assert tw.extract_notice(["Nothing stated."], [])["abstain"]["note"].startswith("Abstention")


def test_water_notice_only_the_first_pages_are_read():
    late = ["x"] * tw.NOTICE_PAGES + ["Applicant requests 5 acre-feet of water per year."]
    assert tw.extract_notice(late, [])["volumes"] == []


def test_water_listing_stands_without_documents_and_unread_notices_stay_listed():
    origin = tceq_origin()
    origin.put(TCEQ_NOTICE, b"MZ not a pdf", ctype="application/pdf")
    records = listing(tw, origin)
    report = stage(tw, origin, records)
    assert len(records) == 2 and report.counts.get("failure_not_pdf_signature") == 1
    assert all("early_signal" not in r for r in records)


def test_water_notice_download_budget_and_size_cap(monkeypatch):
    origin = tceq_origin()
    records = listing(tw, origin)
    report = stage(tw, origin, records, config=StageConfig(1, 20, 120.0, (), False))
    assert report.counts["downloads"] == 1
    monkeypatch.setattr(tw, "MAX_PDF_BYTES", 100)
    over = stage(tw, tceq_origin(), listing(tw, tceq_origin()))
    assert over.counts.get("failure_oversize", 0) == 1


# --------------------------------------------------------------------------- 429 / not_before


@pytest.mark.parametrize(
    ("module", "origin_factory", "doc_url"),
    [
        (oc, occ_origin, OCC_GOOGLE),
        (ca, haskell_origin, HASKELL_AGENDA),
        (tw, tceq_origin, TCEQ_NOTICE),
    ],
)
def test_429_stops_the_stage_sets_not_before_and_rests_until_it_passes(
    module, origin_factory, doc_url
):
    origin = origin_factory()
    origin.force = lambda url: (
        httpx.Response(429, headers={"retry-after": "600"}) if url == doc_url else None
    )
    records = listing(module, origin)
    report = stage(module, origin, records)
    assert report.counts["aborted_rate_limited"] == 1 and report.retry_after_seconds == 600
    assert report.index["not_before"] == (NOW + timedelta(seconds=600)).isoformat()
    n = len(origin.log)
    rested = stage(
        module,
        origin,
        listing(module, origin_factory()),
        index=report.index,
        now=NOW + timedelta(seconds=100),
    )
    assert rested.counts.get("skipped_retry_after") == 1 and len(origin.log) == n
    assert rested.index["not_before"] == report.index["not_before"]
    clear = origin_factory()
    ok = stage(
        module, clear, listing(module, clear), index=report.index, now=NOW + timedelta(seconds=700)
    )
    assert "not_before" not in ok.index and ok.counts.get("new", 0) >= 1


def test_503_without_retry_after_rests_one_hour():
    origin = occ_origin()
    origin.force = lambda url: httpx.Response(503) if url == OCC_GOOGLE else None
    report = stage(oc, origin, listing(oc, origin))
    assert report.index["not_before"] == (NOW + timedelta(hours=1)).isoformat()


# --------------------------------------------------------------------------- evidence only


def test_no_record_carries_an_admission_hook_or_a_load_claim():
    for module, origin in (
        (cr, registry_origin()),
        (oc, occ_origin()),
        (ca, haskell_origin()),
        (tw, tceq_origin()),
    ):
        for record in listing(module, origin):
            assert "permit" not in record and "equipment" not in record
            assert "power_need" not in record and "project" not in record
            assert not re.search(r"\bdemand\b[^.]*\d+\s*MW", record["abstract"], re.I)


def test_more_helpers_normalise_and_quote():
    assert more.norm("a �  b\n c") == "a b c"
    page = more.norm("alpha beta gamma delta")
    item = more.evidence(1, "documented", 2, "beta gamma", page)
    assert item is not None and item["span"] == [6, 16] and item["page"] == 2
    assert more.evidence(1, "documented", 1, "missing", page) is None
    assert more.window("one two three four", 4, 7, 2, 2) == "one two three"


# --------------------------------------------------------------------------- review fixes (WS4b)


def volumes_of(text: str, applicant: str | None = None, organisation: bool = True):
    return tw.extract_notice([text], [], applicant, organisation)["volumes"]


def test_water_role_comes_from_the_clause_that_holds_the_figure():
    text = (
        "The Certificate authorizes the diversion of 500 acre-feet; the Applicant requests an "
        "additional 200 acre-feet."
    )
    assert [(v["value"], v["role"]) for v in volumes_of(text)] == [
        (500, "existing_authorization"),
        (200, "requested"),
    ]
    text = (
        "Owner holds a right which authorizes 300 acre-feet per year. Applicant seeks 40 "
        "acre-feet per year."
    )
    assert [(v["value"], v["role"]) for v in volumes_of(text)] == [
        (300, "existing_authorization"),
        (40, "requested"),
    ]


def test_water_clause_with_both_verb_classes_or_no_verb_is_just_stated():
    both = "The right authorizes 500 acre-feet and applicant requests 600 acre-feet per year."
    assert {v["role"] for v in volumes_of(both)} == {"stated"}
    assert [v["role"] for v in volumes_of("A flow of 12 acre-feet per year is mentioned.")] == [
        "stated"
    ]


def test_water_every_figure_in_a_window_keeps_its_own_value():
    text = "Applicant requests 200 acre-feet per year and 300 acre-feet per year for storage."
    found = volumes_of(text)
    assert [v["value"] for v in found] == [200, 300]
    page = " ".join(text.split())
    for v in found:
        assert page[v["span"][0] : v["span"][1]] == v["quote"]


PERSONAL_NOTICE = (
    "John Smith, 1234 County Road 5, Anytown, Texas 76000, Applicant, seeks to divert 50 "
    "acre-feet of water per year for irrigation use."
)


def test_individual_applicant_is_withheld_everywhere():
    html = tceq_html(
        [
            water_row(
                "John Smith",
                "12-9999",
                "Brazos",
                "5/1/2026",
                "6/2/2026",
                ("john-smith-12-9999-notice.pdf", "9/1/2026"),
            ),
            water_row("Palo Pinto County MWD 1", "12-4031", "Palo Pinto", "9/8/2026"),
        ]
    )
    origin = tceq_origin()
    origin.put(TCEQ_URL, html)
    records = listing(tw, origin)
    blob = repr(records)
    assert "John" not in blob and "Smith" not in blob and "john-smith" not in blob
    person = next(r for r in records if r["document_number"] == "TCEQWR-12-9999")
    assert "individual applicant (name withheld)" in person["title"] + person["abstract"]
    assert person["doc_url"] is None and person["state_key"] is None
    assert person["html_url"] == TCEQ_URL and person["applicant"] is None
    origin.put(TCEQ_URL, html.replace(b"John Smith", b"Jane Doe"))
    again = next(r for r in listing(tw, origin) if r["document_number"] == "TCEQWR-12-9999")
    assert again["source_hash"] == person["source_hash"]


def test_a_quote_with_the_applicant_name_or_an_address_is_dropped():
    out = tw.extract_notice([PERSONAL_NOTICE], [], "John Smith", organisation=False)
    assert out["volumes"] == [] and out["purposes"] == [] and out["applicant_named"] is None
    assert out["withheld_statements"] >= 1
    blob = repr(out)
    assert "John" not in blob and "Smith" not in blob and "1234" not in blob and "76000" not in blob
    out = tw.extract_notice(
        ["Acme Water LLC, 12 Main Street, Austin, TX 78701, requests 90 acre-feet per year."],
        [],
        "Acme Water LLC",
    )
    assert out["volumes"] == [] and "78701" not in repr(out)
    out = tw.extract_notice(
        ["Ingram Readymix No. 87, L.L.C. seeks to amend its right and requests 5 acre-feet."],
        [],
        "Ingram Readymix No. 87, L.L.C",
    )
    assert out["applicant_named"]["value"] == "Ingram Readymix No. 87, L.L.C"
    assert [v["value"] for v in out["volumes"]] == [5]


def test_applicant_name_quote_is_withheld_when_it_also_contains_a_person():
    out = tw.extract_notice(
        [
            "Acme Water LLC requests 100 acre-feet of water per year; "
            "Mr. John Smith, a resident, objects."
        ],
        [],
        "Acme Water LLC",
    )
    assert out["applicant_named"] is None
    assert "John Smith" not in repr(out)
    assert out["withheld_statements"] >= 1


def test_organisation_shapes():
    for name in (
        "City of Bryan",
        "Palo Pinto County Municipal Water District 1",
        "Luminant Generation Co",
        "Kimberlin On the Brazos, LLC",
        "North Texas Municipal Water Authority",
        "Travis County WCID 17",
    ):
        assert more.is_organisation(name), name
    for name in ("John Smith", "Mary Ann Cosper", "Kniffen Revocable Living Trust"):
        assert not more.is_organisation(name), name


def test_water_absolute_notice_href_is_matched_after_joining():
    row = water_row("Acme Water LLC", "12-1111", "Brazos", "1/1/2026")
    link = (
        '<td><a href="https://www.tceq.texas.gov/downloads/permitting/water-rights/pending/'
        'notice/acme-12-1111-notice.pdf">9/1/2026</a></td><td></td></tr>'
    )
    absolute = row.replace("<td></td><td></td></tr>", link)
    assert absolute != row
    rows = tw.parse_listing(tceq_html([absolute]))
    assert rows[0]["notice_url"].endswith("/notice/acme-12-1111-notice.pdf")
    foreign = absolute.replace("www.tceq.texas.gov", "evil.example")
    assert tw.parse_listing(tceq_html([foreign]))[0]["notice_url"] is None


def test_water_malformed_rows_are_counted_and_too_many_fail_loudly():
    good = [water_row(f"Acme {n} LLC", f"12-10{n:02d}", "Brazos", "1/1/2026") for n in range(40)]
    broken = '<tr><td colspan="2">Acme LLC</td><td>12-2000</td><td>x</td></tr>'
    origin = tceq_origin()
    origin.put(TCEQ_URL, tceq_html([*good, broken]))
    result = listing(tw, origin)
    assert result["partial"] is True and result["rejected_count"] == 1
    assert result["rejected_records"][0]["error_code"] == "malformed_row"
    assert len(result["records"]) == 40
    origin.put(TCEQ_URL, tceq_html([*good, broken, broken, broken, broken]))
    with pytest.raises(SourceParseError, match="skipped too many"):
        listing(tw, origin)


def test_water_zero_readable_rows_fails_loudly():
    origin = tceq_origin()
    origin.put(TCEQ_URL, tceq_html([water_row("A", "12-1", "x", "1/1/2026")]))
    with pytest.raises(SourceParseError):
        listing(tw, origin)


def test_text_layer_read_stops_after_the_first_pages_without_a_page_limit_failure(monkeypatch):
    from gridlens.ingestion.adapters import ercot_rpg_extract as rx

    body = pdf([[f"Page {n} states 5 acre-feet of water per year, municipal."] for n in range(6)])
    pages, _scanned = rx.read_pdf_pages(body, 60.0, False, first_pages=2)
    assert len(pages) == 2
    monkeypatch.setattr(rx, "MAX_PAGES", 3)
    with pytest.raises(DocumentFailure) as caught:
        rx.read_pdf_pages(body, 60.0, False)
    assert caught.value.code == "text_layer_too_many_pages"
    assert len(rx.read_pdf_pages(body, 60.0, False, first_pages=2)[0]) == 2


def test_agenda_fee_wind_farm_and_energy_units_do_not_become_data_center_facts():
    text = (
        "9. Consider payment of $25,000 application fee for a tax abatement with Wind Farm LLC "
        "for a 200 MW wind project."
    )
    item = ca.extract_agenda([text], [])["items"][0]
    assert item["fields"] == {} and item["value"]["names_data_center"] is False
    dc = "9. Consider a data center tax abatement for 40 MWh of storage and a $25,000 fee."
    fields = ca.extract_agenda([dc], [])["items"][0]["fields"]
    assert "stated_mw" not in fields and "investment_usd" not in fields
    cue = "9. Consider a data center tax abatement with a $2,000,000 capital investment."
    assert (
        ca.extract_agenda([cue], [])["items"][0]["fields"]["investment_usd"]["value"] == 2_000_000
    )
    hours = "9. Consider a data center tax abatement for a 100 MW-hours study."
    assert "stated_mw" not in ca.extract_agenda([hours], [])["items"][0]["fields"]


def test_agenda_amount_near_fee_fine_or_bond_is_not_an_investment():
    for clause in (
        "capital investment requirements and a $25,000 application fee",
        "investment requirements and a $25,000 fine",
        "capital investment requirements and a $25,000 bond",
    ):
        text = f"9. Consider a data center tax abatement. Discuss {clause}."
        fields = ca.extract_agenda([text], [])["items"][0]["fields"]
        assert "investment_usd" not in fields, clause


def test_bare_abatement_agreement_is_not_a_tax_abatement():
    for text in (
        "7. Discuss the abatement agreement for the neighborhood nuisance at Elm Street.",
        "8. Discuss procedures for the abatement of neighborhood nuisances.",
    ):
        assert ca.extract_items([text]) == []
    assert len(ca.extract_items(["7. Consider a Chapter 312 agreement."])) == 1


def test_unnumbered_text_gets_a_quote_but_no_fields():
    text = "The court may take up a data center project of 300 MW proposed by Alpha Data LLC."
    item = ca.extract_items([text])[0]
    assert item["fields"] == {} and item["value"]["numbered"] is False


def test_an_item_that_spans_a_page_break_is_not_lost():
    first = "1. Call to order. 7. Discuss a data center tax abatement with Alpha Data LLC for"
    second = "a 300 MW campus on 1,200 acres. 8. Adjourn"
    items = ca.extract_items([first, second])
    assert len(items) == 1 and items[0]["fields"]["stated_mw"]["page"] == 2
    assert items[0]["fields"]["entity"]["page"] == 1
    for f in items[0]["fields"].values():
        page = " ".join((first, second)[f["page"] - 1].split())
        assert page[f["span"][0] : f["span"][1]] == f["quote"]


def test_agenda_quotes_are_short_and_personal_items_abstain():
    long = "7. Consider a tax abatement " + "filler words " * 80 + "with Alpha Data LLC."
    quote = ca.extract_items([long])[0]["quote"]
    assert len(quote) <= 300 and "tax abatement" in quote
    personal = "7. Mr. Jones of 123 County Road 5 asks about the tax abatement for his land."
    assert ca.extract_items([personal]) == []
    with_company = "7. Alpha Data LLC at 123 County Road 5 requests a tax abatement."
    assert ca.extract_items([with_company]) == []


def test_agenda_withholds_personal_context_even_when_item_names_a_company():
    address = (
        "7. Alpha Data LLC requests a 300 MW data center at 123 County Road 5; "
        "Mr. Jones, a nearby resident, objects to the abatement."
    )
    name = "8. Discuss the data center abatement with Alpha Data LLC and Jane Smith, landowner."
    assert ca.extract_items([address]) == []
    assert ca.extract_items([name]) == []


def test_haskell_listing_keeps_undated_labels_and_rejects_encoded_separators():
    links = [
        ("/upload/page/7690/docs/Agenda 1.pdf", "Special Called"),
        ("/upload/page/7690/docs/Agenda 2.pdf", "May 12, 2026"),
        ("/upload/page/7690/docs/Agenda 3.pdf", "June 1, 2026"),
        ("/upload/page/7690/docs/a%2Fb.pdf", "June 2, 2026"),
        ("/upload/page/7690/docs/a%5Cb.pdf", "June 3, 2026"),
    ]
    html = (
        "<ul>" + "".join(f"<li><a href='{h}'>{label}</a></li>" for h, label in links) + "</ul>"
    ).encode()
    docs = ca.parse_listing(html, 1)
    assert [d["meeting"] for d in docs] == [None, "2026-06-01"]
    assert not ca.file_url_ok("https://www.haskellcountytx.gov/upload/page/7690/a%2Fb.pdf")
    with pytest.raises(SourceParseError):
        ca.parse_listing(b"<a href='/elsewhere.pdf'>x</a>", 5)


def test_occ_hyphen_in_a_company_name_does_not_split_and_empty_lists_fail():
    parsed = oc.parse_label("ACME - North LLC - Tulsa County - October 15, 2026")
    assert parsed["company"] == "ACME - North LLC" and parsed["county"] == "Tulsa"
    both = oc.parse_label("Emerald Inc – Battles 112 – Pittsburg County - July 10, 2026")
    assert both["project"] == "Battles 112" and both["company"] == "Emerald Inc"
    foreign = occ_html([("https://evil.example/x.pdf", "A - B County - May 1, 2026")])
    for body in (occ_html([]), foreign):
        origin = occ_origin()
        origin.put(OCC_URL, body)
        with pytest.raises(SourceParseError):
            listing(oc, origin)


def test_occ_lists_after_the_first_ul_are_read():
    base = occ_html(occ_links()).decode()
    second = (
        '<ul><li><a href="/content/dam/ok/en/occ/documents/pu/data-center-act/'
        'notice-of-intent-submissions/2026-11-01-acme-osage-county.pdf">'
        "Acme LLC - Osage County - November 1, 2026</a></li></ul>"
    )
    origin = occ_origin()
    origin.put(OCC_URL, base.replace("</ul>", "</ul>" + second, 1).encode())
    assert len(listing(oc, origin)) == 3


def test_parser_handles_nesting_unclosed_cells_and_spans():
    html = (
        b"<table><tr><th>A</th><th>B</th></tr>"
        b"<tr><td>1<td>2<tr><td>3<td>4</table>"
        b"<table><tr><td>x<table><tr><td>inner</td></tr></table>y</td><td>z</td></tr></table>"
        b"<table><tr><td colspan='2'>wide</td></tr></table>"
    )
    first, second, third = more.parse_tables(html)
    assert [[c.text for c in r] for r in first] == [["A", "B"], ["1", "2"], ["3", "4"]]
    assert [c.text for c in second[0]] == ["xy", "z"]
    assert third[0][0].span == 2


def test_registry_shifted_or_misaligned_rows_are_skipped_not_shifted():
    shifted = registry_row(
        "Shifted",
        "01/01/2025",
        "A LLC",
        "Some Name",
        "B LLC",
        "DC111111-OC1",
        "C LLC",
        "DC111111-OP1",
    )
    short_bad = (
        "<tr><th>Short</th><td>01/01/2025</td><td>A LLC</td><td>DC222222-OW1</td><td>B LLC</td>"
        "<td>DC222222-OC1</td><td>C LLC</td></tr>"
    )
    named = registry_row(
        "DC333333-OW1",
        "01/01/2025",
        "A LLC",
        "DC333333-OW1",
        "B LLC",
        "DC333333-OC1",
        "C",
        "DC333333-OP1",
    )
    rows, skipped = cr.parse_registry(registry_html([shifted, short_bad, named, DC_ROW], [LD_ROW]))
    assert [r["root"] for r in rows] == ["DC046706", "LD549949"]
    assert skipped["unreadable_row"] == 3
    many_good = [
        registry_row(
            f"Site {n}",
            "01/01/2025",
            "A LLC",
            f"DC9{n:05d}-OW1",
            "A",
            f"DC9{n:05d}-OC1",
            "A",
            f"DC9{n:05d}-OP1",
        )
        for n in range(30)
    ]
    origin = registry_origin(dc_rows=[shifted, *many_good], ld_rows=[LD_ROW])
    result = listing(cr, origin)
    assert result["partial"] is True
    assert result["rejected_records"][0]["error_code"] == "unreadable_row"
    many = registry_origin(dc_rows=[shifted, shifted, shifted, DC_ROW], ld_rows=[LD_ROW])
    with pytest.raises(SourceParseError, match="skipped too many"):
        listing(cr, many)


def test_registry_duplicate_roots_are_chosen_independent_of_page_order():
    a = registry_row(
        "Zeta",
        "01/01/2025",
        "A LLC",
        "DC555555-OW1",
        "A LLC",
        "DC555555-OC1",
        "A LLC",
        "DC555555-OP1",
    )
    b = registry_row(
        "Alpha",
        "01/01/2025",
        "B LLC",
        "DC555555-OW1",
        "B LLC",
        "DC555555-OC1",
        "B LLC",
        "DC555555-OP1",
    )
    first, _ = cr.parse_registry(registry_html([a, b], [LD_ROW]))
    second, skipped = cr.parse_registry(registry_html([b, a], [LD_ROW]))
    assert first == second and skipped["duplicate"] == 1
    assert next(r for r in first if r["root"] == "DC555555")["name"] == "Alpha"


def test_anchors_read_single_quoted_hrefs():
    found = more.anchors(b"<a class=x href='/a b.pdf'>One</a><a href=\"/c.pdf\">Two</a>")
    assert found == [("/a b.pdf", "One"), ("/c.pdf", "Two")]


def test_evidence_uses_the_known_offset_not_the_first_occurrence():
    page = "five acre-feet. five acre-feet."
    first = more.evidence(5, "documented", 1, "five acre-feet.", page)
    second = more.evidence(5, "documented", 1, "five acre-feet.", page, start=16)
    assert first["span"] == [0, 15] and second["span"] == [16, 31]
    assert more.evidence(5, "documented", 1, "five acre-feet.", page, start=3) is None
