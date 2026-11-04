"""FERC eLibrary policy: public references only, CEII and privileged material rejected."""

from __future__ import annotations

import socket

import pytest

from gridlens.domain.ferc_equipment_interpretation import source_docket_context
from gridlens.ingestion.adapters import ferc_elibrary as fe
from gridlens.ingestion.parsers.ferc_equipment import _docket_references

SHEET = "https://elibrary.ferc.gov/eLibrary/docketsheet?docket_number="


def test_module_makes_no_request(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("FERC eLibrary must not be fetched")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    assert fe.docket_sheet_url("CP22-123-000").startswith("https://elibrary.ferc.gov/")
    assert not hasattr(fe, "fetch") and not hasattr(fe, "retrieve")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CP22-123-000", "CP22-123-000"),
        ("cp22-0123", "CP22-123"),
        ("CP22-123", "CP22-123"),
        ("CP22-123-0001", None),
        ("RP22-123-000", None),
        ("EL22-123-000", None),
        ("CP22-", None),
        ("", None),
    ],
)
def test_cp_docket_normalization(raw, expected):
    assert fe.normalize_cp_docket(raw) == expected


@pytest.mark.parametrize(
    "marker",
    [
        "CEII",
        "ceii",
        "Critical Energy Infrastructure Information",
        "critical_electric_infrastructure",
        "Privileged",
        "NON-PUBLIC",
        "non public",
        "nonpublic",
        "PRIV_filing",
        "protected material",
    ],
)
def test_ceii_and_privileged_markers_are_rejected_anywhere(marker):
    with pytest.raises(fe.NonPublicRejected):
        fe.reject_nonpublic(f"prefix {marker} suffix")
    url = f"https://elibrary.ferc.gov/eLibrary/filelist?accession_number=20260101000001&{marker}=1"
    assert fe.is_public_elibrary_url(url) is False
    with pytest.raises(fe.NonPublicRejected):
        fe.docket_sheet_url(f"CP22-123-000 {marker}")


def test_public_text_and_values_pass_the_gate():
    fe.reject_nonpublic("Compressor Station 9 Project", None, 5, "CP22-123-000")


@pytest.mark.parametrize(
    "url",
    [
        SHEET + "CP22-123-000",
        "https://elibrary.ferc.gov/eLibrary/filelist?accession_number=20260101123456",
    ],
)
def test_exact_public_page_shapes_are_accepted(url):
    assert fe.is_public_elibrary_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://elibrary.ferc.gov/eLibrary/docketsheet?docket_number=CP22-123-000",
        "https://elibrary.ferc.gov.attacker.test/eLibrary/docketsheet?docket_number=CP22-123-000",
        "https://www.ferc.gov/eLibrary/docketsheet?docket_number=CP22-123-000",
        "https://elibrary.ferc.gov/eLibrary/search?q=CP22-123",
        SHEET + "CP22-123-000&x=1",
        SHEET + "RP22-1-000",
        "https://elibrary.ferc.gov/eLibrary/filelist?accession_number=abc",
        SHEET + "CP22-123-000#frag",
        "https://u:p@elibrary.ferc.gov/eLibrary/docketsheet?docket_number=CP22-123-000",
        "https://elibrary.ferc.gov/eLibraryWebAPI/api/Search",
        "https://elibrary.ferc.gov/eLibrary/docketsheet",
    ],
)
def test_other_urls_are_not_public_references(url):
    assert fe.is_public_elibrary_url(url) is False


def _context(text):
    class Extracted:
        pass

    Extracted.docket_references, Extracted.docket_issues = _docket_references(text)
    return source_docket_context(Extracted, text)


def test_reference_derives_from_a_source_bound_cp_docket_only():
    text = "Docket No. CP22-123-000 for the Example Compressor Station Project."
    refs = fe.docket_references(_context(text))
    assert refs == [
        {
            "docket": "CP22-123-000",
            "identity_level": "full",
            "docket_sheet_url": SHEET + "CP22-123-000",
            "access": "reference_only_not_fetched",
        }
    ]


def test_root_only_docket_is_labelled_root_only():
    refs = fe.docket_references(_context("Docket No. CP22-123 was noticed."))
    assert [(r["docket"], r["identity_level"]) for r in refs] == [("CP22-123", "root_only")]


def test_conflicting_or_absent_dockets_yield_no_reference():
    assert fe.docket_references(_context("Dockets CP22-123-000 and CP23-9-000.")) == []
    assert fe.docket_references(_context("No docket stated here.")) == []
    assert fe.docket_references(None) == []
    assert fe.docket_references({"status": "UNKNOWN", "normalized_full": "CP22-1-000"}) == []
