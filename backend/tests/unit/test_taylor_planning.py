from pathlib import Path

from gridlens.domain.taylor_planning import interpret_taylor_planning
from gridlens.ingestion.adapters.taylor_newsflash import _article


def record(**overrides):
    base = {
        "category": "Development Notices",
        "source_geography": "Taylor, Texas",
        "title": "Project Mustang data center planning review",
        "abstract": (
            "Planning and Zoning Commission public hearing for Project Mustang data center "
            "property in Taylor, Williamson County, Texas."
        ),
        "publication_date": "2026-09-04",
        "disposition": None,
    }
    return {**base, **overrides}


def test_dated_named_planning_signal_has_unknown_power_fields():
    result = interpret_taylor_planning(record())
    assert result is not None
    assert result["activity_key"] == "facility-expansion"
    assert result["location"] == "Taylor, Texas"
    assert "investigate" in result["rationale"]
    assert "MW" not in result["rationale"]


def test_withdrawn_or_ambiguous_notices_do_not_create_or_cancel_signals():
    assert (
        interpret_taylor_planning(record(title="WITHDRAWN - Project Mustang data center planning"))
        is None
    )
    assert interpret_taylor_planning(record(title="Development agreement public hearing")) is None
    assert interpret_taylor_planning(record(abstract="")) is None


def test_real_comal_article_uses_visible_title_body_address_and_original_citation():
    path = Path(__file__).resolve().parents[1] / "fixtures" / "taylor-newsflash-2032.html"
    url = "https://taylortx.gov/m/NewsFlash/Home/Detail/2032"
    article = _article(path.read_bytes(), url, "2032", None)
    article["source_geography"] = "Taylor, Texas"
    result = interpret_taylor_planning(article)
    assert article["title"] == "Project Comal - Employment Center Plan at 1051 CR 401"
    assert "Taylor, TX 76574" not in article["abstract"]
    assert result is not None
    assert result["name"] == article["title"]
    assert "1051 CR 401" in result["rationale"]


def test_real_withdrawn_mustang_revision_stays_observation_only():
    path = (
        Path(__file__).resolve().parents[3]
        / ".agent"
        / "artifacts"
        / "GL3-015A"
        / "taylortx.gov-m_NewsFlash_Archive_Item_2079.html"
    )
    article = _article(
        path.read_bytes(),
        "https://taylortx.gov/m/NewsFlash/Archive/Item/2079?arcId=3442",
        "2079",
        "3442",
    )
    article["source_geography"] = "Taylor, Texas"
    assert article["title"].startswith("Archived - WITHDRAWN")
    assert interpret_taylor_planning(article) is None
