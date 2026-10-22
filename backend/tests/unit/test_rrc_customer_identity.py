from gridlens.ingestion.adapters.rrc_customer_identity import (
    RrcOperatorIdentity,
    rrc_operator_identity,
)


def test_rrc_operator_identity_requires_typed_source_bound_fields():
    record = {
        "abstract": "Operator number: 217012\nOperator: DIAMONDBACK E&P LLC\nProperty: Lease A",
        "permit": {
            "source_type": "texas-rrc-flare-vent-exceptions",
            "operator_number": "217012",
            "operator": "DIAMONDBACK E&P LLC",
        },
    }
    assert rrc_operator_identity("texas-rrc-flare-vent-exceptions", record) == RrcOperatorIdentity(
        "217012", "DIAMONDBACK E&P LLC"
    )
    assert rrc_operator_identity("texas-rrc-drilling-permits", record) is None

    wrong_source = {**record, "permit": {**record["permit"], "source_type": "publisher-rss"}}
    assert rrc_operator_identity("texas-rrc-flare-vent-exceptions", wrong_source) is None

    wrong_quote = {**record, "abstract": "Operator number: 217013\nOperator: DIAMONDBACK E&P LLC"}
    assert rrc_operator_identity("texas-rrc-flare-vent-exceptions", wrong_quote) is None

    for invalid_number in ("21701", "0217012", "000000", "unknown"):
        invalid = {**record, "permit": {**record["permit"], "operator_number": invalid_number}}
        assert rrc_operator_identity("texas-rrc-flare-vent-exceptions", invalid) is None

    mutable_name = {**record, "permit": {**record["permit"], "operator": "OTHER LLC"}}
    assert rrc_operator_identity("texas-rrc-flare-vent-exceptions", mutable_name) is None


def test_rrc_operator_number_is_not_a_project_or_company_name_guess():
    assert (
        rrc_operator_identity(
            "publisher-rss",
            {
                "permit": {
                    "operator_number": "217012",
                    "operator": "DIAMONDBACK E&P LLC",
                },
                "abstract": "Operator number: 217012\nOperator: DIAMONDBACK E&P LLC",
            },
        )
        is None
    )


def test_rrc_operator_labels_do_not_borrow_values_across_lines_or_accept_conflicts():
    source = "texas-rrc-flare-vent-exceptions"
    for abstract in (
        "Operator number: 217012\nOperator:\nOperator number: 217013",
        "Operator number: 217012\nOperator number: 217013\nOperator: DIAMONDBACK E&P LLC",
        "Operator number: 217012\nOperator: DIAMONDBACK E&P LLC\nOperator: OTHER LLC",
    ):
        assert rrc_operator_identity(source, {"abstract": abstract}) is None
