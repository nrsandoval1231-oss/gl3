# Patterns

## Table semantics, card presentation (2026-11-06)
Restyle a data table as cards by giving `table/tr/td` explicit `role="table|row|cell"` and `display:grid` rows with `data-label` pseudo-labels. Keeps accessibility and most tests intact. Beware legacy `td:first-child{width}` and fixed-height rules overriding the new grid (`web/src/features/workspace/canonical-opportunity-results.css`).

## Server-side attention rules with an explicit unknown (2026-11-06)
Needs-Attention returns reason codes; "contact missing" fires only when evidence was readable and empty. Unreadable evidence → `unknown`, never flagged (`backend/src/gridlens/domain/commercial_pursuits.py`).

## Hide, don't unmount, to preserve page state (2026-11-06)
Keep the Opportunities main mounted but hidden while Companies/Reports are open, so filters, scroll and loaded data survive. Cost: hidden page can still react to history changes (see retrospectives).

## Strict email validation for every mailto href (2026-11-06)
Never let `? & = % , ;`, whitespace, angle brackets or quotes into a `mailto:` address (header injection found by the critic). Today the rule is implemented three times, not shared: `STRICT_EMAIL` in `web/src/features/workspace/CanonicalOpportunityDetail.tsx`, `mailHref` in `web/src/features/pursuits/pursuitFormat.ts`, and `safeContactHref` in `web/src/features/pursuits/ResearchView.tsx`. Consolidating them into one module is a worthwhile follow-up; until then change all three together.

## Verifying agent definitions (2026-11-06)
A running Claude Code session loads its agent list at startup; agents added to `.claude/agents/` mid-session return "Agent type not found". Verify in a fresh process: `claude -p "<prompt>" --allowedTools "Agent,Bash,Read,Grep,Glob" < /dev/null`, which discovers all six agents and can delegate to them.
