# Contact suppression and browse recovery

Migration `0045_contact_suppressions` retains privacy controls in an append-only ledger. Never delete or downgrade this ledger as part of an application rollback. Application images built before suppression support do not read the ledger and can expose methods the current image hides. Keep contact surfaces and refresh workers disabled until a compatible image reads suppression across contact search, opportunity, company, project, history, import, and refresh surfaces.

Retained source evidence and correction history remain immutable for audit. The privacy overlay applies to structured contact reads; it must not rewrite or delete those records.

## Saved browse recovery lane

Use the recovery stage/publish flow when a retained-data snapshot needs recovery. It only rebuilds derived browse summaries; it does not restore, delete, or rewrite canonical evidence. Never downgrade migrations `0045_contact_suppressions`, `0046_import_meta_reparse`, or `0047_scoped_identity_link_browse` to roll back application code.

Migration `0047_scoped_identity_link_browse` is copied byte-for-byte from the reviewed live release source. Migration `0048_browse_recovery_stages` adds a durable compare-and-swap receipt for staged generations. Production rollout should apply the normal new `0048` migration; do not replay `0047` against an already-migrated database.

Run the CLI from the deployed image/worktree with its normal, correctly scoped database configuration:

```powershell
python -m gridlens.jobs.browse stage-recovery
python -m gridlens.jobs.browse inspect-recovery --generation <generation-id>
python -m gridlens.jobs.browse publish-recovery --generation <generation-id>
```

`stage-recovery` builds and stores complete derived rows and a receipt, but does not change either browse pointer, prune retained generations, or delete dirty-project journal rows. Record the returned generation ID. Inspection must report `ready` immediately before publish. It reports only identifiers, revisions, policy/digest, row count, validity and CAS state; it does not print contact or project payloads.

`publish-recovery` serializes with ordinary browse builders and takes the browse-state row lock. It publishes only if the recorded input revision, full revision, active pointer, and prepared pointer still match. It also requires the current exact runtime policy, matching digest/receipt, a nonempty complete row count, a candidate already valid at publish time, and at least 60 seconds of remaining validity. Any drift or failed candidate check rejects publication without moving pointers. Successful publication atomically selects the candidate and clears the prepared pointer. The displaced active and prepared generations remain retained. Retrying the same successful publish returns `already_published`.

There is no direct `rollback --generation` operation. A candidate that is stale, future-dated, expired, generated under another application policy, incomplete, or built before any state/pointer change must be rebuilt and staged against the current state. Do not disable freshness or invalidation fences to force recovery. After publication, verify browse readiness and contact suppression behavior using the coordinated release procedure; no paid provider calls or production canonical-data mutations are part of this lane.
