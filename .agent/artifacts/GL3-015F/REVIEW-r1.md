# GL3-015F independent review — repair record

**Verdict:** FIX
**Candidate reviewed:** `0dfb09fb…`

**Sol issue (verbatim):**

> Parser behavior accepted, but the documented validator command overwrites tracked validation.json/sample.json and embeds current UTC; controller rerun changed validation SHA, so COMPLETION candidate hash is stale.

**Repair direction:** Make the default documented proof command read-only; allow generated exports only to an explicitly selected ignored output directory. Freeze tracked proof receipts once for the repaired candidate, verify exact file hashes, and demonstrate two default reruns leave the tracked receipt hashes unchanged. Obtain fresh Sol review after the repaired candidate is frozen.
