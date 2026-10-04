# Commercial pursuits

The commercial workspace deterministically groups the highest-priority retained
Signal needs into up to 50 review cards. `ACTION NOW`, `RESEARCH`, `WATCH`, and
`REJECT` are workflow dispositions only; they do not qualify a need, alter its
evidence tier, or authorize outreach. A permit establishes permitting evidence,
not construction underway. Campus/nameplate capacity is never substituted for
need-specific MW. Unknown facts remain unknown.

Authenticated clients may read `GET /api/commercial/triage?limit=50`. The GET is
read-only: its current cohort counts are not daily evaluated/surfaced events.
Use same-origin `POST /api/commercial/triage/evaluate` to retain an evaluation
receipt in the existing Pursuit snapshot. Daily `evaluated` counts those
receipts; `surfaced` counts only new or materially changed cards entering
`ACTION NOW`. Replaying an unchanged card does not increment either count.
Contact outcomes are operator-reported notes. `Reached buying organization` and
`Qualified` do not change a tier; promotion history and a trustworthy de-duplicated
MW total remain explicitly unavailable when the retained data cannot support
them.

Targeted research accepts one question about one need at
`POST /api/commercial/triage/{need_id}/research`. It reuses the existing bounded
PowerNeed brief worker and current retained evidence; it does not perform web
research or make a new external claim. An identical question and evidence
fingerprint reuse the pending job or cached brief. A changed question or source
version requires a distinct request after the prior job finishes.

For a local operator shell, run:

```powershell
uv run --project backend python scripts/commercial_triage.py --limit 50
```

This prints the same read-only projection without creating evaluation
receipts. Set the same local database configuration used by the application
first. Do not use this output as evidence of contact,
qualification, customer intent, construction start, utility delay, or rental
demand unless a cited retained source explicitly establishes that fact.

Saved history uses authenticated `GET /api/commercial/triage/history`. The workspace exposes evaluated pursuits outside today's cohort, including closed/dropped records and operator notes. Cards are saved-as-of snapshots, explicitly not rechecked against current evidence. Older metadata-only receipts preserve disposition and notes without reconstructing missing facts.

The root URL shows a compact commercial next-action entry over existing Signals browse; use `?view=pursuits` for the full queue. Mixed-state exact-event siblings retain per-need states and a group RESEARCH question. Meaningful evaluation changes append immutable versions inside the existing snapshot; unchanged replay preserves versions/timestamps. Read exact-question progress with `GET /api/commercial/triage/{need_id}/research?question=...`; this read never queues another model request.
