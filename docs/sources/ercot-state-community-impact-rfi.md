# ERCOT State and Community Impact RFI — public information contract

Inspected main: `94c3acb7b36c6d5d04a77a0ec445e793e05120a4`, October 7, 2026.
Existing Project identity JSON, Interpretation assessment JSON, Source, Observation and
versioned Evidence are sufficient storage. Main lacked a typed RFI contract and public
publication-state handling. This change adds those without a database migration.
Texas §25.194 readiness is separate work in draft PR29, not part of main or this mapping.

## Official sources and scope

- [RFI landing page](https://www.ercot.com/about/legal/data-center-impact-rfi):
  public program description; intended public report by December 10, 2026.
- [Question guide, version 1.0, September 18](https://www.ercot.com/files/docs/2026/09/18/State-and-Community-Impact-RFI_Question-Reference-9.18.26.pdf):
  pages 1–4 define respondents, confidentiality and FI questions. RIOO controls the
  response process; this guide is reference material, not submitted answers.
- [September 24 notice](https://www.ercot.com/services/comm/mkt_notices/M-B091426-02):
  newly substantiated medium loads have a voluntary route; October 5 was the cutoff
  for issuing new voluntary RFIs. Responses remain due October 12 at 5 p.m. Central.
- [September 21 visibility notice](https://www.ercot.com/services/comm/mkt_notices/M-C092126-01):
  submitting TSP/DSP contacts cannot see developer responses and uploaded documents.

The reference guide includes virtual-currency mining facilities. Its medium-load
interval is **at least 25 and less than 75 MW**, not an integer-only 25–74 interval.
Required medium respondents must be substantiated and reported in the August 19
Medium Load RFI. Newly substantiated, previously unreported loads have a separate
voluntary category. Qualifying Batch Zero base/studied loads are distinct.
Non-energization refers to any voltage for medium loads; for qualifying Batch Zero
it refers to the facility or addition at transmission voltage (60 kV or above).
The input flag must describe the relevant facility/addition and voltage scope;
partial campus operation does not establish the flag for a new addition.

## Smallest representation

| Public schema attribute | Typed field | Interpretation boundary |
|---|---|---|
| FI-3 / FI-4 project and developer | project_name / developer | Site-specific disclosure required |
| FI-5 latitude / longitude | latitude / longitude | Texas bounds; not an inferred address |
| FI-6 water planning group | regional_water_planning_group | Keep reported text; no coordinate-to-region inference |
| Respondent instructions | peak_requested_load_mw, ercot_region, not_yet_energized, substantiated_load, medium_load_reported, newly_substantiated, batch_zero_classification | Requested site load is not activity demand |
| Sections A–F | public_financial_assistance, grid_dependence, onsite_generation, water, cooling, community_impacts, ownership_control | Quoted source reports; not verified supply or buyer authority |

Each claim retains a value and exact excerpt within its Evidence abstract. The
record carries evidence UUID/hash and conservative project identity key.
Interpretation status/version, current observation hash, assessment hash, record
hash, evidence UUID, public URL and source date must agree before projection.
Different disclosures remain separate; contradictions are not silently resolved.
Unknown/N/A information is omitted rather than converted to false or zero.

Source family: `ercot-impact-rfi`. Supported provenance labels:

- `ercot-impact-rfi-schema`: public questions, no project answers.
- `ercot-impact-rfi-project`: independently public, dated, site-identified disclosure.
- `ercot-impact-rfi-aggregate`: public aggregate results, no named-project assignment.
- `ercot-impact-rfi-anonymized`: public anonymized results, no reverse identification.

The last two are future publication classifications, not claims that results have
already been released. Restricted responses are not a supported publication state.
Schema/aggregate/anonymized records prohibit project identity and project claims.
The contract is stored under `Interpretation.assessment.ercot_impact_rfi`, with
evaluator version `ercot-impact-rfi-v1`; the normal exact assessment evidence hash
is also required. Project-state adds a read-only `ercot_impact_rfi` section.

## Acquisition and commercial boundaries

This is a typed representation and read projection, not a new active feed, parser,
writer or backfill. No operational source-registry entry is enabled: registry host
and adapter admission require a separate real retrieval/persistence/replay proof.
Public documents can be retained through an authorized existing/manual acquisition
path with the Source family/method contract above. This change does not automate
that process. The source matrix's utility family remains PLANNED.

No RFI context independently admits an opportunity. A source-backed category is
Derived advisory metadata; it does not prove submission, attestation, study entry,
financial funding, interconnection readiness, utility delay, temporary MW, gap
duration, adequate generation, foreign control, or purchasing authority.
The model introduces no legal compliance conclusion, lifecycle event, tier change,
notification, outreach, or deployment. Independent public permits and utility
records continue through existing admission gates.
