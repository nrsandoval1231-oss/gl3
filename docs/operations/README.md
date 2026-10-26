# Operations authority

Current implementation follows the owner-approved [Autonomous Intelligence Canon](../product/AUTONOMOUS_INTELLIGENCE_CANON.md) and [current owner request](../../.agent/OWNER_REQUEST.md). The autonomous pipeline must operate independently of the user's device, but repository implementation and local checks do not prove deployed operation. Exact deployed images/schema, scheduler cadence, provider credentials/budgets, alerts and recovery remain subject to current environment verification.

Earlier October 24 release authorization and observations below are historical, candidate-specific context; they are not continuing authorization to deploy this surgery, spend provider credits, modify credentials or mutate production data. Use the [autonomous retention map](../architecture/autonomous-intelligence.md) and [Finish Contract](../../.agent/FINISH_CONTRACT.md) for current implementation and acceptance boundaries.

## Runtime and release procedure

The October 24 pre-release inspection at 21:19 UTC found API/worker/browse revision `ca013d4c2dc8084a708ff5cfc092ec20b1d8c61b`, web `fae481db749b2e71dfb41ee63547c3fa1f6b1170`, and schema `0041_evidence_packages`. Frontend HTML/JS/CSS matched the audited main build. API RRC and runtime-container hardening remained undeployed at that observation. Final deployed identities must be read from the current release receipt, not inferred from this dated snapshot.

The actual host uses `/etc/gridlens/compose.app.yaml`, `/etc/gridlens/runtime.env`, immutable images and `/opt/gridlens/releases/<tag>`. Its protected Infisical startup wrapper is verified. [PR120's release plan](hardening-release-plan-20261024.md) records the wrapper identity, selective companion, local restore/rollback and canary proofs. That document's absent-deployment-authorization wording describes its earlier preparation scope; that October 24 owner approval was recorded in its completion packet and does not authorize a later candidate. Its data, quiescence, identity and recovery guards remain required.

The alternate `deploy/digitalocean/` proposal is not the actual production runbook. Never print runtime values or install replacement credentials. Preserve prior images and the live database; prove forward-schema compatibility before rollback and do not replay unknown provider calls.

## Recovery and remaining limits

Take a fresh on-host checkpoint through the established mechanism before cutover. Verify its archive, digest and required restoration/rollback evidence. Existing local retained-data rehearsals are evidence for their exact images/dumps only. One successful off-host copy does not establish scheduled retention. Production data corrections require attributed evidence, exact expected versions, dry-run results and reversible history.

[Security dispositions](hardening-security-20261024.md), [runtime/source findings](hardening-runtime-20261024.md), [credential/commercial boundaries](hardening-credentials-and-acceptance-20261024.md) and [current source follow-up](completion-source-findings-20261024.md) retain unresolved limits. Package audit success does not clear every runtime vendor finding. Historical key ownership and the original 446-record corpus remain unresolved; no new credential lookup or paid call is implied.

## Guides and historical evidence

- [Runtime configuration](runtime-configuration.md), [local runtime](local-runtime.md), [local recovery](runtime-recovery.md), and [local restore drill](local-restore-drill.md).
- [Delivery gates](../delivery/milestones.md), [production intelligence record](production-pipeline-20261023.md), and [prior readiness audit](readiness-audit-20261024.md).
- [October 20 observation](observations/2026-10-20-production-readonly.md) and [archived former operations index](../../.agent/archive/COMPLETION-20261024/operations-README.md) preserve dated evidence and superseded unknowns.

Repository repair, runtime release and PRD commercial launch are separate outcomes. No network/authentication or branch-governance setting is changed by this release.
