# GL3 saved-work review and operational handoff

Saved at Nick's October 20, 2026 01:13 UTC instruction: **save all work and open an unmerged review PR**. Further recovery, inference, activation, merge and deployment actions are stopped. This documentation PR does not deploy or enable anything. Scripts below are historical review material, not instructions to execute them.

## What is already deployed

Live URL: **https://app.grid-lens.com/** on the existing DigitalOcean `gridlens-production` host (droplet 609407604, NYC1). No new infrastructure was purchased.

Already merged, therefore not presented as unmerged changes in this PR:

- [PR88: evidence-backed call preparation](https://github.com/nrsandoval1231-oss/gl3/pull/88), merge `b97de9bae6efa008f01ff44b9a625f978b977bdc`.
- [PR89: source-backed workspace titles](https://github.com/nrsandoval1231-oss/gl3/pull/89), merge `37e8274638407fb9cfb97fdc3e2fb0c512780dad`.
- [PR90: title enrichment and scoped Jev](https://github.com/nrsandoval1231-oss/gl3/pull/90), merge `3ee90f131af18d8839a1bb5019e7ca6369698852`.

Exact deployed PR90 source `802cbb4055c515699ce998445f77f98ab96d65b1` has the same tree as the merge (`8efd99f5c1d3711fd18c2f08099f019375da1804`). API/worker/browse image is `sha256:be07ead1cecc353e500a1f657ae3d4c8ab6062820c4f121f2558adc6f23ded07`; web is `sha256:f816a62a84e412bfc475ac8a773c34032a599baa04dd07b23893776dc1c8f5f2`. Release directory: `/opt/gridlens/releases/title02-802cbb4055c5`.

PostgreSQL remains canonical: database `gridlens_restore_20261014`, volume `gridlens_postgres-data`, additive schema `0032_power_need_titles`. Existing services/data were preserved.

## Confirmed live state when work stopped

The 01:09:45–01:09:53 UTC restart check passed: API ready, fresh worker heartbeat, same API/worker/browse container identities and environment. Web/database were not restarted. All 10 logical calls, 42 budget rows, three title rows, two title history versions and six validation jobs retained identical hashes. The unresolved request and reservation were preserved.

Runtime read at **01:10:33 UTC** confirmed:

- Scheduled ingestion `worker_auto_refresh=true`; intelligence advisory mode enabled.
- Only `POWER_NEED_BRIEF` is enabled in the ordinary contract list. New title enable flag remains absent/false.
- `JEV_ENABLED=false`, `INTELLIGENCE_TYPESAFE_ENABLED=false`. No continuing title/Jev activation was performed.
- OpenAI enabled, model `gpt-6-luna`; global monthly budget $50, max call $0.01, max active calls one. All narrower caps unchanged.
- The unknown call occupies the shared active slot, so **new paid calls across providers are blocked**. Cached completed results remain reusable. Healthy web/worker status does not mean continuing inference works.

After restart, a read-only browser check found list/detail label inconsistency: saved browse had the controller's title-enabled projection while detail followed disabled ordinary runtime. The already-running corrective browse rebuild finished successfully under the actual disabled policy. It preserved hashes for logical calls, budget rows, titles, title versions and signal decisions. **No subsequent browser rerun was performed because Nick stopped work.** That final UI consistency check is pending. No provider request was made by the rebuild. Transient QA sessions were revoked.

## Tests and actual inference results

Exact-candidate CI: **2,212 backend tests passed, one skipped**; **176 browser/authentication checks passed, one skipped**; Ruff, mypy (126 files), migrations/schema parity, frontend type/build and dependency gates passed. [Merged-main CI also passed](https://github.com/nrsandoval1231-oss/gl3/actions/runs/39350390836).

The additional single-CPU isolated full run was interrupted after exact CI passed; it is not claimed green. Two observed harness failures were isolated socket URL handling and executable-bit loss in a Windows archive; unchanged tests passed with correct harness/export. The isolated focused suite passed 130 tests. Pre-validation live desktop/mobile/reload QA passed for three public records. Ordinary production password login and post-rebuild browser consistency were not rechecked.

Nick approved the three cited public Austin records at 00:51 UTC. No private documents/notes were sent. The fixed six-job validation stopped after four successes and one unknown outcome:

| Public record | Title | Jev assessment |
| --- | --- | --- |
| Toaster temporary electrical permit 2026-120890EP | Saved cited title; gpt-6-luna; 593 input / 71 output tokens | Saved SHOW; jev-1.13.0; 883 input / 120 output; six dimensions |
| Hospital permit 2026-095413BP | Saved cited title; gpt-6-luna; 657 input / 67 output tokens | Saved REVIEW; jev-1.13.0; 961 input / 120 output; six dimensions |
| Data-center permit 2025-155325BP | Provider outcome unknown; no title result | Held, never dispatched, zero attempts |

The saved titles retain verbose source clauses. They are not a completed polished-title rollout. All four successful original call IDs returned cached results with provider invocation forbidden; the unknown ID rejected replay. No retry, replacement, cancellation, reconciliation, settlement or budget release occurred.

Five new dispatched calls reserved **$0.021307**, bringing retained monthly application reservations to **$0.034613 across 10 calls**. Actual invoices are unknown; reservations are not invoice ceilings.

## Preserved unknown outcome and held recovery

- Logical call `4d688637-3715-4efa-bce8-19fd41e51e09`, status `SENT_OUTCOME_UNKNOWN`.
- Job `dfe654a4-20e5-4c8e-bd8b-5dad736cf6e7`; need `ebd6ab87-1c95-415c-bff6-4db1d2615887`.
- OpenAI / `gpt-6-luna`, dispatched `2026-10-20T01:02:17.931273Z`, original reservation **$0.000434** retained.
- Job recorded `ProviderResponseError`; no response payload/ID, usage, actual charge or finish time was retained. The client has a five-second read-phase timeout, consistent with the timing but not proof of the precise transport cause.
- This request used `store:false` and did not retain a provider response ID or client request ID. No usable direct retrieval route for this specific request has been established. No new request was sent to recover it.
- Original sixth Jev job `47e89357-3622-4ec2-a8a8-565ca86551c0` remains held, zero attempts and no logical call.

The independent [recovery review](recovery-review.md) recommends a separately approved, audited exception for this exact unknown call's occupied slot, preserving its unknown status and all financial accounting. **No recovery implementation or policy exception was applied.** Existing reconciliation requires conclusive outcome proof that is unavailable. Merely excluding the third project does not unblock the global active slot. Raising the active-call cap or directly decrementing budget counters is not an approved workaround.

A replacement would require explicit duplicate-charge approval and a reviewed linked recovery identity: **$0.000434 additional title reservation**, plus **$0.010000** for the original unsent Jev if included, **$0.010434 additional total**. Both original and replacement might be billed. The successful-six activation gate remains unmet and unchanged. Original activation script is prepared/reviewed, **never executed**, and must not be run with a fabricated gate.

## Backup and rollback handoff

Fresh pre-release backup: `/opt/gridlens/backups/pre-title02-802cbb4055c5-20261020T005816Z.dump`, 19,458,710 bytes; SHA256 `a903976cf7d4f034e5e0102471430e1ce7827d73a393ec2d21425f66d5a8d52f`. Isolated restore and hashes/counts for 47 existing canonical tables passed before rollout.

Prior Compose: `/etc/gridlens/compose.app.pre-title02-802cbb4055c5-20261020T005816Z.yaml`. Prior images retained: API `sha256:4cf33d1f20d281b8971ba64dfea87c104dbb644a29a612f60a1e413d5d731609`; web `sha256:51660ba008a571a011d51706699969b91a38bfc897265913fff96bd9dcc78747`.

No rollback is requested now. If later authorized, first recheck current state, preserve a fresh backup, stop admissions and safely drain writers, then use the reviewed prior application images/configuration and verify health. **Keep schema 0032, all title/history/ledger records, and the unresolved reservation. Never restore the old dump over the live database or remove its volume as an application rollback.** Historical operator scripts require fresh review and state binding before any reuse.

## Saved work, exclusions and separate unpublished work

This PR saves the title/Jev operator scripts, independent reviews, this handoff, and a hash manifest of retained local evidence. It adds no application implementation and changes no runtime defaults. Raw runtime artifacts, logs, databases, screenshots, credentials, session material and secret-bearing environment files remain outside Git as required by `.agent/AGENT_RULES.md`. Their safe filenames/content hashes are inventoried; originals remain in this task workspace.

The [repository inventory](repository-inventory.json) records checkout branches, commits and dirty paths before this handoff branch was created. Existing changes in other checkouts are preserved and have not been folded into this PR:

- **Paused source recovery:** `gl3-source-repair`, branch `fix/source-collection-recovery`, clean commit `a5e4cf9ed7851e58de8599520c7f617a7ae5b831`; not pushed, no PR, not merged/deployed. Its bounded corpus replay failed at a source deadline; final full-suite acceptance is unverified. Historical pause evidence is preserved locally in `SOURCE_RECOVERY_PAUSED_2026-10-19.md`. Publication/deployment remain paused.
- `gl3`: existing modified `web/src/features/environment/Environment.tsx` left untouched; another Codex/UI lane, not silently adopted.
- `gl3-persistent-ingestion`: historical dirty `.agent` handoff/packet files and four untracked integration tests remain in that checkout; not silently merged into current main.
- `gl3-preload`: historical dirty `.agent` state/graph/archive/packet files remain in that checkout.
- Other inventoried GL3 checkouts were clean. TITLE-02 implementation checkout was clean at `802cbb4` before this documentation branch.

## Next steps after review

1. Review this PR; **do not merge or deploy automatically**.
2. Recheck final list/detail consistency after the completed browse rebuild; no additional inference is needed for that check.
3. Decide separately whether to authorize an exact-call accounting isolation design and/or a duplicate-risk replacement. Preserve the original failed six-job journal and unknown outcome in any follow-up.
4. Only after reviewed recovery and truthful validation should a new activation plan enable ongoing titles/Jev. Source recovery, bulk historical replay, broader feed coverage, Research selected-need reload/citation compatibility, and long-duration PC-off acceptance remain separate unresolved work.
