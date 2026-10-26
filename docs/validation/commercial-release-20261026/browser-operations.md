# Commercial release browser and operations acceptance — 2026-10-26

Status: **BLOCKED — required real-corpus browser cases and current runtime evidence are unavailable.** This receipt belongs to browser lane baseline `29c4fe0` on `release/browser-20261026`. It is not a production readiness claim.

## Real-corpus browser cases

No persisted project database or project-ID handoff for this lane was available at inspection. The corpus lane confirmed that the release clone has no `.xlsx` attachments or database artifacts. Its available isolated Austin verifier is a separate database with six projects, 171 evidence records, zero canonical company identities, and no published selection; it is not a substitute for the requested cases. The retained `gl3-016-jev-corpus.json` has two Texas data-center items (one withdrawn Mustang item and one Comal city approval) and does not cover the four scenarios. The broader production workspace is unavailable without authentication, and the requested 25-project production cohort remains blocked in the controller's [availability receipt](../system-repair-20261026/input-availability.json).

| Case | Required review | Result |
|---|---|---|
| A | Source-backed data-center owner, facility/activity gap, timing, buyer and contact | **NOT RUN** — no qualifying persisted case or stable project ID supplied. Do not infer owner/buyer or fill unknown load, gap, timing, or contact fields from workbook rows. |
| B | Source-backed midstream compression/processing need | **NOT RUN** — no qualifying persisted case or project ID supplied. |
| C | Genuine delayed energization, temporary supply, and utility bridge | **NOT RUN** — no qualifying persisted case or project ID supplied. The historic Crusoe bridge example in older evidence does not establish a present procurement need. |
| D | Source-cited contact tied to an actionable next step | **NOT RUN** — no qualifying persisted case or project/contact ID supplied. A contact or method must remain attached to its source and company/person attribution; role alone does not establish purchasing authority. |

No browser screenshots were captured as commercial evidence. The existing synthetic browser tests remain software checks only and are not counted toward these four cases. Once a real persisted cohort and IDs are handed off, run authenticated desktop and mobile views through Opportunities, Research, Signals, and search; inspect each detail's source citations, contact attribution, unknowns and next action; and save screenshots plus a sanitized project/source manifest in this directory.

## Local runtime and worker

The release/browser clone has the expected Python virtual environment and web Playwright dependencies, but no private `.env`, `.artifacts`, local database connection file, PostgreSQL listener, API listener, or Vite listener at inspection. The other `/workspace/gl3` checkout contains ignored artifacts and a PostgreSQL cluster last logged running on September 30; it is stopped and outside this release worktree. Those stale artifacts/logs were not used as current acceptance evidence. The separate `gridlens_release_browser` and `gridlens_release_browser_test` databases were not available to this lane.

No app or ordinary worker was started. Without the lane's isolated database/config, worker startup cannot be shown to use the intended corpus and may schedule due public-source retrieval. No acquisition was attempted. Local scheduling, worker heartbeat, queue retries, source diagnostics, provider configuration, and cost observations therefore remain **NOT OBSERVED** for this candidate.

The code settings page documents defaults such as hourly `WORKER_AUTO_REFRESH`, disabled paid model/provider routes and zero default intelligence cost limits. Those are code defaults only; environment overrides and deployed values are unknown. Do not describe them as deployed controls or measured costs. No paid provider call was made.

## Production runbook and access boundary

The operations authority identifies `/etc/gridlens/compose.app.yaml`, `/etc/gridlens/runtime.env`, the protected Infisical startup wrapper, and immutable releases under `/opt/gridlens/releases/<tag>` as the actual host arrangement. The alternate `deploy/digitalocean/` proposal is not the host runbook. None of those `/etc/gridlens` or `/opt/gridlens` paths exists in this environment, and this lane has no SSH/host receipt, so current deployed image IDs, schema, flags, scheduler cadence, backup state, alerts, provider budgets, and runtime diagnostics are **UNKNOWN**. The October 20/24 host receipts are dated evidence and do not refresh those facts.

The supplied release context notes that `/health/live` and `/health/ready` return SPA HTML on production rather than API health evidence. `/api/health` is authentication-gated, and an unauthenticated workspace request returned 401 in the controller's read-only availability receipt. Those outcomes do not establish production health or authenticated browser acceptance; the root controller owns the production access/authentication report.

The local helper may be used after a lane-scoped real database/config handoff. It must not copy production runtime values or switch to the alternate deployment proposal. No production writes, merge, deployment, paid activation, or credential change occurred in this lane.
