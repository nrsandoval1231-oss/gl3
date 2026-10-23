from gridlens.ingestion.adapters.federal_register import SourceParseError
from gridlens.ingestion.service import _normalize_source_acquisition


def _record(identity: str, **overrides):
    return {
        "document_number": identity,
        "title": f"Public filing {identity}",
        "publication_date": "2026-10-01",
        "event_date": None,
        "html_url": f"https://example.gov/filing/{identity}",
        "extraction_location": "public filing page 1",
        "abstract": "Public filing summary",
        "permit": None,
        **overrides,
    }


def test_normalization_preserves_ordinary_list_contract():
    result = _normalize_source_acquisition({"id": "example"}, [_record("one")])

    assert isinstance(result, list)
    assert [record["document_number"] for record in result] == ["one"]


def test_malformed_required_fields_and_dates_are_isolated_from_valid_siblings():
    result = _normalize_source_acquisition(
        {"id": "example"},
        [
            _record("good-a"),
            _record("bad-title", title=" "),
            _record("bad-date", publication_date="yesterday"),
            _record("good-b"),
        ],
    )

    assert result["partial"] is True
    assert result["rejected_count"] == 2
    assert [record["document_number"] for record in result["records"]] == ["good-a", "good-b"]
    assert [record["identity"] for record in result["rejected_records"]] == [
        "bad-title",
        "bad-date",
    ]
    assert all(len(record["raw"]) <= 16 for record in result["rejected_records"])


def test_partial_adapter_result_and_presence_only_marker_remain_incomplete():
    rejection = {
        "identity": "TCEQ-123",
        "stage": "tceq_document",
        "error_code": "http_status_404",
        "selected_fields": ["permit"],
        "omitted_fields": ["document_body"],
        "raw": {"permit": "NSR-123"},
    }
    result = _normalize_source_acquisition(
        {"id": "example"},
        [
            _record("good"),
            {
                "document_number": "TCEQ-123",
                "presence_only": True,
                "partial_snapshot": True,
                "rejected_record": rejection,
            },
        ],
    )

    assert result["partial"] is True
    assert result["rejected_count"] == 1
    assert [record["document_number"] for record in result["records"]] == ["good"]
    assert result["rejected_records"] == [rejection]


def test_conflicting_duplicate_identity_quarantines_both_rows_and_keeps_siblings():
    first = _record("ambiguous")
    second = _record("ambiguous", abstract="Conflicting public filing content")
    result = _normalize_source_acquisition({"id": "example"}, [first, _record("unrelated"), second])

    assert result["partial"] is True
    assert result["rejected_count"] == 2
    assert [row["document_number"] for row in result["records"]] == ["unrelated"]
    assert len(result["rejected_records"]) == 2
    assert [item["identity"] for item in result["rejected_records"]] == [
        "ambiguous",
        "ambiguous",
    ]


def test_identical_duplicate_identity_is_deduplicated_with_counter():
    row = _record("same")
    result = _normalize_source_acquisition({"id": "example"}, [row, dict(row)])

    assert result["partial"] is True
    assert result["records"] == [row]
    assert result["rejected_count"] == 0
    assert result["duplicate_count"] == 1


def test_invalid_partial_contract_fails_closed():
    try:
        _normalize_source_acquisition({"id": "example"}, {"records": []})
    except SourceParseError as error:
        assert "invalid result contract" in str(error)
    else:
        raise AssertionError("invalid partial acquisition contract was accepted")
