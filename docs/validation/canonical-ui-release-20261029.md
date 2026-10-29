# Canonical UI production release — October 29, 2026

PR [148](https://github.com/nrsandoval1231-oss/gl3/pull/148) is merged and deployed from main `ca12443f5c57f3502584d8a353d83cdf7d5372b1`. Final production verification passed at `2026-10-29T23:18:24.320795+00:00` (6:18 pm America/Chicago). This is observed release evidence, not continuous monitoring or commercial launch certification.

## Deployed identities

- API, ingestion worker and browse worker: `sha256:8d904b612abb24e51fe203d6f588fb0894fa9dcf2df1e953f39b4bc06eed2f62`.
- Web: `sha256:2ccfafc1ba2a8659fec9e78caeb20662364c3348abf30b260ff3d99ca551cc5a`.
- All four services running with zero restarts; readiness `READY`; external HTTPS 200.
- Served homepage SHA-256 `edde14e797b3daacd94b6bb6551a1484e37b3443f0a63102563988bf7546e1cd` matches the verified built artifact. Source and all 229 web assets were checked in immutable images.
- Schema remains `0049_scoped_identity_browse`, 74 public tables. No migration or production database restoration was performed.

The reviewed PR source `402dfd8bc6b193348b8119a128828d52c525935f` and merged main have the identical complete Git tree `7fe632cc35edd3d337dd41c8da5d5e19915933f8`. Source CI passed on both the PR and merged main: 169 browser tests and 3,309 backend tests, one skipped. Independent source and deployment-tooling review found no unresolved material findings before execution.

## Backup, cutover and safety gates

A fresh quiesced backup was 36,105,894 bytes, SHA-256 `5387e80bc82f78539abe8ebed7104abb44f03563e97321236fba09c78bf4ab3c`. Its network-isolated restore matched all 74 tables. The release reused the existing startup wrapper and preserved effective runtime environments, credentials, provider settings and protected helper files. Compose changes were limited to image pins. Sixteen worker and twenty API provider/dispatch/OCR checks confirmed paid gates remained closed, both before cutover and worker resumption.

The candidate retained-data generation `b6d27571-d4bf-49a6-98df-b42b86fb0929` was staged, inspected and published while writers were held. The prior API/web images were retained for current-data rollback; no old database would be restored over live data. A stale persisted progress label during the rebuild was diagnosed read-only; both probes had passed and the stage was running normally. No failed gate was bypassed and no cutover retry or rollback was needed.

## Live authenticated acceptance

The API canary passed 38 serial reads with an ordinary short-lived persisted session; only that exact session was removed afterwards. It verified authentication denial, current generation/freshness/cohorts, grouped All/Oil & Gas/Data Centers, search, atomic group open, project/need details, and canonical flat All with Signals plus pagination. It confirmed 1,896 projects, 25 records on each of the first two pages, and unchanged cohort/total.

Actual authenticated Chrome validation passed at desktop 1440, tablet 768 and mobile 390 widths. Observed: All 1,896 projects, page two 26–50, Data Centers 18 projects, LEVIATHAN search six projects, row selection, Overview/Timeline, Back/Clear and page-local sorting. The EOG Leviathan C Well 3H detail displayed two retained company phone and three email links with source dates and unconfirmed purchasing-authority labels. No outbound call or email was sent. No browser console errors or page-level horizontal overflow were observed in the tablet/mobile detail. Desktop/mobile screenshots are private owner-local artifacts, not synthetic captures.

After browser acceptance, all 64 non-auth/non-browse table hashes still matched the stage snapshot. Workers resumed only after exact-run API and browser receipts passed. The final verifier checked all four source/image identities, zero restarts, readiness, served HTML, schema, unchanged protected settings and effective environments, backup/restore, canary bindings and provider gates.

## Evidence and limits

Private execution receipts and screenshots are retained under `.artifacts/pr148-release/` in the owner checkout and `/opt/gridlens/releases/canonical-ui-pr148-20261029/canonical-ui-20261029T230059Z-8df8c86d` on the host. They contain the manifest/proof/helper hashes and operator-authored browser receipt; production backup and authentication material were not committed to Git.

The 38-read mixed-route sample had p50 496.4 ms and p95 1,378.1 ms. This small mixed sample is not a per-route tail estimate or sustained-load benchmark. Oil filtering and atomic group-open performance remain follow-up work. Long-duration live update overlap and midnight rollover remain unverified.

Contact coverage and deliverability remain separate: missing phone/email stays unavailable, and a company route does not prove direct buyer authority. No new enrichment providers were activated. Unsupported Follow/completion persistence and KPI/history metadata remain the documented API limits; region/stage/priority filters and sorting remain page-local. Existing external-source failures were not claimed repaired by this UI release.
