# Documentation inventory and dispositions

Baseline captured before documentation cleanup on 2026-10-20. The ignored inventory contained 151 Markdown files; this committed register gives each one a durable disposition. Classification uses document path, heading, and known authority role; it does not claim that every sentence in every historical report was revalidated. Preserve the listed evidence unchanged.

Use the repository [documentation map](../../../docs/README.md) for topic authorities. Product and owner authority are [PRD](../../../docs/product/PRD.md), [UI canon](../../../docs/design/UI_CANON.md), and repository [instructions](../../../AGENTS.md). Operational state and safe procedures are centralized in [operations status](../../../docs/operations/README.md); delivery gates are [milestones](../../../docs/delivery/milestones.md).

Disposition classes: `authority` controls a product/owner decision; `current-entry` is a maintained entry point; `technical-note` explains an implemented subsystem and may require code verification; `source-note` records source-specific behavior or dated acquisition evidence, never current coverage by itself; `candidate-evidence` is tied to a named date/candidate and is not current status; `superseded-or-preparation` is retained but replaced or preparation-only.

| Path | Class | Disposition and use |
|---|---|---|
| `README.md` | `current-entry` | Current local setup and top-level documentation entry point. |
| `AGENTS.md` | `authority` | Current repository implementation constraints; read before changing code or product surfaces. |
| `docs/architecture/acquisition-transaction-boundaries.md` | `technical-note` | Focused design or implementation note; verify code and date before using operationally. |
| `docs/architecture/autonomous-pursuit-research.md` | `technical-note` | Focused design or implementation note; verify code and date before using operationally. |
| `docs/architecture/data-model.md` | `technical-note` | Focused design or implementation note; verify code and date before using operationally. |
| `docs/architecture/evidence-graph-jev.md` | `technical-note` | Focused design or implementation note; verify code and date before using operationally. |
| `docs/architecture/grounded-document-candidates.md` | `technical-note` | Focused design or implementation note; verify code and date before using operationally. |
| `docs/architecture/INTELLIGENCE_INTEGRATION_STRATEGY.md` | `technical-note` | Focused design or implementation note; verify code and date before using operationally. |
| `docs/architecture/jev-task-contexts.md` | `technical-note` | Focused design or implementation note; verify code and date before using operationally. |
| `docs/architecture/overview.md` | `current-entry` | Maintained summary or operator entry point; use its linked authority and verify commands against code. |
| `docs/architecture/README.md` | `current-entry` | Maintained summary or operator entry point; use its linked authority and verify commands against code. |
| `docs/architecture/worker-planning-liveness.md` | `technical-note` | Focused design or implementation note; verify code and date before using operationally. |
| `docs/AUDIT-2026-10-12.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/decisions.md` | `authority` | Canonical product, owner UI, or recorded decision authority; preserve owner intent. |
| `docs/delivery/build-plan.md` | `superseded-or-preparation` | Superseded procedure retained byte-for-byte in `pre-docs-followup-20261020__docs__delivery__build-plan.md`; use the current authority linked in its notice. |
| `docs/delivery/environment-browse-pursuits/README.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/delivery/environment-continuity/README.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/delivery/first-path-checkpoint.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/delivery/ingestion-breadth-validation.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/delivery/intelligence-integration.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/delivery/local-signal-verification.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/delivery/logical-call-settlement-runbook.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/delivery/milestones.md` | `current-entry` | Current release-gate status; update only with dated evidence. |
| `docs/delivery/permit-pipeline-validation.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/delivery/project-pipeline-validation.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/delivery/quieter-environment/README.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/delivery/README.md` | `current-entry` | Maintained summary or operator entry point; use its linked authority and verify commands against code. |
| `docs/delivery/signal-card-review.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/delivery/validation.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/design/BRAND_ASSETS.md` | `authority` | Approved asset preservation rules; subordinate to owner brand approval. |
| `docs/design/BUILD_FOCUS_EXPERIENCE.md` | `superseded-or-preparation` | Historical concept superseded by October 18 UI canon; retain unchanged. |
| `docs/design/PURSUIT_WORKSPACE.md` | `candidate-evidence` | Retain as dated evidence for its named candidate and observation; do not use as current status. |
| `docs/design/UI_CANON.md` | `authority` | Canonical product, owner UI, or recorded decision authority; preserve owner intent. |
| `docs/operations/authentication-and-proxy.md` | `technical-note` | Feature-specific procedure or technical record; use current operations status for deployment, secrets, backup, and rollback. |
| `docs/operations/commercial-pursuits.md` | `technical-note` | Feature-specific procedure or technical record; use current operations status for deployment, secrets, backup, and rollback. |
| `docs/operations/intelligence-activation.md` | `technical-note` | Feature-specific procedure or technical record; use current operations status for deployment, secrets, backup, and rollback. |
| `docs/operations/intelligence-evaluation.md` | `technical-note` | Feature-specific procedure or technical record; use current operations status for deployment, secrets, backup, and rollback. |
| `docs/operations/intelligence-surfaces.md` | `technical-note` | Feature-specific procedure or technical record; use current operations status for deployment, secrets, backup, and rollback. |
| `docs/operations/local-recovery-proof.md` | `technical-note` | Feature-specific procedure or technical record; use current operations status for deployment, secrets, backup, and rollback. |
| `docs/operations/local-runtime.md` | `current-entry` | Maintained summary or operator entry point; use its linked authority and verify commands against code. |
| `docs/operations/local-signal-verification.md` | `superseded-or-preparation` | Superseded procedure retained byte-for-byte in `pre-docs-followup-20261020__docs__operations__local-signal-verification.md`; use the current authority linked in its notice. |
| `docs/operations/manual-pr-review.md` | `superseded-or-preparation` | Superseded procedure retained byte-for-byte in `pre-docs-followup-20261020__docs__operations__manual-pr-review.md`; use the current authority linked in its notice. |
| `docs/operations/post-gl3-019-handoff.md` | `technical-note` | Feature-specific procedure or technical record; use current operations status for deployment, secrets, backup, and rollback. |
| `docs/operations/power-pursuits.md` | `superseded-or-preparation` | Superseded procedure retained byte-for-byte in `pre-docs-followup-20261020__docs__operations__power-pursuits.md`; use the current authority linked in its notice. |
| `docs/operations/public-acquisition-bounds.md` | `technical-note` | Feature-specific procedure or technical record; use current operations status for deployment, secrets, backup, and rollback. |
| `docs/operations/README.md` | `current-entry` | Maintained summary or operator entry point; use its linked authority and verify commands against code. |
| `docs/operations/research-recovery.md` | `technical-note` | Feature-specific procedure or technical record; use current operations status for deployment, secrets, backup, and rollback. |
| `docs/operations/retained-editorial-records.md` | `technical-note` | Feature-specific procedure or technical record; use current operations status for deployment, secrets, backup, and rollback. |
| `docs/operations/runtime-recovery.md` | `current-entry` | Maintained summary or operator entry point; use its linked authority and verify commands against code. |
| `docs/operations/saved-browse-b1.md` | `technical-note` | Feature-specific procedure or technical record; use current operations status for deployment, secrets, backup, and rollback. |
| `docs/operations/saved-browse-ingestion.md` | `technical-note` | Feature-specific procedure or technical record; use current operations status for deployment, secrets, backup, and rollback. |
| `docs/operations/source-controls-and-worker-health.md` | `technical-note` | Feature-specific procedure or technical record; use current operations status for deployment, secrets, backup, and rollback. |
| `docs/operations/source-scheduling-proof.md` | `technical-note` | Feature-specific procedure or technical record; use current operations status for deployment, secrets, backup, and rollback. |
| `docs/product/PRD.md` | `authority` | Canonical product, owner UI, or recorded decision authority; preserve owner intent. |
| `docs/product/ranking-weights.md` | `authority` | Product strategy or policy subordinate to the canonical PRD and owner decisions. |
| `docs/product/README.md` | `authority` | Product strategy or policy subordinate to the canonical PRD and owner decisions. |
| `docs/product/TEXAS_PERMITTING_PAUSE.md` | `authority` | Product strategy or policy subordinate to the canonical PRD and owner decisions. |
| `docs/product/VERTICAL_LIFECYCLE_STRATEGY.md` | `authority` | Product strategy or policy subordinate to the canonical PRD and owner decisions. |
| `docs/README.md` | `current-entry` | Current topic map and authority routing. |
| `docs/sources/bay-area-policy-states-20261007.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/california-ceqanet-data-centers.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/coverage.md` | `current-entry` | Maintained summary or operator entry point; use its linked authority and verify commands against code. |
| `docs/sources/ercot-state-community-impact-rfi.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/fort-worth-development-permits.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/georgia-air-permits.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/gl3-018-admission-and-acquisition.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/gl3-019-permit-enrichment.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/gl3-023-city-permits.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/gl3-027-priority-flare-intake.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/ingestion-strategy.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/initial-discovery-review.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/local-news-breadth.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/local-quality-review.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/ma-ccc-cultivation-applications.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/onboarding.md` | `current-entry` | Maintained summary or operator entry point; use its linked authority and verify commands against code. |
| `docs/sources/permit-breadth.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/permit-ingestion-restrategy.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/project-interpretation.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/README.md` | `current-entry` | Maintained summary or operator entry point; use its linked authority and verify commands against code. |
| `docs/sources/san-antonio-development-permits.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/SIGNAL_GAP_AUDIT.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/SIGNAL_SOURCE_MATRIX.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/taylor-access-contract.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/taylor-newsflash.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/tceq-nsr-pending.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/tceq-temporary-batch-plants.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/temporary-power-screening.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/texas-large-load-interconnection.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/texas-tdlr-tabs-data-centers.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/sources/xcel-sps-proposed-large-load-tariff.md` | `source-note` | Source-specific contract, interpretation, or dated retrieval evidence; live availability is only in current coverage observation. |
| `docs/superpowers/plans/2026-10-18-b1-clock-transitions.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/superpowers/plans/2026-10-18-b1-pursuits.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/superpowers/plans/2026-10-18-b1-save-readback.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/superpowers/plans/2026-10-18-b1-saved-browse.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/b1/README.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/b1-clock/README.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/b1-pursuits/README.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/b1-saves/README.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/ercot-impact-rfi-20261007.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-015-persisted-signal-review.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-016-backend-contract.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-016-live-adjudication.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-017-buying-chain.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-018-validation.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-019-acquisition-continuation.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-019-validation.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-020-validation.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-021-power-pursuits.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-023-city-permits.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-024-commercial-signals.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-025-card-briefs.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-026-national-intake.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-027-priority-flare-intake.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-028-evidence-graph-jev-shadow.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-029-autonomous-pursuit-research.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-029-browser-recovery-20261007.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-029-closure-20261006.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/GL3-029-commercial-pursuits.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-029-delivery-checkpoint-20261007.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-029-final-acceptance-20261007.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-029-five-category-20261007.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-029-georgia-identity-fix-20261007.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-029-live-fact-proof-20261007.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-029-merge-validation-20261007.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-029-pr24-audit-repair.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-029-regeneration-20261007.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-029-regeneration-repair-20261007.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/gl3-audit-examples-20261007.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/intelligence-evaluation.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/intelligence-incremental-20261018.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/intelligence-monitoring-20261018.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/lifecycle-real-examples.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/lifecycle-reconciliation-20261007.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/open-pr-merge-2026-10-01.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/PR21-CORRECTNESS-REPAIR.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/pr4-repair-validation.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/pr43-pr44-reconciliation-20261009.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/procedures/stage2-priority-supplement-20261009.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/procedures/stage2-priority-supplement-final-20261009.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/procedures/stage2-reproducibility-20261009.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/procedures/stage2-source-quality-review-20261009.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/project-jupiter-20261007.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/stage1-baseline-20261009.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/stage2-pursuit-shortlist-20261009.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/stage2-source-quality-20261009.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/stage3-recall-20261009.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/texas-large-load-interconnection-20261007.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/ui79-pursuit-workspace.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `docs/validation/xcel-sps-tariff-20261007.md` | `candidate-evidence` | Preserve date, candidate and evidence limits; historical result is not a current release claim. |
| `deploy/digitalocean/README.md` | `superseded-or-preparation` | Alternate deployment preparation, not the observed production layout; do not execute as production instructions. |
| `deploy/README.md` | `current-entry` | Maintained summary or operator entry point; use its linked authority and verify commands against code. |

## Counts

- `authority`: 9
- `candidate-evidence`: 73
- `current-entry`: 13
- `source-note`: 28
- `superseded-or-preparation`: 6
- `technical-note`: 22

## Unavailable evidence and archive rule

The inventory records 34 missing relative targets across the pre-cleanup corpus. This count is not a list of 34 unavailable receipts: targets include ordinary relative-link issues and local ignored artifacts. Each target is checked from its referring document when that document is active; historical references remain attached to their original report and are not recreated. Ignored local artifact paths are unavailable in a clean checkout unless separately preserved by their owner.

Original versions of the 14 entry pages revised in commit `8163f13` are stored byte-for-byte beside this index as `pre-docs-repair-8163f13__*`. Four superseded active narratives were then shortened to archive notices; their prior bytes are stored as `pre-docs-followup-20261020__*`. The remediation baseline state files and original audit are also retained in this directory. The PRD and UI canon were not edited. The owner decision log preserves prior rows and has one authorized October 20 append.

The index itself is a disposition register, not a new documentation framework. If a page is retired later, preserve its evidence and update this register with the replacement authority.

## Added during the follow-up repair

`docs/operations/runtime-configuration.md` is the code-default reference. `docs/operations/observations/2026-10-20-production-readonly.md` is the sanitized source-bound observation. Both are current entries and are not included in the 151-file baseline count. The October 20 site-specific news decision is appended to `docs/decisions.md`; implementation and validation remain pending.
