# Intelligence research and operations surfaces

The authenticated intelligence API exposes bounded task metadata, per-need job
history, operator job requests, explicit need watches, attributed owner review,
and a read-only operations summary. The operations summary covers a rolling
30-day window and limits source rows to 200, source due receipts to 20,000, and
logical calls to 5,000. It reads PostgreSQL only; it does not probe providers,
retrieve sources, or invoke a model.

Provider configuration reports only key presence, enable flags, and pinned
model names. Those values describe configuration, not connectivity or provider
health. Actual model, latency, token use, and cost appear only when a completed
provider receipt recorded them. Cost is a known subtotal when any call records
actual cost; missing amounts remain `UNKNOWN`. Reserved cost is maximum-cost
exposure for unresolved calls and completed calls missing actual cost. Uncertain
call count includes all retained unresolved calls. Candidate acceptance stays `UNKNOWN` until a
separate owner review path records it. Reviewed Signals, independently proven
Leads, and backup/restore receipts remain `UNKNOWN` where this database has no
supporting provenance.

Grounded candidates retain their exact evidence ID, hash, quote, extraction
section and span, publisher, publication date, and source URL. A candidate is
advisory and unaccepted. Owner notes append to the existing pursuit call-note
table with a stable client ID and a JSON review record containing the exact
need, job, logical call, candidate snapshot, and matching source references.
Replaying an identical client ID returns the saved note; changing its content
returns a conflict. Review metadata is explicitly pending independent review
and is not a canonical fact, tier decision, or benchmark label.

An uncertain provider outcome cannot be retried because a duplicate remote
charge may have occurred. Cancellation applies only to a queued request before
dispatch. Missing or zero budget controls, disabled contracts, and missing
provider configuration reject a request before a provider call can occur.

The optional `intelligence_review` column on `pursuit_call_notes` is nullable;
existing call notes are unchanged by migration 0027. Watch API responses expose
only the ten most recent revisions plus the total count, while the complete
revision history remains stored in PostgreSQL.
