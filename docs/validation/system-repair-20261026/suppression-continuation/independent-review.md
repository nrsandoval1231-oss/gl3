# Independent suppression-continuation review

Status: **ENGINEERING ACCEPTED for the frozen production source, with complete reconstructed local test coverage. Deployment acceptance remains separate.**

Review scope: PR126 local suppression repair after PR123 integration, including refresh baselines, permit-summary privacy, latest/all-version commercial-history projections, and successful research replay deduplication. The root froze the implementation at local commit `78f632c` (`[skip ci]`), parent `7498efc`, which includes main's PR123 merge `6a6551d`. The reviewer separately approved the final test-only correction described below. All four production-source hashes were rechecked unchanged after the final rechecks. No remote merge, push, Actions run, or deployment is implied by this engineering decision.

The reviewer independently confirmed these SHA-256 values after freeze:

| Source | SHA-256 |
| --- | --- |
| `backend/src/gridlens/api/app.py` | `eca54e81affc7cf86e466b769201a716643acf183bd084226fd35197e9c678d3` |
| `backend/src/gridlens/intelligence/buying_chain.py` | `2a9450f50eb6c7fbd98d5ff353fa1e5c073809d6ebf5a6caf6860f40ea0dad56` |
| `backend/src/gridlens/intelligence/company_contact_discovery.py` | `55c8d1316ca2a5df6df1efb9b3591e9381810155d2acb6fdd55338226de24119` |
| `backend/src/gridlens/intelligence/saved_history_privacy.py` | `78f7f931068295273a8fba596259038770348678dda588683c1658c9088f7b01` |

Repository authority reviewed: `AGENTS.md`, `docs/product/AUTONOMOUS_INTELLIGENCE_CANON.md`, and compatible PRD/UI privacy, evidence, and qualification requirements. Inspection and synthetic local reviewer probes are read-only with respect to implementation, retained business data, and production. This report is the reviewer's sole assigned writable file.

## Findings and final inspection

The reviewer identified and reported the following issues during implementation. Final source inspection and the final local coverage establish the corresponding repairs:

- Saved-only scoped methods were not requested from the ledger when retained `public_contacts` was empty. A request-set-faithful synthetic probe confirmed both the missing key and returned email.
- Whole-person suppression left saved-only methods in outer contacts without claim IDs. A synthetic probe confirmed the email remained after name redaction.
- Free-form contact `role` was treated as immutable metadata, allowing a suppressed name/email to remain. A synthetic probe confirmed the unchanged role text.
- Saved international phone scanning initially covered only NANP, unlike the established live-contact scanner.
- Aggregate ledger requests required a total key budget, not merely per-claim and per-card limits.
- Assigning every same-account method to every person incorrectly suppressed unrelated coworkers. Company-scoped key discovery and person-method ownership must remain separate.
- Conflicting historical identities initially left saved-only prose methods visible. A synthetic probe confirmed a redacted person name alongside the original email.
- Note-only methods required their own bounded ledger lookup if history notes remain visible.
- Permit-summary organization substring matching was not authoritative, and independent rewrites could restore prior redactions.
- Permit-summary authority cannot depend on already-redacted candidate evidence: whole-person/company privacy clears that evidence before the summary pass. Historical retained claims and the actual evidence relation must support authority; latest visible candidates alone are insufficient.
- Permit overflow initially collected only the first 129 methods, leaving later tokens visible. The final fallback streams contact-token redaction and recognizes contextual bare phones while preserving engineering identifiers and citation URLs.
- Multi-party permit summaries required scoped-method lookup against every evidence-bound historical account, without relying on retained structured methods being populated.
- The first regenerated-claim regression was misplaced and checked the wrong phone. The final regression asserts the actual 512 method on original and cloned raw claim rows, absence of a copied company link, active single/batch projected visibility, and removal of canonical phone variants without whole-subject suppression.

No remaining blocking defect has been identified in the frozen implementation by this review.

The internal baseline, retention comparisons, and before/after support comparisons use the unfiltered buying-chain view. Public single and bulk views apply privacy. Current candidate privacy follows bounded company and person lineage by the exact project/entity pair, and checks all authoritative historical IDs. Saved-history reads use deep response copies, bounded claim/link/correction/key sets, and explicit fail-closed handling. Snapshot-supplied company/person IDs do not create identity authority. Historical grouped project IDs and DB claims allow former members to remain protected. Scoped method discovery is separated from person ownership so unrelated coworkers remain visible.

Permit summaries resolve immutable claim citations through `BuyingChainEvidence.id` or its `retained_evidence_id`, with literal supported quotes and explicit party facts. This remains effective after output candidates have been redacted or omitted. The global method path also runs without visible candidates. Physical facts, qualification metadata, and unsuppressed source URLs remain distinguishable from contact tokens.

Successful discovery replay compares a stable source/request digest plus recorded outcome gaps and completed depth. Exact company/project/need/source/import-hint/URL/epoch/generation/policy inputs remain in scope; stricter profiles, changed needs, or changed gaps cannot use the settled replay fallback. Queued/running/failed fencing retains exact request-digest behavior. Explicit same-generation replay is supported, while a different generation changes the stable digest.

## Local verification

- Reviewer execution on frozen source: `PYTHONPATH=src .venv/bin/pytest -q tests/unit/test_commercial_history_privacy.py` — **17 passed in 1.65 seconds**.
- Reviewer execution: `git diff --check` — clean.
- Reviewed local static receipts: Ruff passed; **380 files already formatted**; mypy **no issues in 174 source files**. Mypy retains its normal notes about untyped function bodies; this is not a claim of complete runtime proof.
- Complete logical backend coverage: **3,175 passed and 1 skipped across 3,176 expected test IDs**, reconstructed from the interrupted initial run and disjoint isolated-database partitions described below. This was **not one uninterrupted successful full-suite run**.

### Interrupted-run coverage audit

The initial run ended with SIGKILL after 913 passing progress markers and no final pytest summary. The root observed no OOM-kill indication. Only the first **912** tests were retained as completed; the last reported test was rerun so its teardown boundary was covered. The reviewer checked that the preserved list exactly equals the first 912 entries of the frozen default-order collection, that the original log contains 913 dots and no other status markers, and that this integration-test prefix contains no subtests or repository reordering hooks.

The four continuation selections contain **117 / 90 / 90 / 1,967** tests. The reviewer independently compared their IDs: they are mutually disjoint and disjoint from the retained prefix; their union is exactly the **3,176 unique expected IDs**, with no omissions or extras. The first two integration partitions have complete clean setup/call/teardown reports and exit status 0. The third had 89 passes and the one saved-history assertion failure adjudicated below. Its corrected focused rerun has all three phases passed and exit status 0.

The unit partition's terminal parent summary was 1,963 passed, 1 skipped, and 3 failed. Its temporary runner lacked a `__main__` guard, so multiprocessing spawn re-entered pytest and caused three timeout failures. The original unit JSONL contains duplicate phase groups for 44 node IDs from that harness issue and is **not a pristine per-phase execution ledger**. After the runner guard was corrected, precisely those three failed IDs were rerun; the reviewer checked their clean setup/call/teardown reports and exit status 0. Production code was unchanged. The terminal parent summary, exact selections, and clean focused rechecks support the aggregate logical coverage without treating duplicate harness events as additional tests.

The raw plan, expected collection, retained prefix, selections, logs, phase reports, and exit receipts were audited under `/workspace/gl3-handoff-research/` (`validation-partition-plan.json`, `expected-tests.json`, `preserved-prefix.json`, and `partition-*`). The root's [verification receipt](verification.json) records the retained validation artifacts and final candidate. No interrupted run is represented as having a successful session exit.

### Saved-history test adjudication

`test_saved_history_page_and_detail_apply_suppressions_to_historical_group_members` originally expected `external-scope@example.test` to survive even though its nested claim pointer belongs to project C, outside the saved A/B project cohort. That expectation contradicted the required fail-closed unresolved-pointer behavior. The reviewer independently approved changing the expectation to absence, without deriving company/person authority from the foreign pointer. The legitimate in-scope `visible@example.test` control, all suppressed-method assertions, qualification/disposition/input metadata checks, and immutable DB snapshot equality remain intact. This is a test correction, not a production relaxation. The final rerun passed in **3.13 seconds**, with all phases passed and exit status 0.

All tests and probes here establish software behavior using synthetic fixtures. They are not a genuine commercial benchmark or production-operation evidence.

## Commercial evidence review

The bounded follow-up matrix contains **25 unique frozen project IDs**, all with `release_qualified=false`. The reviewer verified that all 11 primary-source raw files exist locally and match their recorded SHA-256 hashes; no searches or source retrievals were repeated for this review.

Text extraction of the city-hosted Rice presentation confirms Dennis Finster and `dennis.finster@egai.us`; the retained company page identifies him as CEO. This is a published named business-contact candidate, not verified mailbox delivery, a verified project buyer, purchasing authority, or rental-power demand. The presentation's 2025 and 2.5 MW facility context does not resolve the conflicting schedule or exact TABS phase. The distinct TDLR owner contact must not be merged with him.

The retained Hut 8 page contains “Project Inquiries: info@hut8.com.” The matrix correctly treats Beacon Point's address as a company contact route, not a reachable named procurement person. EPCM scope and target energization dates do not establish a temporary power gap. Pecos's planned generation strategy and Circle T's developer context likewise do not establish project-specific temporary demand.

The 21 upstream records, including the 15 additional bounded lease/well investigations, remain unqualified. Candidate APIs, secondary locations, spud dates, neighboring wells, and conflicting dates are kept as research pointers or unresolved conflicts. No newly confirmed temporary MW or residual gap, canonical admission, or benchmark rescore is evidenced. The new research does not close the commercial thresholds.

## Release authority and commercial assessment

The earlier conditional contract required commercial acceptance before PR126 merge/deployment. The root coordinator subsequently conveyed the owner's explicit **2026-10-26 17:55 UTC release exception**: “yes those are too strict ... just merge126 and deploy as is.” For this release, the 25-project denominator, 15 named / 10 direct / 10 actionable thresholds, and four genuine commercial browser scenarios are **no longer merge/deployment blockers**. This latest owner instruction supersedes the stricter release condition in the active Canon, [finish contract](../../../../.agent/FINISH_CONTRACT.md), and [release protocol](../../commercial-release-20261026/PROTOCOL.md) for PR126. The reviewer is not inventing an engineering-only exception; the owner explicitly granted it.

The retrospective commercial assessment remains **NOT MET**. The frozen 25 records do not demonstrate 25 distinct eligible, source-backed physical opportunities or the prior **15 named outreach / 10 direct project-connected contacts / 10 commercially actionable records** minimums. Published Rice CEO contact evidence and Beacon Point's company route do not change those findings. The waiver authorizes release despite those results; it does not turn missing commercial evidence into a pass or establish production/launch outcomes.

**Independent engineering acceptance is granted for merge of the reviewed repair**, including the separately reviewed test correction, on the unchanged production-source hashes above. The explicit owner exception removes the former commercial minimums as release blockers. Merge acceptance and actual deployment acceptance are distinct. Deployment is authorized through the existing connection, subject to execution and verification of the essential safeguards.

The root reports that the existing desktop executor obtained strict SSH access to the established GridLens host, observed deployed revision `d75a856`, PostgreSQL 18.6 and schema `0044`, and verified today's backup checksum. The active database `gridlens_restore_20261014` must be preserved. These are reported executor observations, not actions performed by this reviewer. Fresh isolated `0044`→`0046` restore/migration validation, a rollback compatible with retained suppression data, and final deployed-service verification still require retained executor receipts before deployment acceptance. Earlier local test results do not prove those production facts.

Predeployment safeguards include authenticated deployment identity/access, observed deployed revision/schema/counts, verified backup/restore and rollback readiness, and observed runtime/provider configuration, budgets, schedules, and health. Actual deployed-service verification follows a deployment once release prerequisites pass. The finish contract's seven actual scheduled cycles with 95% successful due checks and 30-record/24-correct source-quality review are production/launch outcome gates; this review does not invent a requirement to observe seven future-candidate cycles before the initial deployment. They must be observed before claiming those production outcomes, and cannot be replaced by local replay or historic receipts.

No remote, GitHub Actions, paid-provider, deployment, or production action is part of this review.
