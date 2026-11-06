# Mistakes

## 2026-11-06 — Misdiagnosed a deterministic failure as flaky
A Playwright test failed after removing the "Intelligence" nav button; I first called it load-related flakiness because it passed once in isolation. Root cause: the test clicked a removed button. Prevention: repeat a failing test on the base commit and read the locator in the failure before classifying; never label flaky without a repeat run.

## 2026-11-06 — Agent told to run a command it has no tool for
The documentarian had no shell but was instructed to run `check_docs.py`. Prevention: check each agent's tool list against its instructions.

## 2026-11-06 — `git stash` in a shared working tree
A builder ran `git stash` in a tree shared with another builder; only luck prevented loss. Prevention: parallel builders use separate worktrees; no stash/reset in shared trees.

## 2026-11-06 — Mocks returning identical data for different inputs
Reports sector mocks returned the same data for every sector, so swapped/merged data passed tests. Prevention: distinct fixtures per input.

## 2026-11-06 — New panel endpoints left unmocked
Tests that don't mock a new endpoint hit a real-backend 401, which now correctly clears session state and breaks the test. Prevention: mock every endpoint a new panel calls; auxiliary reads can use the `background: true` client option (see `web/src/state/pursuitStore.ts`).

## 2026-11-06 — Worked as a single agent
Implemented a large multi-phase task without delegating to the specialized agents. Prevention: follow `CLAUDE.md` engineering loop; use `engineering-council` for substantial work.
