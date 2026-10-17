from gridlens.domain.market import classify, group_items, normalize_title


def test_items_not_about_power_are_excluded():
    assert classify("Bakery opens third location", "Fresh bread daily.") is None
    # Keywords alone are not enough without a power signal.
    assert classify("Neighborhood market reopens", "Local shops return.") is None


def test_region_and_topic_come_from_title_and_abstract():
    placed = classify(
        "ERCOT large load interconnection queue tops 200 GW",
        "Data center requests drive the Texas grid operator's queue.",
    )
    assert placed == {"region": "ercot", "topic": "load-growth"} or placed["region"] == "ercot"
    assert placed["topic"] in {"load-growth", "interconnection"}


def test_title_weighs_more_than_abstract():
    placed = classify(
        "PJM capacity auction prices jump",
        "The utility also discussed a solar project and a battery project in Ohio.",
    )
    assert placed["region"] == "pjm"
    assert placed["topic"] == "prices-markets"


def test_region_falls_back_to_source_geography_then_national():
    assert classify("Grid operator sets new wholesale record", "", "Texas")["region"] == "ercot"
    assert (
        classify("Grid operator sets new wholesale record", "", "California")["region"] == "caiso"
    )
    assert classify("Grid operator sets new wholesale record", "", "Global")["region"] == "national"


def test_short_tokens_do_not_match_inside_words():
    # "ai" must not match inside "said"/"train"; "spp" must not match "wrapped".
    placed = classify("Utility said the train line wrapped up", "Electric grid crews finished.")
    assert placed is not None
    assert placed["topic"] == "transmission"
    assert placed["region"] == "national"


def _item(i, region, topic, day):
    return {"id": f"{i:02d}", "region": region, "topic": topic, "published_at": day}


def test_grouping_is_deterministic_and_capped():
    items = [_item(i, "ercot", "load-growth", f"2026-10-{10 + i % 5}") for i in range(12)]
    items += [_item(20 + i, "pjm", "prices-markets", "2026-10-12") for i in range(3)]
    items += [_item(30, "caiso", "generation", "2026-10-11")]
    groups = group_items(items, max_per_group=8, max_total=60)
    assert [g["key"] for g in groups] == [
        "ercot:load-growth",
        "pjm:prices-markets",
        "caiso:generation",
    ]
    assert len(groups[0]["item_ids"]) == 8
    assert groups[0]["total_items"] == 12 and groups[0]["omitted_items"] == 4
    assert groups == group_items(list(reversed(items)), max_per_group=8, max_total=60)


def test_total_cap_applies_across_groups_in_order():
    items = [_item(i, "ercot", "load-growth", "2026-10-12") for i in range(8)]
    items += [_item(10 + i, "pjm", "generation", "2026-10-12") for i in range(5)]
    groups = group_items(items, max_per_group=8, max_total=10)
    assert sum(len(g["item_ids"]) for g in groups) == 10
    assert groups[1]["omitted_items"] == 3


def test_title_normalization_collapses_punctuation_and_case():
    assert normalize_title("PJM: Prices—JUMP!") == normalize_title("pjm prices jump")
