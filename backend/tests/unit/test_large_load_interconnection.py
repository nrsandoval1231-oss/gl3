"""Synthetic request fixtures; none represents an actual project or commitment."""

import unittest
from copy import deepcopy
from datetime import date
from importlib import import_module


class LargeLoadInterconnectionTests(unittest.TestCase):
    def state(self, facts, *, today=date(2026, 10, 8), extra=()):
        module = import_module("gridlens.domain.large_load_interconnection")
        record = {
            "request_id": "synthetic-request-1",
            "evidence": {
                "id": "e1",
                "hash": "a" * 64,
                "url": "https://example.test/filing",
                "published_at": "2026-10-08",
                "retrieved_at": "2026-10-08T12:00:00Z",
                "extraction_location": "request schedule",
            },
            "text": "Synthetic request schedule: " + repr(facts),
            "facts": [{"field": k, "value": v, "quote": repr(facts)} for k, v in facts.items()],
        }
        return module.interconnection_state([record, *extra], today=today)["requests"][0]

    def base(self, **changes):
        return {
            "ercot_region": True,
            "energized_as_of_effective_date": False,
            "request_kind": "new",
            "expected_site_peak_mw": "75",
            "colocated_generation": False,
            **changes,
        }

    def test_threshold_and_incremental_expansion(self):
        cases = [
            (self.base(expected_site_peak_mw="74.9"), "NOT_APPLICABLE", None),
            (self.base(), "APPLIES", "3750000"),
            (
                self.base(
                    request_kind="expanded", existing_site_peak_mw="60", expected_site_peak_mw="75"
                ),
                "APPLIES",
                "750000",
            ),
            (
                self.base(
                    request_kind="expanded",
                    existing_site_peak_mw="100",
                    expected_site_peak_mw="174",
                ),
                "NOT_APPLICABLE",
                None,
            ),
            (
                self.base(
                    request_kind="expanded",
                    existing_site_peak_mw="100",
                    expected_site_peak_mw="175",
                ),
                "APPLIES",
                "3750000",
            ),
            (self.base(ercot_region=False), "NOT_APPLICABLE", None),
            (self.base(energized_as_of_effective_date=True), "NOT_APPLICABLE", None),
        ]
        for facts, applies, security in cases:
            with self.subTest(facts=facts):
                view = self.state(facts)["interpretation"]
                self.assertEqual(view["applicability"], applies)
                self.assertEqual(view["intermediate_security_baseline_usd"], security)

    def test_unknown_scope_cannot_be_inferred_from_campus_size(self):
        for field in ("ercot_region", "energized_as_of_effective_date", "request_kind"):
            facts = self.base()
            del facts[field]
            self.assertEqual(self.state(facts)["interpretation"]["applicability"], "UNKNOWN")

    def test_publication_is_not_effective_date(self):
        view = self.state(self.base(), today=date(2026, 10, 7))["interpretation"]
        self.assertFalse(view["rule_in_effect"])
        self.assertIsNone(view["intermediate_security_baseline_usd"])

    def test_report_issue_date_starts_clock_without_proving_service(self):
        view = self.state(
            self.base(allocating_study_report_issued_on="2026-10-10", allocated_mw="0"),
            today=date(2026, 12, 10),
        )
        self.assertEqual(view["interpretation"]["sllia_due_on"], "2026-12-09")
        self.assertEqual(
            view["interpretation"]["sllia_follow_up"], "DEADLINE_PASSED_CHECK_EVIDENCE"
        )
        self.assertNotIn("tier", view)
        self.assertNotIn("supply", view)
        self.assertEqual(view["facts"]["allocated_mw"]["value"], "0")

    def test_execution_and_funding_remain_distinct(self):
        view = self.state(self.base(intermediate_executed_on="2026-10-08"))
        self.assertEqual(view["facts"]["intermediate_executed_on"]["status"], "REPORTED")
        self.assertEqual(view["facts"]["intermediate_funded_on"]["status"], "UNKNOWN")
        self.assertEqual(view["facts"]["study_state"]["status"], "UNKNOWN")
        self.assertEqual(view["facts"]["financial_security_usd"]["status"], "UNKNOWN")

    def test_batch_zero_requires_separate_financial_review(self):
        view = self.state(self.base(batch_zero=True))["interpretation"]
        self.assertIsNone(view["intermediate_security_baseline_usd"])
        self.assertTrue(view["transition_review_required"])

    def test_conflicting_and_unquoted_facts_do_not_drive_interpretation(self):
        record = {
            "request_id": "synthetic-request-1",
            "text": "Peak 80 MW",
            "evidence": {
                "id": "e2",
                "hash": "b" * 64,
                "url": "https://example.test/other",
                "published_at": "2026-10-08",
                "retrieved_at": "2026-10-08T12:00:00Z",
                "extraction_location": "page 2",
            },
            "facts": [{"field": "expected_site_peak_mw", "value": "80", "quote": "Peak 80 MW"}],
        }
        view = self.state(self.base(), extra=[record])
        self.assertEqual(view["facts"]["expected_site_peak_mw"]["status"], "CONFLICT")
        self.assertEqual(view["interpretation"]["applicability"], "UNKNOWN")
        bad = deepcopy(record)
        bad["facts"][0]["quote"] = "not retained"
        self.assertEqual(
            self.state(self.base(), extra=[bad])["interpretation"]["applicability"], "APPLIES"
        )

    def test_undated_or_malformed_claims_are_visible_limitations(self):
        view = self.state(self.base(expected_site_peak_mw="NaN", study_state="ready"))
        self.assertEqual(view["interpretation"]["applicability"], "UNKNOWN")
        self.assertGreaterEqual(len(view["limitations"]), 1)

    def test_no_request_facts_returns_empty_instead_of_creating_a_project(self):
        module = import_module("gridlens.domain.large_load_interconnection")
        self.assertEqual(module.interconnection_state([], today=date(2026, 10, 8))["requests"], [])

    def test_unknown_colocation_does_not_exempt_small_expansion(self):
        facts = self.base(
            request_kind="expanded", existing_site_peak_mw="100", expected_site_peak_mw="120"
        )
        del facts["colocated_generation"]
        self.assertEqual(self.state(facts)["interpretation"]["applicability"], "UNKNOWN")

    def test_co_location_and_financial_evidence_are_separate_from_security_baseline(self):
        facts = self.base(
            request_kind="expanded",
            existing_site_peak_mw="100",
            expected_site_peak_mw="120",
            colocated_generation=True,
            financial_security_usd="1000000",
            financial_security_form="guaranty",
            financial_security_stage="intermediate",
        )
        view = self.state(facts)
        self.assertEqual(view["interpretation"]["applicability"], "APPLIES")
        self.assertEqual(view["interpretation"]["intermediate_security_baseline_usd"], "1000000")
        self.assertEqual(view["facts"]["financial_security_form"]["value"], "guaranty")

    def test_missing_report_date_never_uses_publication_for_deadline(self):
        view = self.state(self.base(allocated_mw="75"))["interpretation"]
        self.assertIsNone(view["sllia_due_on"])

    def test_inflation_baseline_not_silently_used_from_2032(self):
        view = self.state(self.base(), today=date(2032, 1, 1))["interpretation"]
        self.assertIsNone(view["intermediate_security_baseline_usd"])


if __name__ == "__main__":
    unittest.main()
