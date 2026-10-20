# TITLE-02 / JEV-ESTIMATE-01 independent financial review

Reviewed 2026-10-20 UTC. Verdict: **PASS — financial code review; no remaining financial-safety findings in the bound candidate.** The four findings from the preceding review are resolved. This verdict is not publication, deployment, provider-call, or runtime-activation authorization. The controller's exact-candidate PostgreSQL and full regression gates must still pass, followed by the required release decision.

## Exact binding

- Backend candidate: `0427d566d5280d70a9e11655ab04f243162f8ac3e95e409f796bdfaeff46246a` (`title02-candidate-manifest.json`).
- Full source candidate: `31260342d118c810cd6faf686c11e776bfced76e385b1791c868f563c70c256d` (`title02-full-candidate-manifest.json`).
- Archive: `title02-0427d566d528.tar.gz`; independently measured SHA256 `d31b495b78c329e2b7f110624d4f8dd6d52b1387383264981c7020612284a465`.
- Independently checked all 388 backend-manifest entries and all 488 full-source entries against the checkout: zero missing or mismatching files, checked at `2026-10-20T00:16:06.4808779Z`.
- Proposed activation JSON SHA256: `5f6d5a44e6e740aed583d1269babdaa21eb9a2cfd954e952047cd499526608d5`.
- Proposed scope JSON SHA256: `ce5b146ab3759a9af012ad521c15450c9621a64abc387c9999a4eb071d453cfc`.
- Release-plan SHA256: `0acce95e98ce237999ffc36c99200d7ec1074a885ead9ce7e0380139fa3fc7ab`.

## Prior findings resolved

1. **Under-reservation:** `intelligence_jobs._estimated_signal_policy_block_reason` now requires exactly `Decimal("0.01")`, within the configured per-call limit. Smaller, larger, zero, or invalid amounts cannot use this policy. The unit and ordinary-worker regression cases exercise nonreviewed amounts before provider dispatch. At the fixed published input rate, the 64,000-token review scenario is $0.002688; the $0.01 reservation remains an estimate, not a claimed invoice ceiling.

2. **Lost policy provenance on uncertainty/failure:** `legacy_calls.perform_legacy_call` passes a copy of its captured billing-policy dictionary through `before_dispatch_with_policy`. `signal_adjudication._save_signal_call_id_if_current` stores that exact dictionary in `Job.checkpoint.logical_call_policy`, together with `logical_call_id`, under the live job fence before `mark_dispatched`. It rejects replacement of an existing call ID or policy snapshot. A received error, conclusive failure, timeout, or ledger quarantine does not replace the job checkpoint. Regression cases inspect the persisted policy on success, 4xx failure, quarantine, and unknown outcome. Rates used for estimated usage come from the captured snapshot, not settings after the call.

3. **Unrelated model override:** the legacy response guard now reads TypeSafe's documented `model` field directly; the `actual_model` fallback remains confined to OpenAI. The conflicting-fields regression (`model` wrong, `actual_model` expected) requires model-mismatch quarantine. The provider-error path retains its normalized model/usage checks.

4. **Result-envelope overflow:** the estimate path rechecks the complete result after adding usage/policy metadata. An oversized final envelope enters bounded provider quarantine rather than failing completion without quarantine. Its regression deliberately supplies a provider result 64 bytes below the ledger maximum and verifies that enrichment exceeds the limit, the call remains `SENT_OUTCOME_UNKNOWN`, the reservation/active counts remain held, actual cost stays null, and checkpoint replay sends no additional request.

## Remaining controls reviewed

- The estimate policy is explicitly selected, default-off (zero reservation and empty observation scope), limited to `SIGNAL_ADJUDICATION`, and pinned to `jev-1.13.0`. Global, mode, contract, Jev/provider, credential, pricing, and selected-observation checks remain required. Partial invalid estimate configuration fails closed. Other TypeSafe contracts continue through the original `_typesafe_billing_block_reason`; its verified-total-input requirement is unchanged.
- The full canonical request, including metadata and escaped Unicode, must fit 16,384 bytes. The worker uses the same request builder and `_jev_call(..., max_attempts=1)`; no long-context header is added. Boundary and oversized Unicode/metadata cases are present.
- The dispatcher rechecks eligibility and captured billing-policy identity after the fenced predispatch callback. That callback revalidates the observation/evidence relationship, current hashes, and both source-enable flags. The worker rechecks current evidence/source/eligibility before accepting the result. Regression cases mutate evidence or disable the source after reservation and require cancellation without transport.
- Returned model and integer usage guards remain in place. More than 64,000 reported input tokens under the estimate policy causes `ESTIMATED_CONTEXT_ASSUMPTION_EXCEEDED`, not a fabricated hard-bound breach. Missing input usage stays unknown; null output with known input supports the input-only estimate. Actual billed cost remains null. The completed result retains model/answers/usage and adds explicit estimate metadata with false hard-bound verification.
- The shared `logical_calls` implementation is unchanged. Reservations consume the existing global/provider/model/source/project daily/monthly scopes and active slot. Completion retains the full application cost reservation; quarantine retains the active slot and can account for larger reported exposure. Existing ledger regression coverage includes concurrent caps and unknown calls retaining the global active slot across periods. New worker cases cover a disabled active allowance and insufficient shared budget; these tests are not claimed as independent execution evidence here.
- A saved logical-call checkpoint takes precedence over a newly computed fingerprint. Noncompleted saved calls cannot be replayed after a settings change; exact completed results can be reused. The ordinary-worker regression also verifies that a duplicate unchanged semantic job does not generate another provider call. The release controller must preserve these checkpoints and must not replace an uncertain validation intent with a fresh job.

## Proposed activation and rollback

`title02-proposed-activation.json` is consistent with the reviewed two-phase plan and remains marked `PROPOSED_NOT_AUTHORIZED_OR_APPLIED`. Its three observation IDs exactly match the scope JSON. It selects only `POWER_NEED_BRIEF`, `POWER_NEED_TITLE`, and `SIGNAL_ADJUDICATION`; pins Jev/model pricing, the estimate policy and $0.01 reservation; explicitly keeps total-input-bound verification false; and requires unchanged $50 monthly aggregate, $0.01 per-call limit and one active call. `BILLING_VERIFIED=true` here refers to documented input-only billing and is distinct from total-input hard-bound verification.

Phase 1 is six fixed controller job IDs with exact approved evidence hashes, process-scoped new-contract enablement, normal application new-contract flags off, and no unrestricted polling worker. Phase 2 requires its separately stated approval and successful validation; it leaves explicit authenticated title actions enabled and ordinary Jev limited to current/future retained versions of the three observations. $0.06 is additional initial application reservation, not a lifetime allowance or provider charge ceiling. All narrower live caps still need checking without increases. This review does not attest that proposed unchanged fields currently match production.

The rollback plan correctly disables new dispatch, holds undispatched validation jobs, restores application images/settings, and preserves additive tables, every logical call/budget/settlement, provider quarantine, and job checkpoint. It prohibits database replacement, accounting reset, release of sent/unknown reservations, unsupported reconciliation, or replacement jobs. Those requirements remain essential.

## Verification status and limits

This was an independent static code and regression-source review plus PowerShell file-integrity/scope checks. No application code was edited, no database/provider/live-runtime actions were performed, and only this local report was written. The exact-candidate controller log showed Ruff passing and mypy starting when inspected; PostgreSQL focused/full results were not yet available. Do not treat this report as a test-pass receipt. Final publication/activation remains gated on the controller's completed exact-candidate validations and the user's release decision. Frontend behavior and title semantic correctness are covered by separate reviewers.

## Rebinding to integrated HEAD — 2026-10-20 00:30 UTC

**Financial/static PASS remains valid for integrated HEAD `38d7499b6726fc9dd835944f301e50fd06c82095`.**

- Backend candidate: `8f5d19165ab53d529457d16984e4a9e87dad6973fd59d795ad48e0a55f4f0242`.
- Full source candidate: `5750769c0b4cbd316fd5d70d30a5f40accb4bb33ef500b33682d1e2e88dbc778`.
- Archive: `title02-8f5d19165ab5.tar.gz`; independently measured SHA256 `afe6cfe14492c9df42f7e5309bb275aae89dd5579c75d15c769e474c4a080f16`.
- At `2026-10-20T00:30:31.9631988Z`, all 488 current full-source entries matched the checkout. Git HEAD was independently checked and the worktree was clean.
- Compared every entry with retained `title02-frozen-0427d566d528-manifest.json`: no removed files and exactly two changed files, both tests: `backend/tests/integration/test_intelligence_worker_integration.py` and `backend/tests/integration/test_power_need_title_jobs.py`. Production backend code, migration, policy and accounting hashes are unchanged. Git diff from integrated feature commit `97c3d1d` to HEAD likewise lists only those two test files.

The fixture repairs are valid and preserve the substantive assertions. Explicit flushes insert Source before Observation and Observation before Evidence/Job, respecting PostgreSQL foreign keys. Patching `gridlens.persistence.database.SessionLocal` reaches the ordinary worker's function-local imports; the previously patched `signal_adjudication.SessionLocal` attribute was not a real module import. Directly imported legacy and worker session factories remain patched where appropriate. The title expectation now uses `asset operator`, matching the unchanged production formatter's underscore-to-space conversion. Provider transport stays mocked; these repairs do not substitute mock financial guards or weaken the reservation/quarantine/replay assertions.

Observed controller evidence in `title02-backend-8f5d19165ab5.log`: Ruff passed; mypy reports a successful result reused from identical application code; migration/repeat and schema parity completed with no new upgrade operations; **130 focused tests passed, one warning, in 92.95 seconds**. The full PostgreSQL backend suite started at `2026-10-20T00:29:42.083066+00:00` and was still running when reviewed. These are inspected controller results, not a separately executed test run by this reviewer.

No new financial findings. The six-intent execution controller has not yet been reviewed; its later concrete review is separate from this code rebinding. Per the parent's clarified authorization, the earlier restriction on new-PR approval pertains to paused source recovery and is not an additional publication blocker for this requested title/inference work. Continuing public-data runtime activation still awaits Nick's response. This review itself neither changes runtime settings nor sends provider requests.
