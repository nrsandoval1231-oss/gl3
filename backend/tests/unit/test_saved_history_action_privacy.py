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
