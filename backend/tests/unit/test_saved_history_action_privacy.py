from gridlens.intelligence.contact_suppressions import _method_parts
from gridlens.intelligence.saved_history_privacy import _SUPPRESSED_ACTION, _redact


def _card(value):
    return {
        "next_action_type": "confirm_power_strategy_with_owner",
        "next_action": f"Call Circle T Owner LP on phone {value}.",
        "next_action_target": {
            "organization": "Circle T Owner LP",
            "category": "owner_developer",
            "kind": "phone",
            "value": value,
            "source_url": "https://example.test/p",
        },
    }


def test_suppressed_contact_method_removes_the_typed_target_and_call_text():
    hidden_methods = {_method_parts("phone", "571.731.1698")}
    redacted = _redact(_card("571.731.1698"), set(), set(), hidden_methods)
    assert redacted["next_action_target"] is None
    assert redacted["next_action_type"] == "research_question"
    assert redacted["next_action"] == _SUPPRESSED_ACTION
    assert "571" not in str(redacted)


def test_unsuppressed_target_is_left_intact():
    hidden_methods = {_method_parts("phone", "555-0000")}
    redacted = _redact(_card("571.731.1698"), set(), set(), hidden_methods)
    assert redacted["next_action_target"]["value"] == "571.731.1698"
    assert redacted["next_action_type"] == "confirm_power_strategy_with_owner"


def _labeled_card(kind, value):
    card = _card(value)
    card["next_action_target"]["kind"] = kind
    return card


def test_permit_summary_labeled_kinds_honor_canonical_phone_and_email_suppression():
    phone_hidden = {_method_parts("phone", "(512) 555-0100")}
    redacted = _redact(
        _labeled_card("Contractor phone", "512-555-0100"), set(), set(), phone_hidden
    )
    assert redacted["next_action_target"] is None
    assert redacted["next_action"] == _SUPPRESSED_ACTION
    email_hidden = {_method_parts("email", "mailto:Pat@Example.test")}
    redacted = _redact(
        _labeled_card("Contractor email", "pat@example.test"), set(), set(), email_hidden
    )
    assert redacted["next_action_target"] is None


def test_labeled_kind_with_a_different_number_is_left_intact():
    hidden = {_method_parts("phone", "(512) 555-0100")}
    redacted = _redact(_labeled_card("Contractor phone", "512-555-0199"), set(), set(), hidden)
    assert redacted["next_action_target"]["value"] == "512-555-0199"
