from __future__ import annotations

from _permit_pdf import make_pdf

from gridlens.ingestion.parsers.permit_docs.text_layer import (
    CanonicalText,
    TextLayerFailure,
    TextLayerLimits,
    build_canonical_text,
)


def test_pages_offsets_scanned_and_locate() -> None:
    pdf = make_pdf(
        [
            ["EU Point Description Horsepower Serial #", "C1 S1 Cooper GMVA-10 1,350 45756 1963"],
            [],  # no text layer: a scanned page
            ["Second text page with enough characters to count as a text layer."],
        ]
    )
    canon = build_canonical_text(pdf)
    assert isinstance(canon, CanonicalText)
    assert [p.page for p in canon.pages] == [1, 2, 3]
    assert canon.scanned_pages == [2]
    assert canon.pages[1].chars == 0
    offset = canon.text.index("Cooper")
    located = canon.locate(offset)
    assert located is not None and located.page == 1 and located.bbox is not None
    third = canon.text.index("Second text")
    third_location = canon.locate(third)
    assert third_location is not None and third_location.page == 3
    # separator characters between pages belong to no page
    assert canon.page_of(canon.page_span(1)[1]) is None


def test_corrupt_pdf_is_a_typed_failure() -> None:
    result = build_canonical_text(b"%PDF-1.4 this is not a pdf")
    assert isinstance(result, TextLayerFailure)
    assert result.code == "unreadable"


def test_oversized_pdf_fails_before_parsing() -> None:
    result = build_canonical_text(make_pdf([["x" * 50]]), TextLayerLimits(max_bytes=100))
    assert isinstance(result, TextLayerFailure) and result.code == "too_large"


def test_page_bound_is_a_failure_not_partial_success() -> None:
    pdf = make_pdf([["page one has some text on it for the test"]] * 3)
    result = build_canonical_text(pdf, TextLayerLimits(max_pages=2))
    assert isinstance(result, TextLayerFailure) and result.code == "too_many_pages"


def test_page_character_cap_and_time_budget() -> None:
    pdf = make_pdf([["y" * 200]])
    capped = build_canonical_text(pdf, TextLayerLimits(max_page_chars=50))
    assert isinstance(capped, TextLayerFailure) and capped.code == "page_too_long"
    timed = build_canonical_text(pdf, TextLayerLimits(max_seconds=-1.0))
    assert isinstance(timed, TextLayerFailure) and timed.code == "time_budget"


def test_page_text_seam_has_no_geometry() -> None:
    canon = CanonicalText.from_page_texts(["a" * 50, "short"])
    assert canon.scanned_pages == [2]
    location = canon.locate(3)
    assert location is not None and location.bbox is None


def test_one_unreadable_page_is_reported_not_fatal(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import pdfplumber.page

    original = pdfplumber.page.Page.extract_text_lines

    def flaky(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.page_number == 2:
            raise RuntimeError("broken content stream")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pdfplumber.page.Page, "extract_text_lines", flaky)
    pdf = make_pdf([["First page has enough text to count as a text layer."]] * 3)
    canon = build_canonical_text(pdf)
    assert isinstance(canon, CanonicalText)
    assert canon.failed_pages == [2] and canon.scanned_pages == [2]
    assert len(canon.pages) == 3 and canon.pages[0].chars > 40
