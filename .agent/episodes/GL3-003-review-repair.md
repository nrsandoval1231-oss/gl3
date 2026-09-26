# Episode: independent review of transaction fencing

State: candidate 515d20e63ee65a9709166c61ee01b0be5b74473fa62addab5564ac8a40c31bda passed 45 deterministic tests and real runtime/browser/replay checks. Independent Sol verified all 163 file hashes and returned FIX.

Finding: the raw-evidence commit released the job fence before network PDF retrieval. A lease could expire and be reclaimed during that wait, after which the former worker could commit PDF evidence and interpretation state before its next ownership check. Existing stale-cache and reclaim tests did not exercise that exact network/transaction boundary.

Direction: CORRECT only this finding through GL3-003-repair-1. Preserve original REVIEW.json, candidate and validation receipts. Stop the owned worker while repairing. Add a deterministic two-session reclaim-during-PDF test; verify no stale post-retrieval effects persist and the replacement can safely finish. Do not weaken the source-evidence durability boundary or hold job locks over network calls.

Attribution/candidate lesson: ownership checks need to cover transaction boundaries after external waits, not merely loop entry or final completion. Named metric: stale post-retrieval durable writes under deterministic reclaim, target zero. This is a local candidate lesson pending regression evidence and independent acceptance, not a promoted global policy.

Review time: 153 seconds as recorded by reviewer UTC timestamps. Earlier validation success is retained as evidence of tested coverage, not certification of the missing case. Final outcome belongs to the fresh candidate's validation and REVIEW_REPAIR1.json.

Final outcome: repaired candidate dc1a49e0e5e9a1d3636f3a71be8fa99ef8756dc362c32f22f7ce18990df8d072 passed 46 tests and all final controller gates, followed by independent Sol PASS at 2026-09-25 20:07:00 UTC. Deterministic regression proves zero stale post-retrieval writes. The lesson is validated for this local transaction boundary; no global memory or canonical product policy was changed. Direction: COMPLETE immediate slice; next A-cloud packet remains blocked on external authority/configuration.
