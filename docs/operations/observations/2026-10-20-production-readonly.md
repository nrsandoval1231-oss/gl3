# Production read-only observation — 2026-10-20

Observation window: 18:28:48–18:50:41 UTC, October 20, 2026. This is a sanitized transcription of controller-provided read-only receipts. It records the actual inspected time only; it is not a current-after-this-date health claim.

## Container, schema, and saved browse

| Measure | Observed value |
|---|---:|
| Running image tag | `title02-802cbb4055c5` |
| PostgreSQL schema revision | `0032_power_need_titles` |
| Application database name | `gridlens_restore_20261014` |
| Projects | 1,620 |
| Saved power needs | 1,619 |
| Saved browse input / generation revision | 15,663 / 15,663 |
| Saved browse row count | 1,619 |
| Generation valid through | 2026-10-21 00:00 UTC |
| Worker heartbeat | 2026-10-20 18:29:01 UTC (fresh at observation) |
| Queued / running jobs | 0 / 0 |
| Historical jobs, failed / succeeded | 228 / 662 |
| Logical calls, COMPLETED / RECONCILED | 9 / 1 |
| Active budget slots | 0 |

The only enabled intelligence contract reported was `POWER_NEED_BRIEF`; the existing brief limit was 8 requests/day and the monthly intelligence limit was $50. These are observed configuration values, not authorization to increase spend or use another provider.

## Source state

The source registry had 26 rows. The receipt classified 19 as recent successes. Boston, Chicago, and Georgia last succeeded October 14. California CEQAnet, Texas TCEQ NSR, and Houston had no recorded successful check. TDLR was registry-disabled. The full point-in-time result by source was:

| Source | Last success (UTC) | Status at observation |
|---|---|---|
| Austin building permits | 2026-10-20 12:19:41 | Checked—No Change |
| Boston building permits | 2026-10-14 18:09:39 | Partial |
| California CEQAnet data centers | None | Failed |
| Chicago building permits | 2026-10-14 18:16:13 | Partial |
| Construction Dive news | 2026-10-20 18:16:07 | Updated |
| Dallas monthly permits | 2026-10-20 12:17:18 | Checked—No Change |
| DCD news | 2026-10-20 18:16:14 | Checked—No Change |
| El Paso new commercial permits | 2026-10-20 12:16:04 | Checked—No Change |
| Federal Register EIS | 2026-10-20 12:22:50 | Updated |
| Fort Worth development permits | 2026-10-20 12:17:12 | Checked—No Change |
| Georgia air draft Title V | 2026-10-14 18:16:42 | Failed |
| Houston weekly permits | None | Failed |
| Massachusetts CCC cultivation applications | 2026-10-20 12:20:26 | Checked—No Change |
| Manufacturing Dive news | 2026-10-20 18:16:16 | Checked—No Change |
| MJBizDaily news | 2026-10-20 18:16:18 | Checked—No Change |
| NC Commerce | 2026-10-20 12:20:40 | Checked—No Change |
| OGJ exploration news | 2026-10-20 18:16:19 | Checked—No Change |
| San Antonio development permits | 2026-10-20 12:16:09 | Checked—No Change |
| Seattle building permits | 2026-10-20 12:18:54 | Checked—No Change |
| Taylor development newsflash | 2026-10-20 12:21:37 | Checked—No Change |
| Texas RRC drilling permits | 2026-10-20 12:16:12 | Checked—No Change |
| Texas RRC flare/vent exceptions | 2026-10-20 12:24:49 | Updated |
| Texas TCEQ NSR pending | None | Failed |
| Texas TCEQ temporary batch plants | 2026-10-20 12:15:45 | Checked—No Change |
| Texas TDLR data centers | None | Overdue; registry disabled |
| Utility Dive news | 2026-10-20 18:16:22 | Checked—No Change |

The receipts display timestamps with fractional seconds in some rows; the table truncates to seconds. A status such as `Checked—No Change` records a check, not a new opportunity. These results do not establish seven consecutive scheduled days, complete breadth, or authenticated user workflow.

## Backup observation

The host reported `gridlens-db-backup.timer`; the associated service reported success. The 2026-10-20 17:04 UTC daily dump was 18,811,807 bytes. The earlier pre-deploy dump from 15:19 UTC was copied off-host and its SHA-256 matched:

`b74583c19cf03fc6a290d736d4aa942388157cece729358da7c6f2e834d742e1`

That copied dump restored into a private local PostgreSQL 18 database with 1,620 projects, 18,016 evidence versions, and 16,694 observations. This is one copy and restore. Scheduled off-host retention, retention length, repeatable restore commands, and production recovery timing remain UNKNOWN.

## Host path and command uncertainty

The inspected path was `/etc/gridlens/compose.app.yaml`, `/etc/gridlens/runtime.env`, prebuilt images, and `/opt/gridlens/releases/<tag>`. The host `compose config` check did not run successfully because the controller shell lacked the `TYPESAFE_API_KEY` injection context. That failure does not show a running-container failure. The approved injection wrapper, release command, rollback command, installed backup service/script body, and repeatable restore command were not present in the sanitized receipts; all remain UNKNOWN. No executable production deploy or restore commands are inferred from this snapshot.

## Source receipt digests

SHA-256 digests below bind the sanitized source receipts kept in the controller's ignored `.artifacts/audit-remediation/` directory. The raw receipts are intentionally not copied into this repository. Digests provide identity, not authenticity or a claim that the observation has been independently re-run.

| Receipt | SHA-256 |
|---|---|
| `production-readonly-20261020.txt` | `cce15c19072beceeeeabe786012c94fdaee16293b1944cfaec88019f9d28e84b` |
| `production-readonly-browse-20261020.txt` | `fadc34e31d66134cf5f48d0d03e3729e52b0078e938fce3c72a6504ee254328d` |
| `production-readonly-db-20261020.txt` | `daf80ef5fc1d647e08ddad788c1660693405a2981e032f1baad8824233312287` |
| `production-readonly-flags-20261020.txt` | `78ca71dc06f5a6ad80664ce61656ae4b3b8afcb0422bbddc1deca772c48add10` |
| `production-readonly-layout-20261020.txt` | `29ae9350a41e1ab081953db72c29fd04c6100e45a96852a8ead6f9e8c2ef3247` |
| `production-readonly-layout-metadata-20261020.txt` | `c03b483bdbcaed667a24c5663d94720c01cf33871f8d29fdc5abda3db39b6c4e` |
| `production-backup-sha256-20261020.txt` | `ed908c40709dbcfbcb2264915131b20894993abd682f1275a989c5d18ca1f145` |

The explicit provenance and UNKNOWN limits are summarized in the [operations authority](../README.md). The pre-cleanup file inventory and per-file disposition list are in the [archive index](../../../.agent/archive/AUDIT-20261020/DOCUMENTATION-INVENTORY-20261020.md).
