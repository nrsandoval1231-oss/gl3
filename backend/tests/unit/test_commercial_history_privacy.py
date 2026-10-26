from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import gridlens.intelligence.saved_history_privacy as privacy
from gridlens.intelligence.contact_suppressions import (
    company_suppression_key,
    global_method_suppression_key,
    global_person_suppression_key,
    method_suppression_key,
)
from gridlens.persistence.models import (
    BuyingChainClaim,
    BuyingChainCorrection,
    BuyingChainIdentityLink,
)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    """Small SQL-shaped fake that honors each requested cohort and LIMIT."""

    def __init__(self, claims=(), links=(), corrections=()):
        self.rows = {
            BuyingChainClaim: list(claims),
            BuyingChainIdentityLink: list(links),
            BuyingChainCorrection: list(corrections),
        }

    def scalars(self, query):
        model = query.column_descriptions[0]["entity"]
        rows = self.rows[model]
        params = query.whereclause.compile().params if query.whereclause is not None else {}
        requested = set()
        for value in params.values():
            if isinstance(value, list | tuple | set):
                requested.update(value)
            else:
                requested.add(value)
        if model is BuyingChainClaim:
            rows = [row for row in rows if row.project_id in requested]
        else:
            rows = [row for row in rows if row.claim_id in requested]
        limit = query._limit_clause
        if limit is not None:
            rows = rows[: int(limit.value)]
        return _Rows(rows)


def _claim(project, *, entity="entity-a", name="Avery Lee", org="Northstar Compute", methods=None):
    return SimpleNamespace(
        id=uuid4(),
        project_id=project,
        entity_key=entity,
        person_name=name,
        organization=org,
        public_contacts=methods or [],
    )


def _link(claim, *, company=None, person=None, state="superseded"):
    # State intentionally remains historical: privacy lineage is not limited
    # to the current identity-link row.
    return SimpleNamespace(
        id=uuid4(),
        claim_id=claim.id,
        company_identity_id=company,
        person_identity_id=person,
        state=state,
    )


def _card(project, claim, *, nested=True):
    contact = {
        "claim_id": str(claim.id),
        "person": claim.person_name,
        "kind": "email",
        "value": "Avery@Example.test",
        "source_url": "mailto:Avery@Example.test?ref=source",
    }
    result = {
        "id": str(uuid4()),
        "project_id": str(project),
        "related_project_ids": [str(project)],
        "name": "Northstar Compute",
        "tier": "Signal",
        "disposition": "RESEARCHED",
        "reason": "Avery Lee directs the project; avery@example.test is listed.",
        "next_action": "Call +1 713-555-0123 at Northstar Compute.",
        "qualification": {"status": "qualified", "reason": "Evidence-backed"},
        "contacts": [{"person": claim.person_name, "value": "Avery@Example.test"}],
        "sources": [{"title": "Avery Lee confirmed the phone +1 713-555-0123"}],
    }
    if nested:
        result["intelligence_card"] = {
            "contacts": [contact],
            "summary": "Avery Lee owns this decision.",
        }
    return result


def _history(project, card, versions=None):
    return {
        "project_id": str(project),
        "related_project_ids": [str(project)],
        "disposition": "RESEARCHED",
        "saved_card": deepcopy(card),
        "versions": versions
        if versions is not None
        else [{"version": 1, "saved_card": deepcopy(card)}],
    }


def _ledger(monkeypatch, suppressed=()):
    requested = []
    suppressed = set(suppressed)

    def states(_session, keys):
        requested.append(set(keys))
        # Only return suppression for a key the projector actually requested.
        return {key: "suppress" for key in suppressed if key in keys}

    monkeypatch.setattr(privacy, "_ledger_states", states)
    return requested


def test_method_suppression_projects_all_versions_without_mutating_snapshot(monkeypatch):
    project, company = uuid4(), uuid4()
    claim = _claim(project, methods=[{"kind": "email", "value": "avery@example.test"}])
    ledger_key = ("method", method_suppression_key(company, None, "email", "avery@example.test"))
    requested = _ledger(monkeypatch, [ledger_key])
    card = _card(project, claim)
    original = _history(project, card, [{"version": 1, "saved_card": deepcopy(card)}])
    session = _Session([claim], [_link(claim, company=company, person=uuid4())])

    projected = privacy.project_saved_history_privacy(session, original)

    assert original["saved_card"] == card
    assert "[redacted]" in projected["saved_card"]["reason"]
    assert "[redacted]" in projected["versions"][0]["saved_card"]["reason"]
    assert projected["saved_card"]["qualification"] == card["qualification"]
    assert ledger_key in requested[0]


def test_person_suppression_uses_historical_person_link_and_redacts_prose(monkeypatch):
    project, company, person = uuid4(), uuid4(), uuid4()
    claim = _claim(project)
    ledger_key = ("person", global_person_suppression_key(person))
    requested = _ledger(monkeypatch, [ledger_key])
    card = _card(project, claim)
    session = _Session([claim], [_link(claim, company=company, person=person, state="superseded")])

    result = privacy.project_saved_history_privacy(session, _history(project, card))

    assert ledger_key in requested[0]
    assert "Avery Lee" not in result["saved_card"]["reason"]
    assert "Avery Lee" not in result["saved_card"]["intelligence_card"]["summary"]
    assert "Avery Lee, contact avery@example.test" not in str(result["saved_card"])
    assert result["saved_card"]["tier"] == "Signal"
    assert result["saved_card"]["disposition"] == "RESEARCHED"
    assert result["saved_card"]["qualification"] == card["qualification"]


def test_whole_person_suppression_removes_unlinked_legacy_contact_method(monkeypatch):
    project, company, person = uuid4(), uuid4(), uuid4()
    claim = _claim(project, methods=[])
    ledger_key = ("person", global_person_suppression_key(person))
    requested = _ledger(monkeypatch, [ledger_key])
    card = _card(project, claim, nested=False)
    card["contacts"] = [
        {
            "organization": claim.organization,
            "person": "Avery Lee",
            "role": "Avery Lee, contact avery@example.test",
            "kind": "email",
            "value": "Avery@Example.test",
        }
    ]
    session = _Session([claim], [_link(claim, company=company, person=person)])

    result = privacy.project_saved_history_privacy(session, _history(project, card))

    assert ledger_key in requested[0]
    assert not result["saved_card"]["contacts"]
    assert "Avery@Example.test" not in str(result["saved_card"])
    assert "Avery Lee" not in str(result["saved_card"]["contacts"])


def test_person_suppression_hides_unowned_prose_method_without_company_link(monkeypatch):
    project, person = uuid4(), uuid4()
    claim = _claim(project, methods=[])
    known_coworker_method = {"kind": "email", "value": "morgan@example.test"}
    coworker = _claim(
        project,
        entity="coworker",
        name="Morgan Chen",
        methods=[known_coworker_method],
    )
    key = ("person", global_person_suppression_key(person))
    requested = _ledger(monkeypatch, [key])
    card = _card(project, claim, nested=False)
    card["contacts"] = []
    card["reason"] = (
        "Avery Lee can be reached at avery@example.test. "
        "Morgan Chen can be reached at morgan@example.test."
    )

    result = privacy.project_saved_history_privacy(
        _Session([claim, coworker], [_link(claim, person=person)]),
        _history(project, card),
    )

    assert key in requested[0]
    assert "Avery Lee" not in result["saved_card"]["reason"]
    assert "avery@example.test" not in result["saved_card"]["reason"].casefold()
    assert "Morgan Chen" in result["saved_card"]["reason"]
    assert "morgan@example.test" in result["saved_card"]["reason"].casefold()
    assert result["saved_card"]["qualification"]["status"] == card["qualification"]["status"]


def test_legacy_contact_without_claim_id_and_prose_only_method_use_project_claims(monkeypatch):
    project, company = uuid4(), uuid4()
    claim = _claim(project, methods=[{"kind": "email", "value": "avery@example.test"}])
    method_key = ("method", method_suppression_key(company, None, "email", "avery@example.test"))
    requested = _ledger(monkeypatch, [method_key])
    card = _card(project, claim, nested=False)
    card["sources"] = [{"text": "Reach Avery at MAILTO:avery@example.test or +1 713-555-0123"}]
    card["contacts"] = [{"person": "Avery Lee", "value": "avery@example.test"}]

    result = privacy.project_saved_history_privacy(
        _Session([claim], [_link(claim, company=company)]), _history(project, card)
    )

    assert method_key in requested[0]
    assert "[redacted]" in result["saved_card"]["sources"][0]["text"]
    assert "avery@example.test" not in result["saved_card"]["contacts"][0]["value"].casefold()


def test_company_scoped_method_in_saved_prose_uses_authoritative_claim_scope(monkeypatch):
    project, company = uuid4(), uuid4()
    value = "private@example.test"
    claim = _claim(project, methods=[])
    scoped_key = ("method", method_suppression_key(company, None, "email", value))
    requested = _ledger(monkeypatch, [scoped_key])
    card = _card(project, claim, nested=False)
    card["next_action"] = f"Email {value} about the archived scope."
    card["sources"] = [{"title": f"Business contact: {value}"}]

    result = privacy.project_saved_history_privacy(
        _Session([claim], [_link(claim, company=company)]), _history(project, card)
    )

    assert scoped_key in requested[0]
    assert value not in str(result["saved_card"])


def test_prose_only_international_phone_uses_global_method_suppression(monkeypatch):
    project = uuid4()
    claim = _claim(project, methods=[])
    phone = "+44 20 7946 0958"
    global_key = ("method", global_method_suppression_key("phone", phone))
    requested = _ledger(monkeypatch, [global_key])
    card = _card(project, claim, nested=False)
    card["next_action"] = f"Call {phone} for the listed facilities contact."
    card["sources"] = [{"title": f"Main office {phone}"}]

    result = privacy.project_saved_history_privacy(
        _Session([claim], [_link(claim, company=uuid4())]), _history(project, card)
    )

    assert global_key in requested[0]
    assert phone not in str(result["saved_card"])


def test_conflicting_identity_links_fail_closed_for_affected_contact_only(monkeypatch):
    project = uuid4()
    target = _claim(project, entity="target", name="Avery Lee", methods=[])
    unrelated = _claim(project, entity="unrelated", name="Morgan Chen", methods=[])
    company_a, company_b, person_a, person_b, unrelated_company = (uuid4() for _ in range(5))
    _ledger(monkeypatch)
    card = _card(project, target)
    card["intelligence_card"]["contacts"].append(
        {
            "claim_id": str(unrelated.id),
            "person": "Morgan Chen",
            "kind": "email",
            "value": "morgan@example.test",
        }
    )
    session = _Session(
        [target, unrelated],
        [
            _link(target, company=company_a, person=person_a),
            _link(target, company=company_b, person=person_b),
            _link(unrelated, company=unrelated_company),
        ],
    )

    result = privacy.project_saved_history_privacy(session, _history(project, card))

    contacts = result["saved_card"]["intelligence_card"]["contacts"]
    assert not any(contact["claim_id"] == str(target.id) for contact in contacts)
    assert any(contact["claim_id"] == str(unrelated.id) for contact in contacts)
    assert "Avery Lee" not in result["saved_card"]["reason"]
    assert "Morgan Chen" in str(result["saved_card"])


def test_ambiguous_company_scope_redacts_prose_only_method_and_preserves_metadata(monkeypatch):
    project, company_a, company_b, coworker_company = uuid4(), uuid4(), uuid4(), uuid4()
    claim = _claim(project, methods=[])
    coworker = _claim(
        project,
        entity="coworker",
        name="Morgan Chen",
        methods=[{"kind": "email", "value": "morgan@example.test"}],
    )
    _ledger(monkeypatch)
    card = _card(project, claim)
    card["contacts"] = []
    card["reason"] = (
        "Avery Lee directs work; contact avery@example.test. "
        "Morgan Chen can be reached at morgan@example.test."
    )
    card["intelligence_card"]["contacts"].append(
        {
            "claim_id": str(coworker.id),
            "person": "Morgan Chen",
            "kind": "email",
            "value": "morgan@example.test",
        }
    )
    session = _Session(
        [claim, coworker],
        [
            _link(claim, company=company_a),
            _link(claim, company=company_b),
            _link(coworker, company=coworker_company),
        ],
    )

    result = privacy.project_saved_history_privacy(session, _history(project, card))

    projected = result["saved_card"]
    assert "avery@example.test" not in str(projected).casefold()
    assert "Morgan Chen" in str(projected)
    assert "morgan@example.test" in str(projected)
    assert projected["tier"] == card["tier"]
    assert projected["disposition"] == card["disposition"]
    assert projected["qualification"]["status"] == card["qualification"]["status"]


def test_global_suppressed_email_is_removed_from_history_notes_without_mutation(monkeypatch):
    project = uuid4()
    claim = _claim(project, methods=[])
    email = "hiddennotes@example.test"
    key = ("method", global_method_suppression_key("email", email))
    requested = _ledger(monkeypatch, [key])
    card = _card(project, claim, nested=False)
    history = _history(project, card)
    history["notes"] = [{"text": f"Please contact {email} about the saved opportunity."}]
    original = deepcopy(history)

    projected = privacy.project_saved_history_privacy(
        _Session([claim], [_link(claim, company=uuid4())]), history
    )

    assert key in requested[0]
    assert email not in str(projected["notes"])
    assert history == original


def test_person_suppression_does_not_cross_attribute_methods_to_another_person(monkeypatch):
    project, company, suppressed_person, visible_person = uuid4(), uuid4(), uuid4(), uuid4()
    suppressed = _claim(project, entity="person-a", name="Avery Lee", methods=[])
    visible = _claim(project, entity="person-b", name="Morgan Chen", methods=[])
    key = ("person", global_person_suppression_key(suppressed_person))
    _ledger(monkeypatch, [key])
    card = _card(project, suppressed)
    card["intelligence_card"]["contacts"][0].update(
        {
            "kind": "email",
            "value": "avery@example.test",
        }
    )
    card["intelligence_card"]["contacts"].append(
        {
            "claim_id": str(visible.id),
            "person": "Morgan Chen",
            "kind": "email",
            "value": "morgan@example.test",
        }
    )
    card["contacts"] = [
        {
            "organization": suppressed.organization,
            "person": "Avery Lee",
            "kind": "email",
            "value": "avery@example.test",
        },
        {
            "organization": visible.organization,
            "person": "Morgan Chen",
            "kind": "email",
            "value": "morgan@example.test",
        },
    ]
    session = _Session(
        [suppressed, visible],
        [
            _link(suppressed, company=company, person=suppressed_person),
            _link(visible, company=company, person=visible_person),
        ],
    )

    result = privacy.project_saved_history_privacy(session, _history(project, card))

    nested = result["saved_card"]["intelligence_card"]["contacts"]
    assert not any(contact["claim_id"] == str(suppressed.id) for contact in nested)
    assert any(contact["claim_id"] == str(visible.id) for contact in nested)
    assert any(contact["person"] == "Morgan Chen" for contact in result["saved_card"]["contacts"])
    assert not any(contact["person"] == "Avery Lee" for contact in result["saved_card"]["contacts"])
    assert "morgan@example.test" in str(result["saved_card"])
    assert "avery@example.test" not in str(result["saved_card"])


def test_aggregate_ledger_key_budget_fails_closed_before_ledger_lookup(monkeypatch):
    monkeypatch.setattr(privacy, "MAX_HISTORY_KEYS", 2)
    project, company, person = uuid4(), uuid4(), uuid4()
    claim = _claim(project, methods=[])
    card = _card(project, claim)
    card["sources"] = [{"title": "Contact avery@example.test at Northstar Compute"}]
    requested = _ledger(monkeypatch)

    result = privacy.project_saved_history_privacy(
        _Session([claim], [_link(claim, company=company, person=person)]), _history(project, card)
    )

    assert requested == []
    projected = result["saved_card"]
    assert projected["tier"] == card["tier"]
    assert projected["disposition"] == card["disposition"]
    assert projected["qualification"]["status"] == card["qualification"]["status"]
    assert projected["contacts"] == []
    assert projected["sources"] == []
    assert projected["reason"] == "[redacted]"


def test_saved_version_former_project_id_is_resolved_against_retained_claims(monkeypatch):
    current_project, former_project, company = uuid4(), uuid4(), uuid4()
    latest_claim = _claim(current_project, entity="latest")
    former_claim = _claim(
        former_project, entity="former", methods=[{"kind": "email", "value": "former@example.test"}]
    )
    old_card = _card(former_project, former_claim)
    old_card["reason"] = "Contact former@example.test is in the archived claim."
    latest_card = _card(current_project, latest_claim)
    history = _history(
        current_project,
        latest_card,
        [{"version": 1, "saved_card": {**old_card, "related_project_ids": [str(former_project)]}}],
    )
    method_key = ("method", method_suppression_key(company, None, "email", "former@example.test"))
    requested = _ledger(monkeypatch, [method_key])
    session = _Session(
        [latest_claim, former_claim],
        [_link(latest_claim, company=uuid4()), _link(former_claim, company=company)],
    )

    result = privacy.project_saved_history_privacy(session, history)

    assert method_key in requested[0]
    assert "[redacted]" in result["versions"][0]["saved_card"]["reason"]


def test_suppression_for_unrelated_company_does_not_redact_saved_card(monkeypatch):
    project, company = uuid4(), uuid4()
    unrelated_project, unrelated_company = uuid4(), uuid4()
    claim = _claim(project, methods=[{"kind": "email", "value": "avery@example.test"}])
    unrelated = _claim(unrelated_project, entity="other", name="Different Person")
    unrelated_key = ("company", company_suppression_key(unrelated_company))
    requested = _ledger(monkeypatch, [unrelated_key])
    card = _card(project, claim)

    result = privacy.project_saved_history_privacy(
        _Session(
            [claim, unrelated],
            [_link(claim, company=company), _link(unrelated, company=unrelated_company)],
        ),
        _history(project, card),
    )

    assert unrelated_key not in requested[0]
    assert result["saved_card"] == card


def test_claim_limit_fails_closed_and_preserves_qualification(monkeypatch):
    project = uuid4()
    claims = [
        _claim(project, entity=f"entity-{index}") for index in range(privacy.MAX_HISTORY_CLAIMS + 1)
    ]
    card = _card(project, claims[0])
    requested = _ledger(monkeypatch)

    result = privacy.project_saved_history_privacy(_Session(claims), _history(project, card))

    assert requested == []  # overflow never asks the ledger using an incomplete key set
    projected = result["saved_card"]
    assert projected["tier"] == card["tier"]
    assert projected["disposition"] == card["disposition"]
    assert projected["qualification"]["status"] == card["qualification"]["status"]
    assert projected["qualification"]["reason"] == "[redacted]"
    assert projected["contacts"] == []
    assert projected["sources"] == []
    assert projected["reason"] == "[redacted]"


def test_internal_candidate_method_overflow_hides_last_token_but_keeps_physical_fact(monkeypatch):
    project = uuid4()
    claim = _claim(project, methods=[])
    emails = [f"contact{index}@example.test" for index in range(privacy.MAX_HISTORY_METHODS + 1)]
    card = _card(project, claim, nested=False)
    card["contacts"] = []
    card["sources"] = []
    card["reason"] = (
        "Contact tokens: "
        + " ".join(emails)
        + ". Description: Call 5125550100. Facility load is 500 kW."
    )
    requested = _ledger(monkeypatch)

    projected = privacy.project_saved_history_privacy(
        _Session([claim]),
        _history(project, card),
        _claim_ids={claim.id},
        _contact_tokens_only=True,
    )

    assert requested == []  # incomplete overflow cohorts never reach the ledger
    result = projected["saved_card"]
    assert emails[-1] not in result["reason"]
    assert "5125550100" not in result["reason"]
    assert "500 kW" in result["reason"]
    assert result["tier"] == card["tier"]
    assert result["disposition"] == card["disposition"]


def test_internal_whole_person_fallback_scrubs_email_but_preserves_evidence_url(monkeypatch):
    project, person = uuid4(), uuid4()
    claim = _claim(project, methods=[])
    person_key = ("person", global_person_suppression_key(person))
    _ledger(monkeypatch, [person_key])
    evidence_url = "https://source.example.test/permit/123"
    email = "avery@example.test"
    card = _card(project, claim, nested=False)
    card["contacts"] = []
    card["reason"] = f"Avery Lee at {email}; source record {evidence_url}."

    projected = privacy.project_saved_history_privacy(
        _Session([claim], [_link(claim, person=person)]),
        _history(project, card),
        _claim_ids={claim.id},
        _contact_tokens_only=True,
    )

    result = projected["saved_card"]
    assert email not in result["reason"].casefold()
    assert evidence_url in result["reason"]
    assert result["tier"] == card["tier"]
    assert result["disposition"] == card["disposition"]
