# C2 — Incremental retrieval and migration consistency

Base local candidate 9aa3117, integration branch; actual SHA recorded at handoff.
One Luna, after F slot release. No provider calls/activation/production effects.

Own watch_models.py and narrow Job.__table_args__ model index parity; migration
0026 remains prerelease and must match metadata. Fresh corpus upgrade reached head
but alembic check found migration-only ix_jobs_project_monitor_active_source and
BIGINT Identity watch-source id versus model Integer. Repair model parity, do not
drop useful index or rewrite existing deployed migrations.

Complete actual conditional acquisition where upstream supports it, first bounded
publisher RSS using existing bounded_http, registry/source checkpoint and worker
ingestion APIs. Reuse durable Job.checkpoint/Source.health namespaced validator metadata; no new table or queue.
Scope allowed publisher_rss.py, bounded_http.py optional typed response support,
service.py narrow retrieve/commit checkpoint integration, monitoring.py only if
required, focused tests and concise ingestion docs. Coordinate E worker ownership;
do not edit worker/settings/API/web/provider modules.

Persist ETag/Last-Modified only after successful complete parse and retained batch
commit; send validators only for same endpoint/parser/source policy and previously
completed snapshot. 304 is a successful unchanged check, not empty-source withdrawal;
no normalizers/models/material changes. Missing/changed policy/parser or deliberate
versioned reprocessing must bypass conditional suppression. Malformed/empty200 must
preserve last-good cursor/validators and fail/partial visibly. Do not let validator
suppress unfinished resume jobs. Honor per-host safety/byte/time limits. Explicit
reprocessing of unchanged retained records should remain possible. Avoid changing
other adapters without evidence of need.

Tests transport-only:200 retain→304 no duplicate/change/model; interrupted batch
does not advance validators; malformed/empty200 no advance; parser/policy/reprocess
invalidates cache; headers exact; existing RSS/service/monitoring regressions and
fresh+repeat migration/schema check. Disposable DB gl3_intelligence_incremental_20261018_test,
app gl3_intelligence_incremental_20261018_app at loopback55487 user gl3_intelligence.
Portable fixture guards. Two distinct repairs then controller handoff. No self-grade.

Completion artifact commands/counts/files/UTC/limits. Root reruns and final Sol review.
