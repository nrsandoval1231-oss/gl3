"""Real-source regression for bounded, complete GovInfo notice capture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from gridlens.ingestion.adapters.govinfo_pdf import retrieve_companion

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "govinfo-complete-notice"
PDF_PATH = FIXTURE_DIR / "FR-2024-12869.pdf"
PROVENANCE_PATH = FIXTURE_DIR / "provenance.json"


def test_retains_complete_real_notice_and_equipment_sentence_with_native_boundaries():
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    content = PDF_PATH.read_bytes()
    assert hashlib.sha256(content).hexdigest() == provenance["sha256"]
    assert len(content) == provenance["response_bytes"]

    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            content=content,
            headers={"content-type": "application/pdf"},
        )

    record = {
        "document_number": provenance["document_number"],
        "title": provenance["official_title"],
        "publication_date": provenance["publication_date"],
        "pdf_url": provenance["source_url"],
    }
    with httpx.Client(transport=httpx.MockTransport(respond), timeout=15.0) as client:
        rows = retrieve_companion(record, client)

    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == provenance["source_url"]
    assert len(rows) == 1
    row = rows[0]
    text = row["abstract"]

    # This equipment evidence occurs after the adapter's former 1,200-char cut.
    assert (
        "Install one new electric motor driven compressor unit with a rating of 18,340 hp." in text
    )
    assert text.index("18,340 hp") > 1200
    assert "Natural Gas Pipeline Company of America LLC" in text
    assert "Compressor Station 302 in Montgomery County, Texas" in text
    assert "FR Doc. 2024–12869" not in text
    assert row["extraction_location"] == "GovInfo PDF pages 1-2"

    # The PDF starts with the tail of an earlier Federal Register notice. Capture
    # begins at this record's complete title and ends at this record's own footer.
    assert text.startswith(f"[GovInfo PDF page 1] {provenance['official_title']}")
    assert "FR Doc. 2024–12866" not in text
    assert "Commission Information Collection Activities (FERC–716) Comment Request" not in text
    assert "Dated: June 6, 2024." in text
    assert row["content_hash"] == provenance["sha256"]
    assert row["published_at"] == provenance["publication_date"]
