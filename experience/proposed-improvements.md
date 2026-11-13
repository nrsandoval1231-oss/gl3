# Proposed improvements

Proposals to change core engineering policy (CLAUDE.md, agent definitions, rules). Adopt only after review.


## 2026-11-06 — Give `documentarian` a restricted shell, or drop its link-check duty — ADOPTED 2026-11-06
Owner decision (2026-11-06): drop the duty; the Chief Architect or `tester` runs `scripts/check_docs.py`. `.claude/agents/documentarian.md` now says so.

`.claude/agents/documentarian.md` instructs the agent to run `scripts/check_docs.py` but its tool list (Read, Edit, Write, Grep, Glob) has no Bash, so it could not (observed: it reported the check as unverified and the Chief Architect had to run it). Options: add `Bash` to its tools with a rule limiting use to `check_docs.py` and read-only commands, or remove the instruction and make link verification the tester's job. Recommendation: remove the instruction (keeps the agent least-privileged); the Chief Architect or `tester` runs the check. Needs owner review before changing the agent definition.

## 2026-11-06 — Forbid `git stash` / `git checkout` / `git reset` in builder and tester definitions — ADOPTED 2026-11-06
Owner decision (2026-11-06): adopted. The rule (and the `git worktree` alternative) is now in `.claude/agents/{builder,tester,optimizer,critic}.md`.

Parallel agents share one working tree. A builder ran `git stash` to compare against the old CSS while another builder had uncommitted edits (the stash happened not to take effect, so nothing was lost — luck, not design). Proposal: add to `.claude/agents/builder.md` and `tester.md`: "Never run git stash, checkout, reset or clean; to compare against a base commit use `git worktree add <scratchpad path> <rev>`." Needs owner review before changing agent definitions.

## 2026-11-13 — Proposed edit to AGENTS.md line ~21 (PROPOSED, needs owner review)
Context: the paragraph "Current Phase 2 execution authority (November 8) ... one tested and independently reviewed draft PR only ... PR187 merge permission is historical" still reads as current authority. The Phase 2 work merged as PR #188 on 2026-11-10 (main later passed PRs #190, #191, #193, #194, #197; main `5ee2f30`, schema head 0056). Merge authorization for PR #188 and later PRs is not documented in the repository; owner confirmation is needed, and nothing here asserts who authorized them.
Proposed replacement: "Phase 2 authority (November 8) was scoped to one draft PR and is historical (merged as PR188, 2026-11-10; authorization for that and later merges is not documented in the repository and needs owner confirmation). Current owner authority: none beyond what a new task states; see [.agent/CURRENT_STATE.md](.agent/CURRENT_STATE.md). Merge, deployment, paid-provider execution, source activation, operational retained-data writes and credential changes need separate authorization."

## 2026-11-13 — Proposed edit to AGENTS.md line ~28 (PROPOSED, needs owner review)
Context: the "DATED RUNTIME OBSERVATION" paragraph says the repository includes PR183/PR186 and schema 0050 and that deployment is "unverified in Slice 1". It is stale on schema head and later merges.
Proposed replacement: keep the Nov 2 receipt sentence (`ec6486a2`, schema 0049) as a dated last-verified receipt; replace the PR183/PR186 sentence with "Repository main (`5ee2f30` on 2026-11-13) includes PR183, PR186 and PRs #188, #190, #191, #193, #194, #197, schema head 0056. Current deployment and retained schema are unverified; neither source merges nor the older receipt prove current production operation."

## 2026-11-13 — CLAUDE.md verification quick reference does not match the repo (PROPOSED, needs owner review)
Observed: CLAUDE.md says the Playwright regression project needs only dummy `DATABASE_URL`, `SESSION_SECRET`, `APP_PASSWORD_HASH`. `scripts/check.ps1` also requires a separate `TEST_DATABASE_URL`, and `auth.spec.ts` and the CI browser job use `GRIDLENS_TEST_PASSWORD` with a real backend (retrospective 2026-11-06). The Playwright config was not re-read in this session, so whether the regression project itself needs `TEST_DATABASE_URL` is unverified.
Proposed: add to the Web bullet "plus `GRIDLENS_TEST_PASSWORD` for real-backend specs; `scripts/check.ps1` also requires `TEST_DATABASE_URL` (separate database, name ending `_test`)", after the tester confirms the minimal env for `--project=regression`.
