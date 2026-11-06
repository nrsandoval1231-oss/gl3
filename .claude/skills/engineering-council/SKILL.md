---
name: engineering-council
description: Run the Chief Architect workflow for a substantial task — plan, delegate to builder/tester/critic (and optimizer/researcher/documentarian when warranted), integrate, verify, report. Use for multi-file features, risky changes or anything needing independent review.
---
# Engineering council

1. **Inspect** — read the relevant code, tests and canon docs (`AGENTS.md`). Note existing components to reuse.
2. **Plan** — list tasks with owner agent, exact file ownership (no overlaps) and checkable acceptance criteria. Present a short plan.
3. **Delegate** — spawn independent tasks in one message so they run in parallel. Brief each agent like a peer: goal, files, what is already ruled out. Use `researcher` for open technical questions first; skip delegation for trivial edits.
4. **Implement** — `builder` writes code and tests. `optimizer` only for measured problems.
5. **Test** — `tester` runs the verification in `CLAUDE.md`, classifying failures with evidence.
6. **Review** — `critic` reviews the integrated diff independently (give code, not conclusions). Repair CONFIRMED findings, then have `tester` re-verify.
7. **Learn** — if a meaningful decision, pattern, mistake or measurement emerged, have `documentarian` record it (see experience-driven-development).
8. **Handoff** — report what ran, real results, what did not run, and known limitations. No claim without evidence; no role claimed that did not execute.
