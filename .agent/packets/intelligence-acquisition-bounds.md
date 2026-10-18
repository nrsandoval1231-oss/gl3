# C5 — Finite public acquisition and cross-worker admission

WAIT for C4 worker and D3 service/settings/helper release. Current intelligence
worktree/branch, base cad2e19 plus C4/D3. Sol runtime_architect chose this bounded
follow-up; no new tribunal, queue, platform or schema required.

Own narrow worker lease/admission/runtime helpers, source service retrieval and
record-boundary deadline plumbing, adapters/__init__.py importable pure entrypoint,
bounded_http.py IPC/result boundary, focused tests and operations documentation.
Coordinate settings after D3 freeze; no providers/ledger/schema/evaluation/API UI.
Use exclusive grounding `_test`/`_app` DBs after C4 release; preserve others' work.

One existing PostgreSQL nonblocking session-advisory global PUBLIC ACQUISITION
slot, held outside a transaction, initially serializes discovery and monitoring.
Global1 implies per-host<=1 even when adapters discover a different document host.
Source endpoint-only host locks cannot prove that bound. Preserve existing
per-source lock but make waiting finite/nonblocking. Contention defers under the
current fence with short bounded jitter and restores the unused attempt; it must
not mark an external call sent. Release all locks/connections in finally. Model,
OCR/provider dispatch remains under durable ledgers and its own existing caps;
do not kill/retry a paid call. Inventory other controlled public research retrieval
paths and apply the same admission where needed without nested self-deadlock, or
state their separately enforced finite caps precisely rather than overclaiming.

Keep all DB sessions, evidence commits and fencing in parent. Pure retrieve_source
and retrieve_companion network+parse functions use the existing killable spawn
boundary in deployed normal operation (client=None). Retain explicit injected-client
path for deterministic tests and label its cooperative deadline honestly. The
initial leased absolute lease_until establishes a finite per-attempt deadline;
derive monotonic remaining time once and never reset it after each request/record.
Independent fenced renewal uses its own short session only until that deadline,
never extends beyond deadline plus a stated small settlement allowance, and stops
on cancellation/fence loss. Check deadline before HTTP/record mutations/checkpoints.
Keep original committed progress on timeout. Ordinary retry count remains bounded;
unknown paid outcomes cannot be refunded/retried through this acquisition repair.

Audit/fix run_isolated IPC: receiver.poll then unbounded recv of arbitrary result
does not itself prove a hard wall bound. Bound serialized result size and receive
time; child errors must not expose request credentials. Preserve RSSSnapshot cache
metadata. Windows spawn and stalled body/DNS child must terminate within the
measured deadline allowance. Reuse finite memory/process limits; no arbitrary
callable path from documents or model output. Bound parent DB statement/lock phases
and report cooperative parent processing limits honestly; never claim an absolute
whole-job hard wall merely from child timeout.

Real PostgreSQL tests: two workers contend/no second HTTP, bounded defer/no attempt
loss, release after exception, cancellation/stale-fence during retrieval/renewal,
deadline preserves committed evidence/checkpoint and replay, slow child termination,
bounded result/IPC, Windows spawn, RSS conditional metadata and legacy injected
client regression. Existing monitoring/research/provider all-OFF/zero behavior must
remain zero calls. Parse failures remain visible/quarantined as bounded failed jobs
with last-good freshness separate; do not manufacture successful partial snapshots
or withdraw evidence because retrieval failed. No live HTTP/providers/production.

Two materially different repairs then canonical reconstruction. Record exact files,
commands, exit codes, UTC start/finish and unknown timing/usage honestly in C5
completion. Controller rerun/final exact-candidate gates and independent Sol review.
