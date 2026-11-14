"""Integrity tests for the additive, proposed reference context overlay."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
V1 = ROOT / "eval/customer-commercial-v1"
sys.path.insert(0, str(HERE))
import build_reference_context as builder  # noqa: E402


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha(value: object) -> str:
    return sha(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    )


class ReferenceContextV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.overlay = json.loads((HERE / "source-context-annotations.json").read_text())
        cls.gold_bytes = (V1 / "reference-customers-r2.json").read_bytes()
        cls.gold = json.loads(cls.gold_bytes)
        cls.records = {record["id"]: record for record in cls.gold["records"]}
        cls.annotations = {
            record["reference_record_id"]: record for record in cls.overlay["records"]
        }

    def test_v1_tree_matches_frozen_preservation_manifest(self) -> None:
        manifest = json.loads((HERE / "v1-preservation-manifest.json").read_text())
        current = {
            path.relative_to(V1).as_posix(): sha(path.read_bytes())
            for path in sorted(V1.rglob("*"))
            if path.is_file()
        }
        self.assertEqual(current, manifest["files_sha256"])
        self.assertEqual(
            self.overlay["preserved_v1_json_sha256"],
            {
                f"eval/customer-commercial-v1/{name}": digest
                for name, digest in sorted(current.items())
            },
        )
        self.assertEqual(sha(self.gold_bytes), self.overlay["v1_reference_sha256"])

    def test_all_twenty_records_sources_and_assertions_are_covered(self) -> None:
        self.assertEqual(self.overlay["record_count"], 20)
        self.assertEqual(set(self.annotations), set(self.records))
        all_assertions = 0
        for record_id, annotation in self.annotations.items():
            source_ids = {
                item["source_id"] for item in self.records[record_id]["provenance"]
            }
            annotated_sources = {
                item["source_id"] for item in annotation["source_bundles"]
            }
            self.assertEqual(annotated_sources, source_ids, record_id)
            evidence_ids = {
                item["id"] for item in annotation["source_context_evidence"]
            }
            self.assertEqual(
                len(evidence_ids), len(annotation["source_context_evidence"]), record_id
            )
            physical = annotation["physical_subject"]
            self.assertTrue(set(physical["evidence_refs"]) <= evidence_ids)
            for phrase in physical["source_phrase_evidence"]:
                self.assertIn(phrase["evidence_ref"], evidence_ids)
                evidence = next(
                    item
                    for item in annotation["source_context_evidence"]
                    if item["id"] == phrase["evidence_ref"]
                )
                self.assertEqual(phrase["exact_quote"], evidence["quote"])
            for section in (
                annotation["asset_scope"],
                annotation["source_supported_location"],
                annotation["organization_role"],
            ):
                self.assertTrue(
                    set(section["evidence_refs"]) <= evidence_ids, record_id
                )
            for entity in annotation["other_named_entities_not_site_aliases"]:
                self.assertIn(entity["evidence_ref"], evidence_ids)
            for alias in annotation["source_supported_aliases"]:
                self.assertIn(alias["evidence_ref"], evidence_ids)
                evidence = next(
                    item
                    for item in annotation["source_context_evidence"]
                    if item["id"] == alias["evidence_ref"]
                )
                self.assertIn(
                    alias["value"], evidence["quote"], (record_id, alias["value"])
                )
            for child in annotation["source_supported_child_identifiers"]:
                self.assertIn(child["evidence_ref"], evidence_ids)
                evidence = next(
                    item
                    for item in annotation["source_context_evidence"]
                    if item["id"] == child["evidence_ref"]
                )
                self.assertIn(
                    child["value"], evidence["quote"], (record_id, child["value"])
                )
            for bundle in annotation["source_bundles"]:
                self.assertTrue(
                    bundle["evidence_refs"], (record_id, bundle["source_id"])
                )
                self.assertTrue(set(bundle["evidence_refs"]) <= evidence_ids)
            expected = sum(
                len(self.records[record_id][kind]) for kind in ("capacity", "timeline")
            )
            self.assertEqual(len(annotation["assertion_context"]), expected, record_id)
            all_assertions += expected
        self.assertEqual(all_assertions, 64)

    def test_evidence_quotes_have_exact_source_spans_and_hashes(self) -> None:
        for record_id, annotation in self.annotations.items():
            provenance = {
                item["source_id"]: item
                for item in self.records[record_id]["provenance"]
            }
            for item in annotation["source_context_evidence"]:
                source = json.loads((V1 / item["source_file"]).read_bytes())
                self.assertEqual(
                    item["source_file"], provenance[item["source_id"]]["excerpts_file"]
                )
                self.assertEqual(
                    item["source_url"], provenance[item["source_id"]]["source_url"]
                )
                self.assertEqual(
                    item["source_file_sha256"],
                    sha((V1 / item["source_file"]).read_bytes()),
                )
                pointer = item["text_pointer"]
                text = (
                    source["title"]
                    if pointer == "/title"
                    else source["excerpts"][int(pointer.rsplit("/", 1)[1])]
                )
                self.assertEqual(item["text_sha256_utf8"], sha(text.encode("utf-8")))
                self.assertEqual(text[item["start"] : item["end"]], item["quote"])
                self.assertEqual(
                    item["quote_sha256_utf8"], sha(item["quote"].encode("utf-8"))
                )
                self.assertEqual(item["offset_unit"], "unicode_code_points")

    def test_assertions_preserve_identity_and_partition_denominator(self) -> None:
        counts: Counter[str] = Counter()
        for record_index, record in enumerate(self.gold["records"]):
            annotation = self.annotations[record["id"]]
            self.assertEqual(
                annotation["v1_record_json_pointer"], f"/records/{record_index}"
            )
            self.assertEqual(
                annotation["v1_record_sha256_canonical_json"], canonical_sha(record)
            )
            mapped = {
                item["v1_json_pointer"]: item
                for item in annotation["assertion_context"]
            }
            for kind in ("capacity", "timeline"):
                for index, assertion in enumerate(record[kind]):
                    pointer = f"/records/{record_index}/{kind}/{index}"
                    context = mapped[pointer]
                    self.assertEqual(context["v1_record_id"], record["id"])
                    self.assertEqual(context["assertion_kind"], kind)
                    self.assertEqual(
                        context["v1_assertion_sha256_canonical_json"],
                        canonical_sha(assertion),
                    )
                    self.assertTrue(context["evidence_refs"])
                    self.assertTrue(
                        set(context["evidence_refs"])
                        <= {
                            item["id"] for item in annotation["source_context_evidence"]
                        }
                    )
                    selected_sources = {
                        next(
                            item["source_id"]
                            for item in annotation["source_context_evidence"]
                            if item["id"] == evidence_ref
                        )
                        for evidence_ref in context["evidence_refs"]
                    }
                    self.assertTrue(
                        selected_sources
                        <= set(assertion.get("evidence_source_ids", []))
                    )
                    if "source_conflict" in context:
                        self.assertTrue(
                            set(context["source_conflict"]["evidence_refs"])
                            <= {
                                item["id"]
                                for item in annotation["source_context_evidence"]
                            }
                        )
                    counts[context["context_eligibility"]] += 1
                    denominator = context["v1_scoring_denominator"]
                    counts[f"v1_{denominator['metric']}_{denominator['status']}"] += 1
        self.assertEqual(
            counts["subject_bound"]
            + counts["excluded_from_physical_site_metric"]
            + counts["unresolved"],
            64,
        )
        self.assertEqual(counts["subject_bound"], 59)
        self.assertEqual(counts["excluded_from_physical_site_metric"], 3)
        self.assertEqual(counts["unresolved"], 2)
        self.assertEqual(counts["v1_physical_capacity_included"], 32)
        self.assertEqual(counts["v1_physical_capacity_excluded"], 2)
        self.assertEqual(counts["v1_timeline_included"], 30)
        scored_context_counts = Counter(
            item["context_eligibility"]
            for annotation in self.annotations.values()
            for item in annotation["assertion_context"]
            if item["v1_scoring_denominator"]["status"] == "included"
        )
        self.assertEqual(scored_context_counts["subject_bound"], 57)
        self.assertEqual(scored_context_counts["excluded_from_physical_site_metric"], 3)
        self.assertEqual(scored_context_counts["unresolved"], 2)
        exclusions = {
            (record_id, item["v1_json_pointer"])
            for record_id, annotation in self.annotations.items()
            for item in annotation["assertion_context"]
            if item["v1_scoring_denominator"]["status"] == "excluded"
        }
        self.assertEqual(
            exclusions,
            {
                ("qts-hillsboro", "/records/4/capacity/2"),
                ("fervo-cape-station", "/records/17/capacity/3"),
            },
        )

    def test_known_context_distinctions_are_explicit(self) -> None:
        microsoft = self.annotations["microsoft-fairwater"]
        self.assertEqual(
            microsoft["display_label"]["interpretation_status"],
            "unsupported_by_assigned_source",
        )
        self.assertEqual(microsoft["physical_subject"]["status"], "unsupported_subject")
        self.assertEqual(
            microsoft["source_supported_location"]["status"],
            "unsupported_by_assigned_source",
        )

        aligned_location = self.annotations["aligned-conesville"][
            "source_supported_location"
        ]
        self.assertEqual(
            aligned_location["status"], "project_state_supported_county_unverified"
        )
        self.assertEqual(aligned_location["display_value"], "Coshocton County, Ohio")
        self.assertIn("not established", aligned_location["display_value_specificity"])

        cyrus = self.annotations["cyrusone-bosque"]["assertion_context"]
        self.assertEqual(cyrus[1]["binding_disposition"], "regional_or_portfolio")
        meta = self.annotations["meta-richland"]
        self.assertEqual(
            meta["other_named_entities_not_site_aliases"][0]["value"], "Hyperion"
        )
        self.assertEqual(
            meta["assertion_context"][0]["binding_disposition"], "same_subject"
        )
        self.assertEqual(
            self.annotations["aws-madison"]["asset_scope"]["value"], "multisite"
        )
        edgecore = self.annotations["edgecore-mesa"]
        self.assertEqual(
            edgecore["assertion_context"][0]["binding_disposition"], "ambiguous"
        )
        self.assertEqual(
            edgecore["assertion_context"][1]["binding_disposition"], "nested_subject"
        )
        self.assertEqual(
            edgecore["assertion_context"][3]["binding_disposition"], "nested_subject"
        )
        dominion_dates = self.annotations["dominion-cvow"]["assertion_context"][3:5]
        self.assertEqual(
            [item["binding_disposition"] for item in dominion_dates],
            ["same_subject", "same_subject"],
        )
        self.assertTrue(
            all(
                item["source_conflict"]["status"]
                == "same_subject_conflicting_source_dates"
                for item in dominion_dates
            )
        )

    def test_v1_physical_metric_exclusions_do_not_erase_subject_binding(self) -> None:
        qts = self.annotations["qts-hillsboro"]["assertion_context"][2]
        fervo = self.annotations["fervo-cape-station"]["assertion_context"][3]
        for item in (qts, fervo):
            self.assertEqual(item["binding_disposition"], "nested_subject")
            self.assertEqual(item["context_eligibility"], "subject_bound")
            self.assertEqual(
                item["v1_scoring_denominator"]["metric"], "physical_capacity"
            )
            self.assertEqual(item["v1_scoring_denominator"]["status"], "excluded")

    def test_overlay_is_deterministic(self) -> None:
        expected = (
            json.dumps(builder.build_annotations(), ensure_ascii=False, indent=2) + "\n"
        )
        self.assertEqual(
            (HERE / "source-context-annotations.json").read_text(), expected
        )


if __name__ == "__main__":
    unittest.main()
