from datetime import date
from pathlib import Path

import httpx
import pytest

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.nc_commerce import retrieve
from gridlens.ingestion.registry import load_registry


def listing_row(path: str, title: str, published: str) -> str:
    return f"""
    <div class="views-row">
      <div class="views-field-title"><h2><a href="{path}">{title}</a></h2></div>
      <div class="views-field-field-release-date">
        <span property="dc:date" content="{published}"></span>
      </div>
      <div class="views-field-body"><div class="field-content">Listing excerpt.</div></div>
    </div>"""


def article(title: str, published: str, paragraphs: str, path: str) -> str:
    return f"""
    <html><head><title>{title} | NC Commerce</title>
      <link rel="canonical" href="{path}"></head><body>
      <h1 class="node__title">{title}</h1>
      <div class="first-published"><span property="dc:date" content="{published}"></span></div>
      <article><div class="field--name-body">{paragraphs}</div></article>
    </body></html>"""


def test_traverses_complete_window_and_keeps_distinct_article_ids():
    source = next(item for item in load_registry() if item["id"] == "nc-commerce")
    today = date.today().isoformat()
    second_page = "https://www.commerce.nc.gov/news/press-releases?page=1"
    paths = [
        "/news/press-releases/2026/09/09/same-title-fayetteville",
        "/news/press-releases/2026/09/09/same-title-beaufort",
    ]
    requested = []

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == "/news/press-releases":
            if request.url.params.get("page") is None:
                body = (
                    '<div class="view-content">'
                    + listing_row(paths[1], "Same Title", today)
                    + "</div>"
                )
                return httpx.Response(
                    200,
                    text=f'<html>{body}<a rel="next" href="{second_page}">Next</a></html>',
                )
            body = (
                '<div class="view-content">' + listing_row(paths[0], "Same Title", today) + "</div>"
            )
            return httpx.Response(200, text=f"<html>{body}</html>")
        path = request.url.path
        return httpx.Response(
            200,
            text=article(
                "Same Title",
                today,
                "<p>The company will expand operations in Cumberland County.</p>",
                path,
            ),
        )

    rows = retrieve(source, httpx.Client(transport=httpx.MockTransport(respond)))
    assert {row["document_number"] for row in rows} == set(paths)
    assert len({row["document_number"] for row in rows}) == 2
    assert rows[0]["extraction_location"] == "article body paragraphs 1-2"
    assert len(rows[0]["source_hash"]) == 64
    assert len(requested) == 4


def test_fails_when_declared_window_is_not_complete():
    source = next(item for item in load_registry() if item["id"] == "nc-commerce")
    source = {
        **source,
        "query": {
            **source["query"],
            "window_days": 90,
            "max_pages": 1,
        },
    }
    html = (
        '<html><div class="view-content">'
        + listing_row(
            "/news/press-releases/2026/09/25/example", "Example", date.today().isoformat()
        )
        + '</div><a rel="next" href="/news/press-releases?page=1">Next</a></html>'
    )
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html))
    )
    with pytest.raises(SourceParseError, match="exceeds 1 listing pages"):
        retrieve(source, client)


@pytest.mark.parametrize(
    "html, error",
    [
        ('<html><form id="user-login-form"></form></html>', "login"),
        ("<html><h1>Unexpected response</h1></html>", "no article rows"),
    ],
)
def test_login_and_empty_listing_fail_visibly(html: str, error: str):
    source = next(item for item in load_registry() if item["id"] == "nc-commerce")
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html))
    )
    with pytest.raises(SourceParseError, match=error):
        retrieve(source, client)


def test_oversized_listing_response_fails_before_parsing():
    source = next(item for item in load_registry() if item["id"] == "nc-commerce")
    source = {
        **source,
        "query": {**source["query"], "max_response_bytes": 1024, "max_run_bytes": 2048},
    }
    body = b"<html><body>" + (b"x" * 1200) + b"</body></html>"
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    )
    with pytest.raises(SourceParseError, match="exceeds 1024 bytes"):
        retrieve(source, client)


def test_live_probe_article_parses_without_becoming_a_fixture_or_runtime_seed():
    root = Path(__file__).parents[3]
    probe = root / ".artifacts" / "source-probes" / "nc-detail.html"
    if not probe.exists():
        pytest.skip("local access probe is not present")
    html = probe.read_bytes()
    title = (
        "National Steel Fabrication Company Plans a $19 Million Manufacturing Expansion "
        "in Fayetteville"
    )
    expected = {
        "title": title,
        "publication_date": "2026-09-09",
    }
    from gridlens.ingestion.adapters.nc_commerce import _parse_article

    result = _parse_article(
        html,
        expected,
        "https://www.commerce.nc.gov/news/press-releases/2026/09/09/national-steel-fabrication-company-plans-19-million-manufacturing-expansion-fayetteville",
    )
    assert "Cumberland County" in result["abstract"]
    assert result["source_hash"]
