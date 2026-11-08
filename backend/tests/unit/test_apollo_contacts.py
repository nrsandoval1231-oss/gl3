from gridlens.ingestion.adapters.apollo_contacts import (
    ACTIVATION_BLOCKED_REASON,
    APOLLO_ENABLED,
    ApolloContactRequest,
    enrich_contact,
)


def test_apollo_contact_adapter_is_disabled_and_returns_explicit_block():
    assert APOLLO_ENABLED is False
    result = enrich_contact(ApolloContactRequest("example.com", "Alex Example", "procurement"))
    assert result.status == "activation_blocked"
    assert result.reason == ACTIVATION_BLOCKED_REASON
    assert result.contacts == ()
