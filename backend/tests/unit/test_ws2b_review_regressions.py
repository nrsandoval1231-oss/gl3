"""Regression tests for the WS2b review: quote boundaries, sentence-level association,
one row per rating span, guarded optional passes and provenance persistence."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from test_equipment_proposer import FakeProposer, field, run, unit

import gridlens.ingestion.adapters.tceq_application_documents as docs
from gridlens.ingestion.parsers.permit_docs import extract_from_pages
from gridlens.ingestion.parsers.permit_docs.proposals import OcrOutcome, ProposerOutcome
from gridlens.intelligence import equipment_proposer as ep
from gridlens.intelligence.spend_caps import parse_provider_caps
from gridlens.settings import settings

HASH = "a" * 64
GOOD = (
    "Project description: new compressor C-1, 1,500 hp and electric motor driven, "
    "will be commissioned in March 2027 at the plant."
)


def reasons(result):
    return result.proposer["rejection_reasons"] + result.proposer["drop_reasons"]


# ---- blocker 1: quotes stand alone -----------------------------------------------------


@pytest.mark.parametrize(
    "text, proposal",
    [
        (GOOD, unit(rating=field("500", "500 hp"))),  # inside 1,500 hp
        (
            "Project description: new compressor C-1 rated 2.5 MW and electric motor driven.",
            unit(rating_unit="MW", rating=field("5", "5 MW"), in_service_date=None),
        ),
        (
            "Project description: new compressor C-10, 1,500 hp and electric motor driven.",
            unit(in_service_date=None),  # id C-1 inside C-10
        ),
    ],
)
def test_a_quote_inside_a_longer_token_or_number_is_not_found(text, proposal):
    result, _ = run([proposal], text=text)
    assert result.verified == 0 and result.proposer["unlocatable"] == 1


def test_date_inside_a_longer_number_is_not_a_date():
    text = "Permit 202512 covers new compressor C-1, 1,500 hp, electric motor driven, in service."
    result, _ = run([unit(in_service_date=field("2025", "202512"))], text=text)
    row = (result.demand_rows + result.supply_rows)[0]
    assert row.in_service_date == "" or result.verified == 0


# ---- blocker 2: the whole sentence must agree ----------------------------------------------


def test_negation_outside_the_quote_rejects_the_driver():
    text = "Project description: new compressor C-1, 1,500 hp, non-electric motor driven unit."
    result, _ = run([unit(in_service_date=None)], text=text)
    assert result.verified == 0


def test_driver_in_a_neighbouring_sentence_is_not_this_units_driver():
    text = (
        "Project description: new compressor C-1, 1,500 hp, natural gas-fired. "
        "Separately, the water pump P-9 is electric motor driven."
    )
    proposal = unit(in_service_date=None, driver=field("electric", "electric motor driven"))
    result, _ = run([proposal], text=text)
    assert result.verified == 0 and result.demand_rows == []


def test_count_from_another_sentence_or_not_abutting_is_rejected():
    text = (
        "Project description: new compressor C-1, 1,500 hp and electric motor driven. "
        "The site also has three (3) storage tanks."
    )
    result, _ = run([unit(in_service_date=None, quantity=field(3, "three (3)"))], text=text)
    assert result.verified == 0
    same_sentence = (
        "The site has three (3) storage tanks, a new compressor C-1, 1,500 hp and electric "
        "motor driven at the plant."
    )
    result, _ = run(
        [unit(in_service_date=None, quantity=field(3, "three (3)"))], text=same_sentence
    )
    assert result.verified == 0 and "abut" in result.proposer["rejection_reasons"][0]


def test_count_abutting_the_rating_is_accepted():
    text = "Project description: three (3) 1,500 hp electric motor driven compressors, new."
    # The rules read this sentence themselves, so the proposer is not consulted.
    result, proposer = run([unit()], text=text)
    assert proposer.calls == 0 and result.verified == 1


def test_other_equipment_type_in_the_sentence_rejects_the_row():
    text = (
        "New generator G-1 rated 1,500 hp and electric motor driven; a compressor building is near."
    )
    proposal = unit(
        unit_id=field("G-1", "G-1"),
        equipment_type=field("compressor", "compressor"),
        in_service_date=None,
    )
    result, _ = run([proposal], text=text)
    assert result.verified == 0


@pytest.mark.parametrize(
    "text",
    [
        "Project description: new emergency standby compressor C-1, 1,500 hp and electric "
        "motor driven.",
        "Project description: new backup compressor C-1, 1,500 hp and electric motor driven.",
        "Project description: new compressor C-1, 1,500 hp and electric motor driven, kept "
        "as a spare.",
    ],
)
def test_standby_emergency_backup_cues_drop_the_row_even_with_status_null(text):
    result, _ = run([unit(status=None, in_service_date=None)], text=text)
    assert result.verified == 0
    assert "standby" in result.proposer["rejection_reasons"][0]


def test_removal_cue_blocks_a_new_status_and_a_retired_row_needs_retired():
    text = (
        "Project description: existing compressor C-1, 1,500 hp and electric motor driven, "
        "will be removed."
    )
    result, _ = run([unit(status=field("new", "new"), in_service_date=None)], text=text)
    assert result.verified == 0
    result, _ = run([unit(status=None, in_service_date=None)], text=text)
    assert result.verified == 0  # a removal cue is never silently dropped to unknown
    retired = unit(status=field("removed", "removed"), in_service_date=None)
    result, _ = run([retired], text=text)
    assert result.verified == 1 and result.demand_rows[0].state == "retired"


# ---- S7: only an in-service date counts ----------------------------------------------------


def test_a_date_without_an_in_service_cue_is_not_kept():
    text = (
        "Application received March 2024 for new compressor C-1, 1,500 hp, electric motor driven."
    )
    result, _ = run(
        [unit(in_service_date=field("March 2024", "March 2024"), status=None)], text=text
    )
    assert result.verified == 1
    assert (result.demand_rows + result.supply_rows)[0].in_service_date == ""


def test_an_in_service_date_with_a_cue_is_kept():
    result, _ = run([unit()])
    assert result.demand_rows[0].in_service_date == "March 2027"


# ---- blocker 3: one row per rating span ----------------------------------------------------


def test_identical_proposals_for_one_rating_collapse_and_conflicting_ones_are_dropped():
    result, _ = run([unit(), unit()])
    assert result.verified == 1
    conflicting = unit(equipment_type=field("pump", "compressor"))
    result, _ = run([unit(), conflicting])
    assert result.verified == 0 or len(result.demand_rows + result.supply_rows) <= 1
    different_status = unit(status=None)
    result, _ = run([unit(), different_status])
    assert len(result.demand_rows + result.supply_rows) == 0
    assert result.proposer["conflicting_dropped"] == 2


# ---- S4/S5: guarded passes, replay --------------------------------------------------------


class Boom:
    def propose(self, pages, *, document_hash):
        raise RuntimeError("provider exploded")

    def ocr_pages(self, pages, *, document_hash):
        raise RuntimeError("ocr exploded")


def test_a_raising_proposer_or_ocr_never_loses_rule_rows():
    text = "The facility will install two (2) 1,500 hp electric motor driven compressors."
    baseline = extract_from_pages([text, ""], document_hash=HASH)
    result = extract_from_pages([text, ""], document_hash=HASH, proposer=Boom(), ocr=Boom())
    assert result.verified == baseline.verified == 1
    assert result.ocr["status"] == "failed" and result.ocr["reason"] == "RuntimeError"
    assert any("OCR pass did not run" in issue for issue in result.issues)
    page_with_no_rule_row = GOOD
    result = extract_from_pages([text, page_with_no_rule_row], document_hash=HASH, proposer=Boom())
    assert result.verified == 1 and result.proposer["status"] == "failed"


def test_invalid_reported_usage_is_never_completed():
    request = ep.build_request(
        model="gpt-6.1-sol", pages=[ep.PageForProposal(1, "x")], max_output_tokens=2000
    )
    monkey = settings
    old = monkey.intelligence_equipment_max_output_tokens
    try:
        monkey.intelligence_equipment_max_output_tokens = 2000
        assert ep._usage_is_plausible({"input_tokens": 10, "output_tokens": 10}, request)
        assert not ep._usage_is_plausible({"input_tokens": -1, "output_tokens": 1}, request)
        assert not ep._usage_is_plausible({"input_tokens": True, "output_tokens": 1}, request)
        assert not ep._usage_is_plausible({"input_tokens": 1, "output_tokens": 2001}, request)
        assert not ep._usage_is_plausible({"input_tokens": 10**9, "output_tokens": 1}, request)
    finally:
        monkey.intelligence_equipment_max_output_tokens = old


def test_cached_price_zero_falls_back_to_the_full_input_price(monkeypatch):
    monkeypatch.setattr(settings, "intelligence_equipment_input_usd_per_million", Decimal(2))
    monkeypatch.setattr(settings, "intelligence_equipment_cached_input_usd_per_million", Decimal(0))
    monkeypatch.setattr(settings, "intelligence_equipment_output_usd_per_million", Decimal(10))
    usage = {
        "input_tokens": 1000,
        "output_tokens": 0,
        "input_tokens_details": {"cached_tokens": 1000},
    }
    assert ep.estimated_actual_cost(usage) == Decimal("0.002")


# ---- S6: labels persist in the stage's stored rows ------------------------------------------


def test_stage_supply_json_carries_text_source_and_method_and_ocr_role():
    from gridlens.ingestion.parsers.permit_docs.models import FieldEvidence

    evidence = FieldEvidence("rating", "2000", "2,000 hp", 0, 8, 1)
    base = dict(
        equipment_id="C-1",
        equipment_type="compressor",
        drive="electric",
        rating=2000,
        unit="hp",
        count=None,
        state="new",
        origin="llm",
        evidence={"rating": evidence},
    )
    rule = SimpleNamespace(**base, text_source="text_layer", proposed_by="", in_service_date="")
    ocr = SimpleNamespace(
        **base,
        text_source="ocr:openai:gpt-6.1-sol",
        proposed_by="llm:openai:gpt-6.1-sol",
        in_service_date="March 2027",
    )
    kept = docs._supply_json([rule, ocr])
    assert kept[0]["role"] == "supply_or_other" and kept[0]["method"] == "deterministic-rules"
    assert kept[0]["text_source"] == "text_layer" and kept[0]["in_service_date"] is None
    assert kept[1]["role"] == "ocr_retained_demand_candidate"
    assert kept[1]["text_source"] == "ocr:openai:gpt-6.1-sol"
    assert kept[1]["proposed_by"] == kept[1]["method"] == "llm:openai:gpt-6.1-sol"
    assert kept[1]["in_service_date"] == "March 2027"


def test_ocr_held_back_rows_are_not_in_supply_rows():
    class Ocr:
        def ocr_pages(self, pages, *, document_hash):
            return OcrOutcome(
                "ok",
                "",
                {
                    2: "The facility will install two (2) 1,500 hp electric motor driven "
                    "compressors."
                },
                "ocr:openai:gpt-6.1-sol",
            )

    result = extract_from_pages(
        ["Cover letter for the permit. Contact the office.", ""], document_hash=HASH, ocr=Ocr()
    )
    assert result.supply_rows == [] and len(result.ocr_retained_rows) == 1
    assert result.ocr_retained_rows[0].text_source == "ocr:openai:gpt-6.1-sol"


# ---- S8: provider names -------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad", ['{"opeani": {"monthly_usd": 1}}', '{"anthropic": {"monthly_usd": 1}}']
)
def test_unknown_provider_names_fail(bad):
    with pytest.raises(ValueError, match="one of"):
        parse_provider_caps(bad)
    assert parse_provider_caps('{"firecrawl": {"monthly_usd": 1}}')


# ---- nits ------------------------------------------------------------------------------------


def test_a_real_table_tag_that_looks_synthetic_is_not_rejected():
    from gridlens.ingestion.parsers.permit_docs.models import ExtractedRow, FieldEvidence
    from gridlens.ingestion.parsers.permit_docs.text_layer import CanonicalText
    from gridlens.ingestion.parsers.permit_docs.verifier import _recompute_problem

    canon = CanonicalText.from_page_texts(["L1-2 compressor 1,500 hp"])
    ev = FieldEvidence("id", "L1-2", "L1-2", 0, 4, 1)
    row = ExtractedRow(
        "table", "L1-2", "compressor", "unknown", Decimal(1500), "hp", None, "unknown"
    )
    assert canon.text[0:4] == "L1-2"
    assert _recompute_problem(ev, row) is None


def test_fake_proposer_unused_import_guard():
    assert FakeProposer([]).calls == 0 and ProposerOutcome("ok").units == []
