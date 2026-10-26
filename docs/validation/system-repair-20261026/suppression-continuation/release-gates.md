# Owner release exception and deployment handoff

At **October 26, 17:55 UTC**, the owner explicitly said: **“yes those are too strict of requirements.. just merge 126 and deploy as is”**. This supersedes the prior commercial merge/deploy gate for PR126 only. Finish the already-running code-safety validation and independent engineering review, mark PR126 ready, merge with skip-CI controls, verify remote main, and deploy using existing authorized infrastructure.

The commercial thresholds below remain unmet assessment results, **not release blockers under this exception**. Do not claim commercial P0 complete. No new features or additional commercial research are required before this release. No paid calls, workbook activation, credential creation or destructive data operation is authorized. Essential backup/rollback, schema/data-preservation, services and authenticated live checks remain required.

Authority: [current canon](../../../product/AUTONOMOUS_INTELLIGENCE_CANON.md), [finish contract](../../../../.agent/FINISH_CONTRACT.md), and [predeclared release protocol](../../commercial-release-20261026/PROTOCOL.md). Historical task packets do not override these or the latest owner authorization.

| Gate | Required evidence | Current result |
| --- | --- | --- |
| Eligible cohort | 25 distinct eligible physical projects, unchanged TX/OK/NM rules and 300 kW qualification floor | Frozen 25 are real source records, but eligible distinct temporary-power sites are not demonstrated |
| Supported claims | No unsupported positive identity, power, timing, authority or verification claims | Unknowns retained; fixtures and campus capacity do not fill missing demand |
| Company attribution | At least 20/25 supported buying organization/site relationships | 25 source-reported routes and 21 unique primary companies; weaker than independent physical-site/buyer validation |
| Named outreach | At least 15/25 relevant named professionals with exact current published business method | Canonical benchmark: 0 person-bound methods. Rice follow-up adds one source-published CEO email candidate with unresolved phase/schedule binding, not a passed threshold |
| Direct project contacts | At least 10/25 source-bound person/company/project role and usable method | Not demonstrated; company routes do not count |
| Actionable opportunities | At least 10/25 supported temporary-power relevance, timing/constraint, buyer and usable relevant contact | 0 demonstrated in frozen benchmark; no new confirmed activity-specific rental MW or residual gaps |
| Actual browser cases | Four persisted genuine cases A–D on desktop/mobile | Retained diagnostic cases do not pass the complete commercial scenario gate; current continuation does not claim production browser acceptance |
| Engineering | Exact-candidate regression/static checks and independent acceptance | Frozen implementation `78f632c`; final receipt tracked in verification.json and independent-review.md |
| Pre-deployment safeguards | Existing authenticated deployment identity, observed deployed revision/schema/counts/configuration, logical backup restoration, compatible migration/rollback | Missing authenticated execution/session; control-plane droplet is active but cannot prove these |
| Post-deployment verification | Merged/deployed SHA, schema, services, preserved records, authenticated desktop/mobile behavior | Not performed; deployment has not occurred |
| Production/launch outcomes | Real scheduled operation, seven actual cycles/95% due checks, retained 30-record/24-correct source-quality and real-Lead review | Not established by local tests. These are sustained production/launch claims, not evidence that can be fabricated before initial deployment |

The numerical commercial minimums were proposed by the lead and approved independently before scoring; they are not owner-supplied numbers or population estimates. The owner has now explicitly overridden their use as merge/deploy blockers for this release. Their measurement and unknowns remain unchanged.

No credentials were created or transferred. The exact access input remains the established production deployment identity and an authenticated GridLens session through secure environment configuration or an already authenticated supported connection. Commercial evidence failures no longer block this release. The remaining release sequence is code-safety acceptance, merge, and an existing authorized production execution connection for the essential deployment safeguards. No credentials should be created or transferred through this task.

## Deployment execution boundary

This cloud task remains the implementation and merge owner. It has no SSH identity/agent, authenticated GridLens session or production execution tool. An existing authorized desktop execution connection may perform **only the deployment** using the exact merged SHA supplied after merge; implementation does not move to another task. Use `/etc/gridlens/compose.app.yaml`, protected Infisical configuration and immutable `/opt/gridlens/releases` artifacts, following the [established deployment/rollback plan](../../commercial-release-20261026/deployment-and-rollback.md). First inventory the deployed SHA/schema/counts and configuration, verify a logical backup and isolated restore, validate compatible migration through 0046 if needed, deploy the exact SHA, rebuild its matching saved-browse projection, verify services/authenticated desktop-mobile behavior and preserved evidence/contact/privacy records, then record the deployed SHA and receipt. Do not run unverified workbook promotion or paid enrichment.

The schema and service checks are not waived. Keep the additive suppression/import history on rollback; an older image that exposes suppressed contacts is not a valid rollback. Production execution has not occurred in this cloud task.

### Host-specific safeguards for the deployment executor

Use [operations authority](../../../operations/README.md) and the [historical host wrapper receipt](../../../operations/hardening-release-plan-20261024.md) to locate the existing protected `/etc/gridlens/start-gridlens.py` and its selective operation companion, then verify their **current** identity on-host. Do not substitute the alternate `deploy/digitalocean/` proposal or print/copy protected wrapper inputs. The dated receipt's wrapper hash and image IDs are not current production observations.

The older `scripts/rehearse_release.py` still fixes both expected and target schema to `0041_evidence_packages`; it cannot establish this candidate's required migration through `0046_import_meta_reparse` unchanged. Validate the actual restored production revision against the current Alembic migrations and metadata, preserving row content/privacy/import history, rather than falsely reporting that older rehearsal as current. No change to that historical rehearsal helper or production schema was made in this continuation.

### Current production preflight reported by the deployment task

The existing authorized desktop task reported successful strict-host-check SSH as `gridlens`, live source `d75a856dc77f403e77929c1ab9a58b17545c0cc2`, PostgreSQL18.6, schema `0044_enrichment_planner_cursor`, and active database **`gridlens_restore_20261014`**. Preserve that database despite its name. It also reported today's backup checksum verified; obtain a fresh pre-cutover checkpoint and isolated restore/migration proof. These are the deployment executor's observations, not host execution by this cloud task. No credentials were created or transferred.

Migration route: `0044_enrichment_planner_cursor` → `0045_contact_suppressions` → `0046_import_meta_reparse`. The migrations are additive.0045 refuses downgrade of a populated suppression ledger;0046 refuses downgrade when metadata-reparse receipts exist. Do not delete ledger/reparse receipts to bypass guards. The currently deployed pre0045 application is **not** a suppression-compatible rollback once protected contacts exist. Retain compatible new application images; otherwise close contact surfaces and stop refresh workers while recovery is coordinated.

### Exact-source image build handoff

After merge, this task supplies and verifies the full remote-main release SHA. From a clean checkout/archive of **that exact SHA**, using repository root as build context:

```sh
# RELEASE_SHA is supplied by the verified merge receipt; do not substitute main later.
release_tag="release-$(printf '%s' "$RELEASE_SHA" | cut -c1-12)"
docker build -f deploy/Dockerfile.backend \
  --label "org.opencontainers.image.revision=$RELEASE_SHA" \
  -t "gridlens-api:$release_tag" .
docker build -f deploy/Dockerfile.web \
  --label "org.opencontainers.image.revision=$RELEASE_SHA" \
  -t "gridlens-web:$release_tag" .
```

Record the resulting image content IDs and revision labels; transport immutable artifacts through the existing `/opt/gridlens/releases` mechanism. This is a build recipe, not authorization to substitute a new Compose configuration or secret wrapper. Use the actual protected deployment wrapper/selective operations for backup, migration, API/web canary, exact-source browse rebuild, and worker/browse release. No provider or workbook activation belongs in the cutover. The desktop task performs deployment only; source implementation and merge stay in this task.
