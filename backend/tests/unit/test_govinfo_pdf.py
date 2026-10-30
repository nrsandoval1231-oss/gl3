from datetime import date
from io import BytesIO

import httpx
import pytest

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.govinfo_pdf import retrieve_companion

TITLE = "Mount Taylor Ranger District; New Mexico; Roca Honda Mine Project"
TARGET_TITLE = "Mount Taylor Ranger District New Mexico Roca Honda Mine Project"


class FakePage:
    def __init__(self, text: str):
        self.text = text

    def extract_text(self) -> str:
        return self.text


class FakeReader:
    def __init__(self, _: BytesIO, strict: bool):
        assert strict is True
        self.is_encrypted = False
        self.pages = [
            FakePage(
                "UNRELATED PRIOR NOTICE. AMS document body. "
                "Mount Taylor Ranger District; New Mexico; Roca Honda Mine Project "
                "Proposed development includes dewatering wells and ventilation shafts. "
                "FR Doc. 2026-18765 Filed 9-13-26; 8:45 am"
            )
        ]


def fr_record() -> dict[str, str]:
    return {
        "document_number": "2026-18765",
        "title": TITLE,
        "publication_date": "2026-09-14",
        "pdf_url": "https://www.govinfo.gov/content/pkg/FR-2026-09-14/pdf/2026-18765.pdf",
    }


def test_extracts_page_cited_excerpt_after_target_title_and_matches_document_footer(monkeypatch):
    import gridlens.ingestion.adapters.govinfo_pdf as adapter

    monkeypatch.setattr(adapter, "PdfReader", FakeReader)
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=b"%PDF-test", headers={"content-type": "application/pdf"}
            )
        )
    )
    rows = retrieve_companion(fr_record(), client)
    assert len(rows) == 1
    assert rows[0]["extraction_location"] == "GovInfo PDF page 1"
    assert "UNRELATED PRIOR NOTICE" not in rows[0]["abstract"]
    assert "dewatering wells" in rows[0]["abstract"]
    assert len(rows[0]["content_hash"]) == 64
    assert rows[0]["published_at"] == date(2026, 9, 14).isoformat()


def test_rejects_mismatched_pdf_identity_before_download():
    record = fr_record()
    record["pdf_url"] = record["pdf_url"].replace("2026-18765.pdf", "2026-18766.pdf")
    with pytest.raises(SourceParseError, match="does not match"):
        retrieve_companion(record)


def test_rejects_non_pdf_or_missing_target_footer(monkeypatch):
    import gridlens.ingestion.adapters.govinfo_pdf as adapter

    monkeypatch.setattr(
        adapter,
        "PdfReader",
        lambda *_args, **_kwargs: type(
            "Reader",
            (),
            {
                "is_encrypted": False,
                "pages": [FakePage(TARGET_TITLE + " page body")],
            },
        )(),
    )
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=b"%PDF-test", headers={"content-type": "application/pdf"}
            )
        )
    )
    with pytest.raises(SourceParseError, match="lacks the matching"):
        retrieve_companion(fr_record(), client)

    bad_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, text="login page", headers={"content-type": "text/html"}
            )
        )
    )
    with pytest.raises(SourceParseError, match="not a PDF"):
        retrieve_companion(fr_record(), bad_client)


def _client() -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=b"%PDF-test", headers={"content-type": "application/pdf"}
            )
        )
    )


def _reader_with_pages(monkeypatch, *texts: str) -> None:
    import gridlens.ingestion.adapters.govinfo_pdf as adapter

    class Reader:
        def __init__(self, _: BytesIO, strict: bool):
            assert strict is True
            self.is_encrypted = False
            self.pages = [FakePage(text) for text in texts]

    monkeypatch.setattr(adapter, "PdfReader", Reader)


def _target_start() -> str:
    return f"Header; {TARGET_TITLE}. Notice body. "


def test_collects_full_multipage_notice_and_stops_at_matching_footer(monkeypatch):
    _reader_with_pages(
        monkeypatch,
        "Preceding notice FR Doc. 2026-18764 Filed 9-13-26; 8:45 am. "
        + _target_start()
        + ("a long bounded paragraph " * 100)
        + "18,340 hp engineering sentence.",
        "Continuation with final target paragraph. "
        "FR Doc. 2026-18765 Filed 9-13-26; 8:45 am. NEXT NOTICE TEXT.",
    )
    rows = retrieve_companion(fr_record(), _client())
    abstract = rows[0]["abstract"]

    assert rows[0]["extraction_location"] == "GovInfo PDF pages 1-2"
    assert "18,340 hp engineering sentence" in abstract
    assert "Preceding notice" not in abstract
    assert "FR Doc. 2026-18765" not in abstract
    assert "NEXT NOTICE TEXT" not in abstract
    assert "[GovInfo PDF page 1]" in abstract
    assert "[GovInfo PDF page 2]" in abstract
    assert len(abstract) > 1200


def test_rejects_text_over_configured_notice_limit(monkeypatch):
    import gridlens.ingestion.adapters.govinfo_pdf as adapter

    monkeypatch.setattr(adapter, "MAX_NOTICE_CHARS", 100)
    _reader_with_pages(
        monkeypatch,
        _target_start() + ("notice text " * 30) + "FR Doc. 2026-18765 Filed 9-13-26; 8:45 am",
    )

    with pytest.raises(SourceParseError, match="exceeds the text character bound"):
        retrieve_companion(fr_record(), _client())


def test_rejects_foreign_footer_before_matching_target_footer(monkeypatch):
    _reader_with_pages(
        monkeypatch,
        _target_start() + "body. FR Doc. 2026-18764 Filed 9-13-26; 8:45 am",
        "FR Doc. 2026-18765 Filed 9-13-26; 8:45 am",
    )

    with pytest.raises(SourceParseError, match="different FR document footer"):
        retrieve_companion(fr_record(), _client())


def test_rejects_ambiguous_full_title_starts(monkeypatch):
    _reader_with_pages(
        monkeypatch,
        _target_start() + "body. " + TARGET_TITLE + ". FR Doc. 2026-18765 Filed 9-13-26; 8:45 am",
    )

    with pytest.raises(SourceParseError, match="ambiguous target title starts"):
        retrieve_companion(fr_record(), _client())


def test_rejects_blank_or_unextractable_page_inside_target_notice(monkeypatch):
    _reader_with_pages(
        monkeypatch,
        _target_start() + "first page body.",
        "   ",
        "FR Doc. 2026-18765 Filed 9-13-26; 8:45 am",
    )

    with pytest.raises(SourceParseError, match="blank inside the target notice"):
        retrieve_companion(fr_record(), _client())

    class BrokenPage:
        def extract_text(self):
            raise RuntimeError("unreadable page")

    import gridlens.ingestion.adapters.govinfo_pdf as adapter

    class Reader:
        is_encrypted = False
        pages = [FakePage(_target_start()), BrokenPage()]

        def __init__(self, _: BytesIO, strict: bool):
            assert strict is True

    monkeypatch.setattr(adapter, "PdfReader", Reader)
    with pytest.raises(SourceParseError, match="extraction failed"):
        retrieve_companion(fr_record(), _client())


def test_requires_full_title_and_rejects_target_footer_before_title(monkeypatch):
    _reader_with_pages(
        monkeypatch,
        "Prior project notice. Roca Honda Mine Project. "
        "FR Doc. 2026-18765 Filed 9-13-26; 8:45 am. " + _target_start(),
    )

    with pytest.raises(SourceParseError, match="footer occurs before its full title"):
        retrieve_companion(fr_record(), _client())


def test_rejects_title_suffix_without_complete_full_title(monkeypatch):
    _reader_with_pages(
        monkeypatch,
        "Roca Honda Mine Project. body. FR Doc. 2026-18765 Filed 9-13-26; 8:45 am",
    )

    with pytest.raises(SourceParseError, match="footer occurs before its full title"):
        retrieve_companion(fr_record(), _client())


@pytest.mark.parametrize(
    "url",
    [
        "https://user@www.govinfo.gov/content/pkg/FR-2026-09-14/pdf/2026-18765.pdf",
        "https://www.govinfo.gov:444/content/pkg/FR-2026-09-14/pdf/2026-18765.pdf",
        "https://www.govinfo.gov/content/pkg/FR-2026-09-14/pdf/2026-18765.pdf?download=1",
        "https://www.govinfo.gov/content/pkg/FR-2026-09-14/pdf/2026-18765.pdf?",
        "https://www.govinfo.gov/content/pkg/FR-2026-09-14/pdf/2026-18765.pdf#page=1",
        "https://www.govinfo.gov/content/pkg/FR-2026-09-14/pdf/2026-18765.pdf#",
    ],
)
def test_rejects_noncanonical_pdf_urls_before_download(url):
    record = fr_record()
    record["pdf_url"] = url
    with pytest.raises(SourceParseError, match="outside the GovInfo document path"):
        retrieve_companion(record)


def test_rejects_package_date_mismatch_before_download():
    record = fr_record()
    record["pdf_url"] = record["pdf_url"].replace("FR-2026-09-14", "FR-2026-09-13")
    with pytest.raises(SourceParseError, match="package date does not match"):
        retrieve_companion(record)
