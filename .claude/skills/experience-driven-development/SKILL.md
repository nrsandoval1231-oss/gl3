---
name: experience-driven-development
description: Read and curate the experience/ knowledge base. Read it before substantial work to avoid repeating mistakes; write to it only for meaningful decisions, proven patterns, recurring failures or measured improvements.
---
# Experience-driven development

**Before** a substantial task: skim `experience/decisions.md`, `patterns.md` and `mistakes.md` for relevant entries.

**After** a task, add an entry only if a future engineer would otherwise rediscover it:
- `decisions.md` — decision, context, alternatives, rationale, date.
- `patterns.md` — a reusable approach that worked, with where it is used.
- `mistakes.md` — what went wrong, root cause, how to prevent it.
- `retrospectives.md` — end-of-initiative review (what shipped, what was learned).
- `benchmarks.md` — measured numbers with command and environment.
- `agent-performance.md` — observed agent strengths/failures, with evidence.
- `architecture.md` — current high-level structure; update, don't append.

Rules: no entry for routine changes; keep entries short and dated; correct or remove stale entries. Changes to core policy (CLAUDE.md, agent definitions, rules) are written as a proposal in `proposed-improvements.md` and adopted only after review.
