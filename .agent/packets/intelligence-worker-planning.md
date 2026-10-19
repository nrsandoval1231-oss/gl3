# C4 — Keep durable planning and liveness moving during acquisition

READY after C3 handoff. Current intelligence worktree/branch; base304062d plus C3.
Sol runtime_architect direction MODIFY then PROCEED: fixed named heartbeat lane
and separate source/pursuit/watch planner lanes plus one job-execution lane. Only
enabled planner lanes start. Each iteration owns its DB session, failures log and
do not stop other lanes; stop Event.wait enables finite shutdown. Retain persisted
PlannerState cadence/backoff. No futures/thread-per-job. Heartbeat means process
liveness, never completed acquisition or healthy source freshness. C5 separately
owns whole-job deadline/HTTP admission; C4 must not claim those are solved here.

Own jobs/worker.py main/planning/heartbeat loop only, focused new worker tests and
concise runtime documentation. D3 owns dispatcher branches only; negotiate serialized
file edits before touching worker.py. No queue, ledger, migrations, source service,
provider, schema or accepted-state changes. Exclusive released grounding test/app
DBs; preserve all other work. One Luna, no delegation.

Evidence: main currently runs planners and heartbeat then synchronous run_one;
slow acquisition delays both indefinitely. Reuse the existing PostgreSQL durable
jobs/planners and bounded worker infrastructure. Separate bounded planner/heartbeat
execution from the one job-execution lane without introducing a queue/platform or
unbounded job threads. Keep source discovery and watch monitoring independent under
their existing flags, persisted retry/cadence/backpressure and source policy. A
slow/failing planner must not silently destroy heartbeat or the other planner;
bound/release database transactions. Preserve worker identity/fence semantics and
truthful health. Clean shutdown must stop/join background activity with a finite
bound; failures visible in logs and retry state. Zero controls still means no
provider requests and no unexpected collection/research scheduling.

Use meaningful real-PG test with deliberately blocked job retrieval while planning
and heartbeat continue from another session, plus planner failure isolation, flags,
shutdown and existing source schedule/monitoring/worker regressions. No real network
or providers. Two distinct repairs then canonical reconstruction. Record measured
test timing/commands/exit codes, unknown metrics honestly, changed files and handoff
artifact. Controller final exact-candidate gates and independent review required.
