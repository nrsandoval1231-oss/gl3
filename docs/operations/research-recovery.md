# Autonomous research recovery

Research freshness applies after a source route has actually been checked. A
checked negative search can be reused until its category freshness window ends.
An unavailable provider, transient failure, or exhausted budget does not count
as a checked result and remains eligible for bounded recovery with unchanged
project evidence.

Transient attempts use delays of 1, 6, and 24 hours. The retry count follows the
same question and evidence fingerprints across replacement question rows. After
the final retry is exhausted, automatic scheduling pauses for that unchanged
question. This is a persisted unresolved outcome, not a user-facing manual refresh task.
Other eligible missing-fact categories must continue to be scheduled. Recovery or
policy changes occur through internal machine/diagnostic controls with the
original retry and provider-effect safeguards; no public question-entry or retry
button is part of the product.

Before a paid Firecrawl request, the worker persists its source and cost
reservation in `inflight_url` at the dispatch callback. A free source or public
GET uses `inflight_acquisition_url` for its bounded retrieval reservation; that
marker does not represent a paid provider effect. If a paid request may have
been sent but its outcome cannot be confirmed, the receipt retains
`inflight_url` and records an `UNKNOWN` effect. Internal retries, new questions,
and changed evidence do not authorize another paid attempt while that marker
remains. Reconcile the provider request and update the receipt through an
explicit recovery procedure before retrying; the system does not infer that a
timeout means no request occurred.

Evidence collected before a provider failure remains available. A retry does
not promote a pursuit by itself; accepted evidence still passes through normal
admission and deterministic commercial evaluation.

The isolated acquisition worker enforces a 512 MiB memory bound before loading
acquisition code. Linux uses `RLIMIT_AS`; Windows uses a Job Object process
commit limit, whose accounting is not byte-for-byte equivalent to Linux
virtual-address-space accounting. Job Object creation, configuration, or child
assignment failures stop the operation with an explicit error; acquisition
never falls back to an unbounded child.
