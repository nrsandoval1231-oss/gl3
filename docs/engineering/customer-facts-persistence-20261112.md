# Retained customer facts and generation publication

`backend/src/gridlens/intelligence/customer_intelligence.py` extends existing Evidence,
Interpretation, canonical Project and EvidencePackage records. It introduces no identity
namespace, company table, research queue, migration or navigation-time research.

## Receipt versus publication

`persist_customer_facts(session, *, project_id, evidence_id)` appends one immutable,
idempotent `customer-facts-v1` package with `provider=deterministic`, null `need_id`, and
an exact project/source-version binding. It never emits alerts, qualifies a need or changes
Pursuits. Normal and quiet backfill change behavior belongs to existing material-state hooks.
The normalized new/unchanged ingestion paths and accepted retained research path invoke it.

Publication does not trust a package merely because it is stored. Generation builders call
`project_customer_facts(..., generation=None)` once per project batch and deterministically
reparse all current accepted, exactly bound source evidence. The query checks interpretation
status/decision, raw and semantic hashes, canonical project identity, evidence URL/ID,
source association and exact targeted research-need association. Relationship-only admission
cannot authorize capacity or dates. Current canonical-source records may contribute without
creating a PowerNeed merely to store capacity. Forged audit-package payloads cannot change
published facts; package-only writes do not require a new browse invalidation trigger.

The builder freezes `customer_facts` and per-project `customer_priority` in existing
BrowseRow.compact. Requests call `project_customer_facts(..., generation=<existing generation>)`
and read that exact snapshot, preserving last-complete-generation semantics. The API owns
current-generation/source-policy/identity authorization and current read-time privacy filtering.
Do not expose this low-level frozen reader without those existing guards.

Source publication and observation dates remain distinct. `extracted_at` is null unless
retained Evidence.provenance supplies an actual extraction timestamp; observation time is
never relabeled as extraction time. Extraction method/version and location remain explicit.

## Scope and bounds

A document-level project match cannot assign every paragraph to the selected site. Numeric
and timeline quotes additionally require the exact canonical project or site to be the
grammatical subject and the relevant value/date to follow a supported local predicate.
Comparative/coordinated clauses abstain. A target name mentioned in another project's
sentence cannot lend it identity. This intentionally misses unsupported phrasing and pronouns.

Generation hydration uses one batched SELECT and does not create packages. More than 128
current source versions per project, 200,000 source characters, 1,000 source clauses or the
200-claim bound yields an explicit overflow package and incomplete aggregate/scenario state.
No bounded prefix is presented as a complete total. All contributing accepted source versions
within those bounds are considered; sources are not chosen by arrival order.

## Narrow structured commissioning path

An already admitted exact-project source can contain one bounded fenced JSON section:

```json
{
  "project_name": "Exact canonical project name",
  "commissioning_test_plan": [
    {
      "project_id": "existing-canonical-project-UUID",
      "block_id": "generator-test-A",
      "load_scope_id": "electrical-path-A",
      "sequence_stage": "stage-1",
      "rating": "2",
      "unit": "MW",
      "rating_basis": "electrical_output",
      "installed_units": 4,
      "concurrent_units": 2,
      "test_fraction": "0.75"
    }
  ]
}
```

This is a narrow retained engineering-section contract, not a manual product fact-entry
workflow or an inference from campus capacity. All ratings, loading, counts and sequence
must occur literally in the source section. Every block must carry the existing project ID
and the enclosing name must exactly match. The adapter supplies only canonical identity
and the current retained Evidence reference; supplied references to a different source are
rejected. Multiple concurrent electrical load scopes additionally require an explicit
`disjoint_load_scope_ids` list covering those scopes. Duplicate upstream/downstream scopes,
missing required data, malformed or multiple sections and inconsistent scenarios abstain.
The [engineering calculator](commissioning-model-20261112.md) still validates the whole plan.

Ordinary narrative test plans, source formats lacking this explicit identity/section contract,
and campus-only announcements remain Insufficient data. No existing production engineering
coverage is asserted. The runtime path is proven with disposable synthetic source documents;
that is separate from real-customer acceptance or live-source availability.

## Verification and rollback

Focused command with the task's disposable database environment:

```bash
uv run --project backend pytest backend/tests/integration/test_customer_commercial_intelligence.py -q
```

Tests exercise persistence/replay, source/hash/URL/project refusal, frozen generation reads,
no package writes on build, source bounds, company/project misassociation, actual retained
research admission, capacity-only versus rental demand, and runtime engineering scenarios.

Rollback can withhold the additive customer fields and revert their generation-build hooks
while retaining all immutable receipts and existing schema. It must preserve current source,
identity, privacy and material-history safeguards. Nothing here authorizes production deployment,
retained-data backfill, paid providers or operational source activation.
