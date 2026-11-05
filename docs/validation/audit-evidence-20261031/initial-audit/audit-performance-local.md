# Local fixture performance — 2026-10-30

Commit: `593cfd516d82a12b66558f53b975ad6c2b711517`. Local Vite production build preview on127.0.0.1:5193, system headless Chromium, no throttling, immediate synthetic API responses (26 projects,25 per page), no backend or database requests. All nonlocal requests were aborted. This establishes frontend-only fixture timing, not live authenticated performance.

Three fresh browser contexts per viewport, six page initializations total. Each sample performs one search, sector filter, pagination and detail navigation. Initial timing runs from browser navigation start until first project rows have painted (two animation frames). Interaction timing runs from before the browser action through target render readiness polled every animation frame and two further animation frames; it includes automation/IPC and scheduling overhead. LCP/CLS snapshot is taken at initial rows readiness, not a long field observation. Fresh contexts have empty page cache but server/OS caches and shared browser process may be warm.

|Viewport|Initial rows|LCP snapshot|Search|Sector filter|Next page|Detail|
|---|---:|---:|---:|---:|---:|---:|
|Desktop1440×900|474ms (387–492)|384ms (316–404)|410ms (407–456)|96ms (82–114)|114ms (101–114)|100ms (98–112)|
|Phone390×844|412ms (367–455)|304ms (256–392)|396ms (378–425)|81ms (67–96)|115ms (95–178)|100ms (99–101)|

Table values: median and observed minimum–maximum, n=3 each. Tiny samples are diagnostic and do not establish p75/p95 or a service objective.

Desktop initial CLS: median0.00033, range0.00033–0.00036. Initial long tasks over50ms observed: [62, 51, 64].

Mobile initial CLS: median0.00079, range0.00079–0.01391. Initial long tasks over50ms observed: [54].

No browser page errors occurred across six completed samples. Search is consistently slower than other local interactions; `web/src/features/workspace/CanonicalOpportunityResults.tsx:85` deliberately waits300ms before submitting a changed search. That fixed debounce explains part of the observed delay. No evidence here isolates another dominant frontend bottleneck or proves a backend performance defect. Production bundle measured by the earlier current-main build is JS422.48kB (gzip122.08kB) and CSS101.75kB (gzip17.55kB); bundle size alone is not proof of harmful latency.

The backend suite and PostgreSQL workloads were running concurrently in this shared cloud environment during collection. CPU contention, headless browser, absent mobile hardware/network throttling and immediate mocked API service limit comparability. These results exclude real authentication roundtrips, saved-browse materialization, database query duration, server cold starts, geographic latency, real record sizes, user devices and live contact detail. Parent performs separate public live speed checks; authenticated speed requires an already-authorized session.

Evidence: `/workspace/audit-evidence/frontend/performance-local.json`, `performance-local.mjs`, `performance-local.log`. No code edits, source retrieval, paid calls, production requests or production writes. A prior harness attempt with a mismatched synthetic detail heading and a locator-polling exploratory run were discarded; only the final six successful samples are reported.
