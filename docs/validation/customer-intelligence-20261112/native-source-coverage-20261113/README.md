# Retained-source commercial runtime evaluation

This offline evaluation sends retained public text through the current native
GridLens path: source admission, canonical project matching, evidence and
interpretation creation, project-scoped organization claims, saved browse
publication, and the account queue API. It never uses reference customer labels
to create projects, aliases, claims, or account memberships. The immutable
reference bundle is used only for hash verification and the separate scope
replay.

The adapter re-parses source spans and holds a document unless a single physical
project, site, and activity are directly linked by supported source wording. It
requires an exact publication day for admission. The 29 retained artifacts
resolve to 22 source documents; 4 were admitted and 18 were held. The held
documents contain public facts, but the bounded parser could not verify the
complete project/site/activity relation. This is parser missingness, not a
finding that the public facts do not exist. Aligned is now admitted as a
Conesville Industrial Park site, but its title's Ohio reference is not joined to
the body site, so region remains unknown and no PowerNeed is created. Applied
Digital's building activity still cannot be safely joined to its Ellendale
campus across separate excerpts. Switch is now admitted as a Round Rock project;
its Austin/Houston ecosystem quantities were not attached to that site.

## Latest native runtime receipt

See [native-runtime-replay-source-role-final-20261113.json](native-runtime-replay-source-role-final-20261113.json)
for the latest complete output. The earlier [source-coverage receipt](native-runtime-replay-source-coverage-final-20261113.json) is preserved as a historical capture. It was created in a fresh loopback PostgreSQL database
ending in `_test`, which the runner dropped after completion. The run produced:

- 4 admitted source records created 4 Projects and 4 accepted
  Evidence/Interpretation pairs. Three PowerNeeds were created, all with
  `required_mw: null`. Aligned's Conesville project is held outside the
  eligible-region policy and creates no PowerNeed.
- 3 saved browse rows and 3 account queue API cards, with 3 current
  project-scoped company identity links.
- The ordinary and primary
  `groups(shortlist=False, canonical_only=True)` queries each returned 3
  project-scoped customer groups: CyrusOne, DataBank, and Switch. A retained
  source-bound developer claim now links Switch to the admitted Round Rock
  project. These links do not establish global company identity, cross-project
  grouping, or legal ownership. The explicit shortlist query returned 0 rows,
  and the canonical detail API opened CyrusOne. These counts show endpoint
  behavior, not customer usefulness.
- A DataBank project-scoped `owner_developer` claim for the 2024 Red Oak
  announcement and a CyrusOne `project_customer` claim for the 2025 Bosque
  County service agreement. These are source-reported roles, not verified legal
  ownership or global company identity matches.
- A DataBank source fact package with up-to 240 MW Phase 1 IT load and up-to
  480 MW site IT load. These remain separately scoped evidence claims and do
  not populate required demand. Portfolio roll-up and double-count accuracy
  were not evaluated.
- The Switch Round Rock project is linked to a project-scoped company identity
  through source-derived developer involvement. This is a source-reported role,
  not verified legal ownership or a globally reconciled company identity. The
  project has a PowerNeed with unknown MW; the retained text produced no
  source-backed capacity or timeline claims for it in this runtime. The
  source's separate Austin/Houston and ecosystem figures remain unassigned.
- All three cards are WATCH signals. The API returns no verified contact evidence;
  contact state is `unavailable_unverified`.
- CyrusOne's opened project detail includes a source-reported operational
  target: expected operation by Q4 2026, at quarter precision, from its July
  30, 2025 source. It is an operational deadline, not a construction-start or
  energization date; required MW and commissioning demand remain unknown.

The integration test also verifies replay stability, same-source 480→640 MW
role identity continuity, and a same-URL adverse title update. That update
closes the prior Need without inventing zero MW. A later accepted 720 MW source
version receives a new project-scoped identity after the adverse version; a
withdrawal removes the published account membership. These are finite offline
source-path controls, not production coverage.

The separately scored 20-project source-text replay is in
[source-text-scope-replay-source-role-final-20261113.json](source-text-scope-replay-source-role-final-20261113.json). The earlier [source-coverage replay](source-text-scope-replay-source-coverage-final-20261113.json) remains available as a historical receipt.
It verified 29 retained artifacts against 27 distinct source captures in the
reference bundle; 2 artifacts were not assigned to those source captures. With
reference project/location used only as disclosed oracle scope context, it
scored capacity claims at 2 true positives, 0 false positives, and 30 false
negatives (100% precision, 6.25% recall). Timeline claims scored 0 true
positives, 0 false positives, and 30 false negatives. These low coverage
results are parser/extractor missingness, not a conclusion that the retained
sources lack those facts. The source-text replay still scores CyrusOne's Q4
2026 operational target as a scoped false negative even though the separate
native ingestion-to-API runtime surfaces that source-backed quarter forecast.
These are separate evaluation paths; the runtime fact is not counted as an
oracle-scope true positive.

The publication date rule and bounded reviewer outcome are recorded in
[publication-date-boundary-review-20261113.md](../../../../eval/customer-commercial-v1/runtime/publication-date-boundary-review-20261113.md).
The per-source miss breakdown and the difference between runtime projection
and oracle-scoped scores are detailed in
[coverage-diagnostic.md](coverage-diagnostic.md).

## Measurement limits

Identity accuracy is not measured because reference IDs were never seeded.
Project-scoped company identities do not establish global company grouping or
cross-project deduplication. Capacity roll-up/double-counting, ranking
usefulness, and salesperson usefulness are not measured. The three canonical customer groups and detail demonstrate
saved-generation/API plumbing; the empty shortlist indicates no needs meet its
current eligibility rules. The three identities are project-scoped and do not
measure global identity resolution or cross-project grouping.
Contact availability is unknown because this run acquired no current contact
evidence.

## Reproduce

Use a configured loopback PostgreSQL `TEST_DATABASE_URL` whose base database
ends in `_test`, plus a distinct configured `DATABASE_URL`. The runner creates
and drops its own uniquely named `_test` database. V1 is frozen; keep generated
receipts in this dated validation directory. Choose a new output filename; the
script refuses to overwrite an existing receipt.

```sh
: "${TEST_DATABASE_URL:?configure a loopback PostgreSQL test URL ending in _test}"
: "${DATABASE_URL:?configure a distinct application database URL}"
uv run --project backend python scripts/evaluate_customer_commercial_runtime.py \
  --database-url "$TEST_DATABASE_URL" \
  --output "docs/validation/customer-intelligence-20261112/native-source-coverage-20261113/native-runtime-replay-$(date -u +%Y%m%dT%H%M%SZ).json"
```
