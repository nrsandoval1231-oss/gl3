"""Scanned-page OCR routing, text_source labels and the bake-off harness (no live calls)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gridlens.ingestion.parsers.permit_docs import extract_from_pages
from gridlens.ingestion.parsers.permit_docs.proposals import OcrOutcome
from gridlens.ingestion.parsers.permit_docs.text_layer import CanonicalText
from gridlens.intelligence import ocr_bakeoff
from gridlens.intelligence import permit_page_ocr as ocr
from gridlens.settings import settings

HASH = "b" * 64
OCR_TEXT = "The facility will install two (2) 1,500 hp electric motor driven compressors."
TEXT_PAGE = "Application cover letter for the permit. Contact the environmental office."
LABEL = "ocr:openai:gpt-6.1-sol"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ocr_bakeoff"


class FakeOcr:
    def __init__(self, outcome: OcrOutcome):
        self.outcome = outcome
        self.requested: list[int] = []

    def ocr_pages(self, pages: list[int], *, document_hash: str) -> OcrOutcome:
        self.requested = pages
        return self.outcome


def ok(texts: dict[int, str]) -> OcrOutcome:
    return OcrOutcome("ok", "", texts, LABEL, {"pages_failed": {}})


def test_scanned_page_is_routed_to_ocr_and_labelled():
    fake = FakeOcr(ok({2: OCR_TEXT}))
    result = extract_from_pages([TEXT_PAGE, ""], document_hash=HASH, ocr=fake)
    assert fake.requested == [2]
    assert result.ocr["status"] == "ok" and result.ocr["pages_read"] == [2]
    assert result.ocr["text_source"] == LABEL
    assert result.routes.get("scan", 0) == 0 and result.needs_ocr_pages == []
    assert result.scanned_pages == 1  # the document did have a scanned page
    row = (result.demand_rows + result.supply_rows)[0]
    assert row.text_source == LABEL and row.evidence["rating"].page == 2


def test_ocr_rows_are_retained_with_lower_trust_but_not_demand_by_default():
    result = extract_from_pages([TEXT_PAGE, ""], document_hash=HASH, ocr=FakeOcr(ok({2: OCR_TEXT})))
    assert result.demand_rows == [] and result.claims == [] and result.schedule_text == ""
    assert len(result.supply_rows) == 1
    assert any("retained, not demand" in issue for issue in result.issues)


def test_ocr_rows_feed_demand_only_when_explicitly_allowed_and_keep_the_label():
    result = extract_from_pages(
        [TEXT_PAGE, ""],
        document_hash=HASH,
        ocr=FakeOcr(ok({2: OCR_TEXT})),
        allow_ocr_demand=True,
    )
    assert len(result.claims) == 1
    entry = next(iter(result.provenance.values()))
    assert entry["text_source"] == LABEL and entry["text_trust"] == "ocr_lower_trust"
    assert entry["page"] == 2 and entry["verifier"] == "exact-span-v1"
    assert entry["fields"]["rating"]["bbox"] is None  # no geometry for OCR text


def test_text_layer_rows_are_labelled_text_layer():
    result = extract_from_pages([OCR_TEXT], document_hash=HASH)
    entry = next(iter(result.provenance.values()))
    assert entry["text_source"] == "text_layer" and entry["text_trust"] == "text_layer"
    assert entry["method"] == "deterministic-rules"


@pytest.mark.parametrize(
    "outcome",
    [
        OcrOutcome("disabled", "PERMIT_OCR_SETTING_OFF"),
        OcrOutcome("blocked", "OCR_HOST_NOT_ALLOWLISTED"),
        OcrOutcome("capped_out", "GLOBAL_DAILY_CAP_REACHED"),
        OcrOutcome("unknown", "OCR_OUTCOME_UNKNOWN"),
        OcrOutcome("failed", "OCR_NO_PAGES_READ"),
    ],
)
def test_a_failed_ocr_pass_leaves_the_scan_pages_unread_and_says_why(outcome):
    result = extract_from_pages([TEXT_PAGE, ""], document_hash=HASH, ocr=FakeOcr(outcome))
    assert result.ocr["status"] == outcome.status and result.ocr["reason"] == outcome.reason
    assert result.needs_ocr_pages == [2] and result.verified == 0
    assert any(outcome.status in issue for issue in result.issues)


def test_ocr_text_is_span_checked_like_any_other_text():
    result = extract_from_pages([TEXT_PAGE, ""], document_hash=HASH, ocr=FakeOcr(ok({2: OCR_TEXT})))
    row = (result.demand_rows + result.supply_rows)[0]
    canon = CanonicalText.from_page_texts([TEXT_PAGE, OCR_TEXT])
    for ev in row.evidence.values():
        assert canon.text[ev.start : ev.end].split() == ev.quote.split()


def test_ocr_never_overwrites_a_page_that_has_a_text_layer():
    fake = FakeOcr(ok({1: OCR_TEXT, 2: OCR_TEXT}))
    result = extract_from_pages([TEXT_PAGE, ""], document_hash=HASH, ocr=fake)
    assert fake.requested == [2]
    assert result.ocr["pages_read"] == [2]
    canon = CanonicalText.from_page_texts([TEXT_PAGE, ""])
    merged = canon.with_ocr_pages({1: OCR_TEXT, 2: OCR_TEXT}, LABEL)
    assert merged.pages[0].text == TEXT_PAGE and merged.pages[0].source == "text_layer"
    assert merged.pages[1].source == LABEL and merged.pages[1].text == OCR_TEXT
    assert canon.pages[1].text == ""  # original untouched


def test_no_ocr_object_means_no_ocr_and_unchanged_output():
    result = extract_from_pages([TEXT_PAGE, ""], document_hash=HASH)
    assert result.needs_ocr_pages == [2] and result.ocr == {}


# ---- allowlist, gates and label ----------------------------------------------------------


def test_ocr_label_names_provider_and_model():
    assert ocr.ocr_label("gpt-6.1-sol") == LABEL


def test_stage_ocr_is_off_by_default():
    assert ocr.stage_ocr_ready() == (False, "PERMIT_OCR_SETTING_OFF")
    assert ocr.allowed_hosts() == set()


def test_host_allowlist_is_narrowed_by_config_but_capped_by_code(monkeypatch):
    monkeypatch.setattr(
        settings,
        "permit_ocr_allowed_hosts",
        "www.tceq.texas.gov, evil.example.com,applications.deq.ok.gov",
    )
    assert ocr.allowed_hosts() == {"www.tceq.texas.gov", "applications.deq.ok.gov"}


def test_stage_pdf_must_match_host_source_and_retention(monkeypatch):
    monkeypatch.setattr(settings, "permit_ocr_allowed_hosts", "www.tceq.texas.gov")
    url = "https://www.tceq.texas.gov/assets/public/permitting/air/nsr/1234-ac.pdf"
    assert ocr.stage_pdf_allowed(url, "texas-tceq-nsr-pending") == (
        False,
        "OCR_SOURCE_NOT_RETENTION_ALLOWLISTED",
    )
    monkeypatch.setattr(settings, "intelligence_ocr_retention_source_ids", "texas-tceq-nsr-pending")
    assert ocr.stage_pdf_allowed(url, "texas-tceq-nsr-pending") == (
        False,
        "OCR_RETENTION_REFERENCE_MISSING",
    )
    monkeypatch.setattr(settings, "intelligence_ocr_retention_reference", "owner-policy-1")
    assert ocr.stage_pdf_allowed(url, "texas-tceq-nsr-pending") == (True, "")
    for bad in (
        "http://www.tceq.texas.gov/x.pdf",
        "https://user:pw@www.tceq.texas.gov/x.pdf",
        "https://www.tceq.texas.gov:8443/x.pdf",
        "https://applications.deq.ok.gov/x.pdf",
        "https://www.tceq.texas.gov.evil.example/x.pdf",
        "https://www.tceq.texas.gov/x.pdf#frag",
    ):
        assert not ocr.stage_pdf_allowed(bad, "texas-tceq-nsr-pending")[0], bad


def test_a_disabled_stage_ocr_never_reaches_the_ledger():
    # No DB, key or settings: the gate answers before any session is opened.
    fake_pdf = ocr.StagePdfOcr(
        pdf_path="missing.pdf", source_url="https://www.tceq.texas.gov/x.pdf", source_id="s"
    )
    outcome = fake_pdf.ocr_pages([1], document_hash=HASH)
    assert (outcome.status, outcome.reason) == ("disabled", "PERMIT_OCR_SETTING_OFF")


# ---- bake-off harness --------------------------------------------------------------------


def test_bakeoff_scores_precision_recall_and_per_dollar():
    scores = ocr_bakeoff.run_bakeoff(FIXTURES / "gold_set.json", FIXTURES / "recordings.json")
    by_name = {s.provider: s for s in scores}
    assert set(by_name) == {"openai-vision", "textract", "mistral-ocr"}
    openai = by_name["openai-vision"]
    assert (openai.precision, openai.recall, openai.true_positive) == (1.0, 1.0, 4)
    assert str(openai.total_cost_usd) == "0.036"
    textract = by_name["textract"]
    assert (textract.precision, textract.recall) == (1.0, 0.75)  # "l,500" misread loses a row
    assert by_name["mistral-ocr"].f1_per_dollar > textract.f1_per_dollar > openai.f1_per_dollar
    assert scores[0].provider == "mistral-ocr"  # ranked by F1 per dollar


def test_bakeoff_reports_missing_pages_and_has_no_live_adapter():
    gold = json.loads((FIXTURES / "gold_set.json").read_text())
    provider = ocr_bakeoff.RecordedProvider(
        "partial", {"s01": "nothing here"}, ocr_bakeoff.Decimal(1)
    )
    score = ocr_bakeoff.score_provider(provider, gold["pages"])
    assert score.missing_pages == ["s02", "s03"] and score.pages == 1
    assert score.true_positive == 0 and score.recall == 0.0
    source = Path(ocr_bakeoff.__file__).read_text()
    assert "import httpx" not in source and "requests" not in source and "boto3" not in source


def test_bakeoff_markdown_marks_prices_unverified():
    scores = ocr_bakeoff.run_bakeoff(FIXTURES / "gold_set.json", FIXTURES / "recordings.json")
    text = ocr_bakeoff.render_markdown(scores)
    assert "unverified" in text and text.count("|") > 20
