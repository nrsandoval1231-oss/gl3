from datetime import date
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.taylor_newsflash import (
    _archive_interval,
    _article,
    _evidence_location,
    retrieve,
)
from gridlens.ingestion.registry import load_registry

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_archived_revision_identity_and_category_are_retained():
    record = _article(
        (FIXTURES / "taylor-newsflash-2079-3434.html").read_bytes(),
        "https://taylortx.gov/m/NewsFlash/Archive/Item/2079?arcId=3434",
        "2079",
        "3434",
    )
    assert record["document_number"] == "2079:arcId=3434"
    assert record["category"] == "Development Notices"
    assert record["publication_date"] == "2026-08-07"
    assert len(record["source_hash"]) == 64
    assert record["extraction_location"] == "header/body; category: Development Notices"
    assert len(record["extraction_location"]) <= 100


def test_missing_header_posted_date_cannot_use_related_item_date():
    source = Path(__file__).resolve().parents[1] / "fixtures" / "taylor-newsflash-2032.html"
    soup = BeautifulSoup(source.read_bytes(), "html.parser")
    header_date = soup.select_one("#article-header-date")
    assert header_date is not None
    header_date.decompose()
    footer = soup.select_one("main .article-footer")
    assert footer is not None
    footer.append(BeautifulSoup("<p>Related item date: 04/22/2026</p>", "html.parser"))
    with pytest.raises(SourceParseError, match="publication date is missing"):
        _article(
            str(soup).encode(),
            "https://taylortx.gov/m/NewsFlash/Home/Detail/2032",
            "2032",
            None,
        )

    ordinary = _article(
        source.read_bytes(),
        "https://taylortx.gov/m/NewsFlash/Home/Detail/2032",
        "2032",
        None,
    )
    assert ordinary["publication_date"] == "2026-04-21"


def test_evidence_location_fails_instead_of_truncating_overlong_category():
    with pytest.raises(SourceParseError, match="field bound"):
        _evidence_location("a" * 100)


def test_unknown_category_and_incomplete_article_fail_closed():
    with pytest.raises(SourceParseError, match="structure is incomplete"):
        _article(b"<html><main>unexpected</main></html>", "https://taylortx.gov/x", "1", None)
    soup = BeautifulSoup(
        (FIXTURES / "taylor-newsflash-2079-3434.html").read_bytes(), "html.parser"
    )
    category = soup.select_one("main .articles-category:not(.article-footer) > .article-badge")
    assert category is not None
    category.clear()
    category.append("Unrecognized")
    unknown = _article(str(soup).encode(), "https://taylortx.gov/x", "1", None)
    assert unknown["category"] == "Unrecognized"
    missing_soup = BeautifulSoup(
        (FIXTURES / "taylor-newsflash-2079-3434.html").read_bytes(), "html.parser"
    )
    missing_soup.select_one(
        "main .articles-category:not(.article-footer) > .article-badge"
    ).decompose()
    with pytest.raises(SourceParseError, match="category badge is missing"):
        _article(str(missing_soup).encode(), "https://taylortx.gov/x", "1", None)
    ambiguous_soup = BeautifulSoup(
        (FIXTURES / "taylor-newsflash-2079-3434.html").read_bytes(), "html.parser"
    )
    badge = ambiguous_soup.select_one(
        "main .articles-category:not(.article-footer) > .article-badge"
    )
    assert badge is not None
    badge.parent.append(BeautifulSoup("<span class='article-badge'>Second</span>", "html.parser"))
    with pytest.raises(SourceParseError, match="ambiguous"):
        _article(str(ambiguous_soup).encode(), "https://taylortx.gov/x", "1", None)


def test_explicit_news_category_is_retained_as_non_target_crosspost():
    raw = (FIXTURES / "taylor-newsflash-2079-3434.html").read_bytes()
    soup = BeautifulSoup(raw, "html.parser")
    category = soup.select_one("main .articles-category:not(.article-footer) > .article-badge")
    assert category is not None
    category.clear()
    category.append("News")
    record = _article(
        str(soup).encode(),
        "https://taylortx.gov/m/NewsFlash/Home/Detail/2069",
        "2069",
        None,
    )
    assert record["category"] == "News"
    assert record["document_number"] == "2069"
    from gridlens.domain.taylor_planning import interpret_taylor_planning

    assert interpret_taylor_planning({**record, "source_geography": "Taylor, Texas"}) is None


def test_mixed_category_archive_accounts_for_all_rows_and_only_target_can_interpret():
    source = next(item for item in load_registry() if item["id"] == "taylor-development-newsflash")
    source = {**source, "query": {**source["query"], "max_pages": 1}}
    target_article = (FIXTURES / "taylor-newsflash-2079-3434.html").read_bytes()
    news_soup = BeautifulSoup(target_article, "html.parser")
    category = news_soup.select_one(
        "main .articles-category:not(.article-footer) > .article-badge"
    )
    assert category is not None
    category.clear()
    category.append("News")
    news_article = str(news_soup).encode()
    unrelated_article = (
        Path(__file__).resolve().parents[1] / "fixtures" / "taylor-newsflash-1839-3427.html"
    ).read_bytes()
    archive_rows = [("2079", "3434", "08/07/2026"), ("1839", "3427", "11/21/2024")]
    row_html = "".join(
        f"<tr><td><a href='/m/NewsFlash/Archive/Item/{article_id}?arcId={arc_id}'>x</a></td>"
        f"<td>{day} 12:00 AM</td><td>{day} 12:00 AM</td></tr>"
        for article_id, arc_id, day in archive_rows
    )
    archive_bytes = (
        "<div>1–2 of 2</div><table id='archiveTable'><tbody>"
        + row_html
        + "</tbody></table><button aria-label='Next Page' disabled></button>"
    ).encode()
    category_html = b"<a href='/m/NewsFlash/Home/Detail/2069'>Crosspost</a>"

    def response(request):
        if request.url.params.get("cat") == "30":
            return httpx.Response(200, content=category_html)
        if request.url.params.get("cat") == "31":
            return httpx.Response(200, content=category_html)
        if "/Home/Detail/2069" in str(request.url):
            return httpx.Response(200, content=news_article)
        if "/Archive/Item/1839" in str(request.url):
            return httpx.Response(200, content=unrelated_article)
        if "/Archive/Item/2079" in str(request.url):
            return httpx.Response(200, content=target_article)
        return httpx.Response(200, content=archive_bytes)

    client = httpx.Client(transport=httpx.MockTransport(response))
    records = retrieve(source, client, today=date(2026, 9, 28))
    assert [record["publication_date"] or "" for record in records] == sorted(
        record["publication_date"] or "" for record in records
    )
    assert any(
        record["document_number"] == "2069" and record["category"] == "News"
        for record in records
    )
    by_id = {record["document_number"]: record for record in records}
    assert set(by_id) == {"2069", "2079:arcId=3434", "1839:arcId=3427"}
    assert (
        by_id["1839:arcId=3427"]["category"]
        == "Wellness and Recreation Center Study Project Updates"
    )
    for record in records:
        assert len(record["extraction_location"]) <= 100
        assert record["category"] in record["extraction_location"]
    assert "table dates" in by_id["1839:arcId=3427"]["extraction_location"]
    assert by_id["1839:arcId=3427"]["publication_date"] == "2024-11-21"
    assert by_id["1839:arcId=3427"]["archived_date"] == "2024-11-21"
    from gridlens.domain.taylor_planning import interpret_taylor_planning

    assert interpret_taylor_planning({**by_id["2069"], "source_geography": "Taylor, Texas"}) is None
    assert interpret_taylor_planning(
        {**by_id["1839:arcId=3427"], "source_geography": "Taylor, Texas"}
    ) is None


def test_login_response_fails_closed_for_enabled_source():
    source = next(item for item in load_registry() if item["id"] == "taylor-development-newsflash")
    assert source["enabled"] is True
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="<form id='user-login-form'></form>")
        )
    )
    with pytest.raises(SourceParseError, match="login page"):
        retrieve(source, client)


def test_archive_interval_rolls_forward_with_configured_overlap_and_fixed_cutoff():
    query = {"archive_window_days": 59, "archive_overlap_days": 7}
    assert _archive_interval(query, date(2026, 9, 28)) == ("2026-07-25", "2026-09-28")
    assert _archive_interval(query, date(2026, 9, 29)) == ("2026-07-26", "2026-09-29")
