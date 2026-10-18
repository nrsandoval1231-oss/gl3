# Public acquisition runtime bounds

Ingestion, project monitoring, pursuit questions, pursuit research, and OCR
extraction share a nonblocking PostgreSQL public-acquisition session lock. The
workers sharing this PostgreSQL database therefore run at most one of these
jobs at a time, including documents discovered on a different host. The lock remains held for
the whole job handler; OCR's ledger-governed provider phase can therefore keep
the public slot occupied after capture finishes. Provider calls still use
their durable ledger and are never killed or retried by this boundary.
Contention requeues the job with a short deterministic delay and restores the
leased attempt; it does not mark a request as sent. The source advisory lock
remains in place for source identity and configuration coordination.

Each acquisition uses the original job lease as one monotonic per-attempt
deadline. Normal source retrieval and GovInfo companion retrieval run in a
killable spawned process. IPC result payloads are capped at 8 MiB and the
parent waits only for the remaining deadline. The worker renews its fenced
lease through a separate short database session, but never beyond the original
lease expiry plus a five-second settlement allowance. Parent-side database
and evidence processing remains cooperative and checks the same deadline at
record and checkpoint boundaries; this is not a hard bound for arbitrary
database work or the whole queue lifetime.

Registry reconciliation uses a short transaction and a per-source try-lock.
An actively acquired source keeps its persisted schedule epoch for that pass;
the planner continues reconciling persisted epochs for all sources and leaves
that source's due records pending when the live registry differs. A later pass
reconciles the source after acquisition releases its lock. This preserves the
expected schedule denominator and prevents stale configuration from dispatching
new work. Operator enable/disable transitions retain their serialized epoch
path.

The existing question and pursuit workers retain their own smaller research
budgets and retry policies. OCR and other model-provider calls remain under
their existing durable ledgers. This control does not enforce queue-job
lifetime, admission across separate PostgreSQL databases, or provider-call
deadlines.
