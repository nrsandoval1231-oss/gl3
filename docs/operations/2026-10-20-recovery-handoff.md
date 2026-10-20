# Recovery handoff, 2026-10-20

Where Grid Lens recovery stands at end of day, and what to pick up next.
Statuses: VERIFIED / FAILED / BLOCKED / UNVERIFIED. Full audit trail: #93.

## Production (read-only checks, about 14:00–17:00 UTC)

| Item | Status | Evidence |
|---|---|---|
| Running build | VERIFIED `802cbb4` (`title02-802cbb4055c5` images) | `docker ps` |
| Merged fixes #94 and #95 deployed | **No.** On hold by owner | — |
| Live database | VERIFIED `gridlens_restore_20261014`, schema `0032`, labeled LIVE PRODUCTION | DB comment |
| Worker | VERIFIED heartbeat about 4 seconds old | `worker_heartbeats` |
| Stuck AI call `4d688637…` | VERIFIED `RECONCILED` (owner evidence: OpenAI usage 4+2 = 6 completed; call not delivered). No active slot held. | #93 comment |
| Paid AI | Briefs ON (OpenAI, 8 per day) and unblocked. Titles, Jev, TypeSafe, OCR and research OFF | runtime env |
| Daily backup | VERIFIED systemd timer `gridlens-db-backup` at 08:17 UTC. First dump has 54 tables; restore proof passed | host |
| Pre-deploy backup | VERIFIED `/opt/gridlens/backups/pre-deploy-20261020T151920Z.dump` (sha256 `b74583c1…`) | host |
| Off-host backup copy | UNVERIFIED: check DigitalOcean "Backups & Snapshots" tab | — |

### Source freshness (production, before #95)

- **Fresh (19):** 6 hourly news feeds and 13 daily structured sources.
- **Stale since Oct 14 (3):** Boston, Chicago, Georgia. Fixed in #95, not yet deployed.
- **Never succeeded (3):** CEQAnet and TCEQ NSR (fixed in #95), plus Houston (publisher stopped posting after 2026-09-13; correct failure).
- **Never run (1):** TDLR data centers, disabled since `72261e9`. Enabling it needs a bounded live canary and an owner decision.

## Pull requests

| PR | What | State |
|---|---|---|
| #94 | Provider transport: one total deadline, not a 5s read phase | Merged, CI green |
| #95 | Recovered source-collection repair (Boston, Chicago, TCEQ, CEQAnet, Georgia; 8-job chain cap; allowlisted diagnostics) | Merged, CI green |
| #96 | News grammar admits early-stage US data-center events (land, financing, planned-site power deal, conversion) as Signals | Open, local suite 2296 passed |
| #97 | Plan: database identity and verified backups | Open. 1A, 2A and 2B already applied on host by owner |

## Commercial findings

- **The project mix is not commercial.** 1,589 of 1,620 projects (98%) are Texas RRC drilling or well permits. All needs are Signal tier with no MW or start date.
- **News produced zero projects.** All 239 retained items were rejected by the strict grammar. #96 fixes the early-stage data-center misses (0 → 5 on 60 retained headlines).
- **The buying chain is nearly empty.** 31 of 1,620 projects (2%) have any buying-chain claim, and no owner, developer or EPC appears anywhere. Research runs only on a manual API click (`POST` buying-chain research). Permit contractor and operator fields already stored for Chicago, Boston, Austin, Dallas, El Paso and RRC are not extracted until someone clicks.
- **Same organization listed twice.** Many buying-chain claims appear twice per project (same organization, High and Low strength).

## Next actions (in order)

1. **Deploy main plus #96 (owner go).**
   - Use the existing backup.
   - Swap the image tag in `/etc/gridlens/compose.app.yaml` (save a copy as `compose.app.pre-<tag>-<utc>.yaml` first).
   - Optionally do the #97 step 1B rename to `gridlens_prod` in the same window.
   - Live check: rerun the source freshness query. Expect Boston, Chicago, Georgia, CEQAnet and TCEQ to show a recent `last_success`.
2. **Automatic permit-only buying-chain extraction** for permit-derived Signals.
   - Retained data only: no fetch, no paid AI.
   - Rate-limited backfill.
   - Merge the duplicate High/Low claims.
3. **Off-host backup decision:** DigitalOcean droplet backups, or Spaces.
4. **TDLR:** bounded live canary, then enable it if it retrieves real projects.
5. **Commissioning power activity and power-gap math.** These become meaningful once news and buying-chain data flow.

## Host notes

- Deploy layout: `/etc/gridlens/compose.app.yaml` plus `/etc/gridlens/runtime.env` and prebuilt image tags. Release trees live in `/opt/gridlens/releases/<tag>`. The repo's `deploy/digitalocean/README.md` (git clone + `.env.prod` + timers) does **not** match production.
- Scripts are not in the image. To run `backend/scripts/*`, pipe the release copy into `docker exec -i -w /app/backend gridlens-worker-1 uv run python - …`.
- Read-only database queries: `docker exec -e PGOPTIONS='-c default_transaction_read_only=on' gridlens-db-1 psql -U gridlens -d gridlens_restore_20261014 …`. Source health uses the key `last_success`, not `last_success_at`.
- About 45 scratch databases sit beside production. Do not clean them up without an explicit list and approval.
