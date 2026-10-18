# D2 — Retained hard-document passage grounding

READY after E releases intelligence_jobs.py. One Luna; Sol narrow architecture
recommendation recorded2026-10-18. Existing PRD/authority/product boundaries govern.
No provider calls/activation, schema migration or general raw-document store.

Bind deliberate server-owned watch reprocess_revision/version (when present) into
request context/logical-call identity. A watch reprocess request with unchanged
bytes must not accidentally reuse an old completed model result; normal unchanged
checks still avoid calls. Parser/question/policy/accepted fact versions likewise
govern freshness. No arbitrary caller-supplied cache-bypass token or unknown retry.

Own intelligence_jobs.py context projection, grounded_candidates.py,
intelligence_provider.py strict schema, tests/test_grounded_candidates.py,
test_intelligence_processing.py, test_intelligence_worker_integration.py and concise
grounding documentation. F owns API/UI; C2 owns source retrieval/monitoring parity.

Use <=45k byte bounded worker-only retained passage context from immutable Evidence
text, exact version hash/extraction_location and page/section metadata. Current
title600/abstract1800 clipping drops Georgia later-page facts and GovInfo page.
Bound total context and document count explicitly, preserve exact original offsets,
expose truncation/partial metadata; no invented full text from hash. Page validation
uses actual single-page extraction_location or containing Page N segment; a global
page on multipage excerpt is invalid. E repairs accepted supplemental admission;
test accepted exact Interpretation/NeedObservation/hash even though research-public
discovery source stays disabled; reject quarantine/stale unaccepted supplements.

Provide a bounded accepted source-claim bundle and attributable conflict states,
not only accepted operator facts plus raw text. Reuse existing current-need claims/
project-state acceptance predicates (batch inputs to avoid N+1), exact activity,
source authority, evidence hash and field provenance. Null is unknown, not a zero
claim or conflict alternative. Include accepted-state digest in request freshness.
Never equate raw source hash with Observation semantic hash (Boston/PDF differ).

Deterministic Decimal normalization of explicitly quoted kW and MW with original
value/unit/precision; ranges remain ranges, no unsupported precision or campus/flare
conversion. Preserve exact month/quarter/year date precision and explicit unknown
instead of inventing ISO day. Add nullable speaker/organization/role only with cited
support. Citation existence, semantic support state and canonical acceptance are
separate. Matching quote remains unaccepted candidate, never fact/promotion.

Support retained page-aligned OCR transcript only with original document hash,
OCR method/version/provenance and explicit unreviewed status; do not claim scanned
PDF/image OCR generation. Surface its unavailable state honestly pending the
separate bounded OCR acquisition slice; never use hash as unseen text.

Tests: GovInfo page N, Georgia later-page excerpt; public4k retained excerpt/full
input30k partial, accepted vs quarantine supplement; retained OCR provenance missing
rejected, scanned document unavailable; explicit300kW→0.3MW/range/dateprecision;
negated MW/date; speaker missing/tampering; old ground journey regressions. All
isolated local DBs, no external calls. Run focused lint/mypy/tests; exact handoff
artifact, UTC durations/repaircount/UNKNOWN usage. No self-grade/merge/deploy.
