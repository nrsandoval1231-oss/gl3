# Proposed improvements

Proposals to change core engineering policy (CLAUDE.md, agent definitions, rules). Adopt only after review.


## 2026-11-06 — Give `documentarian` a restricted shell, or drop its link-check duty
`.claude/agents/documentarian.md` instructs the agent to run `scripts/check_docs.py` but its tool list (Read, Edit, Write, Grep, Glob) has no Bash, so it could not (observed: it reported the check as unverified and the Chief Architect had to run it). Options: add `Bash` to its tools with a rule limiting use to `check_docs.py` and read-only commands, or remove the instruction and make link verification the tester's job. Recommendation: remove the instruction (keeps the agent least-privileged); the Chief Architect or `tester` runs the check. Needs owner review before changing the agent definition.
