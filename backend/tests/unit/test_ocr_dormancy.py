import base64
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from gridlens.ingestion.adapters import govinfo_scan
from gridlens.ingestion.service import _merge_source_link_provenance
from gridlens.intelligence.scanned_pdf_ocr import (
    _ocr_configuration_ready,
    _preflight_context_digest,
    _validate_source,
    scanned_pdf_ocr_availability,
)
from gridlens.settings import settings

URL = "https://www.govinfo.gov/content/pkg/FR-2026-09-14/pdf/2026-18765.pdf"


def test_real_fr_pdf_companion_uses_byte_hash_separate_from_parent_semantic_hash(monkeypatch):
    source_id = "federal-register-eis"
    monkeypatch.setattr(settings, "intelligence_ocr_retention_source_ids", source_id)
    monkeypatch.setattr(settings, "intelligence_ocr_retention_reference", "approved-policy-ref")
    evidence = SimpleNamespace(content_hash="a" * 64, url=URL)
    observation = SimpleNamespace(content_hash="b" * 64, external_id="2026-18765", id=uuid4())
    source = SimpleNamespace(id=source_id, enabled=True, registry_enabled=True)

    _validate_source(evidence, observation, source)

    with pytest.raises(ValueError, match="document ID"):
        _validate_source(
            evidence,
            SimpleNamespace(**{**observation.__dict__, "external_id": "2026-00001"}),
            source,
        )


def test_positive_preflight_cap_is_insufficient_without_verified_count_cost_bound(monkeypatch):
    monkeypatch.setattr(settings, "intelligence_enabled", True)
    monkeypatch.setattr(settings, "intelligence_mode", "advisory")
    monkeypatch.setattr(settings, "intelligence_ocr_enabled", True)
    monkeypatch.setattr(settings, "intelligence_ocr_vision_enabled", True)
    monkeypatch.setattr(settings, "intelligence_ocr_preflight_enabled", True)
    monkeypatch.setattr(settings, "intelligence_ocr_preflight_max_cost_usd", Decimal("0.10"))
    monkeypatch.setattr(settings, "intelligence_ocr_preflight_cost_bound_verified", False)
    monkeypatch.setattr(settings, "intelligence_ocr_preflight_cost_reference", "")

    assert _ocr_configuration_ready() == (False, "OCR_PREFLIGHT_COST_BOUND_UNVERIFIED")

    monkeypatch.setattr(settings, "intelligence_ocr_preflight_cost_bound_verified", True)
    monkeypatch.setattr(settings, "intelligence_ocr_preflight_cost_reference", "operator-proof-1")
    reference_bound = _preflight_context_digest("pinned-model-a", "c" * 64)
    monkeypatch.setattr(settings, "intelligence_ocr_preflight_cost_reference", "operator-proof-2")
    assert _preflight_context_digest("pinned-model-a", "c" * 64) != reference_bound
    assert _preflight_context_digest("pinned-model-b", "c" * 64) != reference_bound


def test_source_link_merge_preserves_private_write_once_capture():
    capture = {"data_base64": base64.b64encode(b"%PDF-stub").decode("ascii")}
    current = {govinfo_scan.CAPTURE_KEY: capture, "stable": {"keep": True}}
    merged = _merge_source_link_provenance(current, {"raw_source_links": {"pdf": [URL]}})
    assert merged[govinfo_scan.CAPTURE_KEY] == capture
    assert merged["stable"] == {"keep": True}
    assert merged["raw_source_links"]["pdf"] == [URL]


def test_ocr_controls_are_dormant_with_all_off_zero_and_empty_allowlists(monkeypatch):
    for name, value in {
        "intelligence_enabled": False,
        "intelligence_mode": "disabled",
        "intelligence_ocr_enabled": False,
        "intelligence_ocr_preflight_enabled": False,
        "intelligence_ocr_preflight_cost_bound_verified": False,
        "intelligence_ocr_preflight_cost_reference": "",
        "intelligence_ocr_vision_enabled": False,
        "intelligence_ocr_retention_source_ids": "",
        "intelligence_ocr_retention_reference": "",
        "intelligence_ocr_model": "",
        "intelligence_ocr_priced_model_id": "",
        "intelligence_ocr_pricing_verified": False,
        "intelligence_ocr_input_usd_per_million": Decimal("0"),
        "intelligence_ocr_output_usd_per_million": Decimal("0"),
        "intelligence_ocr_max_output_tokens": 0,
        "intelligence_ocr_preflight_max_cost_usd": Decimal("0"),
        "intelligence_ocr_max_call_usd": Decimal("0"),
        "intelligence_enabled_contracts": "",
        "openai_api_key": None,
    }.items():
        monkeypatch.setattr(settings, name, value)
    for scope in ("global", "provider", "model", "source", "project"):
        for period in ("daily", "monthly"):
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_calls", 0)
            monkeypatch.setattr(settings, f"intelligence_{scope}_{period}_usd", Decimal("0"))
    monkeypatch.setattr(settings, "intelligence_max_active_calls", 0)
    monkeypatch.setattr(settings, "intelligence_max_call_usd", Decimal("0"))

    assert _ocr_configuration_ready() == (False, "INTELLIGENCE_DISABLED")
    assert scanned_pdf_ocr_availability(object(), need_id=uuid4(), evidence_id=uuid4()) == (
        False,
        "INTELLIGENCE_DISABLED",
    )
    with pytest.raises(ValueError):
        govinfo_scan.merge_write_once_capture(
            {},
            {
                "document_id": "2026-18765",
                "content_hash": "a" * 64,
                "page_count": 1,
                "scanned_pages": [1],
                "data_base64": base64.b64encode(b"%PDF-test").decode("ascii"),
                "source_url": URL,
            },
            source_allowed=False,
            retention_allowed=False,
            retention_reference="",
        )
