"""Build the additive v2 context overlay; never writes or changes v1 inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
V1 = ROOT / "eval/customer-commercial-v1"
OUT = Path(__file__).resolve().parent / "source-context-annotations.json"
PRESERVATION_MANIFEST = (
    Path(__file__).resolve().parent / "v1-preservation-manifest.json"
)
EXPECTED_REFERENCE_SHA256 = (
    "dd061c52a85b0ba05b59aab4229f5dd886bced31145fe6ab315c5ad1cda0b922"
)

_ELIGIBILITY = {
    "same_subject": "subject_bound",
    "nested_subject": "subject_bound",
    "regional_or_portfolio": "excluded_from_physical_site_metric",
    "other_site": "excluded_from_physical_site_metric",
    "adjacent_generation": "excluded_from_physical_site_metric",
    "cluster_not_physical_site": "excluded_from_physical_site_metric",
    "nonphysical_measure": "excluded_from_physical_site_metric",
    "ambiguous": "unresolved",
    "unsupported_by_assigned_source": "unresolved",
}

_V1_EXCLUDED_ASSERTIONS = {
    (
        "qts-hillsboro",
        "capacity",
        2,
    ): "V1 excludes the approximately 4.5MW lease because its physical capacity basis is unspecified.",
    (
        "fervo-cape-station",
        "capacity",
        3,
    ): "V1 excludes contracted offtake from the physical-capacity denominator.",
}

_SOURCE_CONFLICT_ASSERTIONS = {
    ("dominion-cvow", "timeline", 2): {
        "related_pointer": "/records/18/timeline/3",
        "evidence_refs": ["completion_2026", "completion_2027"],
    },
    ("dominion-cvow", "timeline", 3): {
        "related_pointer": "/records/18/timeline/2",
        "evidence_refs": ["completion_2026", "completion_2027"],
    },
}

_ASSERTION_EVIDENCE_REFS = {
    ("vantage-frontier", "capacity"): [["compute"]],
    ("vantage-frontier", "timeline"): [["building"]],
    ("aligned-conesville", "timeline"): [["site", "timeline"]],
    ("databank-red-oak", "capacity"): [["campus_total"], ["phase"], ["phase"]],
    ("databank-red-oak", "timeline"): [["timeline"]],
    ("cyrusone-bosque", "capacity"): [["site", "contract_role"], ["regional"]],
    ("cyrusone-bosque", "timeline"): [["site", "project_status"]],
    ("qts-hillsboro", "capacity"): [["scope"], ["first_building"], ["first_phase"]],
    ("qts-hillsboro", "timeline"): [["timeline"], ["timeline"]],
    ("switch-the-rock", "capacity"): [["ecosystem"], ["regional"]],
    ("switch-the-rock", "timeline"): [["timeline"]],
    ("meta-richland", "capacity"): [["cluster"], ["compute_second"]],
    ("meta-richland", "timeline"): [["announcement"]],
    ("microsoft-fairwater", "timeline"): [["generic_facility", "two_facilities"]],
    ("stack-svy01", "capacity"): [["campus_total"], ["expansion"]],
    ("stack-svy01", "timeline"): [["site", "timeline"]],
    ("applied-ellendale", "capacity"): [
        ["campus_design"],
        ["first_rfs"],
        ["buildings"],
        ["third_rfs"],
        ["load_study"],
    ],
    ("applied-ellendale", "timeline"): [["first_rfs"], ["second_rfs"], ["third_rfs"]],
    ("crusoe-abilene", "capacity"): [["total"], ["initial_phase"]],
    ("crusoe-abilene", "timeline"): [["start"], ["energization"], ["phase_two"]],
    ("compass-meridian", "capacity"): [["site", "supply"], ["site", "market"]],
    ("compass-meridian", "timeline"): [["site", "groundbreaking"]],
    ("edgecore-mesa", "capacity"): [
        ["new_land", "first_campus", "expansion"],
        ["first_campus"],
        ["expansion"],
    ],
    ("edgecore-mesa", "timeline"): [
        ["future_buildings", "buildings"],
        ["future_buildings", "buildings"],
    ],
    ("equinix-jh2", "timeline"): [["timeline"]],
    ("fervo-cape-station", "capacity"): [
        ["phase_one"],
        ["phase_one"],
        ["phase_two"],
        ["contract"],
    ],
    ("fervo-cape-station", "timeline"): [
        ["first_power"],
        ["first_cod"],
        ["remaining_cod"],
        ["phase_two_cod"],
    ],
    ("dominion-cvow", "capacity"): [["capacity", "turbines"]],
    ("dominion-cvow", "timeline"): [
        ["supplement"],
        ["supplement"],
        ["completion_2026"],
        ["completion_2027"],
    ],
    ("terrapower-kemmerer", "capacity"): [["plant"], ["storage"]],
    ("terrapower-kemmerer", "timeline"): [["support_start"], ["construction_date"]],
}


def _e(
    evidence_id: str,
    source_id: str,
    quote: str,
    *,
    excerpt: int | None = None,
    field: str = "title",
    role: str,
) -> dict[str, Any]:
    return {
        "id": evidence_id,
        "source_id": source_id,
        "quote": quote,
        "text_pointer": f"/excerpts/{excerpt}" if excerpt is not None else f"/{field}",
        "role": role,
    }


SPECS: list[dict[str, Any]] = [
    {
        "id": "vantage-frontier",
        "display_label_status": "literal_source_name",
        "physical_subject": {
            "status": "explicit_named_subject",
            "phrase": "Frontier campus",
            "source_phrase_refs": ["site"],
            "evidence": ["site", "alias"],
        },
        "asset_scope": {
            "value": "campus",
            "status": "source_explicit",
            "evidence": ["scope", "building"],
        },
        "location": {
            "status": "source_explicit",
            "relation": "same_project",
            "evidence": ["site"],
        },
        "organization_role": {
            "organization": "Vantage Data Centers",
            "role": "developer",
            "status": "source_explicit",
            "evidence": ["site"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "The source describes Vantage's development activity; legal ownership of this site is not stated.",
        },
        "aliases": [{"value": "Frontier", "kind": "named_campus", "evidence": "alias"}],
        "other_named_entities": [],
        "evidence": [
            _e(
                "site",
                "vantage",
                "Vantage Data Centers, a leading global provider of hyperscale data centers, today announced its largest investment to date of over $25 billion to develop a mega-scale 1.4GW data center campus in Shackelford County, Texas.",
                excerpt=0,
                role="physical_subject_location_and_developer",
            ),
            _e(
                "alias",
                "vantage",
                "“Frontier,” will lead to advancements in AI",
                excerpt=0,
                role="source_named_alias",
            ),
            _e(
                "scope",
                "vantage",
                "The campus will be home to 10 data centers",
                excerpt=1,
                role="multi_building_scope",
            ),
            _e(
                "building",
                "vantage",
                "the first building scheduled for delivery in the second half of 2026",
                excerpt=1,
                role="building_timeline_scope",
            ),
            _e(
                "compute",
                "vantage",
                "Frontier campus with 1.4GW of GPU compute capacity",
                excerpt=2,
                role="compute_capacity_basis",
            ),
        ],
        "capacity": [
            (
                "same_subject",
                "The 1.4GW statement names the Frontier campus; preserve its GPU-compute qualifier.",
            ),
        ],
        "timeline": [
            (
                "nested_subject",
                "The delivery target is explicitly for the first building within the campus.",
            ),
        ],
    },
    {
        "id": "aligned-conesville",
        "display_label_status": "compositional_location_label",
        "physical_subject": {
            "status": "explicit_descriptive_subject",
            "phrase": "new data center campus inside the Conesville Industrial Park",
            "source_phrase_refs": ["site"],
            "evidence": ["site"],
        },
        "asset_scope": {
            "value": "campus",
            "status": "source_explicit",
            "evidence": ["scope"],
        },
        "location": {
            "status": "project_state_supported_county_unverified",
            "relation": "campus inside Conesville Industrial Park in Central Ohio; Ohio is stated in body, but Coshocton County is not bound to the parcel as an exact site location",
            "evidence": ["site", "region", "state"],
            "dateline_evidence_ref": "location",
            "display_value_specificity": "v1 county-level display is not established by the assigned site-location wording",
        },
        "organization_role": {
            "organization": "Aligned Data Centers",
            "role": "planned_developer",
            "status": "source_explicit",
            "evidence": ["developer"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "A planned development role does not establish legal title to the parcel.",
        },
        "aliases": [],
        "other_named_entities": [
            {
                "value": "former AEP Conesville Power Plant",
                "relation": "adjacent_former_plant_not_data_center_alias",
                "evidence": "adjacent",
            }
        ],
        "evidence": [
            _e(
                "location",
                "aligned",
                "COSHOCTON COUNTY, OH",
                excerpt=1,
                role="dateline_location",
            ),
            _e(
                "site",
                "aligned",
                "planned development of its new data center campus inside the Conesville Industrial Park",
                excerpt=1,
                role="physical_subject_and_host_location",
            ),
            _e(
                "region",
                "aligned",
                "significant expansion in Central Ohio",
                excerpt=1,
                role="regional_context_not_parcel_specific_address",
            ),
            _e(
                "state",
                "aligned",
                "This is Aligned’s third data center campus in Ohio.",
                excerpt=3,
                role="project_state_support",
            ),
            _e(
                "developer",
                "aligned",
                "Aligned will develop a 197-acre parcel",
                excerpt=1,
                role="planned_developer",
            ),
            _e(
                "adjacent",
                "aligned",
                "adjacent to the former AEP Conesville Power Plant",
                excerpt=1,
                role="adjacent_generation_asset_not_subject",
            ),
            _e(
                "scope",
                "aligned",
                "Aligned’s new multi-building campus",
                excerpt=3,
                role="campus_scope",
            ),
            _e(
                "timeline",
                "aligned",
                "targeting initial capacity delivery mid 2026",
                excerpt=3,
                role="first_building_timeline",
            ),
        ],
        "capacity": [],
        "timeline": [
            (
                "nested_subject",
                "The target is for the first data center in the explicitly named new campus.",
            )
        ],
    },
    {
        "id": "databank-red-oak",
        "display_label_status": "literal_source_name",
        "physical_subject": {
            "status": "explicit_named_subject",
            "phrase": "Red Oak Campus",
            "source_phrase_refs": ["site", "alias"],
            "evidence": ["site", "alias"],
        },
        "asset_scope": {
            "value": "campus",
            "status": "source_explicit",
            "evidence": ["scope", "phase"],
        },
        "location": {
            "status": "source_explicit",
            "relation": "same_site",
            "evidence": ["site"],
        },
        "organization_role": {
            "organization": "DataBank",
            "role": "developer",
            "status": "source_explicit",
            "evidence": ["site"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "The announcement identifies development and service roles, not legal ownership.",
        },
        "aliases": [
            {"value": "Red Oak Campus", "kind": "named_campus", "evidence": "alias"}
        ],
        "other_named_entities": [
            {
                "value": "DFW1 and six other data centers",
                "relation": "other_DataBank_market_sites",
                "evidence": "market_sites",
            },
            {
                "value": "Atlanta acquisition",
                "relation": "separate_portfolio_site",
                "evidence": "separate_acquisitions",
            },
            {
                "value": "Northern Virginia acquisition",
                "relation": "separate_portfolio_site",
                "evidence": "separate_northern_virginia",
            },
        ],
        "evidence": [
            _e(
                "site",
                "databank",
                "development of a 480MW data center campus on 292 acres of land in Red Oak, TX",
                excerpt=0,
                role="physical_subject_location_and_capacity_context",
            ),
            _e(
                "alias",
                "databank",
                "new “Red Oak Campus”",
                excerpt=1,
                role="source_named_alias",
            ),
            _e(
                "scope",
                "databank",
                "accommodating up to eight, 2-story data centers",
                excerpt=1,
                role="multi_building_campus_scope",
            ),
            _e(
                "phase",
                "databank",
                "The Phase 1 design of the site will feature 4 buildings and a 400MW sub-station from Oncor that can deliver up to 240MW of critical IT power",
                excerpt=1,
                role="phase_and_distinct_substation_scope",
            ),
            _e(
                "campus_total",
                "databank",
                "400MW sub-station from Oncor that can deliver up to 240MW of critical IT power with the ability to increase this in Phase 2 for a total of 480MW across all 8 buildings",
                excerpt=1,
                role="phased_IT_load_total_and_eight_building_scope",
            ),
            _e(
                "market_sites",
                "databank",
                "headquarters location (DFW1) and 6 other data centers in the metro",
                excerpt=1,
                role="other_market_data_centers_not_Red_Oak",
            ),
            _e(
                "separate_acquisitions",
                "databank",
                "95-acre/120MW campus in the Atlanta market in October 2023",
                excerpt=2,
                role="separate_Atlanta_acquisition_not_Red_Oak",
            ),
            _e(
                "separate_northern_virginia",
                "databank",
                "85-acre/192MW campus in Northern Virginia in November 2023",
                excerpt=2,
                role="separate_Northern_Virginia_acquisition_not_Red_Oak",
            ),
            _e(
                "portfolio",
                "databank",
                "792MW of power to DataBank’s portfolio",
                excerpt=2,
                role="separate_portfolio_capacity_not_Red_Oak",
            ),
            _e(
                "timeline",
                "databank",
                "an initial Ready for Service date of Q2-2026",
                excerpt=1,
                role="phase_ready_for_service_target",
            ),
        ],
        "capacity": [
            (
                "same_subject",
                "The 480MW campus development statement names the Red Oak site; it is an up-to campus total.",
            ),
            (
                "nested_subject",
                "The 240MW IT amount is explicitly Phase 1 within the eight-building campus.",
            ),
            (
                "nested_subject",
                "The 400MW substation is infrastructure for Phase 1; it is a distinct utility asset/basis, not IT load.",
            ),
        ],
        "timeline": [
            (
                "nested_subject",
                "The Q2 2026 Ready for Service target is for the initial phase at this site.",
            )
        ],
    },
    {
        "id": "cyrusone-bosque",
        "display_label_status": "descriptive_label_not_source_site_name",
        "physical_subject": {
            "status": "explicit_descriptive_subject",
            "phrase": "new data center adjacent to the Thad Hill Energy Center",
            "source_phrase_refs": ["site"],
            "evidence": ["site"],
        },
        "asset_scope": {
            "value": "single_facility",
            "status": "source_explicit",
            "evidence": ["site"],
        },
        "location": {
            "status": "source_explicit",
            "relation": "Bosque_County_site_adjacent_to_generation_center",
            "evidence": ["site", "regional"],
        },
        "organization_role": {
            "organization": "CyrusOne",
            "role": "project_customer_and_contract_recipient",
            "status": "source_explicit",
            "evidence": ["contract_role"],
            "company_level_role_description": {
                "role": "data_center_developer_and_operator",
                "status": "general_company_description_not_a_project-role_claim",
                "evidence_refs": ["role"],
            },
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "The agreement secures power, grid connection and land; the excerpt does not establish current legal owner of the facility.",
        },
        "aliases": [],
        "other_named_entities": [
            {
                "value": "Thad Hill Energy Center",
                "relation": "adjacent_generation_asset_not_data_center_alias",
                "evidence": "site",
            },
            {
                "value": "Calpine",
                "relation": "energy_partner_not_CyrusOne_alias",
                "evidence": "regional",
            },
        ],
        "evidence": [
            _e(
                "site",
                "cyrusone",
                "a new data center adjacent to the Thad Hill Energy Center in Bosque County, Texas",
                excerpt=0,
                role="physical_subject_location_and_adjacent_asset",
            ),
            _e(
                "contract_role",
                "cyrusone",
                "new 190-megawatt (MW) agreement with Dallas based CyrusOne",
                excerpt=0,
                role="project_customer_and_contract_recipient",
            ),
            _e(
                "role",
                "cyrusone",
                "CyrusOne, a leading global data center developer and operator",
                excerpt=0,
                role="developer_and_operator_role",
            ),
            _e(
                "project_status",
                "cyrusone",
                "currently under construction and expected to be operational by the fourth quarter of 2026",
                excerpt=0,
                role="project_timeline_context",
            ),
            _e(
                "regional",
                "cyrusone_supplement",
                "Calpine’s ~9,000 MWs of generation and wholesale and retail platform in ERCOT will be capable of delivering up to 400 MWs to data centers located in Bosque, Texas",
                excerpt=2,
                role="regional_multi_customer_delivery_capability",
            ),
            _e(
                "partner",
                "cyrusone_supplement",
                "strategic energy partner to hyperscale data centers",
                excerpt=2,
                role="Calpine_energy_partner_role",
            ),
        ],
        "capacity": [
            (
                "same_subject",
                "The 190MW agreement serves the new Bosque facility; it is contracted utility service, not IT load.",
            ),
            (
                "regional_or_portfolio",
                "The up-to 400MW capability is described for data centers in Bosque as a region, not this single facility.",
            ),
        ],
        "timeline": [
            (
                "same_subject",
                "The operational deadline is stated for the new facility described in the announcement.",
            )
        ],
    },
    {
        "id": "qts-hillsboro",
        "display_label_status": "generic_campus_location_label",
        "physical_subject": {
            "status": "explicit_descriptive_subject",
            "phrase": "new mega data center campus in Hillsboro",
            "source_phrase_refs": ["site"],
            "evidence": ["site"],
        },
        "asset_scope": {
            "value": "campus",
            "status": "source_explicit",
            "evidence": ["scope", "first_phase"],
        },
        "location": {
            "status": "source_explicit",
            "relation": "same_campus",
            "evidence": ["site"],
        },
        "organization_role": {
            "organization": "QTS Realty Trust",
            "role": "developer",
            "status": "source_explicit",
            "evidence": ["site"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "The excerpt reports development, pre-leasing and commissioning expectations; legal ownership is not established.",
        },
        "aliases": [],
        "other_named_entities": [
            {
                "value": "Hillsboro Ring",
                "relation": "regional_fiber_network_not_site_alias",
                "evidence": "regional",
            }
        ],
        "evidence": [
            _e(
                "site",
                "qts",
                "new mega data center campus in [Hillsboro, Or](https://c212.net/c/link/?t=0&l=en&o=2723682-1&h=432291324&u=https%3A%2F%2Fwww.qtsdatacenters.com%2Fdata-centers%2Fhillsboro&a=Hillsboro%2C+Or)",
                excerpt=1,
                role="physical_subject_and_location_with_literal_link_text",
            ),
            _e(
                "scope",
                "qts",
                "can ultimately support the construction of five mega data centers",
                excerpt=1,
                role="multi_building_site_scope",
            ),
            _e(
                "first_phase",
                "qts",
                "pre-leased 100% of the first phase of development at the site to a global software-as-a-service provider representing approximately 4.5 megawatts",
                excerpt=2,
                role="first_phase_lease_basis_unspecified",
            ),
            _e(
                "first_building",
                "qts",
                "The initial development will feature construction of a 158,000 square foot data center",
                excerpt=1,
                role="initial_building_scope",
            ),
            _e(
                "regional",
                "qts",
                "the Hillsboro Ring which includes several ultra-high count fiber optic rings that interconnect 14 data centers",
                excerpt=4,
                role="regional_network_not_site_scope",
            ),
            _e(
                "timeline",
                "qts",
                "formally open and commission the first phase of development in Hillsboro in mid-2020",
                excerpt=2,
                role="first_phase_commissioning_target",
            ),
        ],
        "capacity": [
            (
                "same_subject",
                "The more-than-250MW gross-power assertion is stated for the 5-building campus; its basis differs from IT load.",
            ),
            (
                "nested_subject",
                "The 27MW gross-power figure is for the initial building at the campus.",
            ),
            (
                "nested_subject",
                "The approximately 4.5MW lease is at the first phase, but its electrical basis is unspecified; V1 therefore excludes it from the physical-capacity denominator while preserving its subject binding.",
            ),
        ],
        "timeline": [
            (
                "nested_subject",
                "The mid-2020 commissioning target is for the first phase.",
            ),
            (
                "nested_subject",
                "The second-half-2020 availability statement concerns additional power at the Hillsboro site.",
            ),
        ],
    },
    {
        "id": "switch-the-rock",
        "display_label_status": "literal_source_alias",
        "physical_subject": {
            "status": "explicit_named_subject",
            "phrase": "Fifth Prime data center campus",
            "source_phrase_refs": ["site"],
            "evidence": ["site", "alias"],
        },
        "asset_scope": {
            "value": "campus",
            "status": "source_explicit",
            "evidence": ["site"],
        },
        "location": {
            "status": "source_explicit",
            "relation": "Round_Rock_campus_adjacent_to_Dell_headquarters",
            "evidence": ["site", "regional"],
        },
        "organization_role": {
            "organization": "Switch",
            "role": "planned_developer",
            "status": "source_explicit",
            "evidence": ["site"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "The land purchase agreement with Dell enables Switch construction; it does not establish that Dell owns the data center.",
        },
        "aliases": [
            {"value": "The Rock", "kind": "explicit_campus_alias", "evidence": "alias"}
        ],
        "other_named_entities": [
            {
                "value": "Dell global headquarters",
                "relation": "adjacent_company_headquarters_not_data_center_alias",
                "evidence": "site",
            },
            {
                "value": "Data Foundry Austin and Houston properties",
                "relation": "separate_acquired_sites_not_The_Rock",
                "evidence": "regional",
            },
        ],
        "evidence": [
            _e(
                "site",
                "switch",
                "primary location of its Fifth Prime data center campus in Texas",
                excerpt=0,
                role="named_physical_subject",
            ),
            _e(
                "alias",
                "switch",
                "The Fifth Prime campus will be called “The Rock.”",
                excerpt=0,
                role="explicit_campus_alias",
            ),
            _e(
                "location",
                "switch",
                "next to Dell’s global headquarters in Round Rock, Texas",
                excerpt=0,
                role="adjacent_headquarters_location",
            ),
            _e(
                "regional",
                "switch",
                "properties capable of delivering over 500,000 square feet and 60 megawatts in Austin and Houston",
                excerpt=1,
                role="separate_acquired_properties",
            ),
            _e(
                "ecosystem",
                "switch",
                "Switch’s Texas technology campus ecosystem will be architected to provide over 2 million square feet and 185 megawatts of power upon completion",
                excerpt=1,
                role="multi_site_ecosystem_total",
            ),
            _e(
                "timeline",
                "switch",
                "begin site preparation and permitting at The Rock Campus in the summer of 2021",
                excerpt=1,
                role="site_preparation_target",
            ),
        ],
        "capacity": [
            (
                "regional_or_portfolio",
                "185MW is explicitly a Texas technology campus ecosystem total, not The Rock alone.",
            ),
            (
                "other_site",
                "60MW describes Austin and Houston acquired properties, not the Round Rock campus.",
            ),
        ],
        "timeline": [
            (
                "same_subject",
                "The site preparation and permitting target explicitly names The Rock Campus.",
            )
        ],
    },
    {
        "id": "meta-richland",
        "display_label_status": "composite_label_with_non_alias_cluster",
        "physical_subject": {
            "status": "explicit_named_subject",
            "phrase": "Richland Parish Data Center",
            "source_phrase_refs": ["site"],
            "evidence": ["site", "cluster"],
        },
        "asset_scope": {
            "value": "single_facility",
            "status": "source_explicit_data_center_subject_with_compute_basis",
            "evidence": ["site", "cluster", "compute_second"],
        },
        "location": {
            "status": "source_explicit",
            "relation": "Richland_Parish_Louisiana",
            "evidence": ["site"],
        },
        "organization_role": {
            "organization": "Meta",
            "role": "developer_operator_as_first_person_publisher",
            "status": "source_explicit",
            "evidence": ["site"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "First-person project statements do not establish legal site ownership.",
        },
        "aliases": [],
        "other_named_entities": [
            {
                "value": "Hyperion",
                "relation": "AI_compute_cluster_not_data_center_alias",
                "evidence": "cluster",
            }
        ],
        "evidence": [
            _e(
                "site",
                "meta",
                "building our largest data center to date in Richland Parish, Louisiana",
                excerpt=0,
                role="physical_subject_and_location",
            ),
            _e(
                "cluster",
                "meta",
                "This data center will play a vital role in accelerating our AI progress, delivering 5 gigawatts of compute capacity to house Hyperion, our largest multi-gigawatt AI cluster.",
                excerpt=0,
                role="Richland_data_center_subject_and_hosted_AI_cluster_compute_context",
            ),
            _e(
                "compute_second",
                "meta",
                "The data center will deliver over two gigawatts of compute capacity",
                excerpt=5,
                role="data_center_compute_claim_scope",
            ),
            _e(
                "announcement",
                "meta",
                "In December 2024, Meta announced",
                excerpt=0,
                role="announcement_date_not_milestone",
            ),
        ],
        "capacity": [
            (
                "same_subject",
                "The source says the Richland Parish data center will deliver 5GW of compute capacity to house Hyperion. Hyperion is a hosted AI cluster, not a physical-site alias; this compute basis is not IT load or electrical demand.",
            ),
            (
                "same_subject",
                "The source explicitly assigns over 2GW of compute capacity to the Richland Parish Data Center for model training; this compute basis is not IT load or electrical demand.",
            ),
        ],
        "timeline": [
            (
                "same_subject",
                "The December 2024 date is attached to Meta's announcement about the Richland Parish project; the event is an announcement, not a construction or operating milestone.",
            )
        ],
    },
    {
        "id": "google-fort-wayne",
        "display_label_status": "descriptive_location_label",
        "physical_subject": {
            "status": "explicit_descriptive_subject",
            "phrase": "Fort Wayne data center location",
            "source_phrase_refs": ["break_ground"],
            "evidence": ["break_ground"],
        },
        "asset_scope": {
            "value": "single_facility",
            "status": "source_title_and_locality_explicit",
            "evidence": ["title", "break_ground"],
        },
        "location": {
            "status": "source_explicit",
            "relation": "Fort_Wayne_site_distinct_from_other_Indiana_sites",
            "evidence": ["break_ground", "other_sites"],
        },
        "organization_role": {
            "organization": "Google",
            "role": "builder_operator",
            "status": "title_supported",
            "evidence": ["title"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "A statement that Google is building a site does not establish legal ownership.",
        },
        "aliases": [],
        "other_named_entities": [
            {
                "value": "Michigan City and Morgan County sites",
                "relation": "separate_Indiana_sites",
                "evidence": "other_sites",
            }
        ],
        "evidence": [
            _e(
                "title",
                "google",
                "Google is building a $2B data center in Northeast Indiana",
                excerpt=0,
                role="title_only_region_and_subject",
            ),
            _e(
                "other_sites",
                "google",
                "From our operational data center in Fort Wayne to our sites currently in development in Michigan City and Morgan County",
                excerpt=1,
                role="distinct_sites_in_same_state",
            ),
            _e(
                "break_ground",
                "google",
                "Google breaks ground on Fort Wayne data center location.",
                excerpt=2,
                role="named_local_subject",
            ),
            _e(
                "supplement",
                "google_supplement",
                "Google breaks ground on Fort Wayne data center location.",
                excerpt=1,
                role="duplicate_source_context",
            ),
        ],
        "capacity": [],
        "timeline": [],
    },
    {
        "id": "aws-madison",
        "display_label_status": "regional_multisite_display_label",
        "physical_subject": {
            "status": "multi_site_subject",
            "phrase": "two data center complexes in two Madison County industrial parks",
            "source_phrase_refs": ["complexes", "parks"],
            "evidence": ["complexes", "parks"],
        },
        "asset_scope": {
            "value": "multisite",
            "status": "source_explicit",
            "evidence": ["complexes", "parks"],
        },
        "location": {
            "status": "source_explicit",
            "relation": "Madison_County_two_industrial_parks_no_site_names",
            "evidence": ["parks"],
        },
        "organization_role": {
            "organization": "Amazon Web Services (AWS)",
            "role": "planned_investor_builder",
            "status": "source_explicit",
            "evidence": ["complexes"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "The source says AWS plans investment and construction; it does not establish parcel ownership or individual site identities.",
        },
        "aliases": [],
        "other_named_entities": [
            {
                "value": "AWS",
                "relation": "company_acronym_not_site_alias",
                "evidence": "complexes",
            }
        ],
        "evidence": [
            _e(
                "title",
                "amazon",
                "AWS plans to invest $10 billion in Mississippi",
                field="title",
                role="announcement_title",
            ),
            _e(
                "complexes",
                "amazon_supplement",
                "Amazon Web Services (AWS) plans to invest $10 billion to build two data center complexes",
                excerpt=1,
                role="two_complexes_and_company_name",
            ),
            _e(
                "parks",
                "amazon_supplement",
                "multiple data center complexes in two Madison County industrial parks",
                excerpt=1,
                role="county_level_multisite_scope",
            ),
        ],
        "capacity": [],
        "timeline": [],
    },
    {
        "id": "microsoft-fairwater",
        "display_label_status": "unsupported_by_assigned_source",
        "physical_subject": {
            "status": "unsupported_subject",
            "phrase": None,
            "source_phrase_refs": [],
            "evidence": ["title", "generic_facility"],
        },
        "asset_scope": {
            "value": "mixed_or_ambiguous",
            "status": "source_mentions_first_and_second_datacenters_but_not_Fairwater_subject",
            "evidence": ["two_facilities"],
        },
        "location": {
            "status": "unsupported_by_assigned_source",
            "relation": "Wisconsin_region_only_no_Mount_Pleasant_or_Fairwater",
            "evidence": ["title", "wisconsin"],
        },
        "organization_role": {
            "organization": "Microsoft",
            "role": "first_person_facility_operator_or_developer",
            "status": "source_general_but_site_unbound",
            "evidence": ["generic_facility"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "The assigned excerpt does not name Fairwater or Mount Pleasant and does not prove ownership of the displayed site.",
        },
        "aliases": [],
        "other_named_entities": [
            {
                "value": "250MW solar project in Portage County",
                "relation": "offsite_energy_support_not_datacenter_location",
                "evidence": "solar",
            }
        ],
        "evidence": [
            _e(
                "title",
                "microsoft",
                "Made in Wisconsin: The world’s most powerful AI datacenter",
                field="title",
                role="Wisconsin_article_title_no_project_name",
            ),
            _e(
                "generic_facility",
                "microsoft",
                "We are on track to complete construction and bring this AI datacenter online in early 2026",
                excerpt=1,
                role="generic_unlocated_facility",
            ),
            _e(
                "wisconsin",
                "microsoft",
                "right here at home",
                excerpt=2,
                role="community_context_not_site_location",
            ),
            _e(
                "solar",
                "microsoft",
                "a new 250 MW solar project in Portage County that is under construction to support this commitment",
                excerpt=4,
                role="separate_solar_project",
            ),
            _e(
                "two_facilities",
                "microsoft",
                "Once our first datacenter is fully operational",
                excerpt=5,
                role="first_datacenter_reference",
            ),
        ],
        "capacity": [],
        "timeline": [
            (
                "unsupported_by_assigned_source",
                "The timing statement names an unlocated AI datacenter; the assigned source does not bind it to Fairwater or Mount Pleasant.",
            )
        ],
    },
    {
        "id": "stack-svy01",
        "display_label_status": "literal_site_identifier",
        "physical_subject": {
            "status": "explicit_named_subject",
            "phrase": "San Jose campus, SVY01",
            "source_phrase_refs": ["site"],
            "evidence": ["site"],
        },
        "asset_scope": {
            "value": "campus",
            "status": "source_explicit",
            "evidence": ["site", "campus_total"],
        },
        "location": {
            "status": "source_explicit",
            "relation": "San_Jose_campus",
            "evidence": ["site"],
        },
        "organization_role": {
            "organization": "STACK Infrastructure",
            "role": "developer_and_operator",
            "status": "source_explicit",
            "evidence": ["site"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "Company-wide developer/operator wording is not legal title evidence for SVY01.",
        },
        "aliases": [{"value": "SVY01", "kind": "site_identifier", "evidence": "site"}],
        "other_named_entities": [
            {
                "value": "4.0+GW built or under development",
                "relation": "corporate_portfolio_not_SVY01",
                "evidence": "portfolio",
            }
        ],
        "evidence": [
            _e(
                "site",
                "stack",
                "expansion of its 100MW campus in San Jose, SVY01",
                excerpt=0,
                role="named_site_and_location",
            ),
            _e(
                "expansion",
                "stack",
                "The 60MW data center expansion will provide critical capacity",
                excerpt=0,
                role="expansion_amount",
            ),
            _e(
                "campus_total",
                "stack_supplement",
                "bringing the total campus to 100MW across 19 acres",
                excerpt=4,
                role="post_expansion_campus_total",
            ),
            _e(
                "portfolio",
                "stack",
                "4.0+GW built or under development",
                excerpt=3,
                role="corporate_portfolio_not_site",
            ),
            _e(
                "timeline",
                "stack",
                "today announced a groundbreaking and expansion",
                excerpt=0,
                role="groundbreaking_announcement",
            ),
        ],
        "capacity": [
            ("same_subject", "100MW is explicitly the total campus after expansion."),
            ("nested_subject", "60MW is the named expansion within SVY01."),
        ],
        "timeline": [
            (
                "nested_subject",
                "The announcement date and groundbreaking refer to the campus expansion.",
            )
        ],
    },
    {
        "id": "applied-ellendale",
        "display_label_status": "site_name_location_label",
        "physical_subject": {
            "status": "explicit_descriptive_subject",
            "phrase": "Ellendale data center campus",
            "source_phrase_refs": ["lease"],
            "evidence": ["lease", "campus_design"],
        },
        "asset_scope": {
            "value": "campus",
            "status": "source_explicit_multibuilding",
            "evidence": ["buildings", "campus_design"],
        },
        "location": {
            "status": "source_explicit",
            "relation": "Ellendale_North_Dakota",
            "evidence": ["lease"],
        },
        "organization_role": {
            "organization": "Applied Digital",
            "role": "campus_provider_and_developer",
            "status": "source_explicit",
            "evidence": ["campus_design"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "The lease and campus design statements do not establish legal ownership.",
        },
        "aliases": [],
        "other_named_entities": [
            {
                "value": "CoreWeave",
                "relation": "lessee_not_campus_alias",
                "evidence": "lease",
            }
        ],
        "evidence": [
            _e(
                "lease",
                "applied",
                "deliver 250 megawatts (MW) of critical IT load to host CoreWeave's artificial intelligence (AI) and high-performance computing (HPC) infrastructure at its Ellendale, North Dakota data center campus",
                excerpt=1,
                role="customer_lease_at_named_campus",
            ),
            _e(
                "option",
                "applied",
                "CoreWeave also retains the option to access an additional 150 MW of critical IT load at Ellendale",
                excerpt=2,
                role="optional_future_customer_capacity",
            ),
            _e(
                "campus_design",
                "applied",
                "Ellendale campus is designed to host 400 MW of critical IT load",
                excerpt=5,
                role="campus_design_capacity",
            ),
            _e(
                "load_study",
                "applied",
                "1+ gigawatts of power capacity currently under various stages of load study",
                excerpt=5,
                role="studied_power_potential",
            ),
            _e(
                "buildings",
                "applied",
                "The second building, which is expected to house a 150 MW data center",
                excerpt=4,
                role="building_specific_scope",
            ),
            _e(
                "first_rfs",
                "applied",
                "first 100 MW data center for CoreWeave to be ready for service in the fourth quarter of calendar 2025",
                excerpt=4,
                role="building_one_RFS_target",
            ),
            _e(
                "second_rfs",
                "applied",
                "ready for service in the middle of 2026",
                excerpt=4,
                role="building_two_RFS_target",
            ),
            _e(
                "third_rfs",
                "applied",
                "the third 150 MW building, which is currently in the planning stages",
                excerpt=4,
                role="optional_building_three_target",
            ),
        ],
        "capacity": [
            (
                "same_subject",
                "The designed 400MW IT load is explicitly for the Ellendale campus.",
            ),
            ("nested_subject", "100MW is for the first leased CoreWeave building."),
            ("nested_subject", "150MW is for the second leased building."),
            (
                "nested_subject",
                "The third 150MW building is an option and remains uncommitted.",
            ),
            (
                "same_subject",
                "The 1+GW figure is a load-study qualifier for possible campus expansion, not committed service.",
            ),
        ],
        "timeline": [
            ("nested_subject", "The Q4 2025 RFS target is for the first building."),
            ("nested_subject", "The mid-2026 RFS target is for the second building."),
            ("nested_subject", "The 2027 target is for an optional third building."),
        ],
    },
    {
        "id": "crusoe-abilene",
        "display_label_status": "composite_project_and_host_campus_label",
        "physical_subject": {
            "status": "explicit_descriptive_subject",
            "phrase": "AI data center at the Lancium Clean Campus",
            "source_phrase_refs": ["site"],
            "evidence": ["site", "initial_phase"],
        },
        "asset_scope": {
            "value": "campus",
            "status": "source_explicit_eight_buildings_and_phases",
            "evidence": ["site", "initial_phase"],
        },
        "location": {
            "status": "source_explicit",
            "relation": "Abilene_project_with_host_campus_Lancium",
            "evidence": ["site"],
        },
        "organization_role": {
            "organization": "Crusoe",
            "role": "developer_and_builder",
            "status": "source_explicit",
            "evidence": ["initial_phase"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "Designed and built by Crusoe does not establish legal ownership of the host campus or facilities.",
        },
        "aliases": [],
        "other_named_entities": [
            {
                "value": "Lancium Clean Campus",
                "relation": "host_campus_not_Crusoe_project_alias",
                "evidence": "site",
            },
            {
                "value": "Crusoe total footprint and 10GW pipeline",
                "relation": "corporate_portfolio_not_Abilene_site",
                "evidence": "site",
            },
        ],
        "evidence": [
            _e(
                "site",
                "crusoe",
                "construction has begun on the next phase of its AI data center at the ",
                excerpt=9,
                role="host_campus_location_and_phase_two",
            ),
            _e(
                "total",
                "crusoe",
                "bringing the total facility to eight buildings, approximately 4 million square feet, and a total power capacity of 1.2 gigawatts (GW)",
                excerpt=9,
                role="total_facility_scope",
            ),
            _e(
                "portfolio",
                "crusoe",
                "Crusoe's total data center footprint will reach more than 1.6 GW under operations and construction with an additional pipeline exceeding 10 GW",
                excerpt=9,
                role="corporate_portfolio_not_project_total",
            ),
            _e(
                "initial_phase",
                "crusoe",
                "The initial phase, comprising two buildings at 980,000 square feet and 200+ megawatts",
                excerpt=10,
                role="phase_one_scope_and_capacity",
            ),
            _e(
                "start",
                "crusoe",
                "Crusoe began constructing the AI data center in Abilene in June 2024",
                excerpt=10,
                role="phase_one_construction_start",
            ),
            _e(
                "energization",
                "crusoe",
                "is expected to be energized in the first half of 2025",
                excerpt=10,
                role="phase_one_energization_target",
            ),
            _e(
                "phase_two",
                "crusoe",
                "The second phase of construction, expected to be completed in mid-2026",
                excerpt=9,
                role="phase_two_completion_target",
            ),
        ],
        "capacity": [
            (
                "same_subject",
                "1.2GW is stated as total power capacity for the eight-building facility at this campus.",
            ),
            ("nested_subject", "200+MW is explicitly the two-building initial phase."),
        ],
        "timeline": [
            (
                "nested_subject",
                "June 2024 construction start is for the initial phase of the Abilene AI data center.",
            ),
            (
                "nested_subject",
                "First-half 2025 energization target is for the initial phase.",
            ),
            (
                "nested_subject",
                "Mid-2026 completion target is for the six-building second phase.",
            ),
        ],
    },
    {
        "id": "compass-meridian",
        "display_label_status": "city_and_campus_description",
        "physical_subject": {
            "status": "explicit_descriptive_subject",
            "phrase": "next hyperscale data center campus in Meridian",
            "source_phrase_refs": ["site"],
            "evidence": ["site", "market"],
        },
        "asset_scope": {
            "value": "campus",
            "status": "source_explicit_eight_data_centers",
            "evidence": ["site", "market"],
        },
        "location": {
            "status": "source_explicit",
            "relation": "Meridian_Lauderdale_County_Mississippi",
            "evidence": ["site", "market"],
        },
        "organization_role": {
            "organization": "Compass Datacenters",
            "role": "developer",
            "status": "source_explicit",
            "evidence": ["site"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "The source identifies a developer and local assistance; it does not establish legal ownership.",
        },
        "aliases": [],
        "other_named_entities": [
            {
                "value": "Hoffman Estates, Red Oak, Loudoun County, Goodyear and El Mirage sites",
                "relation": "other_Compass_sites_not_Meridian",
                "evidence": "markets_other",
            }
        ],
        "evidence": [
            _e(
                "site",
                "compass",
                "locating its next hyperscale data center campus in Meridian",
                excerpt=0,
                role="physical_subject_and_city",
            ),
            _e(
                "scope",
                "compass",
                "The campus will consist of eight data centers",
                excerpt=0,
                role="eight_building_campus_scope",
            ),
            _e(
                "supply",
                "compass",
                "Mississippi Power will supply approximately 500 megawatts of power to the facility",
                excerpt=1,
                role="utility_supply_not_IT_capacity",
            ),
            _e(
                "market",
                "compass_markets",
                "Meridian broke ground in 2025, 80 miles east of Jackson, this 320 MW site is set to become one of the largest data center campuses in the Southeast",
                excerpt=1,
                role="Meridian_site_capacity_and_location",
            ),
            _e(
                "markets_other",
                "compass_markets",
                "This 200 MW campus, located 30 miles west of Chicago in Hoffman Estates",
                excerpt=0,
                role="separate_market_site",
            ),
            _e(
                "supplement",
                "compass_supplement",
                "Compass’ first campus in the region",
                excerpt=0,
                role="regional_first_campus_context",
            ),
            _e(
                "groundbreaking",
                "compass_markets",
                "Meridian broke ground in 2025",
                excerpt=1,
                role="groundbreaking_year",
            ),
        ],
        "capacity": [
            (
                "same_subject",
                "The 500MW value is approximate utility supply to the Meridian facility, a different basis from data-center build capacity.",
            ),
            (
                "same_subject",
                "The 320MW site value is explicitly associated with Meridian; the source does not specify IT-load basis.",
            ),
        ],
        "timeline": [
            (
                "same_subject",
                "The 2025 groundbreaking statement names the Meridian site.",
            )
        ],
    },
    {
        "id": "edgecore-mesa",
        "display_label_status": "regional_and_site_composite_label",
        "physical_subject": {
            "status": "multi_site_subject",
            "phrase": "first Mesa campus plus a separate additional Mesa parcel",
            "source_phrase_refs": ["first_campus", "new_land"],
            "evidence": ["new_land", "first_campus"],
        },
        "asset_scope": {
            "value": "mixed_or_ambiguous",
            "status": "source_separates_first_campus_new_parcel_and_market_total",
            "evidence": ["new_land", "first_campus", "future_buildings"],
        },
        "location": {
            "status": "source_explicit",
            "relation": "Mesa_Arizona_with_Metro_Phoenix_market_heading",
            "evidence": ["new_land"],
        },
        "organization_role": {
            "organization": "EdgeCore Digital Infrastructure",
            "role": "developer_owner_operator_company_general",
            "status": "source_general_not_site_specific",
            "evidence": ["new_land", "company_role"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "The source's company-wide 'developer, owner and operator' description does not identify legal title for each Mesa parcel or campus.",
        },
        "aliases": [],
        "children": [
            {
                "value": "PH01",
                "kind": "child_data_center_identifier",
                "parent_relation": "building_within_first_Mesa_campus",
                "evidence": "ph01",
            },
            {
                "value": "PH02",
                "kind": "child_data_center_identifier",
                "parent_relation": "second_Mesa_data_center_building",
                "evidence": "buildings",
            },
            {
                "value": "PH03",
                "kind": "child_data_center_identifier",
                "parent_relation": "third_Mesa_data_center_building",
                "evidence": "buildings",
            },
        ],
        "other_named_entities": [
            {
                "value": "Metro Phoenix data center market",
                "relation": "market_level_scope_not_one_campus",
                "evidence": "new_land",
            }
        ],
        "evidence": [
            _e(
                "new_land",
                "edgecore_press",
                "announced the acquisition of an additional 43.87 acres of land in [Mesa, Arizona](https://edgecore.com/locations/phoenix-data-center) and expanded data center capacity designed to deliver 450 MW+ to its hyperscale customers.",
                excerpt=3,
                role="regional_market_and_new_parcel",
            ),
            _e(
                "first_campus",
                "edgecore_press",
                "Since establishing our first Mesa campus in April 2023, we have worked quickly to construct and commission 206 MW at the site",
                excerpt=4,
                role="first_Mesa_campus_capacity",
            ),
            _e(
                "expansion",
                "edgecore_press",
                "This new tranche of land enables us to deliver another 250+ MW of data center space in Mesa",
                excerpt=4,
                role="new_parcel_expansion_capacity",
            ),
            _e(
                "buildings",
                "edgecore_press",
                "the second (PH02) and third (PH03) data centers currently under construction",
                excerpt=6,
                role="individual_building_ids",
            ),
            _e(
                "ph01",
                "edgecore_press",
                "EdgeCore's first data center in Mesa (PH01)",
                excerpt=6,
                role="first_Mesa_building_identifier",
            ),
            _e(
                "future_buildings",
                "edgecore_press",
                "slated for delivery to the two buildings currently under construction upon their completion in 2025 and 2026",
                excerpt=5,
                role="building_delivery_targets_unspecified_identity",
            ),
            _e(
                "company_role",
                "edgecore_press",
                "a wholesale data center developer, owner and operator",
                excerpt=3,
                role="company_general_role_not_site_title",
            ),
        ],
        "capacity": [
            (
                "ambiguous",
                "The 450MW+ statement is framed by a Metro Phoenix market title and Mesa parcel acquisition; it does not establish a single physical campus total.",
            ),
            (
                "nested_subject",
                "206MW is explicitly the first Mesa campus, a named child within the broader Mesa development context.",
            ),
            (
                "nested_subject",
                "250+MW is the additional data-center space enabled by a new Mesa parcel; it is a distinct expansion scope.",
            ),
        ],
        "timeline": [
            (
                "nested_subject",
                "The 2025 and 2026 power-delivery targets are for the two buildings under construction in the Mesa expansion. The text does not map each year one-to-one to PH02 versus PH03.",
            ),
            (
                "nested_subject",
                "The 2026 target is for the second of the two buildings under construction in the Mesa expansion; the text does not identify a PH02/PH03 pairing.",
            ),
        ],
    },
    {
        "id": "digital-realty-lagos",
        "display_label_status": "title_only_location_label",
        "physical_subject": {
            "status": "title_only_subject",
            "phrase": "new data center in Lagos",
            "source_phrase_refs": ["title"],
            "evidence": ["title", "partial_body"],
        },
        "asset_scope": {
            "value": "single_facility",
            "status": "title_only_retrieval_partial",
            "evidence": ["title", "partial_body"],
        },
        "location": {
            "status": "title_only",
            "relation": "Lagos_Nigeria_in_title_only",
            "evidence": ["title", "partial_body"],
        },
        "organization_role": {
            "organization": "Digital Realty",
            "role": "publisher_announcement",
            "status": "title_only",
            "evidence": ["title"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "The retained body is truncated before the facility assertion; title metadata does not establish ownership or detailed identity.",
        },
        "aliases": [],
        "other_named_entities": [],
        "evidence": [
            _e(
                "title",
                "digitalrealty",
                "Digital Realty Expands Presence in West Africa with New Data Center in Lagos",
                field="title",
                role="title_only_project_and_location",
            ),
            _e(
                "partial_body",
                "digitalrealty",
                "LAGOS, Nigeria – August 22, 2025 – Digital Realty (NYSE: DLR), the leading global provider of carrier-neutral data center, colocation, and interconnection solutions, today announced the...",
                excerpt=0,
                role="retrieval_partial_truncated_body",
            ),
        ],
        "capacity": [],
        "timeline": [],
    },
    {
        "id": "equinix-jh2",
        "display_label_status": "literal_site_identifier",
        "physical_subject": {
            "status": "explicit_named_subject",
            "phrase": "second IBX data center in Johor, JH2",
            "source_phrase_refs": ["site"],
            "evidence": ["site"],
        },
        "asset_scope": {
            "value": "single_facility",
            "status": "source_explicit",
            "evidence": ["site"],
        },
        "location": {
            "status": "source_explicit",
            "relation": "Johor_Malaysia",
            "evidence": ["site"],
        },
        "organization_role": {
            "organization": "Equinix, Inc.",
            "role": "operator_and_developer_context",
            "status": "source_explicit",
            "evidence": ["site"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "The source states an initial investment and construction milestone, not legal ownership.",
        },
        "aliases": [{"value": "JH2", "kind": "site_identifier", "evidence": "site"}],
        "other_named_entities": [],
        "evidence": [
            _e(
                "site",
                "equinix",
                "second International Business Exchange™ (IBX®) data center in Johor, JH2",
                excerpt=1,
                role="named_facility_and_location",
            ),
            _e(
                "location",
                "equinix",
                "KUALA LUMPUR, Malaysia, November 11, 2025",
                excerpt=1,
                role="dateline_metro_not_site_city",
            ),
            _e(
                "timeline",
                "equinix",
                "facility is expected to launch and provide 2,225 cabinets in Q3 2027",
                excerpt=1,
                role="facility_launch_target",
            ),
        ],
        "capacity": [],
        "timeline": [
            (
                "same_subject",
                "The launch target refers to the named JH2 facility in Johor.",
            )
        ],
    },
    {
        "id": "fervo-cape-station",
        "display_label_status": "literal_source_name",
        "physical_subject": {
            "status": "explicit_named_subject",
            "phrase": "Cape Station geothermal development",
            "source_phrase_refs": ["site"],
            "evidence": ["site"],
        },
        "asset_scope": {
            "value": "campus",
            "status": "source_explicit_multiphase_geoblocks",
            "evidence": ["phase_one", "contract"],
        },
        "location": {
            "status": "source_explicit",
            "relation": "Beaver_County_Utah",
            "evidence": ["site"],
        },
        "organization_role": {
            "organization": "Fervo Energy",
            "role": "developer",
            "status": "source_explicit",
            "evidence": ["site"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "The developer and project role do not establish legal ownership of every plant or land parcel.",
        },
        "aliases": [
            {"value": "Cape Station", "kind": "named_project", "evidence": "site"}
        ],
        "other_named_entities": [
            {
                "value": "Project Red",
                "relation": "separate_project",
                "evidence": "other_project",
            },
            {
                "value": "900MW offtake",
                "relation": "contract_not_physical_plant_capacity",
                "evidence": "contract",
            },
        ],
        "evidence": [
            _e(
                "site",
                "fervo",
                "[Cape Station](https://capestation.com/), its flagship geothermal development in Beaver County, Utah",
                excerpt=2,
                role="named_project_location_and_alias_surface",
            ),
            _e(
                "phase_one",
                "fervo",
                "Cape Station Phase I is an approximately 100 MW installation comprising three 33-megawatt GeoBlocks",
                excerpt=4,
                role="phase_and_component_scope",
            ),
            _e(
                "first_power",
                "fervo",
                "the first of which has achieved First Power",
                excerpt=4,
                role="first_GeoBlock_power",
            ),
            _e(
                "phase_two",
                "fervo",
                "The next phase, an additional 400 MW, is already under construction",
                excerpt=4,
                role="phase_two_capacity_and_status",
            ),
            _e(
                "contract",
                "fervo",
                "Fully contracted offtake at Cape Station sits at approximately 900 MW",
                excerpt=4,
                role="contracted_offtake_not_physical_capacity",
            ),
            _e(
                "other_project",
                "fervo",
                "Project Red",
                excerpt=3,
                role="separate_prior_project",
            ),
            _e(
                "first_cod",
                "fervo",
                "expected to reach its contractual commercial operations date (COD) by October 1, 2026",
                excerpt=4,
                role="first_GeoBlock_COD_deadline",
            ),
            _e(
                "remaining_cod",
                "fervo",
                "remaining two GeoBlocks, which are expected to reach contractual COD by January 1, 2027",
                excerpt=4,
                role="remaining_GeoBlocks_COD_deadline",
            ),
            _e(
                "phase_two_cod",
                "fervo",
                "with an expected COD in 2028",
                excerpt=4,
                role="phase_two_COD_target",
            ),
        ],
        "capacity": [
            (
                "nested_subject",
                "The approximately 100MW value is Phase I at Cape Station.",
            ),
            (
                "nested_subject",
                "33MW is for one GeoBlock included in Phase I; it is a component, not additive to the phase total.",
            ),
            (
                "nested_subject",
                "400MW is the additional Phase II at the same named project.",
            ),
            (
                "nested_subject",
                "Approximately 900MW of contracted offtake is for Cape Station, but it is a contract quantity rather than physical generation capacity and is excluded from V1's physical-capacity denominator.",
            ),
        ],
        "timeline": [
            ("nested_subject", "First Power is tied to the first GeoBlock."),
            ("nested_subject", "The COD deadline is for the first GeoBlock."),
            ("nested_subject", "The COD deadline is for GeoBlocks two and three."),
            ("nested_subject", "The 2028 COD target is for Phase II."),
        ],
    },
    {
        "id": "dominion-cvow",
        "display_label_status": "literal_project_name_with_subscope",
        "physical_subject": {
            "status": "explicit_named_subject",
            "phrase": "Coastal Virginia Offshore Wind commercial project",
            "source_phrase_refs": ["project"],
            "evidence": ["project", "supplement"],
        },
        "asset_scope": {
            "value": "mixed_or_ambiguous",
            "status": "project_contains_offshore_generation_and_onshore_transmission",
            "evidence": ["supplement", "turbines"],
        },
        "location": {
            "status": "source_explicit",
            "relation": "Virginia_offshore_and_onshore_transmission",
            "evidence": ["project", "supplement"],
        },
        "organization_role": {
            "organization": "Dominion Energy",
            "role": "project_publisher_and_developer_context",
            "status": "source_explicit",
            "evidence": ["project"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "The assigned project page does not establish legal ownership of all project assets.",
        },
        "aliases": [{"value": "CVOW", "kind": "project_acronym", "evidence": "alias"}],
        "other_named_entities": [
            {
                "value": "onshore transmission infrastructure",
                "relation": "project_subscope_not_offshore_wind_farm",
                "evidence": "supplement",
            }
        ],
        "evidence": [
            _e(
                "project",
                "dominion",
                "Coastal Virginia Offshore Wind commercial project",
                excerpt=0,
                role="named_project",
            ),
            _e(
                "alias",
                "dominion_project_supplement",
                "Coastal Virginia Offshore Wind (CVOW)",
                excerpt=0,
                role="explicit_project_acronym",
            ),
            _e(
                "capacity",
                "dominion",
                "The 2.6-gigawatt project",
                excerpt=1,
                role="commercial_project_generation_capacity",
            ),
            _e(
                "supplement",
                "dominion_project_supplement",
                "Onshore construction for transmission infrastructure began in late 2023, and offshore construction commenced in early 2024",
                excerpt=0,
                role="separate_project_subscopes",
            ),
            _e(
                "completion_2027",
                "dominion_project_supplement",
                "2027 expected completion",
                excerpt=1,
                role="supplement_completion_year",
            ),
            _e(
                "completion_2026",
                "dominion",
                "When fully constructed in 2026",
                excerpt=0,
                role="homepage_completion_year_conflict",
            ),
            _e(
                "turbines",
                "dominion_project_supplement",
                "Its 176 offshore wind turbines will generate",
                excerpt=2,
                role="offshore_generation_scope",
            ),
        ],
        "capacity": [
            (
                "same_subject",
                "2.6GW is stated for the CVOW commercial project; keep generation basis distinct from electrical demand.",
            )
        ],
        "timeline": [
            (
                "nested_subject",
                "Late 2023 refers to onshore transmission construction.",
            ),
            ("nested_subject", "Early 2024 refers to offshore construction."),
            (
                "same_subject",
                "2026 is the homepage completion target for the CVOW commercial project; the source conflicts with the supplement's 2027 expected-completion year.",
            ),
            (
                "same_subject",
                "2027 is the supplement completion target for the same CVOW commercial project; the source conflicts with the homepage's 2026 target.",
            ),
        ],
    },
    {
        "id": "terrapower-kemmerer",
        "display_label_status": "composite_unit_and_technology_label",
        "physical_subject": {
            "status": "explicit_named_subject",
            "phrase": "Natrium plant, Kemmerer Unit 1",
            "source_phrase_refs": ["site"],
            "evidence": ["site"],
        },
        "asset_scope": {
            "value": "single_facility",
            "status": "source_explicit_reactor_and_integrated_storage",
            "evidence": ["plant", "storage"],
        },
        "location": {
            "status": "source_explicit",
            "relation": "Kemmerer_Wyoming",
            "evidence": ["site"],
        },
        "organization_role": {
            "organization": "TerraPower",
            "role": "developer",
            "status": "source_explicit",
            "evidence": ["site"],
        },
        "owner_proof": {
            "status": "not_established",
            "reason": "The announcement identifies TerraPower as developer; it does not establish legal ownership.",
        },
        "aliases": [
            {
                "value": "Kemmerer Unit 1",
                "kind": "named_plant_unit",
                "evidence": "site",
            },
            {
                "value": "Natrium® plant1",
                "kind": "source_published_plant_name_surface",
                "evidence": "site",
            },
        ],
        "other_named_entities": [
            {
                "value": "Bechtel",
                "relation": "EPC_contractor_not_owner_alias",
                "evidence": "contractor",
            }
        ],
        "evidence": [
            _e(
                "site",
                "terrapower",
                "TerraPower, a nuclear innovation company, today, announced the official start of construction on its flagship Natrium® plant1, Kemmerer Unit 1",
                excerpt=2,
                role="named_project_and_location",
            ),
            _e(
                "contractor",
                "terrapower",
                "Bechtel is proud to partner with TerraPower as the engineering, procurement and construction contractor",
                excerpt=9,
                role="EPC_contractor_not_owner",
            ),
            _e(
                "support_start",
                "terrapower",
                "began construction on non-nuclear support facilities",
                excerpt=12,
                role="separate_earlier_support_facilities",
            ),
            _e(
                "plant",
                "terrapower",
                "The plant features a 345-megawatt (MW) sodium-cooled fast reactor",
                excerpt=11,
                role="reactor_base_output",
            ),
            _e(
                "storage",
                "terrapower",
                "The storage technology can boost energy output to 500 MW of power when needed",
                excerpt=11,
                role="integrated_storage_boost_not_additive",
            ),
            _e(
                "construction_date",
                "terrapower",
                "official start of construction on its flagship Natrium® plant1, Kemmerer Unit 1",
                excerpt=2,
                role="nuclear_plant_construction_start_2026",
            ),
        ],
        "capacity": [
            ("nested_subject", "345MW is the reactor base output component."),
            (
                "nested_subject",
                "500MW is storage-boosted peak output from the integrated plant, not additive to 345MW.",
            ),
        ],
        "timeline": [
            (
                "nested_subject",
                "June 2024 refers to non-nuclear support facilities, not nuclear construction.",
            ),
            (
                "same_subject",
                "April 23, 2026 is the stated start of construction for Kemmerer Unit 1.",
            ),
        ],
    },
]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_sha(value: Any) -> str:
    return _sha(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )


def _evidence_for_spec(
    evidence_spec: dict[str, Any],
    provenance_by_id: dict[str, dict[str, Any]],
    source_cache: dict[str, tuple[dict[str, Any], str]],
) -> dict[str, Any]:
    evidence_id = evidence_spec["id"]
    source_id = evidence_spec["source_id"]
    provenance = provenance_by_id[source_id]
    source_file = provenance["excerpts_file"]
    if source_file not in source_cache:
        raw = (V1 / source_file).read_bytes()
        source_cache[source_file] = (json.loads(raw), _sha(raw))
    source, source_hash = source_cache[source_file]
    pointer = evidence_spec["text_pointer"]
    if pointer == "/title":
        text = source["title"]
    elif pointer.startswith("/excerpts/"):
        text = source["excerpts"][int(pointer.rsplit("/", 1)[1])]
    else:
        raise ValueError(f"Unsupported text pointer: {pointer}")
    quote = evidence_spec["quote"]
    if text.count(quote) != 1:
        raise ValueError(
            f"Quote {evidence_id} must occur exactly once in {source_file}{pointer}"
        )
    start = text.index(quote)
    return {
        "id": evidence_id,
        "source_id": source_id,
        "source_file": source_file,
        "source_url": source.get("url"),
        "source_file_sha256": source_hash,
        "text_pointer": pointer,
        "text_sha256_utf8": _sha(text.encode("utf-8")),
        "offset_unit": "unicode_code_points",
        "start": start,
        "end": start + len(quote),
        "quote": quote,
        "quote_sha256_utf8": _sha(quote.encode("utf-8")),
        "context_role": evidence_spec["role"],
    }


def build_annotations() -> dict[str, Any]:
    gold_path = V1 / "reference-customers-r2.json"
    gold_bytes = gold_path.read_bytes()
    if _sha(gold_bytes) != EXPECTED_REFERENCE_SHA256:
        raise ValueError(
            "The v1 r2 reference file changed; do not regenerate v2 against new labels."
        )
    gold = json.loads(gold_bytes)
    if {spec["id"] for spec in SPECS} != {record["id"] for record in gold["records"]}:
        raise ValueError(
            "The v2 annotation specs must cover exactly the v1 r2 records."
        )

    preservation = json.loads(PRESERVATION_MANIFEST.read_text(encoding="utf-8"))
    expected_files = preservation["files_sha256"]
    current_files = {
        path.relative_to(V1).as_posix(): _sha(path.read_bytes())
        for path in sorted(V1.rglob("*"))
        if path.is_file()
    }
    if current_files != expected_files:
        raise ValueError(
            "A pre-v2 file under eval/customer-commercial-v1 changed; preserve the v1 baseline."
        )
    protected_inputs = {
        f"eval/customer-commercial-v1/{relative}": digest
        for relative, digest in sorted(expected_files.items())
    }
    source_cache: dict[str, tuple[dict[str, Any], str]] = {}
    gold_index = {
        record["id"]: (index, record) for index, record in enumerate(gold["records"])
    }
    records_out: list[dict[str, Any]] = []

    for spec in SPECS:
        index, record = gold_index[spec["id"]]
        provenance_by_id = {item["source_id"]: item for item in record["provenance"]}
        evidence = [
            _evidence_for_spec(item, provenance_by_id, source_cache)
            for item in spec["evidence"]
        ]
        evidence_by_id = {item["id"]: item for item in evidence}
        if len(evidence_by_id) != len(evidence):
            raise ValueError(f"Duplicate evidence IDs for {spec['id']}")

        used_sources = {item["source_id"] for item in evidence}
        expected_sources = set(provenance_by_id)
        if used_sources != expected_sources:
            raise ValueError(
                f"Every v1 provenance source needs a v2 context annotation: {spec['id']}"
            )

        physical = dict(spec["physical_subject"])
        physical["normalized_description"] = physical.pop("phrase")
        source_phrase_refs = physical.pop("source_phrase_refs")
        physical["source_phrase_evidence"] = [
            {
                "evidence_ref": evidence_ref,
                "exact_quote": evidence_by_id[evidence_ref]["quote"],
            }
            for evidence_ref in source_phrase_refs
        ]
        physical["evidence_refs"] = physical.pop("evidence")
        asset = dict(spec["asset_scope"])
        asset["evidence_refs"] = asset.pop("evidence")
        location = dict(spec["location"])
        location["display_value"] = record["location"]
        location["evidence_refs"] = location.pop("evidence")
        role = dict(spec["organization_role"])
        role["evidence_refs"] = role.pop("evidence")

        aliases = [
            {**item, "evidence_ref": item["evidence"]} for item in spec["aliases"]
        ]
        for alias in aliases:
            alias.pop("evidence")
        other_entities = [
            {**item, "evidence_ref": item["evidence"]}
            for item in spec["other_named_entities"]
        ]
        for entity in other_entities:
            entity.pop("evidence")
        children = [
            {**item, "evidence_ref": item["evidence"]}
            for item in spec.get("children", [])
        ]
        for child in children:
            child.pop("evidence")

        assertion_context: list[dict[str, Any]] = []
        for kind in ("capacity", "timeline"):
            values = record[kind]
            bindings = spec[kind]
            if len(values) != len(bindings):
                raise ValueError(
                    f"Every {kind} assertion needs a context disposition: {spec['id']}"
                )
            for assertion_index, (assertion, binding) in enumerate(
                zip(values, bindings, strict=True)
            ):
                disposition, reason = binding
                if disposition not in _ELIGIBILITY:
                    raise ValueError(f"Unknown context disposition: {disposition}")
                kind_evidence_refs = _ASSERTION_EVIDENCE_REFS.get((record["id"], kind))
                if kind_evidence_refs is None or len(kind_evidence_refs) != len(values):
                    raise ValueError(
                        f"Every assertion needs explicit evidence refs: {record['id']} {kind}"
                    )
                evidence_refs = kind_evidence_refs[assertion_index]
                if not evidence_refs or not set(evidence_refs) <= set(evidence_by_id):
                    raise ValueError(
                        f"Invalid assertion evidence refs: {record['id']} {kind}[{assertion_index}]"
                    )
                context = {
                    "v1_record_id": record["id"],
                    "v1_json_pointer": f"/records/{index}/{kind}/{assertion_index}",
                    "v1_assertion_sha256_canonical_json": _canonical_sha(assertion),
                    "assertion_kind": kind,
                    "binding_disposition": disposition,
                    "context_eligibility": _ELIGIBILITY[disposition],
                    "evidence_refs": evidence_refs,
                    "reason": reason,
                }
                excluded_reason = _V1_EXCLUDED_ASSERTIONS.get(
                    (record["id"], kind, assertion_index)
                )
                context["v1_scoring_denominator"] = {
                    "metric": "physical_capacity" if kind == "capacity" else "timeline",
                    "status": "excluded" if excluded_reason else "included",
                    **({"reason": excluded_reason} if excluded_reason else {}),
                }
                conflict = _SOURCE_CONFLICT_ASSERTIONS.get(
                    (record["id"], kind, assertion_index)
                )
                if conflict:
                    context["source_conflict"] = {
                        "status": "same_subject_conflicting_source_dates",
                        "related_v1_json_pointer": conflict["related_pointer"],
                        "evidence_refs": conflict["evidence_refs"],
                    }
                if record["id"] == "edgecore-mesa" and kind == "timeline":
                    context["subbuilding_pairing"] = (
                        "target date is subject-bound to the two under-construction Mesa buildings; PH02/PH03 one-to-one year pairing is not stated"
                    )
                assertion_context.append(context)

        records_out.append(
            {
                "reference_record_id": record["id"],
                "v1_record_json_pointer": f"/records/{index}",
                "v1_record_sha256_canonical_json": _canonical_sha(record),
                "display_label": {
                    "company": record["company"],
                    "project": record["project"],
                    "location": record["location"],
                    "interpretation_status": spec["display_label_status"],
                    "source_proof_role": "display_only_until_bound_by_context_annotations",
                },
                "physical_subject": physical,
                "source_supported_aliases": aliases,
                "source_supported_child_identifiers": children,
                "other_named_entities_not_site_aliases": other_entities,
                "asset_scope": asset,
                "source_supported_location": location,
                "organization_role": role,
                "owner_proof": spec["owner_proof"],
                "source_bundles": [
                    {
                        "source_id": item["source_id"],
                        "source_file": item["excerpts_file"],
                        "source_url": item["source_url"],
                        "publication_date": item.get("publication_date"),
                        "observation_date": item.get("observation_date"),
                        "evidence_refs": [
                            annotation["id"]
                            for annotation in evidence
                            if annotation["source_id"] == item["source_id"]
                        ],
                    }
                    for item in record["provenance"]
                ],
                "source_context_evidence": evidence,
                "assertion_context": assertion_context,
            }
        )

    return {
        "schema_version": "customer-commercial-reference-context-v2",
        "status": "proposed_annotations_pending_independent_review",
        "v1_reference_file": "eval/customer-commercial-v1/reference-customers-r2.json",
        "v1_reference_sha256": _sha(gold_bytes),
        "input_hash_policy": "All JSON under eval/customer-commercial-v1 is hashed and protected; v2 never writes to v1.",
        "preserved_v1_json_sha256": protected_inputs,
        "offset_definition": "Half-open Unicode code-point offsets into the exact string addressed by text_pointer; no normalization.",
        "record_count": len(records_out),
        "records": records_out,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check the saved annotation file matches generated content.",
    )
    args = parser.parse_args()
    data = json.dumps(build_annotations(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != data:
            raise SystemExit(
                "The saved context annotation does not match the builder output."
            )
        print(f"Context annotations match: {OUT.relative_to(ROOT)}")
        return
    OUT.write_text(data, encoding="utf-8")
    print(f"Wrote additive v2 overlay: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
