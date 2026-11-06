# Patterns

## Table semantics, card presentation (2026-11-06)
Restyle a data table as cards by giving `table/tr/td` explicit `role="table|row|cell"` and `display:grid` rows with `data-label` pseudo-labels. Keeps accessibility and most tests intact. Beware legacy `td:first-child{width}` and fixed-height rules overriding the new grid (`web/src/features/workspace/canonical-opportunity-results.css`).

## Server-side attention rules with an explicit unknown (2026-11-06)
Needs-Attention returns reason codes; "contact missing" fires only when evidence was readable and empty. Unreadable evidence → `unknown`, never flagged (`backend/src/gridlens/domain/commercial_pursuits.py`).

## Verifying agent definitions (2026-11-06)
A running Claude Code session loads its agent list at startup; agents added to `.claude/agents/` mid-session return "Agent type not found". Verify in a fresh process: `claude -p "<prompt>" --allowedTools "Agent,Bash,Read,Grep,Glob" < /dev/null`, which discovers all six agents and can delegate to them.
