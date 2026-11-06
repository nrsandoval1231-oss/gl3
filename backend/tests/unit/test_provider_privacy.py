from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from uuid import uuid4

import pytest

from gridlens.intelligence.provider_privacy import (
    ProviderPrivacyError,
    contact_free_evidence,
    contains_sensitive_contact,
    require_contact_free,
)


def test_official_permit_quote_and_offsets_are_preserved_without_contact_data():
    item = {
        "source_id": "tx-permit-listing",
        "permit_number": "2026-123456",
        "published_date": "2026-10-31",
        "citation": {"source_url": "https://agency.example/permit/2026-123456"},
        "facts": [
            {
                "quote": "The facility requests 48 MW of additional electric service.",
                "start_offset": 102,
                "end_offset": 159,
            }
        ],
    }
    original = deepcopy(item)

    assert contains_sensitive_contact(item) is False
    safe = contact_free_evidence([item])
    assert safe == [item]
    assert safe[0]["facts"][0] == item["facts"][0]
    assert item == original
    safe[0]["facts"][0]["quote"] = "changed copy"
    assert item == original


@pytest.mark.parametrize(
    "item",
    [
        {"evidence_id": "a", "contact_email": "permit.contact@example.org"},
        {"evidence_id": "a", "phone_number": "+1 (512) 555-0198"},
        {"evidence_id": "a", "public_contacts": [{"kind": "email", "value": "x@y.example"}]},
        {"evidence_id": "a", "recipient": {"kind": "phone", "value": "5125550198"}},
        {"evidence_id": "a", "quote": "For questions call 512.555.0198 before filing."},
        {"evidence_id": "a", "quote": "Write to permit.contact@example.org with questions."},
        {"evidence_id": "a", "quote": "Contact: Jordan Example. Applicant: Northstar Grid LLC."},
        {"evidence_id": "a", "quote": "Applicant: Example Power LLC and Jordan Smith"},
        {"evidence_id": "a", "quote": "Applicant: Northstar Power LLC / jordan smith."},
        {"evidence_id": "a", "quote": "Submitted by Jordan Example on Monday."},
        {"evidence_id": "a", "contact_name": "Jordan Example"},
        {"evidence_id": "a", "applicant_name": "Jordan Example"},
        {"evidence_id": "a", "mailing_address": "123 Example Street"},
        {
            "evidence_id": "a",
            "source_url": "https://public.example/record?applicant_phone=5125550198",
        },
        {"evidence_id": "a", "source_url": "https://agency.example/contact/512-555-0198"},
        {
            "evidence_id": "a",
            "source_url": "https://agency.example/record#applicant_phone=5125550198",
        },
        {"evidence_id": "a", "source_url": "https://public.example/record?x=jane%40example.org"},
        {"evidence_id": "a", "source_url": "https://agency.example/files/jordan%2540example.test"},
        {"evidence_id": "a", "abstract": "Submit to jordan&#64;example.test."},
        {"evidence_id": "a", "quote": "Phone: 5125550198"},
        {"evidence_id": "a", "quote": "Phone: 5125550198 20261105"},
        {"evidence_id": "a", "quote": "Phone:\n5125550198"},
        {"evidence_id": "a", "abstract": "For details: (512)5550198."},
        {"evidence_id": "a", "abstract": "Permits: (512) 5550198"},
        {"evidence_id": "a", "abstract": "Call the contractor at (512) 555-0198 ext. 4."},
        {"jane@example.org": "person-email"},
        {"evidence_id": "a", "fullName": "Jordan Example"},
        {"evidence_id": "a", "quote": "Call 5125550198 for information."},
        {"evidence_id": "a", "quote": "Social Security number: 123-45-6789."},
        {"evidence_id": "a", "quote": "Mailing address: 123 Example Street."},
    ],
)
def test_contact_or_ambiguous_personal_fields_are_sensitive(item):
    assert contains_sensitive_contact(item) is True
    with pytest.raises(ProviderPrivacyError) as raised:
        require_contact_free(item)
    assert "Jordan Example" not in str(raised.value)
    assert "permit.contact@example.org" not in str(raised.value)


@pytest.mark.parametrize(
    "abstract",
    [
        "contractor_phone: 2125550100\napplicant_phone: 2125550199",
        "contractorPhone: 2125550100; applicant-phone: 2125550199",
        "Call 2125550100 for questions.",
    ],
)
def test_embedded_phone_field_labels_with_unformatted_numbers_are_sensitive(abstract):
    assert contains_sensitive_contact({"abstract": abstract}) is True


def test_phone_context_does_not_taint_a_distant_bare_docket_number():
    abstract = "Contact details are listed with the clerk. " + ("x" * 48) + " Docket 202611051234."
    assert contains_sensitive_contact({"abstract": abstract}) is False


def test_canonical_uuid_tokens_do_not_look_like_phone_numbers():
    value = "Call record 12345678-a234-4234-8234-123456789012 for status."
    assert contains_sensitive_contact({"abstract": value}) is False


def test_canonical_uuid_is_still_rejected_under_sensitive_contact_key():
    assert contains_sensitive_contact({"phone": "12345678-a234-4234-8234-123456789012"}) is True


def test_unsafe_evidence_is_dropped_as_a_whole_without_rewriting_other_quotes():
    safe = {
        "evidence_id": "safe",
        "facts": [{"quote": "A 48 MW service request is listed.", "start_offset": 7}],
    }
    unsafe = {
        "evidence_id": "unsafe",
        "facts": [
            {"quote": "A 48 MW service request is listed.", "start_offset": 7},
            {"quote": "Contact: Jordan Example; phone 512-555-0198.", "start_offset": 80},
        ],
    }
    selected = contact_free_evidence([safe, unsafe])

    assert selected == [safe]
    assert selected[0]["facts"][0]["quote"] == safe["facts"][0]["quote"]
    assert selected[0]["facts"][0]["start_offset"] == 7
    assert unsafe["facts"][1]["quote"].startswith("Contact:")


def test_contact_free_check_fails_closed_on_uninspectable_or_oversized_values():
    class HostileMapping(dict):
        def items(self):
            raise RuntimeError("private value must not escape")

    deeply_nested = "safe"
    for _ in range(18):
        deeply_nested = [deeply_nested]

    assert contains_sensitive_contact(HostileMapping(secret="x@y.example")) is True
    assert contains_sensitive_contact(deeply_nested) is True
    assert contains_sensitive_contact({"quote": "x" * 250_001}) is True
    assert contact_free_evidence([{"evidence_id": "safe"}, HostileMapping()]) == [
        {"evidence_id": "safe"}
    ]


def test_personal_numbers_in_permit_ids_and_citation_dates_are_not_treated_as_phones():
    value = {
        "permit_number": "5125550198",
        "retrieved_at": "2026-11-05",
        "source_url": "https://agency.example/docket/2026-11-05/5125550198",
    }
    assert contains_sensitive_contact(value) is False


def test_bare_unformatted_docket_number_remains_safe_without_phone_context():
    assert contains_sensitive_contact({"abstract": "Permit reference 5125550198."}) is False


def test_safe_metadata_types_remain_allowed_but_birth_dates_fail_closed_by_field():
    require_contact_free(
        {
            "project_id": uuid4(),
            "published_at": date(2026, 11, 5),
            "retrieved_at": datetime(2026, 11, 5, 12, 30),
        }
    )
    assert contains_sensitive_contact({"date_of_birth": date(1990, 1, 2)}) is True
