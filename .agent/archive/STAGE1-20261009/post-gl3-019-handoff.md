# Saved-cloud handoff after GL3-019

Canonical main checked October 1 is `2052fd5205a0bd6f7c21981ed5c4812c4bdfe41a`. GL3-019 PR9, this handoff PR11 and CI cleanup PR10 are merged. Work remains in `/workspace/gl3`; no deployment or PC changes were performed.

**October 1 runtime caveat:** the available PostgreSQL cluster contains `gridlens` and `gridlens_test`, but not the documented `gl3_019_live` acceptance database. The configured application database has 13 overdue source rows, no jobs and no observations/projects. Existing API/worker/web processes were absent at inspection; PostgreSQL was restarted for read-only inspection. The historical acceptance corpus and runtime described below must not be assumed present. Preserve existing data/credentials and reconcile the runtime before restarting collection. See [current milestone status](../delivery/milestones.md).

## GL3-020 follow-through — October 1

The initial empty-runtime caveat above is historical. The configured application database was migrated/reconciled in place and populated through real checks for all 15 sources; it now has 7,413 observations, 7,452 evidence versions and 1,981 active Signals. Read [runtime recovery](runtime-recovery.md) and [GL3-020 validation](../validation/gl3-020-validation.md) before resuming. Existing credentials and data remain intact; the old isolated acceptance database remains absent. API/web and the existing development worker are used locally; durable production scheduling and launch gates remain open. Proposed next slice: matching performance, not source expansion or tier promotion.

## Implemented coverage and next gaps

The registry has 15 enabled sources. Enabled means available to the worker, not
verified deployed scheduling. Priority remains data-center construction temporary
power, then commissioning, then O&G. News remains supplemental.

| Route | Implemented and measured boundary | Remaining gap |
|---|---|---|
| Austin | Commercial building/electrical; rolling 30-day issue/7-day status overlap and fixed January 1–September 30, 2026 literal data-center backfill. 2,609 rows, 78 accepted observations/76 projects; 57 organization and 57 permit-listed person candidates. | City-only, keyword-limited backfill; names/phones do not establish employment, authority or ownership. |
| Chicago / Seattle | Existing bounded city permit adapters; Chicago electrical and exact party fields. | No complete national or metro acquisition claim. |
| Georgia EPD | Bounded current air-permit snapshot plus narrative/draft PDFs and attributable identity/equipment excerpts. | Full applications and commissioning power not proven. |
| Texas RRC | Current daily file plus official previous-month EOM; framing, amendments, identity and freshness checks. 1,904 identities, 1,880 Signals. | Not all Texas history. 18 Field transfer + 6 Reclass records retained without Signal admission; all 1,711 Drill records accepted, plus reentry/recompletion. |
| Houston | Four latest official weekly XLSX reports, 1,543 retained records. | Issuance/current-status semantics unverified; zero Signals, no reported party fields, reporting lag. |
| Dallas / El Paso | Tested official routes returned Dallas 401/403 and El Paso 403 from this executor. | Neither enabled; alternative official routes unverified, not declared globally unavailable. |
| Other enabled sources | Federal Register, NC Commerce, Taylor notices, and six publisher feeds (DCD, Utility Dive, Manufacturing Dive, Construction Dive, OGJ, MJBizDaily). | Context is supplemental to authoritative admission; no deployed cadence claim. |
| Commissioning | No dedicated verified connector. | Do not treat decommissioning keywords or generator nameplate as commissioning rental demand. |

Austin's September 30 failed request recovered at **5:22 p.m. CDT** (22:22 UTC);
a normal retry at **6:06 p.m. CDT** (23:06 UTC) passed all pages and both counts,
2,609 unchanged. Original HTTP status is unknown. See [recovery evidence](../validation/gl3-019-austin-recovery.json).
Production dates, MW, supply gaps, fuel suitability and buying authority remain
UNKNOWN unless supported. Signal admission does not qualify a Prospect or Lead.

## Resume the existing cloud runtime

Keep existing ignored `.env`, credentials, databases and `.artifacts` intact.
The established dependencies are `backend/.venv` and `web/node_modules`; no setup
reset is needed. Check existing listeners before starting duplicate services.
From `/workspace/gl3`, these are the existing service entry points (separate terminals):

```bash
backend/.venv/bin/python -m uvicorn gridlens.api.app:app --app-dir backend/src --host 127.0.0.1 --port 8000
PYTHONPATH=backend/src backend/.venv/bin/python -m gridlens.jobs.worker
npm --prefix web run dev
```

Settings read the repository-root `.env`; do not print or commit its values. Use the existing
ignored `.artifacts/local-auth.txt` to sign in. The isolated GL3-019 acceptance DB
is `gl3_019_live`; it is separate from the default runtime database. The prior
acceptance API used port 8019. Do not overwrite either database to reproduce a check.
For a fresh environment, use the README setup instructions rather than copying secrets.

Validation commands from the repository root:

```bash
(cd backend && .venv/bin/ruff check src tests && .venv/bin/mypy src && .venv/bin/pytest tests)
npm --prefix web run typecheck
npm --prefix web run build
npm --prefix web test
```

Backend integration checks require the configured separate `TEST_DATABASE_URL`.
Browser checks require configured authentication, PostgreSQL and browser binaries;
`web/playwright.config.ts` documents API/web startup and port overrides. The saved
cloud live acceptance additionally used sandboxed system Chromium and isolated
ports; its exact artifacts/limitations are in the validation report. Do not disable
browser sandboxing or source protections to make checks pass.

Merged code validation: **418 backend passes / one existing fixture skip**, Ruff,
mypy, clean/repeated migrations and drift check, frontend typecheck/build and
**13 browser passes** (11 repository checks + two saved-cloud real-project cases).
See [final validation](../validation/gl3-019-acquisition-continuation.md). These are
completed build results, not new housekeeping test runs. Hosted CI was blocked
before jobs started by GitHub billing/spending limits. No workflow change here.

## Recoverable branch housekeeping

The following remote tips matched their merged PR heads and merge-commit trees.
GL3-015/017 are also ancestors of main; GL3-018/019 were squash-equivalent.
Deletion uses exact SHA leases so concurrent new work cannot be removed.

| Pruned remote branch | Old SHA | Merged PR |
|---|---|---|
| `feat/gl3-015` | `acab88b3ac06249f5445f6cf6d0659ba1b3d811c` | 5 |
| `feat/gl3-017` | `5836616e0ab2b94230d6901c1bc109821854041c` | 7 |
| `feat/gl3-018` | `a47c582376f66f0651bf3ba0aa8a0f3e03e7912e` | 8 |
| `feat/gl3-019-permit-enrichment` | `96440722873c209a6df37b40555f0a3eecd5c299` | 9 |

No tracked files were deleted: old validation/review artifacts are useful history,
not proven disposable experiments. Untracked/ignored work, local branches, data,
credentials and PR10 remain intact. Restore a removed branch from its recorded SHA
if needed; the merged content remains on main.
