# Acquisition transaction boundaries

Source retrieval and GovInfo companion retrieval run after source and lease
state are checked and the clean caller transaction is ended. The checks reject
new, dirty, deleted, or nested caller work before any transaction is committed.
After each network response, ingestion locks and rechecks the source
configuration and worker fence before accepting the response. A disabled,
reconfigured, cancelled, or reclaimed acquisition cannot write fetched rows.

Canonical source evidence retains its existing evidence-first commit boundary.
Companion retrieval begins only after that evidence is durable; a retrieval
failure therefore leaves the last-good source evidence intact. A stale source
or lease after companion retrieval discards the fetched citation. Callers using
`process_records(commit=False)` keep ownership of their transaction; eligible
PDF enrichment is skipped and reported as `pdf_skipped_transaction` rather than
committing the caller's work or performing network I/O inside it.
