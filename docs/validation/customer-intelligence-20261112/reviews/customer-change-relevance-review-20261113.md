# Independent review: customer change relevance — November 13, 2026

Disposition: bounded source change accepted at the exact final hashes below. Worktree `/workspace/gl3-customer-change-relevance-20261113`, based on `2336b02a`. This review covers the saved-generation projection of commercial recency and its typed labels. It does not approve production deployment, broader source coverage, contact quality, or ranking usefulness.

## Problem and implementation

First observation of a historical source fact previously entered the recent-material-change selection based on ingestion time. That could label DataBank's initial capacity or CyrusOne's initial operational forecast as a revision and add ten potential points, despite empty predecessor facts and old source publication dates. Immutable history itself is valid; the commercial interpretation was wrong.

The change keeps the ledger and material-state producers untouched. The saved-generation query now requires a meaningful prior value, a different new value, and a source date in the inclusive 0–90-day window. It applies these predicates before per-project ranking, so newer initial observations cannot consume slots ahead of a genuine revision. Both displayed capacity/timing developments and the all-material-field priority flag use this filtered set. Navigation continues reading saved rows rather than querying the event ledger.

Unknown, absent and empty predecessors—including an object with an empty `claims` array—do not establish a revision. Known scalars, arrays and populated claim objects remain meaningful. JSON null or empty new values can represent withdrawal of a previously known fact; missing new-state values do not. The existing producer shapes were inspected: capacity/timing use claim objects, phase is a scalar, utility timing and needs use arrays, and buyer/contractor use role arrays. No current producer of a non-claim object filled only with empty metadata was found.

The event's recorded `source_date` takes precedence. Only when absent can an exactly linked immutable Evidence publication date supply it; the join requires Evidence ID, observation ID and content hash. Buying-chain fallback requires the explicit BuyingChainEvidence ID and the same project. Matching its hash against `ChangeEvent.content_hash` would be incorrect: the existing event producer keeps the contextual ingestion Evidence hash even when a separate buying-chain source supports the role change. Observed, created and last-seen timestamps never substitute for publication. Creation time only bounds the snapshot and its existing history window. Future dates are excluded rather than replaced by a convenient older fallback.

Operational-target changes remain operational-target changes. Labeling considers changed claim types, excluding unchanged neighboring construction claims; mixed or unknown event types get the generic project-schedule label. No forecast is promoted to actual construction or energization, and no precision is invented.

## Independent checks

- Read the complete source diff, new tests, material-state/event producers and saved-row consumers. No change to identity matching, source admission, suppression policy, need eligibility, ingestion history or existing tests was found.
- Ran the new pure label module: **9 passed**. Command: `PYTHONPATH=backend/src /workspace/gl3-commercial/backend/.venv/bin/python -m pytest backend/tests/unit/test_customer_revision_labels.py -q -o addopts='' --tb=short`, with dummy required settings and an unreachable loopback database URL. No database fixture or provider ran.
- Executed the actual isolated query-construction function with a capturing session. Verified exact project-ID parameters, 90-day source/date and timestamp bounds, source eligibility before `row_number`, Evidence/BCE link predicates, and absence of observation/last-seen date fallback. This checks query construction, not PostgreSQL execution.
- Read the builder's integration controls for all material fields, old/future/missing dates, fallback mismatch, preserved withdrawals, qualifier-only revisions, real operational targets, and first-event limit starvation. The native DataBank/Cyrus test retains source facts and immutable events while requiring no false recent revisions, no material-change bonus and no revised-evidence next action.

The builder reported 18 integration tests and nine pure tests passing before a new-test-only adjustment removing an accidental cap on future source coverage. The final targeted native-source rerun then passed **1/1** at the frozen integration hash below. That test selects the two targeted real sources rather than requiring the whole adapter corpus to contain only two records, and preserves assertions for both observed material-event types. The reviewer inspected the final test adjustment but did not run database tests during the performance quiet window.

Accepted production source SHA-256: `backend/src/gridlens/intelligence/saved_browse.py` — `108087b8a83658c77edcc0c58653efe0db5f972a27e65108c1c64c4795b082cd`.

Pure test SHA-256: `backend/tests/unit/test_customer_revision_labels.py` — `0f1b078ec3b1ac9b1aff457e49306eea1faa42ef562b64a306663b55689b6c21`.

Integration test SHA-256: `backend/tests/integration/test_customer_change_relevance.py` — `0cb865df36aaad7784c00be8f143ac6bf061b4ee393b357f8ae97d857cafdd0b`.

All three file hashes were independently checked after freeze. Existing tests and evaluation/source artifacts are unchanged against the base; `git diff --check` passes.

No remaining concrete defect was identified within this bounded fix. A newly published saved generation is necessary to expose the corrected interpretation; source acceptance alone does not update an existing snapshot or establish operational readiness.
