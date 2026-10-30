# Prepared operator/customer and project results

This note records the current prepared project-read API contract and dated implementation behavior. The active target presentation semantics are in the [demand-centered results canon](../product/PROJECT_FIRST_RESULTS_CANON.md). Existing company/project/power-need/evidence and qualification models remain current implementation contracts; operator/customer grouped browsing and permit semantics are compatibility behavior, not target product identity.

## Grouped read contract

Authenticated `GET /api/opportunities/groups` groups the complete matching prepared cohort by canonical company identity or supported RRC operator number. Names alone never merge groups. `GET /api/opportunities/groups/{group_id}/projects` paginates the group’s distinct physical assets with their own contacts and evidence. Outer and child pagination are bounded and bind generation, filters and group scope; changed cohorts discard both parent and child state. No retrieval or research runs during either GET.

## Physical-project read contract

Authenticated `GET /api/opportunities/projects` reads the current saved `BrowseGeneration`. It accepts bounded `search`, `sector=all|oil_gas|data_centers`, `sort=priority|updated`, `limit` (1–50), `offset`, `cohort_token`, and optional canonical `need_id`.

The grouped default All view includes every matching source-backed operator/customer and its projects, with Signals clearly labeled by explicit owner choice. The legacy standalone project read remains qualified by default unless `include_signals` is requested. Explicit sector exploration and search admit clearly labeled Signals; a company phone alone never qualifies a power opportunity. Exact `need_id` reads return the containing physical asset, including related needs, and support direct links to a Signal without changing qualification.

`total` and `count_unit=projects` describe the same filtered physical-asset groups as the list. The cohort token binds generation, filter/search, sort and exact-need scope. Nonzero offsets require that token; a changed generation or scope fails closed. SQL counts/ranks scalar groups across the cohort and aggregates compact JSON only for the requested page. The API enforces the existing response-byte budget. No source, model, qualification repair or research acquisition occurs in a project GET.

The public result `id` is the canonical project UUID unless independently validated well API evidence consolidates multiple permit projects. A validated API group uses a deterministic display UUID. `project_id` remains a canonical representative, `project_ids` preserves all original canonical projects, and each nested need retains its own canonical identifiers. Neither company names nor matching lease/well text alone merge projects.

## Prepared intelligence

Generation publication batches retained evidence and current buying-chain views. It saves `project_metadata`, `contact_actions` and `contact_people` in `BrowseRow.compact`. Ordinary list and exact-need reads consume those saved decisions. The full backend policy fingerprint, input revision and validity window still fence publication; deploys require a current rebuild before serving these reads.

Oil & Gas requires retained RRC evidence or an accepted, project-bound explicit O&G relationship. Broad pipeline/cryogenic/industrial classifications alone are insufficient. Utility gas, municipal water and general industrial lookalikes remain excluded. Source-supported midstream, gathering, processing, produced-water/SWD and field infrastructure can qualify for the sector independently of power qualification.

RRC operator, lease, well, original permit issue and amendment dates retain separate meanings. Official W-1 detail joins validate permit, API, operator, lease/well and county. W-1 completion-field semantics are labeled literally; historical W-2 initial completion and recompletion dates never imply completion of a later permit. County labels come from the retained official query form and do not establish coordinates or precise physical sites.

TDLR data-center results use literal owner and campus assertions, registered phase and clearly labeled developer-reported plans. A contractor/applicant does not become the owner. `power_summary_kind` distinguishes a normalized supported residual gap, activity requirement, reported facility demand, source context and unknown fallback. Facility/IT capacity is never promoted to temporary demand or residual gap.

## Contacts and privacy

Prepared methods require current retained support and literal person/company attribution. Named people without methods remain separate from generic company routes. Neither a role nor a method establishes purchasing authority. The read path rechecks all representative and nested actions/people against current company, person and method suppressions in a single bounded ledger read. Call controls map to canonical phone suppression keys. Internal identity/suppression keys do not cross the project-result API boundary.

## Bounded official well research

The existing worker adds a separate well-research lane under `WORKER_AUTO_REFRESH` and `RRC_WELL_RESEARCH_ENABLED`. Planning permits two active jobs and 24 new jobs per UTC day, with a seven-day/native-version dedupe window. Acquisition uses the existing public-source concurrency admission and a shared 35-second deadline: at most four W-1 requests and three CMPL requests, at most two completion packets and 1 MB per response. Broader packet lists remain explicit unresolved coverage.

The worker retains immutable official evidence and version-bound derived project facts; it does not rewrite native snapshots, canonical IDs or qualification. Source/feature disabling is checked at execution. Explicit publisher policy redirects terminate unresolved and defer other well research for 24 hours; ordinary MFT ingestion remains separate. No paid provider is activated.

## Current release boundary

The [October 27 validation report](../validation/project-first-20261027/README.md) distinguishes captured-source replay, synthetic regressions, local authenticated UI checks, live native transport and production evidence. A working projection or screenshot does not establish commercial acceptance or a production deployment.

The frontend handles a 409 changed-cohort response by dropping offset/token and refreshing page one with a notice. The explicit source-access cooldown stores its observation timestamp; old job creation time does not shorten the 24-hour hold. Current native httpx requests encounter a publisher site-policy redirect, so live W-1 operation remains on hold despite successful captured-page parser/worker tests.

The production rollout must observe `SAVED_BROWSE_ENABLED` and the worker publication configuration, warm the new policy generation, and verify incremental publication after source changes. A stale or missing generation returns 503; project GETs never rebuild it opportunistically.
