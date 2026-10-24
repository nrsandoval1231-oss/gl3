# M4 review and dependency repair

Node M4-REVIEW-REPAIR; one Luna, focused correction to existing architecture. Repository gl3-production-20261023, branch feat/production-intelligence-20261023; rejected candidate 258fe7839cd512a78743eb13586ea2494f5f0db5. Root stopped only its exact local gate process tree after CI40033495676 failed dependency audit; partial receipts remain preserved and are not PASS. No other database or process authority is transferred.

## Objective and evidence

Repair the currentness proof, which does not verify the package reference against the current linked Observation identity/content hash. The original contradiction-route finding is retracted as a current blocker by REVIEW-addendum-contradictions.json: accepted M3 produces only empty pairs and rejects every nonempty pair before M4 dispatch. Read the preserved REVIEW-static.json, that addendum, and .agent/artifacts/PRODUCTION-M4-REVIEW-RECOVERY.md. Preserve the deliberately constrained typed advisory; a separate freeform inference schema is not requested.

CI and the root's .artifacts/production-pipeline/m4-dependency-triage.json reproduce three advisories in existing pypdf6.21.1, all fixed by6.21.2: CVE-2026-115572, CVE-2026-115585, CVE-2026-115580. Official release https://github.com/py-pdf/pypdf/releases/tag/6.21.2 confirms the bounded patch. Upgrade only that exact pin and its lock entry; do not suppress audit findings or modify CI.

## Ownership and exclusions

Allowed: backend/src/gridlens/intelligence/intelligence_jobs.py, backend/tests/integration/test_commercial_assessment_job.py, backend/tests/unit/test_commercial_assessment.py only if required for the two findings; backend/pyproject.toml and backend/uv.lock only pypdf patch; docs/operations/production-pipeline-20261023.md for accurate repair note. Own only ignored .agent/artifacts/PRODUCTION-M4-REPAIR/COMPLETION.json and your ignored repair logs. No other product files unless a demonstrated gap is returned first. No schema/migrations, API/UI, canonical requirements, credentials, retained databases, live requests, Git commit/push, or root governance changes. You are not alone: preserve root/reviewer work. No subagents.

## Acceptance and compatibility

Use one shared request/currentness path for prepare, dispatch, post-response validation and replay. Verify observation ID, evidence-to-observation relation and current source/observation version, without equating different hash semantics incorrectly. Add focused tests for bad reference identity and changed observation hash before and after dispatch; no provider call before failure, and no accepted advisory after a changed source. Cover the valid current empty-pair package rejecting an unsupported CONFLICTING_EVIDENCE response, retaining unevaluated coverage. Nonempty cited contradiction production remains an explicit OPEN upstream contract node; do not bypass M3 validation or invent a new pair schema in this repair. Keep all canonical state unchanged.

Retain the one real M4 call d776be18-16b4-42b0-9888-b6f2e5678a6f. Empty contradiction sets keep the existing absent-key representation so its exact digest and keys-disabled replay remain valid. Nonempty pairs remain rejected by the upstream validator. Do not weaken stale checks or silently rewrite prior call payload/timestamps to achieve compatibility. If the current live record cannot be safely replayed, report evidence for controller recovery; do not make a new paid call.

Run lint/format/type checks first with backend/pyproject.toml explicitly selected, then existing root harness m4_checks.py --owner builder --label review-repair (root will enable this new label) using only isolated pipeline_test. Run locked dependency export/audit after uv sync --locked --extra dev. Root reruns focused checks, performs keys-disabled replay, freezes a new candidate and reruns mandatory full gates/CI before independent Sol acceptance. Two materially distinct repair attempts; retain failures and return to canonical recovery if exhausted. Record commands/exit codes, changed files, UTC timing, repair count, model/config identity and measured tokens or UNKNOWN. Completion is a builder claim only.
