# Proposed improvements

Proposals to change core engineering policy (CLAUDE.md, agent definitions, rules). Adopt only after review.


## 2026-11-06 — Give `documentarian` a restricted shell, or drop its link-check duty — ADOPTED 2026-11-06
Owner decision (2026-11-06): drop the duty; the Chief Architect or `tester` runs `scripts/check_docs.py`. `.claude/agents/documentarian.md` now says so.

`.claude/agents/documentarian.md` instructs the agent to run `scripts/check_docs.py` but its tool list (Read, Edit, Write, Grep, Glob) has no Bash, so it could not (observed: it reported the check as unverified and the Chief Architect had to run it). Options: add `Bash` to its tools with a rule limiting use to `check_docs.py` and read-only commands, or remove the instruction and make link verification the tester's job. Recommendation: remove the instruction (keeps the agent least-privileged); the Chief Architect or `tester` runs the check. Needs owner review before changing the agent definition.

## 2026-11-06 — Forbid `git stash` / `git checkout` / `git reset` in builder and tester definitions
Parallel agents share one working tree. A builder ran `git stash` to compare against the old CSS while another builder had uncommitted edits (the stash happened not to take effect, so nothing was lost — luck, not design). Proposal: add to `.claude/agents/builder.md` and `tester.md`: "Never run git stash, checkout, reset or clean; to compare against a base commit use `git worktree add <scratchpad path> <rev>`." Needs owner review before changing agent definitions.
