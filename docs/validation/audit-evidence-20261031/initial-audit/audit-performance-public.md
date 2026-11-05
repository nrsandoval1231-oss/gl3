# Bounded public load-speed QA — 2026-10-30

Public sign-in only; no authenticated app benchmark. Twelve navigations: three cold/warm pairs at each viewport (desktop1440x900/mobile390x844). Cold=new isolated browser context; warm=second navigation in that context. No CPU/network throttling and mobile is a viewport, not phone hardware emulation. Headless system Chromium through the managed outbound HTTPS proxy; provided CA trusted with verification enabled. Backend pytest -n4 shared this4CPU cloud environment. Small samples are diagnostic observations, not p95/SLA or load-test results.

|Viewport/cache|n|Sign-in visible median/range ms|FCP median ms|LCP median ms|Unexpected shift sum median|Observed blocking median/max ms|Resource transfer median B|
|---|---:|---:|---:|---:|---:|---:|---:|
|desktop/cold|3|866 / 630–1001|708|860|0.00430|12 / 48|963681|
|desktop/warm|3|408 / 371–530|288|372|0.00430|0 / 0|963681|
|mobile/cold|3|605 / 504–673|468|596|0.01785|0 / 0|963681|
|mobile/warm|3|371 / 336–383|276|372|0.01785|0 / 0|963681|

LCP is the last observed candidate through load + sign-in visible +700ms. Layout-shift value is the sum of unexpected observer entries in that window, not a complete session-window CLS implementation. Blocking is sum(max(longtask duration−50ms,0)) in that window, an equivalent diagnostic rather than Lighthouse TBT; no Lighthouse score is claimed.

- Browser GET `/api/auth/session`:12 timed samples, median79ms, range60–311ms; status200 authenticated:false. Fetch used credentials:omit, cache:no-store and consumed response body.
- Browser GET `/api/opportunities`:12 timed samples, median66ms, range58–119ms; status401 unauthenticated. Fetch used credentials:omit, cache:no-store and consumed response body.

The SPA also issued its ordinary initial unauthenticated session probe on each navigation; the timed API series above is separate. These401 timings measure access rejection, **not** opportunity query speed. No search/filter/pagination/detail production timing is available without an authorized authenticated session. Local fixture measurements are reported separately.

## Concrete bottleneck: static resources refetch even on warm navigation

All12 samples transferred963,681B of recorded subresources. JavaScript422,484B + CSS101,750B and Inter350,460B + Sora49,240B dominate. Warm loads still transfer the same files. HEAD requests offering gzip/br return no Content-Encoding and Cache-Control:no-store for fingerprinted JS/CSS (headers retained). Resource Timing encoded/decoded sizes agree, supporting uncompressed delivery. Build gzip estimates are JS122.08kB/CSS17.55kB, showing a concrete opportunity to reduce about385kB per load for those two files alone. This is a measured delivery inefficiency, not evidence that all users see slow pages. Warm timing improvement reflects reused process/connections and timing variation rather than effective asset-cache reuse.

Recommendation: review actual edge/Caddy/nginx configuration and enable gzip/Brotli and long-lived immutable caching only for public fingerprinted assets. Keep private API/auth responses and HTML appropriately noncached. Consider supported font subsetting and avoiding full app/header resources on the public sign-in path after profiling. Repository deploy/nginx.conf:17-19 lacks explicit compression/cache policy, but this audit cannot attribute live no-store to that file: the actual edge configuration was unavailable. No changes applied.

Evidence: performance-public.json, performance-public.cjs, perf-js-headers.txt, perf-css-headers.txt; all under /workspace/audit-evidence/.

Normal browser verification: `/workspace/audit-evidence/browser-delivery-headers.json` captures actual GET request Accept-Encoding `gzip, deflate, br, zstd` and200 JS/CSS responses with no Content-Encoding, full body lengths and no-store. No header override/interception was used. Managed proxy effects cannot be ruled out; responsible origin/edge layer remains unverified.
