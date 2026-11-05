"""Synthetic equipment evidence: durable automatic processing, never live coverage."""

from datetime import UTC, date, datetime
from decimal import Decimal, Inexact, localcontext
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.intelligence.demand_summary import summarize
from gridlens.intelligence.equipment_intelligence import (
    _canonical_decimal,
    current_equipment_investigation,
    materialize_equipment_investigation,
)
from gridlens.persistence.database import Base
from gridlens.persistence.models import (
    BrowseGeneration,
    BrowseRow,
    Evidence,
    EvidencePackage,
    Interpretation,
    NeedObservation,
    Observation,
    PowerNeed,
    Project,
    Source,
)
from gridlens.settings import settings


@pytest.fixture
def equipment_db():
    target = make_url(settings.test_database_url)
    assert target.database and target.database.endswith("_test")
    assert target != make_url(settings.database_url)
    schema = "equipment_" + uuid4().hex
    admin = create_engine(target)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(target, connect_args={"options": f"-csearch_path={schema}"})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def seed(session, *, body=None):
    body = body or (
        "Company: Prairie Example LLC\nFacility: Mock Permian Compression Station\n"
        f"As of: {date.today().isoformat()}\n"
        "Equipment ID: C-101 | Type: compressor | Drive: electric | "
        "Rating: 1000 hp mechanical output | Count: 2 | Operating: 1 | State: proposed | "
        "Role: duty | Efficiency: 0.90\n"
        "Equipment ID: P-201 | Type: pump | Drive: electric | "
        "Rating: 500 kW electrical input | Count: 1 | Operating: 0 | State: existing | "
        "Role: standby\n"
    )
    source = Source(
        id="synthetic-equipment",
        publisher="Synthetic official fixture",
        endpoint="https://example.test/permits",
        family="construction-permits",
        geography="Texas",
        industries=["oil and gas"],
        retrieval_method="ok-deq-public-review",
        health={},
    )
    session.add(source)
    session.flush()
    project = Project(
        identity_key="equipment-site",
        name="Mock Permian Compression Station",
        location="Midland, TX",
        source_id=source.id,
        external_id="site",
    )
    session.add(project)
    session.flush()
    need = PowerNeed(
        project_id=project.id,
        activity_key="facility-expansion",
        tier="Signal",
        rationale="Synthetic proposed electric compression equipment",
        supply="Unknown",
    )
    obs = Observation(
        source_id=source.id,
        external_id="equipment-doc",
        title=project.name,
        abstract=body,
        published_at=date.today(),
        url="https://example.test/schedule",
        content_hash=sha256(body.encode()).hexdigest(),
    )
    session.add_all([need, obs])
    session.flush()
    ev = Evidence(
        observation_id=obs.id,
        content_hash=obs.content_hash,
        title=obs.title,
        abstract=body,
        url=obs.url,
        published_at=obs.published_at,
        extraction_location="Synthetic equipment schedule",
    )
    session.add(ev)
    session.flush()
    interpretation = Interpretation(
        observation_id=obs.id,
        status="accepted",
        content_hash=obs.content_hash,
        assessment={
            "semantic_hash": obs.content_hash,
            "evidence_hash": ev.content_hash,
            "decision": "accepted",
            "tier": "Signal",
            "subject": project.name,
            "location": project.location,
            "project_identity_key": project.identity_key,
            "power_activity": need.activity_key,
            "evidence": {"id": str(ev.id), "url": ev.url},
        },
    )
    session.add_all([interpretation, NeedObservation(need_id=need.id, observation_id=obs.id)])
    session.flush()
    return need, project, obs, ev, interpretation, source


def build(session, rows):
    need, project, obs, ev, interpretation, source = rows
    return materialize_equipment_investigation(
        session, need, project, obs, ev, interpretation, source
    )


def publish_test_browse(session, monkeypatch, needs, *, sector="oil_gas", identity=None):
    now = datetime.now(UTC)
    generation = BrowseGeneration(
        id=uuid4(),
        input_revision=1,
        policy_version="test",
        built_at=now,
        valid_from=now,
        valid_until=now.replace(year=now.year + 1),
        row_count=len(needs),
        digest="a" * 64,
        counts={},
    )
    session.add(generation)
    session.flush()
    for need, project in needs:
        session.add(
            BrowseRow(
                generation_id=generation.id,
                need_id=need.id,
                project_id=project.id,
                tier=need.tier,
                location=project.location or "",
                industry="",
                activity=need.activity_key,
                has_timing=False,
                mw_low=None,
                mw_high=None,
                priority_segment=0,
                workflow_status="UNKNOWN",
                signal_decision="UNKNOWN",
                project_group="legacy",
                single_group="legacy",
                rank_score=0,
                updated_at=now,
                search_text="",
                display_title=project.name,
                commercial_group=None,
                commercial_segment=None,
                commercial_geography=None,
                commercial_date=None,
                summary={},
                compact={
                    "project_metadata": {
                        "sector": sector,
                        "asset_identity": identity or {},
                    }
                },
            )
        )
    session.flush()
    monkeypatch.setattr(
        "gridlens.intelligence.demand_summary.current_generation",
        lambda _session: generation,
    )


def duplicate_schedule_for_need(session, rows, need):
    _old_need, project, old_obs, old_ev, old_interpretation, source = rows
    body = old_obs.abstract or ""
    obs = Observation(
        source_id=source.id,
        external_id=f"equipment-doc-{need.id}",
        title=project.name,
        abstract=body,
        published_at=old_obs.published_at,
        url=f"https://example.test/schedule/{need.id}",
        content_hash=sha256(body.encode()).hexdigest(),
    )
    session.add(obs)
    session.flush()
    ev = Evidence(
        observation_id=obs.id,
        content_hash=obs.content_hash,
        title=obs.title,
        abstract=body,
        url=obs.url,
        published_at=obs.published_at,
        extraction_location="Synthetic equipment schedule",
    )
    session.add(ev)
    session.flush()
    assessment = {
        **old_interpretation.assessment,
        "semantic_hash": obs.content_hash,
        "evidence_hash": ev.content_hash,
        "project_identity_key": project.identity_key,
        "power_activity": need.activity_key,
        "evidence": {"id": str(ev.id), "url": ev.url},
    }
    interpretation = Interpretation(
        observation_id=obs.id,
        status="accepted",
        content_hash=obs.content_hash,
        assessment=assessment,
    )
    session.add_all([interpretation, NeedObservation(need_id=need.id, observation_id=obs.id)])
    session.flush()
    return (need, project, obs, ev, interpretation, source)


def test_durable_replay_and_current_projection_preserve_qualification(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        first = build(session, rows)
        second = build(session, rows)
        assert first.id == second.id
        assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 1
        result = current_equipment_investigation(session, rows[0].id, rows[1].id)
        assert result["company"] == "Prairie Example LLC"
        assert result["status"] == "SUPPORTED"
        assert result["demand"]["coincident_kw"].startswith("828.555")
        assert result["residual_gap_kw"] is None
        assert result["decision_maker"] is None
        assert result["supply_constraint_evidence"] == []
        assert rows[0].tier == "Signal" and rows[0].required_mw is None
        assert result["evidence"][0]["evidence_id"] == str(rows[3].id)
        assert result["next_action"]


def test_stale_semantic_binding_retracts_current_result(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        build(session, rows)
        rows[2].content_hash = "a" * 64
        session.flush()
        assert current_equipment_investigation(session, rows[0].id, rows[1].id) is None
        assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 1


def test_wrong_facility_abstains_without_numeric_publication(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        rows[1].name = "Different physical facility"
        result = build(session, rows).payload
        assert result["status"] == "ABSTAINED"
        assert result["demand"] is None
        assert any("facility" in question.lower() for question in result["unresolved_questions"])


def test_portfolio_summary_uses_validated_current_record(equipment_db, monkeypatch):
    with equipment_db.begin() as session:
        rows = seed(session)
        rows[1].region_status = "ELIGIBLE"
        build(session, rows)
        publish_test_browse(session, monkeypatch, [(rows[0], rows[1])])
        summary = summarize(session, "oil_gas")
        assert summary["availability"] == "available"
        assert summary["totals"]["identified_records"] == 1
        assert summary["totals"]["known_mw_records"] == 1
        assert summary["classes"]["calculated"]["record_count"] == 1
        assert summary["classes"]["calculated"]["mw"] > 0
        assert summarize(session, "data_centers")["availability"] == "unavailable"


def test_portfolio_summary_retracts_stale_evidence(equipment_db, monkeypatch):
    with equipment_db.begin() as session:
        rows = seed(session)
        rows[1].region_status = "ELIGIBLE"
        build(session, rows)
        publish_test_browse(session, monkeypatch, [(rows[0], rows[1])])
        rows[2].content_hash = "a" * 64
        session.flush()
        summary = summarize(session)
        assert summary["availability"] == "unavailable"
        assert summary["totals"]["known_mw_records"] == 0


def test_portfolio_summary_does_not_add_multiple_needs_for_site(equipment_db, monkeypatch):
    with equipment_db.begin() as session:
        rows = seed(session)
        need, project = rows[:2]
        project.region_status = "ELIGIBLE"
        second = PowerNeed(
            project_id=project.id,
            activity_key="second-activity",
            tier="Signal",
            rationale="Overlapping schedule",
            supply="Unknown",
        )
        session.add(second)
        session.flush()
        second_rows = duplicate_schedule_for_need(session, rows, second)
        build(session, rows)
        build(session, second_rows)
        publish_test_browse(session, monkeypatch, [(need, project), (second, project)])
        result = summarize(session)
        assert result["totals"]["known_mw_records"] == 0
        assert result["totals"]["conflicted_records"] == 1
        assert result["classes"]["calculated"]["mw"] is None


def test_untrusted_or_wrong_activity_cannot_materialize(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        rows[4].assessment = {**rows[4].assessment, "power_activity": "different-activity"}
        assert build(session, rows) is None


def test_unknown_efficiency_is_investigation_not_assumed_load(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(
            session,
            body=(
                "Company: Prairie Example LLC\nFacility: Mock Permian Compression Station\n"
                "Equipment ID: C-1 | Type: compressor | Drive: electric | "
                "Rating: 1000 hp mechanical output | Count: 1 | Operating: 1 | "
                "State: new | Role: duty"
            ),
        )
        result = build(session, rows).payload
        assert result["status"] == "PARTIAL"
        assert result["demand"]["coincident_kw"] is None
        assert result["residual_gap_kw"] is None


def test_legacy_jev_validator_cannot_accept_equipment_contract(equipment_db):
    from gridlens.intelligence.evidence_packages import validate_package

    with equipment_db.begin() as session:
        receipt = build(session, seed(session))
        with pytest.raises(ValueError):
            validate_package(receipt.payload)


def test_modified_calculation_receipt_is_not_published(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        receipt = build(session, rows)
        receipt.payload = {**receipt.payload, "demand": {"coincident_kw": "999999"}}
        session.flush()
        assert current_equipment_investigation(session, rows[0].id, rows[1].id) is None


def test_semantic_and_evidence_hashes_need_not_be_equal(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        rows[2].content_hash = "b" * 64
        rows[4].content_hash = rows[2].content_hash
        rows[4].assessment = {**rows[4].assessment, "semantic_hash": rows[2].content_hash}
        session.flush()
        assert build(session, rows).payload["status"] == "SUPPORTED"
        assert (
            current_equipment_investigation(session, rows[0].id, rows[1].id)["status"]
            == "SUPPORTED"
        )


def additional_document(session, rows, body):
    need, project, _, _, _, source = rows
    obs = Observation(
        source_id=source.id,
        external_id=str(uuid4()),
        title=project.name,
        abstract=body,
        published_at=date.today(),
        url="https://example.test/another-document",
        content_hash=sha256(body.encode()).hexdigest(),
    )
    session.add(obs)
    session.flush()
    ev = Evidence(
        observation_id=obs.id,
        content_hash=obs.content_hash,
        title=obs.title,
        abstract=body,
        url=obs.url,
        published_at=obs.published_at,
    )
    session.add(ev)
    session.flush()
    interpretation = Interpretation(
        observation_id=obs.id,
        content_hash=obs.content_hash,
        status="accepted",
        assessment={
            **rows[4].assessment,
            "semantic_hash": obs.content_hash,
            "evidence_hash": ev.content_hash,
            "evidence": {"id": str(ev.id), "url": ev.url},
        },
    )
    session.add_all([interpretation, NeedObservation(need_id=need.id, observation_id=obs.id)])
    session.flush()
    return need, project, obs, ev, interpretation, source


def test_duplicate_documents_do_not_double_equipment_capacity(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        first = build(session, rows).payload
        build(session, additional_document(session, rows, rows[3].abstract))
        result = current_equipment_investigation(session, rows[0].id, rows[1].id)
        assert result["status"] == "SUPPORTED"
        assert result["demand"]["coincident_kw"] == first["demand"]["coincident_kw"]
        assert len(result["evidence"]) == 2


def test_conflicting_documents_abstain_without_double_counting(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        build(session, rows)
        build(
            session,
            additional_document(session, rows, rows[3].abstract.replace("1000 hp", "2000 hp")),
        )
        result = current_equipment_investigation(session, rows[0].id, rows[1].id)
        assert result["status"] == "ABSTAINED"
        assert result["demand"] is None
        assert len(result["evidence"]) == 2
        assert result["claim_classes"]["demand"] == "UNKNOWN"
        assert set(result["quantity_classification"].values()) == {"UNKNOWN"}
        assert "Reconcile" in result["next_action"]


def test_historical_receipts_do_not_consume_current_document_bound(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        build(session, rows)
        for _index in range(40):
            stale = additional_document(session, rows, rows[3].abstract)
            build(session, stale)
            stale[4].status = "rejected"
            session.flush()
        # A newly admitted old-source-date document remains current and eligible.
        current = additional_document(session, rows, rows[3].abstract)
        # Backdate the source publication before constructing its immutable receipt.
        current[2].published_at = date(2020, 1, 1)
        current[3].published_at = date(2020, 1, 1)
        current[4].assessment = {**current[4].assessment}
        current[4].assessment["published_at"] = date(2020, 1, 1).isoformat()
        build(session, current)
        result = current_equipment_investigation(session, rows[0].id, rows[1].id)
        assert result["status"] == "SUPPORTED"
        assert result["demand"] is not None


def test_thirty_three_current_documents_still_abstain(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        build(session, rows)
        for _ in range(32):
            build(session, additional_document(session, rows, rows[3].abstract))
        result = current_equipment_investigation(session, rows[0].id, rows[1].id)
        assert result["status"] == "ABSTAINED"
        assert result["demand"] is None


def test_identical_reordered_rows_and_case_variant_ids_do_not_conflict(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        build(session, rows)
        body = rows[3].abstract.replace("C-101", "c-101").replace("P-201", "p-201")
        row_lines = body.splitlines()
        reordered = "\n".join(row_lines[:3] + [row_lines[4], row_lines[3]])
        build(session, additional_document(session, rows, reordered))
        result = current_equipment_investigation(session, rows[0].id, rows[1].id)
        assert result["status"] == "SUPPORTED"
        assert result["demand"] is not None
        assert len(result["evidence"]) == 2


def test_tampered_current_binding_fails_closed_before_rank_limit(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        build(session, rows)
        for _ in range(34):
            stale = additional_document(session, rows, rows[3].abstract)
            build(session, stale)
            stale[4].assessment = {**stale[4].assessment, "evidence_hash": "f" * 64}
        session.flush()
        assert (
            current_equipment_investigation(session, rows[0].id, rows[1].id)["status"]
            == "SUPPORTED"
        )


def test_old_parser_and_model_receipts_do_not_consume_current_bound(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        current = build(session, rows)
        for index in range(34):
            stale = additional_document(session, rows, rows[3].abstract)
            old = build(session, stale)
            old.extractor_version = f"old-parser-{index}"
            old.model = f"old-model-{index}"
            old.question_contract = "old-contract"
            session.flush()
        # The current package is old by creation time; obsolete package versions
        # must not consume the current projection's bounded read.
        current.created_at = datetime(2020, 1, 1, tzinfo=UTC)
        current_result = current_equipment_investigation(session, rows[0].id, rows[1].id)
        assert current_result["status"] == "SUPPORTED"
        assert current_result["demand"] is not None


def test_mutable_binding_history_does_not_starve_restored_current_receipt(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        need, project, observation, evidence, interpretation, source = rows
        original_name, original_location = project.name, project.location
        original_assessment = dict(interpretation.assessment)
        original = build(session, rows)
        for index in range(40):
            project.name = f"Temporary Site {index}"
            project.location = "Midland, TX" if index % 2 else "Odessa, TX"
            interpretation.assessment = {
                **original_assessment,
                "subject": "prairie example llc" if index % 2 else "Prairie Example LLC",
                "project_hint": (
                    " Mock Permian Compression Station "
                    if index % 2
                    else "Mock Permian Compression Station"
                ),
            }
            session.flush()
            assert build(session, rows) is not None
        project.name, project.location = original_name, original_location
        interpretation.assessment = original_assessment
        session.flush()
        restored = build(session, rows)
        assert restored.id == original.id
        result = current_equipment_investigation(session, need.id, project.id)
        assert result["status"] == "SUPPORTED"
        assert result["demand"] is not None


def test_more_than_bound_current_tampered_receipts_fail_closed(equipment_db):
    from datetime import UTC, datetime

    with equipment_db.begin() as session:
        rows = seed(session)
        original = build(session, rows)
        original.created_at = datetime(2020, 1, 1, tzinfo=UTC)
        for index in range(34):
            receipt = build(session, additional_document(session, rows, rows[3].abstract))
            receipt.payload = {**receipt.payload, "demand": {"coincident_kw": str(index)}}
        session.flush()
        assert current_equipment_investigation(session, rows[0].id, rows[1].id) is None


def test_decimal_signature_normalization_is_exact_and_context_independent():
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        assert _canonical_decimal(Decimal("1.2300")) == _canonical_decimal(Decimal("1.23"))
        assert _canonical_decimal(Decimal("12345678901234567890.001")) == (
            "12345678901234567890.001"
        )
        assert _canonical_decimal(Decimal("12345678901234567890.002")) == (
            "12345678901234567890.002"
        )


@pytest.mark.parametrize(
    "replacement", ["Drive: electric or gas engine", "Drive: electric (gas engine)"]
)
def test_ambiguous_drive_cannot_publish_numeric_result(equipment_db, replacement):
    with equipment_db.begin() as session:
        rows = seed(session)
        # Use a separate immutable evidence version, not a modified retained document.
        ambiguous = additional_document(
            session, rows, rows[3].abstract.replace("Drive: electric", replacement)
        )
        result = build(session, ambiguous).payload
        assert result["status"] == "ABSTAINED"
        assert result["demand"] is None


def test_ambiguous_current_schedule_conflicts_with_valid_receipt(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        build(session, rows)
        ambiguous = additional_document(
            session,
            rows,
            rows[3].abstract.replace("Drive: electric", "Drive: electric or gas engine"),
        )
        assert build(session, ambiguous).payload["status"] == "ABSTAINED"
        result = current_equipment_investigation(session, rows[0].id, rows[1].id)
        assert result["status"] == "ABSTAINED"
        assert result["demand"] is None


def test_invalid_company_and_undated_schedule_remain_investigations(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        undated = additional_document(
            session, rows, rows[3].abstract.replace("Company:", "Unattributed:")
        )
        undated[3].published_at = None
        session.flush()
        # Existing source admission may withhold an undated document entirely.
        receipt = build(session, undated)
        assert receipt is None or (
            receipt.payload["status"] == "ABSTAINED" and receipt.payload["demand"] is None
        )


def test_different_effective_schedule_dates_cannot_select_arbitrary_capacity(equipment_db):
    with equipment_db.begin() as session:
        body = (
            "Company: Prairie Example LLC\nFacility: Mock Permian Compression Station\n"
            "As of: 2025-01-01\n"
            "Equipment ID: C-1 | Type: compressor | Drive: electric | "
            "Rating: 100 kW electrical input | Count: 1 | Operating: 1 | State: existing | "
            "Role: duty | Effective until: 2026-01-01"
        )
        rows = seed(session, body=body)
        first = build(session, rows)
        assert first.payload["demand"]["coincident_kw"] == "100"
        second = build(
            session,
            additional_document(
                session, rows, body.replace("As of: 2025-01-01", "As of: 2026-01-02")
            ),
        )
        assert second.payload["demand"]["coincident_kw"] == "0"
        result = current_equipment_investigation(session, rows[0].id, rows[1].id)
        assert result["status"] == "ABSTAINED" and result["demand"] is None


def test_partial_schedule_with_unidentified_unit_cannot_publish_subtotal_as_demand(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        incomplete = additional_document(
            session,
            rows,
            rows[3].abstract
            + (
                "\nType: compressor | Drive: electric | Rating: 200 kW electrical input | "
                "Count: 1 | Operating: 1 | State: new | Role: duty"
            ),
        )
        receipt = build(session, incomplete)
        assert receipt.payload["status"] == "ABSTAINED"
        assert receipt.payload["demand"] is None


def test_official_applicant_and_facility_remain_distinct_with_exact_current_hint(equipment_db):
    with equipment_db.begin() as session:
        rows = seed(session)
        rows[1].name = "Prairie Example LLC"
        rows[4].assessment = {
            **rows[4].assessment,
            "subject": rows[1].name,
            "project_hint": "Mock Permian Compression Station",
        }
        session.flush()
        result = build(session, rows).payload
        assert result["status"] == "SUPPORTED"
        assert result["company"] == "Prairie Example LLC"
        assert result["facility"] == "Mock Permian Compression Station"
        assert result["company_id"] is None and result["decision_maker"] is None
        rows[4].assessment = {**rows[4].assessment, "subject": "Unrelated Company"}
        session.flush()
        assert build(session, rows).payload["status"] == "ABSTAINED"


def test_unchanged_frozen_inputs_do_not_repeat_extraction(equipment_db, monkeypatch):
    import gridlens.intelligence.equipment_intelligence as engine

    with equipment_db.begin() as session:
        rows = seed(session)
        first = build(session, rows)

        def unexpected_extraction(_):
            raise AssertionError("Unchanged ingestion repeated extraction")

        monkeypatch.setattr(engine, "extract_equipment_claims", unexpected_extraction)
        assert build(session, rows).id == first.id


def test_disjoint_future_operating_windows_publish_partial_not_simultaneous_total(equipment_db):
    with equipment_db.begin() as session:
        body = (
            "Company: Prairie Example LLC\nFacility: Mock Permian Compression Station\n"
            "Equipment ID: P-1 | Type: pump | Drive: electric | Rating: 100 kW electrical input | "
            "Count: 1 | Operating: 1 | State: proposed | Role: duty | "
            "Effective from: 2030-01-01 | Effective until: 2030-12-31\n"
            "Equipment ID: P-2 | Type: pump | Drive: electric | Rating: 100 kW electrical input | "
            "Count: 1 | Operating: 1 | State: proposed | Role: duty | "
            "Effective from: 2031-01-01 | Effective until: 2031-12-31"
        )
        result = build(session, seed(session, body=body)).payload
        assert result["status"] == "PARTIAL"
        assert result["demand"]["connected_kw"] == "200"
        assert result["demand"]["coincident_kw"] is None
        assert result["classification"] == "UNKNOWN"
        assert any("windows do not overlap" in q for q in result["unresolved_questions"])


@pytest.mark.parametrize(
    "prose", ["", "HVAC compressors will be serviced.", "Equipment is stored onsite."]
)
def test_ordinary_permit_metadata_does_not_materialize_equipment_investigation(equipment_db, prose):
    with equipment_db.begin() as session:
        rows = seed(
            session,
            body=(
                "Company: Prairie Example LLC\nFacility: Mock Permian Compression Station\n"
                "Type: Construction Permit\nState: OK\nStatus: Under Review\n" + prose
            ),
        )
        assert build(session, rows) is None
        assert session.scalar(select(func.count()).select_from(EvidencePackage)) == 0
        assert current_equipment_investigation(session, rows[0].id, rows[1].id) is None
