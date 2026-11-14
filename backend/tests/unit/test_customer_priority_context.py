from copy import deepcopy

from gridlens.domain.customer_intelligence import apply_priority_context


def test_context_is_explainable_idempotent_and_does_not_invent_confidence():
    original = {
        "potential": 40,
        "confidence": 80,
        "score": 32,
        "components": {"capacity": 20, "timing": 20},
        "version": "v1",
    }
    saved = deepcopy(original)
    result = apply_priority_context(
        original, recent_material_change=True, verified_contact_available=True
    )
    assert result["components"]["material_changes"] == 10
    assert result["components"]["verified_contacts"] == 5
    assert result["potential"] == 55 and result["confidence"] == 80
    assert result["score"] == 44
    assert (
        apply_priority_context(result, recent_material_change=True, verified_contact_available=True)
        == result
    )
    assert original == saved
    unknown = apply_priority_context({**original, "confidence": 0}, recent_material_change=True)
    assert unknown["score"] == 0


def test_geography_contributes_only_with_explicit_fit_and_preserves_bounds():
    base = {
        "potential": 90,
        "confidence": 100,
        "score": 90,
        "components": {"capacity": 90},
        "version": "v1",
    }
    assert apply_priority_context(base)["components"]["geographic_fit"] == 0
    matched = apply_priority_context(base, geographic_fit=True, recent_material_change=True)
    assert matched["potential"] == 100 and matched["score"] == 100
