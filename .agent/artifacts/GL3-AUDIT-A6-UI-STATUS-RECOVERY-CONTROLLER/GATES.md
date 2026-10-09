# A6 functional UI/status recovery gates

Tested a1d1b96e8ad89f4184e12404736c9bdb108eaf8f. Backend 1,471 passed, 2 environmental skips, 7 warnings, 232.32 seconds. Browser 81 passed, one dedicated-path skip, 47.6 seconds; separate authenticated local API/browser response-loss proof 1 passed, 8.6 seconds.

Ruff, mypy (80 files), web typecheck/build, diff, locked Python/npm scans, 34-path OpenAPI equality, generated client equality and fresh/repeat/downgrade/reupgrade/drift checks passed. Provider keys blank and automation disabled for application imports. No candidate .env.

All 279 separately hashed working/Git source and governing inputs match, with CRLF/LF-only differences explicitly reported. Recovery changes only FactWorkflowPanel.tsx and call-facts.spec.ts. Builder raw manifest entries verified; earlier FIX and failed attempts preserved.

Read-only retained parity covers 1,167 records, 1,149 groups, 17 searches, all 24 pages. All 24 original-column table fingerprints on corpus/status copies and original dump hash remain unchanged. All seven workflow filters plus UNKNOWN return bounded 50-record pages at 125 SQL; 1,022 synthetic events, 146 true no-event UNKNOWN. Commercial/public payload hashes remain identical, at 135/125 SQL. Local first/warm timings and Python allocation receipts are bounded local evidence, not production SLO.

The actual response-loss case retries the identical frozen request after its first POST committed, confirms the returned exact event by read-back, and proves one event only. Missing/foreign/read-back-outside-window/repeated-loss cases remain UNKNOWN; current competing status remains distinct from confirmed historical request. Recent history shows newest ten. Status never qualifies evidence.

Fresh independent acceptance is pending. Previous UI ce3a03bf FIX review SHA9c2d1290807cc01b702140ce998a27718b5b5d6c549580f407dd1d07697b5415 remains authoritative for that older candidate. Accepted PR43 backend unchanged. Parent, canonical original UI assets, authentic feeds/quality/seven-day/customer gates remain OPEN. No merge/deployment/provider activation/external sends.
