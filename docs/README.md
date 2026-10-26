# Documentation map

The owner-approved [Autonomous Intelligence Canon](product/AUTONOMOUS_INTELLIGENCE_CANON.md) supersedes conflicting older product, workflow and UI directions. Use the supporting authorities below for compatible constraints. Historical reports remain evidence for their stated date and candidate; they do not override current authorities.

| Topic | Authority | Supporting evidence |
|---|---|---|
| Product scope, tiers, and qualification | [Autonomous Intelligence Canon](product/AUTONOMOUS_INTELLIGENCE_CANON.md) | [Supporting PRD](product/PRD.md), [Vertical lifecycle strategy](product/VERTICAL_LIFECYCLE_STRATEGY.md) |
| UI and brand | [Current UI canon](design/UI_CANON.md) | [Pursuit Workspace contract](design/PURSUIT_WORKSPACE.md), [brand assets](design/BRAND_ASSETS.md), [UI migration inventory](design/UI_MIGRATION_20261020.md) |
| Architecture and data flow | [Architecture overview](architecture/overview.md) | [Autonomous architecture and retention map](architecture/autonomous-intelligence.md), [migration inventory](architecture/autonomous-migration-inventory.md), [data model](architecture/data-model.md) and focused architecture notes |
| Source behavior and coverage | [Coverage](sources/coverage.md) | [Source notes](sources/) and [registry](../config/sources/registry.v1.json) |
| Local setup and checks | [Repository README](../README.md) | [Local runtime](operations/local-runtime.md), [script guide](../scripts/README.md) |
| Production observation and deployment boundary | [Operations status](operations/README.md) | [Sanitized dated receipt](operations/observations/2026-10-20-production-readonly.md) binds to the named ignored source receipts |
| Backup and restore | [Operations status](operations/README.md) | [Local restore drill](operations/local-restore-drill.md) and dated receipt prove one copy/restore; scheduled retention and production cutover remain UNKNOWN |
| Runtime environment defaults | [Runtime configuration](operations/runtime-configuration.md) | Verified against `backend/src/gridlens/settings.py`; code defaults are not production configuration |
| Delivery status | [Milestones](delivery/milestones.md) | [Audit remediation matrix](../.agent/AUDIT_REMEDIATION_MATRIX.md), [controller evidence](validation/audit-remediation-20261020.md) |

## Archive and superseded material

The [committed inventory](../.agent/archive/AUDIT-20261020/DOCUMENTATION-INVENTORY-20261020.md) lists all 151 Markdown documents in the pre-cleanup baseline and gives each a disposition. It separates owner authority, current entry points, technical/source notes, candidate evidence, and superseded/preparation material. This classification does not claim every historical sentence was revalidated. The baseline reported 34 missing relative targets; the committed list does not treat them as 34 missing receipts. Historical pages keep their original context and are not silently repaired as live runbooks.

Do not delete historical narratives or receipts. Some ignored local receipts are unavailable in a clean checkout; the index identifies them as evidence referenced by dated reports, not as current links or replacements. Fifteen baseline entry-page Git blobs are preserved with prefix `pre-docs-repair-8163f13__`. Four superseded runbooks were shortened to notices in the follow-up; their pre-edit Git blobs use prefix `pre-docs-followup-20261020__`. The archive index records the source commits and notes that Windows checkout line endings may differ under `core.autocrlf=true`; working-copy byte identity is not claimed. Those October 20 records predate the autonomous amendment; current PRD and UI canon now defer to the Autonomous Intelligence Canon. Earlier decision rows remain intact with one authorized October 20 news decision appended.

The October 20 recovery handoff in PR #98 and production database/backup proposal in PR #97 were reviewed as open documentation proposals. Neither was merged by this packet. Use the consolidated authorities above for the current state. The [archive index](../.agent/archive/AUDIT-20261020/README.md) covers original state histories; archive files and immutable receipts remain evidence, not current status.

The October 18 Pursuit Workspace and October 1 cinematic/map-first presentations are superseded. Their dated records remain historical; they do not create competing design authority.

Manual-pursuit specifications and prior active agent directions are superseded. Their exact pre-amendment text is preserved in [the October 26 governance archive](../.agent/archive/AUTONOMOUS-20261026/README.md). Historical reports, contact benchmark CSVs, screenshots and archived runbooks establish only their dated candidate/environment results and must not be treated as current product instructions or accepted fresh contact data.
