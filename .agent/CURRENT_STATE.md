# Current state — repository checkpoint (2026-10-28)

This is a **repository-only checkpoint**, not a production status certificate. It supersedes the stale October 27 branch-in-progress narrative; that work remains available in Git history and dated validation/release records. Do not infer deployed image, schema, live source freshness, or commercial acceptance from a merge.

## Verified from GitHub main

- Inspected main head: `eadb203be231af045480b97f196b89f1b6457846` (PR #143).
- Recent merged pipeline work: PRs #137–#143. This includes test-fixture reset, isolated pytest-xdist workers, parallel browser CI, path-based CI selection and its follow-up fix, and tightened measured time limits.
- The source and product authorities are [Autonomous Intelligence Canon](../docs/product/AUTONOMOUS_INTELLIGENCE_CANON.md), [Operator/Customer Results Canon](../docs/product/PROJECT_FIRST_RESULTS_CANON.md), and [UI Canon](../docs/design/UI_CANON.md). The [PRD](../docs/product/PRD.md) remains subordinate where directions conflict.
- The original October 27 recovery candidate and its reported test/restore evidence are **historical candidate receipts**, not present production claims. See [recovery protocol](../docs/validation/operator-customer-recovery-20261027/PROTOCOL.md) and Git history.

## Product state and unresolved proof

GridLens has FastAPI, PostgreSQL, a Python worker, and a React frontend. Its intended daily product is operator/customer groups with distinct physical projects/wells nested underneath; source-grounded power needs, relevant contacts, freshness, evidence and next actions; real Oil & Gas and Data Center filters. No routine manual call logs, qualification forms, raw permit dashboards or operations UI.

**Do not mark the following complete without a current observed receipt:**
1. Exact production API/web/worker revision, database schema, on-host recovery/rollback safeguards, and authenticated desktop/mobile release checks.
2. PC-independent scheduled ingestion, incremental source checks, heartbeat *plus useful admissions*, source health and seven actual due cycles.
3. Conservative company/project identity, per-well lifecycle dates, buyer/contact method coverage and evidence-supported residual power gaps on a frozen real TX/OK/NM sample.
4. Commercial acceptance: actual eligible denominator and individually inspected actionable projects/Leads; synthetic tests do not count.
5. Paid-provider budget/credential authorization. No new paid calls or destructive production writes are implied by this checkpoint.

## Next bounded work

1. Reconcile the exact deployed artifacts and source schedule using existing protected operational procedures; report observations with timestamp.
2. Freeze a real-project review cohort; measure source-backed owner/operator, site, dates, power relevance, contacts and next action, retaining explicit unknowns.
3. Repair the highest-impact real data defect first, then run the exact-candidate CI, independent review, and coordinated release checks.

[Operations](../docs/operations/README.md) describes safe runtime verification. [Delivery gates](../docs/delivery/milestones.md) and [Finish Contract](FINISH_CONTRACT.md) describe evidence needed for acceptance. This file is not authorization to deploy, spend, overwrite source data, restore production, or merge feature work.
