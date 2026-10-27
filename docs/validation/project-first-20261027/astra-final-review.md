# Issue 128 independent exact-candidate review

> Integrator provenance clarification: references below to 75133e5 as a “production base” mean the repository baseline used for the diff. The actually deployed production revision was not observed. This annotation preserves the original independent review and does not supply deployment evidence.


Reviewed application candidate `5f4f11688fc7aa7d7b6bb8da131f39377b45e3f5`, including backend foundation `3dec15145f40526490e2e4706bb28225daa74c84`, against production base `75133e5`. Documentation additions remained untracked at the start of review. Read the authoritative project-first/autonomous canons. Review covered source/spec compliance, identity and contact attribution, saved PostgreSQL projection, authenticated API, worker/adapters, focused tests, and actual local evidence reports. No application source writes, production operations, paid calls or outreach were performed.

## Candidate findings

No new P0/P1 defect found. Four P2 findings require correction before engineering acceptance of this SHA:

1. **Selected power-need detail displays a different need's facts.** `backend/src/gridlens/intelligence/project_results.py:104` always chooses the highest-ranked need as the representative after `need_id` selects the asset. `web/src/features/workspace/WorkspaceDetail.tsx:300-315,329-331` uses the selected need's tier/disposition alongside the representative's milestone, power summary and action. Opening a lower-ranked independent need on a multi-need site can therefore show another need's supported gap/date. Select the requested compact row as representative in `need_id` mode, preserving all nested needs, and test deliberately different need summaries.

2. **Methodless person's organization is replaced with project owner/operator.** `web/src/features/workspace/WorkspaceDetail.tsx:337` appends top-level `company` rather than `person.company`. The saved projection includes contacts from all buying-chain organizations, so GC/EPC professionals can be displayed as owner employees. Render the person's own supported organization and test a different-owner/different-contractor example.

3. **Pagination cannot recover from a generation change.** `web/src/features/workspace/ProjectResults.tsx:22-23,38` reads the stale cohort token from the URL for every request; Retry only increments a counter. The client correctly throws `OpportunityCohortChangedError` on 409, but the component never resets the token or offset. After normal ingestion changes a generation, Next then Retry repeats 409 indefinitely. Restart at offset zero without the stale token and test 409 recovery.

4. **Access cooldown starts at job creation rather than restriction observation.** `backend/src/gridlens/intelligence/rrc_well_research.py:41` filters restriction records by `Job.created_at`; the restriction itself is written during execution at lines 317-323. A job delayed more than 24 hours can encounter publisher restrictions now yet establish no global cooldown. Persist the restriction observation instant and apply the stated 24-hour cooldown from it; test an old queued job newly receiving restriction.

All four were sent promptly to integration. Source repairs began after the frozen-SHA review; their acceptance will be recorded in an addendum tied to the repaired candidate.

## Early findings resolved in reviewed source

- O&G sector assignment now requires current retained O&G attribution for broad asset classes, and excludes municipal/utility/air-separation context; it no longer trusts a bare pipeline/cryogenic classification.
- Cached `call` actions map to canonical `phone` suppression keys for both scoped/global lookups, including nested need actions.
- Generic company routes and person-bound methods have distinct API labels/classes; independently supported methodless named people remain separate.
- Native amendments survive into separately typed `Permit amended` events; issue dates are not promoted to drilling milestones.
- Queued well jobs recheck feature/source enable flags before acquisition.
- Qualified default browsing and explicit Signal discovery are separated; cards show Signal status. Supported gap, activity requirement, facility load and source context retain distinct `power_summary_kind` values instead of unconditional unknown text.

## Independent verification and reviewed receipts

- Independently executed the exact-candidate focused unit suite for project contacts, project sectors, RRC identity and RRC completion: **45 passed**. No network calls were needed.
- Inspected `well-and-completion-worker-replay-final.json`: normal worker path with captured official HTTP responses, zero live network requests; Pioneer exact API `4231747395`, no packets returned; both OXY permits exact API `4216538299`, historical initial completion 2015-04-19 and recompletion 2016-06-02. No 2026 completion claim was created.
- W-1 transport is limited to four requests, and optional completion history to three requests/two packets, sharing the 35-second research deadline. Official-host/path, response-size, exact well-identity and native-version fences remain. A live W-1 request encountered a publisher policy redirect; this is honestly recorded as blocked, not successful live operation.
- Inspected frozen benchmark: 25 source records present; **0 qualified**, 4 company routes, 4 methodless named people, 0 person-bound methods, 0 verified purchasing authority. These are Signals, not 25 commercially qualified opportunities. The identity disagreement remains explicit.
- Inspected authenticated local read measurements: 40 warm reads over 1,727 prepared rows, with unchanged job/provider/evidence counts; Oil & Gas 1,722 physical groups, data centers 4, qualified default 0. This supports local read behavior, not production scale/latency.
- Inspected authenticated loaded UI receipts for 390/768/1440 px, tablet return navigation, and the actual 390 px EG AI detail screenshot. Receipts report no horizontal overflow/page errors; generic company phone and methodless Luis Diaz remain separate.
- Inspected isolated backup/restore receipt: matching critical retained-table counts/digests, schema `0046_import_meta_reparse`. The suppression table was empty in this actual corpus, so suppression behavior is established by dedicated software tests rather than that empty-table restore alone.
- Broader backend/frontend/CI results were supplied by integration; they were not independently rerun in full during this review.

## Acceptance status

**Engineering:** pending the four P2 fixes and exact repaired-candidate validation/review.

**Commercial:** not accepted as complete. No qualifying 300 kW temporary-power cohort, current spud/completion coverage, verified direct contacts or purchasing authority were established by the frozen benchmark. Permit/campus source coverage is useful discovery evidence only.

**Production release/deployment:** not approved by this review. Production access, production backup/rollback readiness and authenticated production checks are unavailable; the local restore rehearsal cannot substitute for them. Live scheduled W-1 enrichment remains publisher-blocked. Root release coordination must retain these limits explicitly.

## Repaired exact-candidate acceptance addendum

Reviewed application head **`e2d00edec5cb9bdf5cdccc0f43a22aae8d782e61`**, with backend foundation **`14513dd596a515c45c9e2938b27a9d9812dda5fc`**, by inspecting the complete eight-file repair diff from `5f4f116`. This addendum supersedes the pending engineering decision above for these exact application revisions.

All four P2 findings are resolved:

1. The SQL representative ordering prioritizes the explicitly requested need, while retaining all nested needs and preserving normal unscoped rank ordering. The affected PostgreSQL regression now selects a lower-ranked need and verifies its event, distinct power context and next action.
2. Prepared detail renders `person.company`, independently from the physical project's owner/operator. The browser regression checks a professional at M/E Design LLC under a project owned by Example Energy and rejects the wrong affiliation.
3. Typed cohort-change handling removes the old token and offset, clears stale cards, and reloads the first page. The browser regression covers 409, verifies token/offset removal and confirms the new cohort replaces old cards.
4. Research checkpoints record `access_restricted_at`; cooldown compares that validated timestamp, with legacy fallback and guarded JSON/timestamp parsing. The affected PostgreSQL test now creates jobs two days earlier and verifies a newly observed restriction still defers the other queued work.

Also inspected the limited card-copy/typed-power-summary changes and CSS spacing adjustment in the repair diff. They preserve supported facts, distinct contacts and Signal semantics. No new blocking defect found in this scoped review.

Verification receipts inspected: `.artifacts/issue128/astra-repair-backend.log` records **6 affected PostgreSQL tests passed**; `.artifacts/issue128-frontend-report.md` records **7 focused browser tests passed**, plus frontend typecheck/build. These runs were performed by integration/builders, not rerun independently by this reviewer. The earlier independently run 45 unit tests and earlier full-suite receipts remain separately described above. Earlier actual-source screenshots, warm-read timings, worker replay and restore receipts were measured on the preceding candidate; they are not represented as fresh measurements of `e2d00ed`.

**Engineering decision: ACCEPTED for `e2d00edec5cb9bdf5cdccc0f43a22aae8d782e61` and backend foundation `14513dd596a515c45c9e2938b27a9d9812dda5fc` within this source/spec/safety review scope.** No unresolved findings from the early or final source review remain. This decision is not a claim of commercial completion, production deployment, or successful live scheduled W-1 acquisition.

**Commercial decision: NOT ACCEPTED as complete.** The frozen actual-source cohort remains 0 qualified projects, 4 company routes, 4 methodless named professionals, 0 person-bound verified methods and 0 established purchasing authority, with the retained identity conflict and milestone gaps.

**Production release/deployment decision: NOT APPROVED.** Production access and release safeguards are still unobserved, and native W-1 transport is publisher-blocked. Root release coordination retains responsibility for the applicable exact-candidate checks and production safeguards. Documentation-only additions may record these findings without changing this application-code acceptance; further application changes require review appropriate to their scope.
