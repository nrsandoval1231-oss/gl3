# TITLE-02 recovery choice

2026-10-20 UTC. Read-only source/policy review. No provider call, live read, database mutation, runtime edit, recovery program or PR was performed/prepared by this reviewer. Live facts below are supplied by the parent; code behavior was independently inspected in the reviewed production source.

## Recommended choice

**Seek explicit approval for a narrowly scoped active-slot isolation policy for the one uncertain OpenAI call, while preserving its unknown status and full original accounting.** Implement and independently review that policy before applying it. Do not use ordinary reconciliation to pretend the outcome is known, do not increase the global active cap to two, and do not send a replacement title under the existing authorization.

This is a concrete path to useful continuing inference without permanently blocking all providers, but it changes the handling of unresolved financial exposure. It requires explicit approval and code/audit-gate work. The present review authorizes neither implementation nor application. The already approved ordinary public-data inference scope remains valid; it does not by itself approve duplicate submission or this exception to the unknown-call stop rule.

The immediate no-spend action is consistent cached display of the two successfully enriched projects. Keep the third title visibly unresolved. Existing saved projection and detail views must use a consistent reviewed display policy; rebuilding projections under the actual disabled configuration is safe, while displaying cached successful titles consistently requires a separately reviewed display-only path. Cached display has no provider call, creates no job and does not release an accounting slot. It is not equivalent to enabling paid updates.

## Current facts and why two-project isolation alone cannot resume inference

- Unknown call: `4d688637-3715-4efa-bce8-19fd41e51e09`, third selected need's title, `SENT_OUTCOME_UNKNOWN`, original reservation **$0.000434**, unknown actual cost/usage, no retained response payload or provider request reference. Parent reports `ProviderResponseError` and no available recovery ID. The original request used `store:false`; absence of a retained response cannot be converted into proof of no charge or successful completion.
- Four of six validation jobs completed. The sixth, original Jev job was not dispatched and is held with zero attempts. Do not relabel the validation as successful or overwrite its journal/receipt.
- `reserve_call()` reserves an `active_count` in each global/provider/model/source/project scope, as well as daily/monthly counters. Its global `active` row enforces `max_active=1`. Unknown dispatch retains these contributions. Excluding the third need/observation from feature scope does not remove the **global** blocker, so new calls for either successful project, including Jev, still cannot reserve.
- Returning an existing ready title or completed ledger result can reuse saved data without new reservation/transport. Reading that data is safe. Turning on ordinary generation and expecting it to work for two projects under the unchanged current ledger is not a valid recovery plan.

## Options compared

| Option | Unknown record/accounting | Practical effect | Decision |
|---|---|---|---|
| Leave ledger unchanged; show cached successes | Entire row, status and all counts remain untouched | Zero new provider calls; all new paid work remains globally blocked | Safe immediate display option, not continuing inference recovery |
| Existing explicit outcome reconciliation | `reconcile_call()` changes status to `RECONCILED`, sets finish/reconciliation fields and decrements active contributions; with null actual cost it retains daily/monthly reserved dollars and call counts | Frees active capacity but is terminal, not reusable successful output | **Not appropriate on current evidence**: the host CLI's `--action outcome` explicitly requires conclusive `--outcome-proof`. Approval to accept uncertainty is not conclusive outcome evidence. Directly invoking the lower-level permissive helper would bypass that contract |
| One-call active-slot isolation | Keeps `SENT_OUTCOME_UNKNOWN`, original identity/reservation/actual-null/usage-null/checkpoint; separately records an authorized occupancy exception | Allows one non-isolated call at a time while the original unresolved exposure remains counted financially | **Recommended recovery policy for explicit approval**, exact-call only, with code and audit safeguards below |
| Temporary `max_active=2` | Original unknown row and money remain; no new accounting representation | Creates capacity for another call by raising a global limit applied across scopes | Broader policy change; requires approval, fails to identify isolated exposure clearly, and does not itself solve replay identity or failed validation gate. Not recommended |

Relevant code: `backend/src/gridlens/integrations/logical_calls.py` (`reserve_call`, `_transition`, `reconcile_call`, `settle_call`); `backend/scripts/reconcile_logical_call.py` (`--action outcome`/`--outcome-proof`); `backend/src/gridlens/integrations/legacy_calls.py` (`perform_legacy_call`). Existing outcome reconciliation requires no new money measurement in its CLI, but it does require real outcome proof. Later attributable billing evidence can be recorded with `settle_call`; settlement alone does not establish application success or authorize replay.

## Minimal isolation contract to review before implementation

1. **One exact exception, durable and explicit.** An append-only operator exception record should identify the exact call ID, fingerprint, original job/fence, prior status, reservation, budget-scope snapshot, policy version, actor, actual approval reference, timestamp and fresh state digest. Its recorded meaning is "operator accepts unresolved exposure for concurrency admission; provider outcome and actual cost remain unknown." Give it a unique call binding so repeated application is a no-op. Do not hide it only in a process flag or manually edit a budget counter.
2. **Preserve the original evidence.** Keep the original LogicalCall ID/status/fingerprint/job/fence/request identity, original unknown/error record, null actual bill/usage, checkpoint, $0.000434 reservation, and all daily/monthly `call_count`/`cost_usd`. Do not mark completed, failed, cancelled, billed, refunded or cost zero. Preserve the failed validation journal and held sixth job.
3. **Release occupancy exactly once.** Under the existing provider/call/budget locks, atomically persist the exception and remove only this call's `active_count` contribution from every recorded scope/period. Financial call counts and reserved dollars do not change. Later completion/reconciliation must consult the exception and never decrement those active contributions again; otherwise another live call's slot could be released incorrectly. Settlement must retain the exception and original estimate. Tests must cover exception reapplication, stale digest, concurrent reservation, and later reconciliation/settlement.
4. **Keep the remaining gates.** No wildcard/provider-wide exemption, expiry-based retry or reset. Only this exact generic unknown call may be isolated, after verifying no live owner/lease and matching the approved state. A real billing quarantine must still block its provider; any new unknown/quarantine still stops the affected sequence. The active setting remains one for non-isolated calls, all narrower limits and $50 monthly aggregate remain intact, and max new call remains $0.01.
5. **Be explicit about changed risk.** Before isolation there can be one unresolved/admitted call total. After isolation there can be this old unresolved call plus one admitted call; the original provider activity cannot be proven finished. This is an intentional exception to unresolved-call admission, not a claim that the previous concurrency guarantee is unchanged. Money is still conservatively reserved, and no additional provider request is made by applying the exception itself.
6. **Expose it honestly.** Operations/reporting should separately count and show isolated unknown exposure, original reserved amount, unknown actual bill and exception reference. Ordinary `SENT_OUTCOME_UNKNOWN` dashboards and later audits must not silently drop it merely because its occupancy contribution was released.

Do not apply a bare SQL decrement while leaving the rest of the ledger unaware. It would make later `_transition()` decrements unsafe and undermine the concurrency invariant. A durable explicit distinction between unresolved billing and occupied execution capacity is the essential change.

## Scope, no-replay and staged continuation

The existing `title02-activate-runtime.py` cannot run: it requires six successful results and clear accounting. **Keep that gate unchanged.** A separately named, reviewed partial-recovery gate must bind the failed original receipt, four verified saved successes, the explicit isolation approval/receipt, exact code/images/settings and its narrower ongoing scope. It must state four-of-six validation and the unresolved third title. It cannot fabricate the old sixth completion.

For an initial partial continuation, limit ordinary Jev updates to the two successful observation IDs and prevent title generation for the unresolved third need through a server-side gate; a hidden/disabled button alone is insufficient. The current title flag is global, so a two-need-only title rollout also needs a server-side allowlist if that is the chosen scope. Cached reads can remain available. Existing completed identities must reuse saved results. Do not release held backlog; allow only newly authorized explicit title actions/current selected updates. Recheck sources, retained evidence, exact settings/caps and journal identities before enabling this revised scope.

The original sixth Jev job is a distinct never-sent intent, so sending it later is not a duplicate of the unknown OpenAI title. It is still a new paid request requiring the isolated-capacity policy and a separately reviewed dispatch plan that reuses that original job/fingerprint, verifies attempts zero/no call checkpoint/no prior matching logical call, and journals at most one dispatch. Do not create another Jev job to get around the hold.

## Replacement title is a separate decision

There is a UI/work-queue defect worth fixing separately: `titles.request_title()` can create a replacement job after the old unknown job has failed, since it checks only ready output and queued/running jobs. That does **not** permit an actual provider replay. The replacement has the same semantic fingerprint; `reserve_call()` finds the original unknown entry and returns its status or `IDENTITY_LEASE_MISMATCH`, and `perform_legacy_call()` refuses transport. Repeated clicks can therefore create blocked jobs and misleading pending state, not legitimate recovery. Preserve these replay protections; return the original unresolved state instead of queueing again.

If the user explicitly accepts duplicate-charge risk, a replacement requires a separately designed recovery identity linked to the original call and one authorized attempt. Do not silently bump prompt/policy versions, randomize a task key, remove the original fingerprint or clear its checkpoint to manufacture a new intent. The new identity must express an approved replacement attempt, while the original remains unknown. Its scope, evidence hash, reservation and idempotency must be reviewed before dispatch.

Nominal application reservations at the unchanged request bounds:

- One replacement third title: **$0.000434 additional**; original plus replacement title reserve **$0.000868**.
- Original unsent sixth Jev: **$0.010000 additional**.
- Both new requests: **$0.010434 additional**; including the retained original unknown, **$0.010868** for these three entries.

These are reservations, not measured invoices or a new proof of provider charge ceilings. Actual original charge remains unknown. There is no basis to refund/release its reservation or record zero. Changed request/evidence bounds require recomputation rather than assuming the same amount.

## Concrete approval to obtain

Recommended first decision, suitable for the parent to present after any required implementation design is made concrete:

> Approve a one-call recovery exception for the uncertain third title: keep its unknown ledger record and $0.000434 reservation, but release its occupied slot through an auditable policy so one new call at a time can run for the two successfully validated projects under the existing $50/month and narrower limits. This does not retry or replace the uncertain title, and it does not declare the original six-job validation successful.

If completion of the third project is desired, obtain a separate explicit decision:

> Approve one replacement title despite possible duplicate charging, plus the original never-sent Jev assessment, with at most $0.010434 in additional application reservations and no automatic retries. Keep the original unknown call and reservation intact.

The parent should select the desired concrete recovery scope rather than treating either quotation as granted permission. No approval is needed for read-only diagnosis or displaying already saved successful results. New recovery-policy implementation/application and duplicate submission require the explicit decisions above. Until then, cached display and diagnosis are the safe useful path; ordinary paid work remains blocked by the current global active slot.
