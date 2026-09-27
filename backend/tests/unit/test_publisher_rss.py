from copy import deepcopy

import httpx
import pytest

from gridlens.domain.collection_watch import matched_terms
from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.publisher_rss import retrieve
from gridlens.ingestion.registry import load_registry

SOURCE = next(row for row in load_registry() if row["id"] == "mjbizdaily-news")


def item(
    *,
    title="A company announces a cultivation facility",
    link="https://mjbizdaily.com/news/item/",
    guid="first-guid",
    date_text="Fri, 25 Sep 2026 10:00:00 -0400",
    description="<p>Short <b>publisher</b> summary</p>",
):
    return (
        "<item>"
        f"<title>{title}</title><link>{link}</link><guid>{guid}</guid>"
        f"<pubDate>{date_text}</pubDate><description>{description}</description>"
        "<content:encoded><![CDATA[This body must never be retained]]></content:encoded>"
        "</item>"
    )


def run(xml: str | bytes, source=None):
    selected = deepcopy(source or SOURCE)
    body = xml.encode() if isinstance(xml, str) else xml
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "application/rss+xml; charset=utf-8"},
                content=body,
            )
        )
    )
    try:
        return retrieve(selected, client)
    finally:
        client.close()


def feed(*items: str) -> str:
    return (
        '<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>'
        + "".join(items)
        + "</channel></rss>"
    )


def test_rss_extracts_only_bounded_summary_and_uses_canonical_link_identity():
    record = run(feed(item(guid="changing-guid")))[0]
    assert record["document_number"] == "https://mjbizdaily.com/news/item/"
    assert record["publication_date"] == "2026-09-25"
    assert record["extraction_location"].endswith("-0400")
    assert record["abstract"] == "Short publisher summary"
    assert "This body" not in str(record)
    corrected_guid = run(feed(item(guid="corrected-guid")))[0]
    assert corrected_guid["document_number"] == record["document_number"]
    assert corrected_guid["source_hash"] == record["source_hash"]


def test_rss_summary_is_capped_at_500_characters():
    record = run(feed(item(description="x" * 700)))[0]
    assert len(record["abstract"]) == 500


def test_atom_uses_alternate_link_and_hashes_long_identity():
    long_link = "https://mjbizdaily.com/news/" + "a" * 250
    atom = (
        "<feed xmlns='http://www.w3.org/2005/Atom'><entry><title>Long item</title>"
        "<link rel='self' href='https://mjbizdaily.com/feed/'/>"
        f"<link rel='alternate' href='{long_link}'/><published>2026-09-25T12:00:00Z</published>"
        "<summary>Short summary</summary></entry></feed>"
    )
    record = run(atom)[0]
    assert len(record["document_number"]) == len("sha256:") + 64
    assert record["html_url"] == long_link


@pytest.mark.parametrize(
    "xml, message",
    [
        ("<rss><channel><item>", "malformed"),
        ("<rss><channel></channel></rss>", "no items"),
        (
            "<!DOCTYPE rss [<!ENTITY x 'unsafe'>]><rss><channel>" + item() + "</channel></rss>",
            "unsafe",
        ),
        (feed(item(link="https://attacker.example/item/")), "off-host"),
        (feed(item(date_text="Fri, 25 Sep 2099 10:00:00 -0400")), "future"),
        (feed(item(title="One"), item(title="Two")), "conflicting duplicate"),
        (
            "<feed xmlns='http://www.w3.org/2005/Atom'><link rel='next' href='https://mjbizdaily.com/page/2'/></feed>",
            "continuation",
        ),
    ],
)
def test_rss_rejects_malformed_or_unsafe_snapshots(xml: str, message: str):
    with pytest.raises(SourceParseError, match=message):
        run(xml)


def test_rss_rejects_oversize_payload():
    source = deepcopy(SOURCE)
    source["query"]["max_response_bytes"] = 1024
    with pytest.raises(SourceParseError, match="exceeds"):
        run(feed(item(description="x" * 1300)), source)


def test_rss_rejects_utf16_doctype_before_xml_parser():
    unsafe = ("<!DOCTYPE rss [<!ENTITY x 'expanded'>]>" + feed(item())).encode("utf-16")
    with pytest.raises(SourceParseError, match="UTF-8"):
        run(unsafe)


def test_cannabis_watch_is_a_topic_match_without_a_business_or_power_claim():
    assert matched_terms("Cultivators discuss insurance", "") == ["cultivation-related"]
    assert matched_terms("State licensing for cannabis facilities", "") == [
        "licensing",
        "facilities",
    ]
    assert matched_terms("Cannabis insurance outlook", "") == []
