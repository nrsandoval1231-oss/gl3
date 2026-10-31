# Contact suppression and browse recovery

Migration `0045_contact_suppressions` retains privacy controls in an append-only ledger. Never delete or downgrade this ledger as part of an application rollback. Application images built before suppression support do not read the ledger and can expose methods the current image hides. Keep contact surfaces and refresh workers disabled until a compatible image reads suppression across contact search, opportunity, company, project, history, import, and refresh surfaces.

Retained source evidence and correction history remain immutable for audit. The privacy overlay applies to structured contact reads; it must not rewrite or delete those records.

## Saved browse recovery lane

This is the current code contract, not production authorization. Follow the [release and current-data rollback procedure](recovery-release.md) for protected-context preflight, image pairing and canary ordering. Installed host tooling and current deployed schema remain unverified by this guide.

Use the recovery stage/publish flow when a retained-data snapshot needs recovery. It only rebuilds derived browse summaries; it does not restore, delete, or rewrite canonical evidence. Never downgrade migrations `0045_contact_suppressions`, `0046_import_meta_reparse`, or `0047_scoped_identity_link_browse` to roll back application code.

Migration `0048_browse_recovery_stages` introduced the durable compare-and-swap receipt after `0047_scoped_identity_link_browse`; these are migration history, not instructions to apply 0048 as a new production change. Current repository head is `0049_scoped_identity_browse`. Inspect the actual database head and selected image before any separately authorized migration; do not replay applied revisions, run an older migrate service or downgrade the forward schema for application rollback.

The supported CLI shapes below are for an already authorized, correctly scoped local or protected application context. Staging/publication write derived data; the examples do not authorize execution. Production uses the verified selective companion described in the current procedure, rather than arbitrary host suffixes:

```powershell
python -m gridlens.jobs.browse stage-recovery
python -m gridlens.jobs.browse inspect-recovery --generation <generation-id>
python -m gridlens.jobs.browse publish-recovery --generation <generation-id>
```

`stage-recovery` builds and stores complete derived rows and a receipt, but does not change either browse pointer, prune retained generations, or delete dirty-project journal rows. Record the returned generation ID. Inspection must report `ready` immediately before publish. It reports only identifiers, revisions, policy/digest, row count, validity and CAS state; it does not print contact or project payloads.

`publish-recovery` serializes with ordinary browse builders and takes the browse-state row lock. It publishes only if the recorded input revision, full revision, active pointer, and prepared pointer still match. It also requires the current exact runtime policy, matching digest/receipt, a nonempty complete row count, a candidate already valid at publish time, and at least 60 seconds of remaining validity. Any drift or failed candidate check rejects publication without moving pointers. Successful publication atomically selects the candidate and clears the prepared pointer. The displaced active and prepared generations remain retained. Retrying the same successful publish returns `already_published` only while the candidate continues to pass policy, revision, integrity and validity checks.

There is no direct `rollback --generation` operation. A candidate that is stale, future-dated, expired, generated under another application policy, incomplete, or built before any state/pointer change must be rebuilt and staged against the current state. Do not disable freshness or invalidation fences to force recovery. After publication, verify browse readiness and contact suppression behavior using the coordinated release procedure; no paid provider calls or production canonical-data mutations are part of this lane.
