# Mistakes

## 2026-11-06 — Misdiagnosed a deterministic failure as flaky
A Playwright test failed after removing the "Intelligence" nav button; I first called it load-related flakiness because it passed once in isolation. Root cause: the test clicked a removed button. Prevention: repeat a failing test on the base commit and read the locator in the failure before classifying; never label flaky without a repeat run.

## 2026-11-06 — Worked as a single agent
Implemented a large multi-phase task without delegating to the specialized agents. Prevention: follow `CLAUDE.md` engineering loop; use `engineering-council` for substantial work.
