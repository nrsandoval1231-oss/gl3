# GL3-015H independent review r2

**Verdict: FIX**

Finding: The completion receipt did not distinguish the attachment SHA-256 that D retains from the per-request metadata that D omits. Correct the D request-sequence field to mark method, posted fields, response headers, `Location`, and redirect sequence UNKNOWN while retaining the verified body hash.

Repair scope: completion field and candidate hashes only. No network or edits outside H. The earlier FIX remains preserved in `REVIEW-r1.md`.
