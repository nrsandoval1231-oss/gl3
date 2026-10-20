# Delivery status

Observed 2026-10-20. This page separates repository work from release acceptance. The product requirements remain in the [PRD](../product/PRD.md); the current layout is governed by the [UI canon](../design/UI_CANON.md).

## Current checkpoint

The remediation baseline is `fc5afbb144d5129ef9edcefeeb87d5faf25f03f4`, based on GitHub main `9e9e188bdf2825a8305a0e9eac0b23f0af1df47e`. PRs #94 and #95 are merged; #96, #97, and #98 were open when inspected. Remediation work is in progress. The news held-out corpus has a known failure. On October 20, the owner authorized site-specific news to create discovery Signals with unknown power facts and unchanged Prospect/Lead gates; news implementation and held-out validation remain pending Terra's handoff. See [the decision log](../decisions.md#owner-decision-october-20-2026-site-specific-news-may-create-discovery-signals). This checkpoint does not establish a finished remediation candidate, deployment, or product acceptance.

Read-only production observations from 2026-10-20 18:28:48–18:50:41 UTC are summarized in [operations status](../operations/README.md). The running image was `title02-802cbb4055c5`, schema `0032`, with 1,620 projects and 1,619 saved needs. Authenticated live workflow proof and scheduled off-host backup retention remain UNKNOWN.

## Product gates

| Gate | Required evidence | Status at this observation |
|---|---|---|
| A — Foundation | Scheduled real source check persists while the owner's PC is off | Open; a production worker heartbeat and source state do not prove this gate. |
| B — Daily Signals | Broad real observations, duplicate-free replay, visible failures | Open; source freshness is mixed and several sources lack successful runs. |
| C — Prospects | Reviewed identity/activity and evidence-supported qualification | Open; no new acceptance claim in this checkpoint. |
| D — Leads | Independently discovered, auditable real Lead | Open; none accepted here. |
| E — Daily working release | Requirements 38–41, including seven real cycles and restore proof | Open. |

PRD requirements 38–41, commercial review and Nick's review remain governing release evidence. Source, project, test, or PR counts do not replace those gates. A task's completion artifact reports only the scoped documentation result.

## Audit work status

The [remediation matrix](../../.agent/AUDIT_REMEDIATION_MATRIX.md) maps findings to acceptance criteria. CORE and retained work had validated prior checkpoints at packet creation; UI and news work remained in progress. Documentation is being reconciled against the observed implementation and dated receipts. Final integrated validation, independent review, and any release decision are pending.
