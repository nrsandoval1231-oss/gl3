# Preserved attempts and attribution

1. The pre-fix focused lost-response regression was red: after the first POST committed and the response was lost, same-key replay returned the original event version while the UI searched for a newly incremented version. This is the product defect identified by the independent `FIX` review.
2. The first focused run after repair had one test assertion still looking for the ordinary `Save live status` label after the request had become an ambiguous frozen retry. The UI correctly exposed `Retry same status request`; the test selector was corrected while preserving its event/key assertions. The final focused run passed 19 tests with the one separately persisted test skipped.
3. The first persisted local API/browser launch failed at sign-in (HTTP 401) before the selected Need rendered; its trace confirms no status write. A guarded password/hash check attributed this to a synthetic credential mismatch caused by fixture setup. No product code was changed for it.
4. The first fresh-run seed script had a PowerShell newline-escaping syntax error; it failed before fixture creation. That exact failure log is preserved. A corrected unique seed script ran with generated synthetic credentials, and the persisted browser/API test passed.
5. Earlier fixture path/settings bootstrap failures and all preserved original candidate review evidence remain outside this repair's source scope. Their captured logs are retained in ignored `.artifacts/`; no missing tool output has been reconstructed as raw evidence.

No provider credentials were used or emitted, no original/retained database was mutated, and no external action was taken.
