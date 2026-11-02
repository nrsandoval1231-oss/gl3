# Delivery status and outstanding gates

**Status as of November 2, 2026:** main `ec6486a2726758b2a9fb64a03e99276583a27a6e` is deployed and its exact candidate, recovery rehearsal, authenticated live behavior and post-resume readiness were independently accepted. See the [production release receipt](../validation/production-release-20261102.md) for exact images, generation, checks and limits. The [current repository checkpoint](../../.agent/CURRENT_STATE.md) records ongoing work. The [Autonomous Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md) and [Operator/Customer Results Canon](../product/PROJECT_FIRST_RESULTS_CANON.md) govern functionality. This page distinguishes this accepted release from the broader product gates below.

## Latest accepted production release

The November 2 release serves company/operator groups with nested project browsing, server-side All / Oil & Gas / Data Centers filtering, search, region/stage/priority filters and sorting, plus generation-bound pagination. Authenticated desktop, tablet and phone checks passed. Production API and web image identities, schema `0049_scoped_identity_browse`, 74 public tables, protected backup/restore equality and unchanged provider controls are recorded in the release receipt. The accepted group counts were 417 All, 301 Oil & Gas and 16 Data Centers; they describe the published browse generation, not distinct facilities or full market coverage.

The Oil groups query repair, UI loading/cohort handling, column alignment and header search/artwork separation passed exact-candidate CI, isolated candidate/prior recovery, live canary and independent review. Bounded live readings passed; their measurements are not a sustained-performance SLA. The `equipment-demand-v1` summary covers additional equipment only. It had zero validated records at release verification, so Identified Power Demand (MW) was unavailable and no portfolio total was claimed. Provider master gates remained closed.

## Verified repository developments

PRs #137–#143 merged into main through `eadb203be231af045480b97f196b89f1b6457846`, improving CI scheduling, fixture performance, parallel testing and timeout controls. PR #139 reports 3,296 passing tests and one skip across its measured CI gate runs. These are *engineering* results; they do not certify production deployment or real project quality. Refer to the relevant PRs and exact CI runs for their evidence.

## Acceptance matrix

| Gate | What counts as proof | State |
|---|---|---|
| A — Autonomous foundation | Current deployed API/worker/web/schema identities; protected backup/rollback; actual scheduled retrieval with the owner's PC off | Nov 2 deployment, recovery and resumed-service readiness accepted; scheduled retrieval with the owner's PC off and recurring-cycle evidence remain open |
| B — Daily signals | Source-specific due checks, useful genuine admissions, replay, visible source failures, seven measured cycles and >=95% successful due checks | Open; no new multi-cycle/source-coverage acceptance in this release |
| C — Project and contact quality | Real TX/OK/NM physical-site identity, distinct wells, attributed milestones, buying roles, usable contacts, sourced relevance and explicit unknowns | Real-cohort acceptance open |
| D — Lead quality | Independently reviewed actual Lead, evidenced remaining gap, MW/start/duration, and defensible next action | Commercial acceptance open |
| E — Daily product release | Authenticated user/mobile checks, current data and alerts, deployment receipt, recovery safeguards and owner review | Bounded Nov 2 authenticated desktop/tablet/phone release checks and recovery evidence passed; sustained daily operation and alert delivery remain open |

Prior October 24 release approval and October 26 PR126 exception were **candidate-specific**. Do not reinterpret them as permission for new production writes, paid provider calls, release cutovers or waivers of truth/provenance. Preserve historical source and test observations in [validation](../validation/) and [operations](../operations/README.md); they remain useful dated evidence without proving current runtime health.

## Immediate priority

Run a controlled, read-only evaluation of 25 *actual* eligible project/site records if an accessible, independently validated corpus supports that sample. Report the actual denominator, verified owner/operator, project/site identity, event labels/dates, independent power activity/gap, contact method class, source freshness and recommended action. Do not invent missing records to reach 25. Rank remediation by actionable discovery, not permit count or CI speed.

Historical milestone snapshots remain in [the completion archive](../../.agent/archive/COMPLETION-20261024/milestones.md). Exact operational verification belongs in a newly dated receipt.
