from gridlens.api.verticals import vertical_source_tags


def test_canonical_inbox_groups_match_source_tags():
    assert vertical_source_tags("energy-and-utilities") == ("utilities", "energy")
    assert vertical_source_tags("oil-and-gas") == ("oil and gas",)
    assert vertical_source_tags("construction-and-facilities") == (
        "construction",
        "commercial construction",
        "commercial facilities",
    )
    assert vertical_source_tags("cannabis") == ("cannabis", "cannabis cultivation")


def test_legacy_vertical_filter_values_remain_supported():
    assert vertical_source_tags("oil and gas") == ("oil and gas",)
    assert vertical_source_tags("commercial facilities") == (
        "construction",
        "commercial construction",
        "commercial facilities",
    )
    assert vertical_source_tags("unknown legacy label") == ("unknown legacy label",)
