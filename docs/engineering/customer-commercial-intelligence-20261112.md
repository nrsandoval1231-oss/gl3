# Customer commercial intelligence: architecture audit and contract

Audit date: 2026-11-12. Audited main: `bf75d32746d28ac44effcb65989d53fdeaa765e4`.
This is a source audit and implementation contract, not a production-readiness receipt.
The current owner's Commercial Intelligence & Customer-First Experience request supersedes older draft-only scope and layout prescriptions. Production deployment remains unauthorized.

## Findings and reuse

| Area | Exists on main | Extension needed |
| --- | --- | --- |
| Canonical customer | `backend/src/gridlens/intelligence/customer_results.py` generation-bound grouped SQL; `account_identity.py`; `customer_accounts.py` memberships and aliases | Attach commercial facts to these accounts; no parallel customer table or identity resolver |
| Identity | Company/person identities, versioned project memberships, physical project matching, canonical need aliases | Keep ambiguous and same-name groups explicitly unresolved; never merge subsidiaries by name |
| Evidence | Immutable Evidence and EvidencePackage, source hashes, extraction versions, current/corrected fact decisions | Typed build-capacity, timeline and commissioning inputs, deterministic conflict/supersession policy |
| Briefs | `domain/commercial_brief.py`: why now, scoped power, best contact, action, freshness and sources | Account-wide summary over distinct projects, preserving need-specific actions |
| Research | Autonomous retained-first acquisition, canonical-company research, fences, budgets, retries, refresh | Improve supported engineering inputs and named-contact coverage; no navigation-triggered research |
| Contacts | `company_contacts.py`, `company_contact_discovery.py`, central `company_contact_attribution.py` | Authoritative employer/domain/source binding, relevant named roles, useful missing-contact state |
| Changes | `intelligence/change_detection.py` ProjectMaterialState and idempotent ChangeEvent | Typed capacity, ownership and precise schedule changes; retain privacy-safe history publication |
| Pursuits | Need-scoped persistent commercial pursuits, tasks and confirmed activity | Reuse existing IDs and picker; research cannot create execution state |
| UI | Canonical grouped cards, CompanyView, search and progressive source disclosure | Consolidated capacity/timelines/developments and compact Customers workspace |
| Calculations | Decimal equipment-demand and power-schedule conventions | New commissioning model; existing pump/compressor coefficients are not applicable |
| Performance | Indexed match keys, generation fencing, scoped dirty-project triggers, batched cohort queries | Measure account rollups at realistic scale and preserve bounded query counts |

### Why information is not surfaced

`customer_results.groups()` returns account identity, counts and relevance plus a representative
`featured_project` and `account_contact_project`. It does not expose company-wide typed build
capacity, commissioning scenarios or precise construction/energization timelines. CompanyView
likewise has overview, contacts, projects and pursuits but no consolidated analysis.
This is primarily a missing projection contract, not hidden supported account totals.

`PowerNeed.required_mw` and `BrowseRow.mw_low/high` describe need/activity demand.
They MUST NOT be relabeled or summed as build capacity. LifecycleEvent stores a SQL Date;
original quarter/year labels need explicit precision in retained payloads before publication.
AccountContacts currently favors usable contact routes; verified names and relevant roles can
be useful even without a permitted email/phone, subject to the same publication safeguards.

### Verified PR and schema state

GitHub metadata was checked on 2026-11-12:

- PR183 Pursuits: merged `cbe4aec638be8a4d45e7e7fd22e554a14b997067`.
- PR186 shortlist: merged `3e1982ce6b36b951a634b75333eb08d27d83a097`.
- PR187 account-first: merged `bc433650ce4706dddfb5b30d78a502e3b528f54e`.
- PR188 autonomous commercial research: merged `5d93bea2341955e5b1dcc693f0355c48191d7218`.
- PR190 bounded stale browse and PR191 ingestion writes: merged; preserve all generation and matching fences.
- PR193 match-key race and Phase 2 browser-manifest repair: merged `f2a4a8051374bd86bd3d152d063035a524bdef66`.
- PR194 sign-in: merged as audited main above. Preserve its existing authentication behavior.
- PR189 premium workspace: open draft, head `cfedab6c7a7e0531b430ab06f1ebe4acb3a53164`, conflicting with main.
- Source migration head: `0056_statement_level_dirty_projects`. Older 0049/0050/0051 overview claims are dated, not current migration inventory.

PR189's prior acceptance is source-specific. Reconcile its header, compact cards, mobile layout
and build identity against current main. Preserve serve-stale notices, current auth, contact
privacy, Phase 2 manifest repairs and current schema guards. Omit its decorative architectural
header image and unavailable New Today/In Research KPI tiles under the latest owner direction.
No blind merge or inherited acceptance.

## Canonical customer intelligence contract v1

The contract extends existing account responses. Account/group IDs, company IDs, project IDs
and need IDs are existing identifiers. Unresolved groups remain labeled provisional and cannot
claim a verified canonical company. No new identity namespace.

### Fact envelope

Every supported commercially material fact carries:

- Stable fact key, canonical company/project association and optional phase/equipment/need scope.
- Typed value, unit, exact/approximate/range qualifier and status.
- Source/document reference and URL, immutable source-version/hash binding.
- Source publication date when known, observation date, extraction method and version.
- Verification/confidence state, source authority and explicit conflicting/superseded fact references.
- Selection reason and calculation version where calculated. Unknown is null with a reason, never zero.

Resolve deterministically: require valid current scope and source binding; retain withdrawals and
privacy controls; prefer verified primary authority over secondary reports; prefer explicit
scope/type over inferred interpretation; use publication/event chronology only among comparable
supported claims. Repeated syndication is not independent corroboration. Equal-strength
incompatible assertions remain conflicted. New weaker assertions cannot displace verified facts.
Observation time alone is not evidence of a real-world revision.

### Capacity

Kinds: campus development, IT load, utility service, generation, individual phase, unknown.
A phase amount also records its electrical basis; phase scope does not make IT and service
capacity compatible. Preserve reported amount and normalization to MW with Decimal arithmetic.

Each claim identifies physical site, phase and inclusion relationships. Aggregate only compatible
bases and proven disjoint scopes. Campus totals exclude included phases from addition. Repeated
announcements share one scope; expansions require explicit incremental-versus-total evidence.
Conflicting scope or unknown overlap causes abstention for the affected total, with visible
coverage and excluded claims. Do not report a partial sum as a complete company total.
Different capacity types remain separate; no undocumented PUE or service conversion.

### Timelines

Event kinds: announced construction start, verified actual start, expected first energization,
phase energization, full operational target. Retain original label and precision (day/month/
quarter/year/range/unknown), event scope, actual-versus-expected status and source revisions.
Internal interval bounds support ordering only; they are not exact dates for display.
Operational target is not automatically first energization; permit issue date is not construction.

### Commissioning

Return status, low/base/high MW only when justified, confidence, model/config version and input
digest, assumptions, limitations and input evidence. Label every numeric result an engineering
scenario, not verified demand or rental requirement. No universal campus-capacity percentage.

Baseline uses evidence of rated equipment or a defined commissioning block, electrical basis,
test loading and concurrent test sequence. Do not add upstream/downstream tests of the same
electrical load. Missing sequence, basis, rating or scope yields Insufficient data.
Project constraints and incomplete engineering coverage remain visible. Public announcements
of campus MW alone are insufficient. Parameters are versioned/configurable and changes require
deterministic recomputation and tests, not LLM scoring.

Engineering research read during audit:
- Cummins, Load Bank Performance Testing: https://www.cummins.com/en-na/na/sales-and-service/load-bank-performance-testing
- Robert Trefz, 7x24 Exchange, Load Bank Testing in Data Centers: https://www.7x24exchange.org/industry-news/magazine-archives/load-bank-testing-in-data-centers/
- Cadence, Load Bank Testing for Data Centers (published 2026-10-01): https://cadencenow.com/load-bank-testing-for-data-centers-verifying-backup-power/

These support equipment/system test scenarios and project-specific procedures; none establishes
a universal fraction of campus capacity. Cummins' maintenance/wet-stacking guidance does not
justify using maintenance test percentages as new-project rental requirements.

### Changes, priority and contacts

Reuse immutable snapshots and ChangeEvent replay keys. Compare selected scoped facts; retain
old/new values, source dates, observation timestamps and evidence. Repeated articles for the same
event do not produce another event. Publication must use existing history-privacy projection.

Deterministic commercial priority separates opportunity potential from evidence confidence,
uses explicit component contributions and stable tie-breaking, and considers supported capacity,
timing/phase, material changes, geography, quality, contacts and freshness. Missing inputs do not
become negative facts. The existing enrichment planner ranks research work, not customers.
Scores stay out of primary cards; explanation belongs in detail.

Contacts retain name, role, employer/project association, source and verification state, plus only
permitted professional methods. Publish through central native/source-bound attribution, including
current and historical suppression controls. No fabricated contact methods, inferred employment,
or promotion of a website-domain resemblance into canonical identity. Without verified contacts,
show a specific research state and justified action.

### Read path

Hydrate structured retained facts in batches for the generation-bound account cohort, including
all eligible account projects rather than only a visible child page. Search/filter before account
pagination; predicates on a project must still match the same child. Distinguish account-wide
totals from filtered coverage. Preserve stale-generation policy/source/identity/privacy fences.
No external research or calculation-provider calls on ordinary navigation; no per-card N+1 hydration.

## Evaluation baseline and acceptance

Existing Phase 2 matched evaluation is synthetic: two accounts, four physical projects, five
needs; useful coverage 4/5 unchanged, named-contact coverage zero, all four reported quantities
unknown. Candidate direct read p50/p95 16.17/25.75 ms versus baseline 4.77/12.21 ms, n=5.
These are historical in-process measurements, not current HTTP/scale acceptance.

Historical account-first synthetic measurement: 2,098 rows/417 groups, HTTP p50 105 ms/p95 464 ms,
17 requests. Retain indexed ingestion benchmark harness and matching-equivalence, race, privacy,
Pursuits persistence and generation regression tests.

Required new evaluation: 20 real organizations with actual source excerpts and independently
reviewed reference labels, representative phased campuses and other relevant infrastructure.
Run raw-source extraction separately from structured calculation tests. Report precision/recall,
missingness and coverage with denominators; distinguish unavailable source facts from missed
extraction. Measure identity, association, duplicates, typed capacity/double-counting, precise
timelines, scenario validity/traceability, verified contact coverage, provenance, priority and
sales usefulness. Synthetic tests supplement rather than replace this set. Never turn reference
labels into predictions and call the result end-to-end accuracy.

## Delivery and rollback

1. Audit/contract/reference baseline; independent architecture review.
2. Extend existing retained fact extraction, batched account aggregation and material changes.
3. Versioned commissioning calculation and engineering documentation.
4. Reconcile PR189 into customer-first UI while retaining current main behavior.
5. Contact/prioritization quality, real evaluation, realistic performance, full gates and independent Astra acceptance.

Each candidate needs exact commits, scope, tests, limitations and rollback. Additive contracts
must preserve older clients and migration compatibility. Do not downgrade privacy safeguards
or rewrite retained history. Disable new projection/scenario publication if rollback needs it.
Any migration requires disposable upgrade/drift/recovery checks; no production schema operation
is authorized. Source merge is not deployment evidence. Build identity must bind source SHA,
package/environment and artifact verification; dated deployment receipts do not prove current runtime.

At audit publication, the managed executor remains starting. No new executable tests, database
measurements, screenshots, or production readiness are claimed by this document.
