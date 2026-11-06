# Commercial Pursuits workspace and navigation — 2026-11-06

**Status:** CURRENT; merged to `main` in PR #183 (`cbe4aec`) on 2026-11-06. **Not deployed.** Production remains at the [November 2 release](../validation/production-release-20261102.md) (PR165, schema 0049). Migration 0050 has not been applied to any retained database.

## Owner authorization

On 2026-11-06 the owner explicitly directed an owner-managed Pursuits workspace and a navigation/UI overhaul, overriding the canon's retired manual-workflow and deferred-redesign stance **for the Pursuits workspace only**. Ordinary Opportunities browsing stays autonomous/read-only; audited internal safeguards are unchanged. Single-owner model: no user accounts.

## Navigation and Opportunities

- Primary navigation is exactly **Opportunities | Companies | Pursuits | Reports**. Intelligence and Power Supply items are removed; Developers is renamed Companies; intelligence remains embedded. Companies and Reports deep-link with `?panel=companies|reports` and support back/forward.
- Opportunity rows are compact cards (tier badge, power need/gap, timing, primary contact, priority) with table semantics preserved through ARIA. No confidence value is shown because the payload has none; unknown is not zero.
- **Default browse (owner decision 2026-11-06):** the flat project cards (`CanonicalOpportunityResults`, KPI row, restyled detail) are the default Opportunities browse, including `/`, `?view=workspace` and Companies/Pursuits opportunity links. The released operator/customer group browse (`ProjectResults` + `WorkspaceDetail`) stays available and unchanged at `?groupBrowse=1` (linked from the Companies panel); `?projectBrowse=1` remains an alias for the flat browse. Add to Pursuit works in both. No data or API change; merged to `main` (PR #183) but not deployed.
- The autonomous research view moved to `?view=research`; `view=pursuits` is now the owner workspace. Legacy `view=pursuits&q|researchNeed` URLs map to research.

## Pursuits data and API

- Migration `0050_commercial_pursuits` adds `commercial_pursuits` (unique `need_id`, one pursuit per opportunity), `pursuit_tasks`, `pursuit_activity`. These are unrelated to the autonomous-research `pursuits*` tables.
- Stages: New, Contacted, Engaged, Proposal, Won, Lost; Won/Lost are closed. Follow-up tasks are supported.
- Activity (call/email/meeting/note) is recorded only when the user confirms (`confirmed: true`), idempotent by `client_id`. Opening `tel:`/`mailto:` links never changes stage or logs anything.
- Needs Attention is computed server-side: overdue follow-up; follow-up due within 2 days; no usable contact method (only when evidence was readable; unknown is never reported as missing); source-reported power timing that is a full ISO date within 30 days. Closed pursuits never qualify. "Today" is the America/Chicago calendar day.
- API `/api/commercial-pursuits`: list, create, detail, PATCH stage, tasks, activity. The five write routes are explicitly allow-listed in `backend/tests/unit/test_autonomous_api_surface.py`; no other mutation routes are permitted.

Code: `backend/src/gridlens/{api,domain,persistence}/commercial_pursuit*.py`, `web/src/features/pursuits/`, `web/src/components/CanonicalHeader.tsx`.
