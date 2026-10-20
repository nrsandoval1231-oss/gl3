# Documentation map

Use one authority for each question. Historical reports remain evidence for their stated date and candidate; they do not override current authorities.

| Topic | Authority | Supporting evidence |
|---|---|---|
| Product scope, tiers, and qualification | [PRD](product/PRD.md) | [Vertical lifecycle strategy](product/VERTICAL_LIFECYCLE_STRATEGY.md) |
| UI and brand | [UI canon](design/UI_CANON.md) | [Pursuit Workspace contract](design/PURSUIT_WORKSPACE.md), [brand assets](design/BRAND_ASSETS.md) |
| Architecture and data flow | [Architecture overview](architecture/overview.md) | [Data model](architecture/data-model.md) and focused architecture notes |
| Source behavior and coverage | [Coverage](sources/coverage.md) | [Source notes](sources/) and [registry](../config/sources/registry.v1.json) |
| Local setup and checks | [Repository README](../README.md) | [Local runtime](operations/local-runtime.md), [script guide](../scripts/README.md) |
| Production observation and deployment boundary | [Operations status](operations/README.md) | Dated sanitized receipts in the controller's ignored audit artifact directory |
| Backup and restore | [Operations status](operations/README.md#backups-and-actual-host-layout) | The October 20 receipt proves one copied dump and local restore; retention is UNKNOWN |
| Delivery status | [Milestones](delivery/milestones.md) | [Audit remediation matrix](../.agent/AUDIT_REMEDIATION_MATRIX.md) |

## Archive and superseded material

Do not delete historical narratives or receipts during documentation cleanup. The inventory captured before this repair is retained locally at ignored `.artifacts/docs-inventory-baseline.json` and is not committed. It lists 151 Markdown documents and 34 missing relative targets from the baseline. Those targets were inventoried across the whole corpus, including historical receipts; they are not current operational links. Some ignored local receipts are unavailable in a clean checkout. Their absence is not repaired by inventing a replacement.

The current product/UI authorities above supersede conflicting historical visual guidance. The October 20 recovery handoff in PR #98 and production database/backup proposal in PR #97 were reviewed as open documentation proposals; use this docs map and the dated operations observation for current consolidated status. Neither PR was merged as part of this packet. Retained historical reports remain under `docs/validation/`, `docs/operations/`, and `.agent/archive/`; their own dates and candidate identities govern their claims.

The [archive index](../.agent/archive/AUDIT-20261020/README.md) records preserved state-history material. Archive files and immutable receipts are evidence, not active runbooks.
