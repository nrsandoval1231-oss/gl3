# Recovery handoff, 2026-10-20

**Historical snapshot only.** These are October 20 observations, not current production state or execution instructions. Later PRs and [operations authority](README.md) supersede this frontier. The October 22 documentation review authorizes no deployment, database rename, provider activation, source canary or backup transfer.
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

## Historical proposals and supersession

The original follow-up proposed deploying main plus PR96, automatic retained permit extraction, an off-host backup decision, a TDLR canary, and further commissioning/gap work. These are historical proposals, not current instructions. PR96's code and tests were incorporated into main in `4cc6668`, followed by additional admission and geography safeguards in PR99/100. Review current branches and actual receipts; do not reapply the old module or assume any named source has recovered.

The original optional live-database rename and direct image-swap instructions are withdrawn. No current command or secret-injection context is established by this snapshot. The initial PR97 proposal is superseded by its later observation and guarded restore requirements; its fixed-name restore target must not be dropped or reused.

## Historical host layout

The observed host used `/etc/gridlens/compose.app.yaml`, `/etc/gridlens/runtime.env` and prebuilt release trees under `/opt/gridlens/releases/`. This description neither selects a release nor authorizes execution. Do not print secret values, pipe unreviewed scripts into containers, or clean up adjacent databases from this handoff. Any future operation must bind fresh target, approved procedure, recovery evidence and explicit scope.

The original complete handoff remains in [commit f944be9](https://github.com/nrsandoval1231-oss/gl3/blob/f944be98f980c17558b6a7828a3947257ec4f23a/docs/operations/2026-10-20-recovery-handoff.md). Its historical recommendations do not override the current owner's instructions.
