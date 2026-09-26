# GL3-003 repair 1 — independent review fence finding

Reviewer verdict: FIX, preserved unchanged in `.agent/artifacts/GL3-003/REVIEW.json`, against candidate 515d20e63ee65a9709166c61ee01b0be5b74473fa62addab5564ac8a40c31bda. No commit, push, merge, deployment or acceptance/state advancement before fresh review PASS.

One Luna owns ONLY backend/src/gridlens/ingestion/service.py and backend/tests/integration/test_ingestion.py, plus its repair completion artifact. Not alone: controller owns evidence/reporting; other product files remain frozen. No schema, source-gate, UI, credential, registry or unrelated edits. Exclusive isolated gridlens_test lease for this repair; never reset the application database.

Finding: service commits raw evidence, releases the job lock, waits for PDF retrieval, then can commit PDF evidence and interpretation state without reacquiring/checking the lease fence. A reclaimed worker may write durable stale state before the next check.

Repair: reacquire a fresh locked fence before every post-retrieval mutation transaction/commit. Preserve the deliberate raw-evidence durability boundary; do not hold a job lock during network retrieval or weaken expiry/ownership checks. Inspect all commit boundaries in this service for the same issue. Use existing queue fencing with refreshed ORM state.

Deterministic regression: two PostgreSQL sessions; after old worker commits raw evidence, simulated PDF retrieval expires/reclaims its lease for a replacement worker. Returning old worker must raise fence loss before storing PDF evidence, interpretation status or project/need/digest mutations. Verify initial raw evidence remains, no stale post-retrieval effects persist, and replacement worker can complete safely. This is a concurrency state test, not a real-source mutation.

Validation: focused new regression, affected ingestion/job tests, lint/types. Then terminal completion/hashes and test-DB release. Controller restarts its owned worker, refreezes, reruns mandatory final gates and obtains fresh independent review. Preserve original REVIEW.json; new review is REVIEW_REPAIR1.json. Retry budget two materially different repairs before escalation; do not self-certify.
