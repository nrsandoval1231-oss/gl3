# Customer change relevance — independent review preparation

Date: 2026-11-13. Base: `2336b02ab5f12d88a87ca8b00968050ece047089`.
Worktree: `/workspace/gl3-customer-change-relevance-20261113`.
Branch: `feat/customer-change-relevance-20261113`. Uncommitted; independent review pending.

## Confirmed defect

Read-only inspection of the original native UI smoke database found first-seen
historical facts displayed as recent revisions. DataBank's 2024-09-10 announcement
created a `capacity_changed` event with empty prior claims; CyrusOne's 2025-07-30
announcement created a `build_timing_changed` event with empty prior claims and an
`operational_target`, not energization. Both were ingested on 2026-11-13.

The published snapshot selected material events by ingestion time alone. It
displayed “Build capacity revised” and “Construction or energization schedule
revised”, substituted the revised-evidence next action, and added ten potential
points to each commercial score. Source-age freshness correctly remained zero.
The observed commercial scores were DataBank 3 and CyrusOne 4; without that bonus
they were 1 and 2 under the same scoring inputs. Legacy need rank 45 was unaffected.

## Change to review

Only `backend/src/gridlens/intelligence/saved_browse.py` changes product behavior.
ChangeEvent storage, history, ingestion, scoring weights, company identities,
customer-results code, and existing tests remain unchanged.

The existing generation-publication query now selects dated material revisions:

- A meaningful predecessor must exist, and its value must differ from the new
  value. Null, empty collections, empty claims, and unknown predecessor labels
  do not establish a revision. Removal of a previously known value remains a
  possible revision.
- The event's source date must be within the previous 90 days and not future.
  If absent, only the linked immutable Evidence publication date or same-project
  BuyingChainEvidence publication date can supply it. Evidence fallback also
  requires matching observation and content hash. Observation/creation times
  never supply a source date. The existing creation-time snapshot bounds remain.
- Eligibility is applied before per-project limits. Initial discoveries cannot
  occupy the slots and hide a genuine revision.
- These rules govern both customer developments and the all-material-field
  bonus, including ownership, phase, power-need and utility-timing changes.
- Timing labels reflect the changed claim types. An operational-target change
  is “Operational target revised”; mixed/untyped timing changes use “Project
  schedule revised”. Unchanged neighboring claims do not broaden the label.

Requests continue reading the saved projection; there is no new request-time
history scan. A new saved generation is needed to publish the corrected view.

## Verification

All commands used the shared installed interpreter with
`PYTHONPATH=/workspace/gl3-customer-change-relevance-20261113/backend/src`, so imports
resolved to this worktree rather than the editable installation's original path.

- New unit file `test_customer_revision_labels.py`: **9 passed**, 1.70 seconds.
- New integration file `test_customer_change_relevance.py`, unchanged
  `test_customer_intelligence_projection.py`, and unchanged
  `test_customer_material_changes.py`: **18 passed**, 27.52 seconds.
- After restricting the new native regression to the two targeted sources
  without capping their supported fact count, that test was rerun:
  **1 passed**, 20.34 seconds. It does not constrain broader source coverage.
- Ruff check/format and focused mypy: passed.

Integration used the newly created disposable loopback database
`gl3_customer_change_relevance_20261113_a5c0ad45_test` on port 55439. Each fixture used
and removed its own schema. No original smoke database, retained database,
production service, paid provider, or live publisher was written or called.

New regression coverage includes first facts for all material fields, old/unknown/
future source dates, exact publication-date fallback, mismatched evidence, genuine
ownership/phase/need changes, qualifier-only revisions, withdrawal, and revision
selection despite newer initial events. The existing genuine 50→100 revision
fixture with no event source date passes unchanged via linked publication date.

The actual retained DataBank/CyrusOne regression traverses ingestion, retained-only
enrichment, saved-generation publication and canonical account queries. It verifies
that both accounts and their capacity/timeline facts remain, all immutable change
rows and before/after states remain, recent developments are empty, the material
bonus is zero, and the false revised-evidence next action is absent. A separate
positive snapshot test retains the bonus and correct labels for recent capacity
qualifier and operational-target revisions.

This is a bounded correction of commercial recency, not broader source-coverage,
contact-quality, or production acceptance. No existing test was edited, and no
commit or push was made. Independent review and integrated gates remain pending.

Frozen product SHA-256: `108087b8a83658c77edcc0c58653efe0db5f972a27e65108c1c64c4795b082cd`.
New unit SHA-256: `0f1b078ec3b1ac9b1aff457e49306eea1faa42ef562b64a306663b55689b6c21`.
New integration SHA-256: `0cb865df36aaad7784c00be8f143ac6bf061b4ee393b357f8ae97d857cafdd0b`.
