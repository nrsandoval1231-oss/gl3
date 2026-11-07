"""Source-semantic regressions; fixtures are synthetic, not claimed live records."""

from datetime import date

import pytest

from gridlens.domain.opportunity_shortlist import shortlist_assessment

TODAY = date(2026, 11, 6)


def source(scope, *, title="Official project permit", **extra):
    return {
        "id": "evidence-1",
        "source_id": "official-permits",
        "assessment_current": True,
        "title": title,
        "abstract": f"description: {scope}\nstatus: Active",
        "event_date": "2026-10-01",
        "event_date_label": "Permit issued",
        **extra,
    }


def assess(*sources, **compact):
    return shortlist_assessment(compact, list(sources), as_of=TODAY)


@pytest.mark.parametrize(
    "scope",
    [
        (
            "800A Temporary Service for construction power including 250A "
            "Crane Power and 200A Buck Hoist power."
        ),
        "Install 400A temporary meter loop for construction power to elementary school remodel.",
        "600amp 480volt overhead service for temporary power.",
        (
            "Emergency-Temporary Electrical wiring to reenergize occupied "
            "spaces until permanent repairs can be made."
        ),
        (
            "Replace existing Generator and Fuel Tank; electrical scope split "
            "into 7 phases to maintain emergency power to the hospital. "
            "Fenced switchboard."
        ),
        (
            "TEMPORARY ELECTRICAL PERMIT - Electrical underground work "
            "associated with foundations for the Factory building."
        ),
        "Interior remodel to existing manufacturing facility (20000 SF).",
        "Install new electric motor-driven compressor at the existing processing station.",
    ],
)
def test_specific_electrical_or_substantial_development_survives_unknown_mw(scope):
    result = assess(source(scope), required_mw=None)
    assert result["eligible"]
    assert result["evidence_refs"] == ["evidence-1"]
    assert "MW unknown" in result["reasons"][-1]
    assert "Permit issued 2026-10-01" in result["why_now"]


@pytest.mark.parametrize(
    "scope",
    [
        "Install new non-electric compressor at the existing station.",
        "Install new compressor that is not electrically driven at the existing station.",
        "Install new compressor with no electric drive at the existing station.",
        "Install new compressor without electrical drive at the existing station.",
        "Install new not electric compressor at the existing station.",
        "Install a new compressor with no electric motor at the existing station.",
        "Install new not motor-driven pump at the existing station.",
        "Install new compressor without an electric drive.",
        "Install new compressor that is not an electric model.",
        "Install new non-motor-driven pump.",
        "Install new compressor; electric pump is not included.",
    ],
)
def test_explicitly_non_electric_equipment_does_not_claim_electrical_drive(scope):
    result = assess(source(scope), required_mw=None)
    assert result["eligible"] is False
    assert result["priority"] != 80
    assert all("electrically driven" not in reason for reason in result["reasons"])


def test_non_electric_equipment_does_not_hide_other_industrial_development_or_affirmative_drive():
    industrial = assess(source("New industrial campus expansion with a non-electric compressor."))
    assert industrial["eligible"] is True
    assert industrial["priority"] == 70
    assert all("electrically driven" not in reason for reason in industrial["reasons"])

    affirmative = assess(source("Install new non-electric compressor; install new electric pump."))
    assert affirmative["eligible"] is True
    assert affirmative["priority"] == 80
    assert any("electrically driven" in reason for reason in affirmative["reasons"])

    replacement = assess(source("Replace non-electric compressor with new electric compressor."))
    assert replacement["eligible"] is True
    assert replacement["priority"] == 80
    assert any("electrically driven" in reason for reason in replacement["reasons"])


@pytest.mark.parametrize(
    "scope",
    [
        "Replace pump at El Paso Electric Montana Power Station.",
        "Electrical contractor to install new pump.",
        "Install new electrical service for pump station.",
        "Install new compressor at Example Electric Company.",
        "Install new pump; electrical contractor will complete the work.",
        "Install new compressor with electrical service.",
        "Replace pump at Electric Motor Company.",
    ],
)
def test_electrical_party_or_service_context_does_not_establish_equipment_drive(scope):
    result = assess(source(scope))
    assert not result["eligible"]
    assert not result["evidence_refs"]
    assert all("electrically driven" not in reason for reason in result["reasons"])


@pytest.mark.parametrize(
    "scope",
    [
        "Install a new electric compressor.",
        "Install a new motor-driven pump.",
        "Install a new electrically driven pump.",
        "Install a new electrically-driven centrifugal pump.",
        "Install a new compressor that is electrically driven.",
        "Install a new pump driven by an electric motor.",
        "Install a new compressor with an electric drive.",
        "Upgrade existing pump to electric drive.",
        "Electrical contractor to install a new electric pump.",
    ],
)
def test_explicit_equipment_modifier_or_drive_relation_supports_electrical_interpretation(scope):
    result = assess(source(scope), required_mw=None)
    assert result["eligible"]
    assert result["priority"] == 80
    assert any("electrically driven" in reason for reason in result["reasons"])
    assert any("MW unknown" in reason for reason in result["reasons"])


def test_unproven_pump_drive_does_not_remove_independent_industrial_construction():
    result = assess(
        source("New industrial campus construction. Electrical contractor to install new pump.")
    )
    assert result["eligible"]
    assert result["priority"] == 70
    assert all("electrically driven" not in reason for reason in result["reasons"])


@pytest.mark.parametrize(
    "scope",
    [
        "TEMPORARY ELECTRICAL PERMIT - Scope limited to sports light pole foundations and poles.",
        "New chain link fence to serve an existing warehouse.",
        "New dry well for AC condensation drainage at warehouse.",
        "Product launch event with tents and an LED screen for 100 people.",
        (
            "Temporary power for an event with temporary generators and "
            "distribution for stage vendors."
        ),
        "Need permit for temporary power.",
        "APPROVED temporary electrical permit for inspections.",
        "Replace roof only at existing data center building.",
        "No temporary power required for construction work.",
        "Temporary service is not required for school construction.",
    ],
)
def test_generic_labels_and_minor_or_negated_work_do_not_qualify(scope):
    result = assess(
        source(scope),
        _priority_features={"evidence_construction": True},
        required_mw=100,
        demand_quote="invented",
    )
    assert not result["eligible"]
    assert not result["evidence_refs"]
    assert result["why_now"] is None


def test_drilling_permission_and_existing_registration_are_not_demand():
    assert not assess(source("Drill well 2H", title="W-1 well permit 1234567"))["eligible"]
    assert not assess(source("PBR EXISTING REGISTRATION", title="Example Data Center"))["eligible"]


@pytest.mark.parametrize(
    "title,abstract",
    [
        (
            "First building at Mesa data center campus topped out",
            "Structural work on first building complete, three more to go",
        ),
        ("Example and Other to build 50MW data center", "Companies to build at named Desert site."),
        (
            "Example to spend $600M on campus in Texas",
            "New manufacturing and engineering center will expand production capacity.",
        ),
    ],
)
def test_retained_news_headline_and_abstract_are_meaningful_events(title, abstract):
    result = assess(
        source(
            "",
            title=title,
            abstract=abstract,
            source_id="industry-news",
            event_date=None,
            published_at="2026-10-27",
        )
    )
    assert result["eligible"]
    assert result["why_now"].startswith("Published 2026-10-27:")
    assert result["duplicate_key"]


def test_colon_in_unstructured_news_prose_does_not_suppress_scope_fallback():
    base = {
        "title": "Example to spend $600M on Texas campus",
        "source_id": "industry-news",
        "event_date": None,
        "published_at": "2026-10-27",
    }
    colon = assess(
        source(
            "",
            **base,
            abstract="Plans include: new manufacturing construction and engineering facilities.",
        )
    )
    plain = assess(
        source(
            "",
            **base,
            abstract="Plans include new manufacturing construction and engineering facilities.",
        )
    )
    assert colon["eligible"] is True
    assert colon["eligible"] == plain["eligible"]
    assert colon["priority"] == plain["priority"]
    assert colon["reasons"] == plain["reasons"]


def test_review_complete_is_not_completed_construction_and_buildings_stay_distinct():
    result = []
    for building in ("A", "B", "C"):
        result.append(
            assess(
                source(
                    "",
                    title="Example Data Center",
                    abstract=(
                        f"Project: Example Data Center (Building {building})\n"
                        "Scope: New data center building\nTABS status: Review Complete"
                    ),
                )
            )
        )
    assert all(r["eligible"] for r in result)
    assert len({r["source_subject"] for r in result}) == 3
    assert all(r["duplicate_key"] is None for r in result)


def test_new_building_permit_can_report_facility_scale_without_activity_mw():
    result = assess(
        source(
            "",
            title="Campus building 2",
            abstract=(
                "Permit: PB26-12345 · Commercial Building Permit · New\nWork "
                "description: 488628 SF 196MW data center\nStatus: Plan Review"
            ),
        )
    )
    assert result["eligible"]
    assert "MW unknown" in result["reasons"][-1]


@pytest.mark.parametrize(
    "extra",
    [
        {"assessment_current": False},
        {"source_id": ""},
        {"id": ""},
        {"event_date": None},
        {"event_date": "2024-10-01", "observed_at": "2026-11-06"},
        {"event_date": "2026-12-01"},
        {"published_at": "2026-12-01"},
        {"abstract": "description: New data center building\nStatus: Complete"},
    ],
)
def test_binding_status_and_source_freshness_fail_closed(extra):
    assert not assess(source("New data center building", **extra))["eligible"]


def test_future_developer_schedule_does_not_invalidate_current_registration():
    result = assess(
        source(
            "",
            title="Example Data Center",
            abstract=(
                "Project: Example DC\nScope: New data center "
                "building\nDeveloper-reported start: 2027-01-01; completion: "
                "2028-01-01"
            ),
        )
    )
    assert result["eligible"]
    assert "2027" not in result["why_now"]  # no invented actual start


def test_contact_lines_do_not_supply_scope_or_escape_in_excerpts():
    raw = source("New data center building call 512-555-0100 or test@example.com")
    raw["abstract"] += "\ncontractor_phone: 5125550111\napplicant_email: private@example.com"
    result = assess(raw)
    rendered = str(result)
    assert result["eligible"]
    assert "512" not in rendered
    assert "@" not in rendered
    assert not assess(
        source(
            "Replace fence",
            abstract="Contact: New data center construction\nDescription: Replace fence",
        )
    )["eligible"]


def test_address_and_contact_metadata_alone_do_not_become_source_scope():
    for abstract in (
        "Address: 100 Example Way, Austin, TX\nContact: New data center construction",
        "Applicant: New data center construction",
        "Contractor: New data center construction",
        "Owner: New data center construction",
        "Permit number: New data center construction",
    ):
        assert not assess(source("", abstract=abstract))["eligible"]


@pytest.mark.parametrize(
    "label",
    [
        "Project applicant",  # CEQAnet
        "Lead agency",
        "Owner of record",  # Fort Worth
        "Owner contact email",  # TDLR
        "Design firm",
        "Primary contact",  # San Antonio
        "Legal name",  # TCEQ
        "Physical location",
        "Permit/status number",  # RRC
        "API number",
        "Sponsor as filed",  # FAA
        "Transmission owner",  # ERCOT
        "contractor_company_name",  # Socrata
        "applicant_org",
        "owner_name",  # El Paso
    ],
)
def test_native_adapter_metadata_cannot_supply_missing_development_scope(label):
    metadata = f"{label}: New data center construction"
    missing_scope = assess(source("", abstract=metadata))
    assert not missing_scope["eligible"]
    assert missing_scope["evidence_refs"] == []
    assert missing_scope["why_now"] is None

    # The same metadata must not block real work: only the explicit description
    # supplies the activity evidence, and metadata is absent from its excerpt.
    actual_scope = "Install a new electric compressor at the processing station."
    supported = assess(source("", abstract=f"{metadata}\nDescription: {actual_scope}"))
    assert supported["eligible"]
    assert supported["scope"] == actual_scope
    assert metadata not in supported["why_now"]


def test_party_words_in_colon_prose_are_not_treated_as_metadata_labels():
    result = assess(
        source(
            "",
            title="Example Texas manufacturing campus update",
            abstract=(
                "The project applicant confirmed: new manufacturing construction begins this month."
            ),
        )
    )
    assert result["eligible"]
    assert "new manufacturing construction" in result["scope"]


def test_exact_paired_permit_scope_clusters_without_merging_phase_or_site():
    def permit(suffix, address="1 SITE RD", scope="Generator replacement and new ATS"):
        return source(
            "",
            abstract=(
                f"row: 2026-100000 {suffix}\naddress: {address}\n"
                f"description: {scope}\nstatus: Active"
            ),
        )

    bp, ep = assess(permit("BP")), assess(permit("EP"))
    assert bp["duplicate_key"] == ep["duplicate_key"] is not None
    assert bp["duplicate_key"] != assess(permit("EP", address="2 SITE RD"))["duplicate_key"]
    assert (
        bp["duplicate_key"]
        != assess(permit("EP", scope="Generator replacement and new ATS phase 2"))["duplicate_key"]
    )


def test_summary_reasons_and_evidence_count_cannot_self_certify():
    result = assess(
        source("Painting only"),
        supported_action="New data center construction",
        assessment_reason="Construction",
        evidence_count=100,
        lifecycle_state="construction",
    )
    assert not result["eligible"]


@pytest.mark.parametrize(
    "title,scope",
    [
        (
            "Refinery expansion update",
            "No expansion of the refinery is proposed. Renewal of the existing permit only.",
        ),
        (
            "New data center construction",
            "New data center construction is not proposed; administrative ownership transfer only.",
        ),
    ],
)
def test_explicitly_negated_development_does_not_promote_from_title(title, scope):
    assert not assess(source(scope, title=title))["eligible"]


def test_negated_scope_does_not_veto_separate_affirmative_equipment_work():
    result = assess(
        source(
            "No expansion of the refinery is proposed, but install a new electric compressor.",
            title="Permit update",
        )
    )
    assert result["eligible"]
    assert any("electrically driven" in reason for reason in result["reasons"])


def test_negated_development_title_cannot_be_rescued_by_generic_permit_language():
    result = assess(
        source(
            "New data center construction is not proposed. New permit holder name only.",
            title="New data center construction",
        )
    )
    assert not result["eligible"]


def test_negated_construction_does_not_veto_independent_equipment_work():
    result = assess(
        source(
            "No construction is proposed, but install a new electric compressor.",
            title="Permit update",
        )
    )
    assert result["eligible"]
    assert any("electrically driven" in reason for reason in result["reasons"])


def test_jev_hold_is_source_bound_and_sparse_coverage_abstains():
    held = source("New data center construction", id="jev-held", jev_decision="HOLD")
    unreviewed = source("New data center construction", id="unreviewed")
    result = assess(held, unreviewed)
    assert result["eligible"]
    assert result["evidence_refs"] == ["unreviewed"]

    assert not assess(held)["eligible"]
    # REVIEW and unknown decisions do not veto source-backed deterministic relevance.
    reviewed = source("New data center construction", id="reviewed", jev_decision="REVIEW")
    assert assess(reviewed)["eligible"]


def test_jev_show_only_breaks_equal_deterministic_triage_ties():
    plain = source("New data center construction phase one", id="z-plain")
    shown = source("New data center construction phase two", id="a-shown", jev_decision="SHOW")
    result = assess(plain, shown)
    assert result["eligible"]
    assert result["why_now"].startswith("Permit issued 2026-10-01:")
    assert "phase two" in result["why_now"]
    assert result["evidence_refs"] == ["a-shown", "z-plain"]


def test_published_future_developer_milestone_is_retained_as_estimate():
    result = assess(
        source(
            "New data center construction",
            event_date="2027-01-01",
            event_date_label="Developer-reported start",
            published_at="2026-10-01",
        )
    )
    assert result["eligible"]
    assert result["why_now"].startswith("Published 2026-10-01:")
    assert "Developer-reported start 2027-01-01 (estimate)" in result["why_now"]
    assert not assess(
        source(
            "New data center construction",
            event_date="2027-01-01",
            event_date_label="Permit issued",
            published_at="2026-10-01",
        )
    )["eligible"]


@pytest.mark.parametrize(
    "scope",
    [
        "Utility energization delayed until March; temporary bridge supply is being evaluated.",
        "Permanent service unavailable until the new feeder is complete.",
    ],
)
def test_named_source_project_energization_constraint_needs_no_numeric_load(scope):
    result = assess(source("", abstract=f"Project: North Works\nScope: {scope}"))
    assert result["eligible"]
    assert "energization" in result["reasons"][0]
    assert "interim supply" in result["next_step"]


def test_negated_constraint_is_not_positive_evidence_or_a_demand_veto():
    assert not assess(
        source(
            "", abstract="Project: North Works\nScope: No utility energization delay is reported."
        )
    )["eligible"]
    assert assess(source("New data center construction. No temporary power required."))["eligible"]


@pytest.mark.parametrize(
    "project", ["13782067", "2026-129288", "2026-129288 EP", "PB26-12345", "Permit # 123456"]
)
def test_internal_project_numbers_and_document_ids_are_not_customer_titles(project):
    result = assess(
        source(
            "",
            title="Austin building permit 2026-129288 EP",
            abstract=(
                f"project: {project}\n"
                "description: Emergency-Temporary Electrical wiring to "
                "reenergize occupied spaces.\n"
                "status: Active"
            ),
        )
    )
    assert result["eligible"]
    assert result["source_subject"] == "Temporary electrical restoration"
    assert project not in result["source_subject"]


@pytest.mark.parametrize(
    "scope,expected",
    [
        ("800A Temporary Service for construction power", "Construction electrical service"),
        ("Generator replacement and new ATS", "Generator/transfer-switch replacement"),
        ("New factory foundations", "Industrial construction"),
        ("New data center building", "Data center buildout"),
    ],
)
def test_source_category_titles_are_concise_when_the_source_has_no_project_name(scope, expected):
    result = assess(source(scope))
    assert result["eligible"]
    assert result["source_subject"] == expected


@pytest.mark.parametrize(
    "scope",
    [
        (
            "New shell addition to existing hospital, 5 floors. There are four "
            "4000 amp services to be metered at the transformer."
        ),
        (
            "New Construction Industrial Warehouse, Hydraulics/Bearings Shop. "
            "An 800 amp service for future tenants and a 400 amp service for unit 100."
        ),
        (
            "TEMPORARY ELECTRICAL PERMIT - Electrical underground work associated "
            "with the foundations for the Utility Plant for Project Example."
        ),
        (
            "TEMPORARY ELECTRICAL PERMIT - Electrical underground work associated "
            "with the foundations for the Castings building for Project Example."
        ),
    ],
)
def test_independent_excluded_audit_material_electrical_buildout_regressions(scope):
    # Generalized cases discovered in the separate excluded-source audit;
    # these are not part of the original calibration sample or a new holdout.
    result = assess(source(scope), required_mw=None)
    assert result["eligible"]
    assert result["source_subject"] == "Commercial electrical buildout"
    assert "service ratings are not MW" in result["reasons"][0]
    assert "energization schedule" in result["next_step"]


@pytest.mark.parametrize(
    "scope",
    [
        "New retaining wall at an existing data center.",
        "New structural foundations for the utility plant; structural steel only.",
        "New hospital parking garage with no electrical work proposed.",
        "Hospital renovation. Electrical permit for painting existing service enclosure.",
        "Industrial warehouse maintenance with 800 square feet of new shelving.",
    ],
)
def test_commercial_context_and_civil_work_alone_do_not_become_electrical_buildout(scope):
    assert not assess(source(scope))["eligible"]
