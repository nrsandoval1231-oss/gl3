# B1 follow-on: prepared clock transitions

Authorized overnight backend speed loop; deployment remains with the existing PC thread.
Base c2939d7 (PR77). Keep UI, evidence, canonical semantics, authentication and operating limits.

Observed cause: retained maintenance rebuilds only after current expiry. The final
1×/2× B1 fixtures showed12.374/22.267 seconds of explicit pending at forced expiry.
A focused PostgreSQL test reproduces503 exactly at the stored deadline with no
prepared generation. Broad source/unknown changes also require full rebuilding;
this follow-on does not predict future writes or hide that fallback.

Smallest selected repair: build one next-clock canonical generation ahead of time
(within120 seconds), using an isolated context-local evaluation instant. Existing
canonical evaluators remain authority; no duplicated qualification/rank logic.
Generation intervals are [valid_from,valid_until). One saved prepared pointer is
selected by the same indexed metadata query only at/after its valid_from, with
matching input revision and policy. Reads switch atomically at the boundary
without waiting for a maintenance poll. Physical build/publication/authentication,
leases and operator confirmation clocks remain real.

Every relevant committed write clears preparation. The invalidation trigger first
promotes an already-effective prepared generation as the incremental base, avoiding
an exact-boundary edit dropping back to the expired previous base. Rolled-back
writes preserve preparation. Any write during a future build rejects its
publication; repeated writes can miss preparation and retain explicit pending.
This is conditional availability improvement, not a future-write oracle.

Migration0022 is additive after0021, no canonical evidence changes. Retention
preserves both current and prepared pointers; rollback refuses future intervals.
Restart can use persisted preparation; missed/failed/expired/policy-mismatched
preparation fails closed and rebuilds. Maintenance can promote current preparation
and prepare the next interval. No collection or research jobs are dispatched.

Proof gates: context nesting/failure/thread isolation; canonical parity at future
clock; fact from/until equality; UTC/Chicago/host/DST/year boundaries; early-use,
mutation race/rollback/boundary edit, failed preparation, pruning, restart/missed
maintenance and policy mismatch. Measure1×/2× preparation/build cost and boundary
read p50/p95/max/query counts, with honest simulated-clock fixture limitations.
Independent review, relevant full tests, exact-head CI and guarded merge precede
handoff. Do not deploy from this task or change access/network configuration.
