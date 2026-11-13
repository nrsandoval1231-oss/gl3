"""Controls for binding a matched site activity to its selected subject."""

from gridlens.domain.project_activity_binding import activity_is_bound_to_project


def _span(text: str, value: str, *, start: int = 0) -> tuple[int, int]:
    left = text.index(value, start)
    return left, left + len(value)


def test_direct_construction_status_binds_named_site_and_locality():
    text = "The new Dallas data center campus in Red Oak, Texas is under construction."
    subject = _span(text, "Dallas data center campus")
    site = _span(text, "in Red Oak, Texas")
    activity = _span(text, "under construction")

    assert activity_is_bound_to_project(
        text,
        subject_span=subject,
        activity_span=activity,
        site_span=site,
    )


def test_active_development_verb_must_govern_selected_site_object():
    text = "DataBank plans to develop a new data center campus in Red Oak, Texas."
    subject = _span(text, "new data center campus")
    site = _span(text, "in Red Oak, Texas")
    activity = _span(text, "plans to develop")

    assert activity_is_bound_to_project(
        text,
        subject_span=subject,
        activity_span=activity,
        site_span=site,
    )


def test_development_verb_does_not_govern_a_site_after_another_facility_clause():
    text = (
        "Acme plans to develop Beta facility that will power a new data center campus "
        "in Dallas, Texas."
    )
    subject = _span(text, "new data center campus")
    site = _span(text, "in Dallas, Texas")
    activity = _span(text, "plans to develop")

    assert not activity_is_bound_to_project(
        text,
        subject_span=subject,
        activity_span=activity,
        site_span=site,
    )


def test_data_center_announcement_uses_development_verb_object_and_locality():
    text = (
        "DataBank today announced the development of a 480MW data center campus on 292 acres "
        "of land in Red Oak, TX."
    )
    subject = _span(text, "data center campus")
    site = _span(text, "in Red Oak, TX")
    activity = _span(text, "development of")

    assert activity_is_bound_to_project(
        text,
        subject_span=subject,
        activity_span=activity,
        site_span=site,
    )


def test_planned_campus_development_is_bound_to_its_park_relation():
    text = (
        "Aligned announces a planned development of its new data center campus "
        "inside the Conesville Industrial Park."
    )
    subject = _span(text, "its new data center campus")
    site = _span(text, "inside the Conesville Industrial Park")
    activity = _span(text, "planned development of")

    assert activity_is_bound_to_project(
        text,
        subject_span=subject,
        activity_span=activity,
        site_span=site,
    )


def test_resolved_anaphor_allows_direct_local_status_only():
    text = "The facility is under construction."
    subject = _span(text, "The facility")
    activity = _span(text, "under construction")

    assert activity_is_bound_to_project(
        text,
        subject_span=subject,
        activity_span=activity,
        site_span=subject,
    )


def test_resolved_project_facility_directly_owns_relative_status():
    text = (
        "The deal secures power and land to support a new state of the art facility "
        "that is currently under construction."
    )
    subject = _span(text, "a new state of the art facility")
    activity = _span(text, "under construction")

    assert activity_is_bound_to_project(
        text,
        subject_span=subject,
        activity_span=activity,
        site_span=subject,
    )


def test_competing_facility_subordinate_clause_does_not_borrow_status():
    text = (
        "The Dallas data center campus in Dallas, Texas receives power from "
        "Beta facility which is under construction."
    )
    subject = _span(text, "Dallas data center campus")
    site = _span(text, "in Dallas, Texas")
    activity = _span(text, "under construction")

    assert not activity_is_bound_to_project(
        text,
        subject_span=subject,
        activity_span=activity,
        site_span=site,
    )


def test_resolved_anaphor_cannot_borrow_status_from_foreign_subordinate():
    text = "This facility receives power from Beta plant which is under construction."
    subject = _span(text, "This facility")
    activity = _span(text, "under construction")

    assert not activity_is_bound_to_project(
        text,
        subject_span=subject,
        activity_span=activity,
        site_span=subject,
    )


def test_source_local_anaphor_cannot_borrow_supplier_construction_status():
    text = "This facility receives power from Beta plant, which is under construction."
    subject = _span(text, "This facility")
    activity = _span(text, "under construction")

    assert not activity_is_bound_to_project(
        text,
        subject_span=subject,
        activity_span=activity,
        site_span=subject,
    )


def test_negated_construction_status_is_rejected():
    text = "The Dallas data center campus in Dallas, Texas is not yet currently under construction."
    subject = _span(text, "Dallas data center campus")
    site = _span(text, "in Dallas, Texas")
    activity = _span(text, "under construction")

    assert not activity_is_bound_to_project(
        text,
        subject_span=subject,
        activity_span=activity,
        site_span=site,
    )


def test_hypothetical_after_the_activity_predicate_is_rejected():
    text = (
        "The new data center campus in Dallas, Texas is under construction "
        "in this hypothetical example."
    )
    subject = _span(text, "data center campus")
    site = _span(text, "in Dallas, Texas")
    activity = _span(text, "under construction")

    assert not activity_is_bound_to_project(
        text,
        subject_span=subject,
        activity_span=activity,
        site_span=site,
    )


def test_other_facility_contractor_clause_does_not_bind_activity_to_selected_site():
    text = (
        "The new data center campus in Dallas, Texas has a contractor whose other facility "
        "is under construction."
    )
    subject = _span(text, "data center campus")
    site = _span(text, "in Dallas, Texas")
    activity = _span(text, "under construction")

    assert not activity_is_bound_to_project(
        text,
        subject_span=subject,
        activity_span=activity,
        site_span=site,
    )


def test_unrelated_named_site_between_subject_and_activity_is_rejected():
    text = (
        "The Dallas data center campus in Dallas, Texas connects to Beta facility, "
        "which is under construction."
    )
    subject = _span(text, "Dallas data center campus")
    site = _span(text, "in Dallas, Texas")
    activity = _span(text, "under construction")

    assert not activity_is_bound_to_project(
        text,
        subject_span=subject,
        activity_span=activity,
        site_span=site,
    )
