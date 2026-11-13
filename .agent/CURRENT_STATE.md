# Current checkpoint — 2026-11-13

Repository `main` is at `5ee2f30c2b1c9998063db1c6468d1f4e65f7ac2d`. The Alembic head is `0056_statement_dirty_projects` (`backend/migrations/versions/0056_statement_level_dirty_projects.py`, schema 0056). This checkpoint describes repository source only.

## Merged to main since the November 2 release receipt

PR numbers and the #188 merge commit come from the 2026-11-13 audit's reading of git history (#183/#186 also from `AGENTS.md`); a later review re-checked them against `git log` (origin/main is `5ee2f30`; the local `main` ref lags at `5d93bea`). A merge is a source fact, not a deployment fact.

- PR #183 owner-managed Commercial Pursuits and four-section navigation (schema 0050); PR #186 source-backed shortlist. See [commercial pursuits](../docs/engineering/commercial-pursuits-20261106.md) and [shortlist](../docs/engineering/evidence-led-shortlist-20261106.md).
- PR #188 (merged 2026-11-10, commit `5d93bea`) Phase 2 autonomous commercial research. See [contracts and acceptance](../docs/engineering/autonomous-commercial-research-20261108.md); the running checkpoint is archived in [Phase 2 history](archive/PHASE2-20261108/README.md).
- PRs #190, #191, #193, #194 and #197 followed on `main` through schema 0056. Records in the repository: [ingestion-writes performance Phase 2](../docs/engineering/ingestion-writes-phase2-20261111.md), [account list read performance](../docs/engineering/account-list-read-performance-20261112.md) and the [sign-in redesign](../docs/delivery/sign-in/verification.md) (final receipt PR #194). Per-PR mapping beyond what those records state was not verified here.

## Not verified

- Current deployed application revision, retained database schema and worker/scheduler state are unverified. The [November 2 release receipt](../docs/validation/production-release-20261102.md) is the last dated, independently accepted deployment record (application `ec6486a2`, schema 0049); it does not prove current operation, and source merges do not prove deployment.
- Live provider cost, entitlement and source coverage remain unverified; Phase 2 validation used disabled or mocked providers.
- Merge authorization for PR #188 and later PRs is not documented in the repository. Owner confirmation is needed before treating any of those merges as covered by a recorded authorization.

## Current owner authority

Awaiting a new owner request. The [November 8 Phase 2 authority](archive/PHASE2-20261108/README.md) was scoped to one draft PR and is historical. Without a new task-scoped authorization there is no permission for merge, deployment, production or retained-data writes, paid-provider execution, source activation or credential changes. The [owner request](OWNER_REQUEST.md) and [finish contract](FINISH_CONTRACT.md) hold the standing verification rules.

## Documentation audit, 2026-11-13

An audit of maintained documentation found stale schema heads, Phase 2 authority framed as current, a retired source-enablement route documented as live, and an overclaimed flat-card default. Corrections to docs, backend, deploy, CI and web code are on branch `claude/sweet-dijkstra-kxyssa`, committed on that branch in lane-by-lane commits and pending independent review; there is no PR. Proposed edits to `AGENTS.md` and `CLAUDE.md` are recorded in `experience/proposed-improvements.md` for owner review. Run `uv run --project backend python scripts/check_docs.py` after any further documentation edit.
