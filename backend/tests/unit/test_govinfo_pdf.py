from datetime import date
from io import BytesIO

import httpx
import pytest

from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.adapters.govinfo_pdf import retrieve_companion


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
                "UNRELATED PRIOR NOTICE. AMS document body. New Mexico; Roca Honda Mine Project "
                "Proposed development includes dewatering wells and ventilation shafts. "
                "FR Doc. 2026-18765 Filed 9-13-26; 8:45 am"
            )
        ]


def fr_record() -> dict[str, str]:
    return {
        "document_number": "2026-18765",
        "title": "Mount Taylor Ranger District; New Mexico; Roca Honda Mine Project",
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
            {"is_encrypted": False, "pages": [FakePage("Roca Honda Mine Project page body")]},
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
