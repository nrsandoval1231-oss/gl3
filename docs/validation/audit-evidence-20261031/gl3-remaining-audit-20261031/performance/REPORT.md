# Current public performance and release-readiness check

Observed **2026-10-31 18:09–18:11 UTC**, with six additional public asset/HTML transport reads recorded in `transport-samples-n3.json` afterward. Read-only public checks from the saved cloud environment; no credentials, login submissions, account/session setup, provider calls, production writes, admin routes, source triggers, source edits, builds or test-suite runs.

## Result

The public HTTPS application is reachable: `GET https://app.grid-lens.com/` returned **HTTP200** with the GridLens HTML shell. This is public availability, not authenticated application acceptance. `GET /api/auth/session` returned200 with `{"authenticated":false}`; `GET /api/health` and known project-list route `GET /api/opportunities/projects?limit=1` both returned401 Authentication required. Those401s establish these anonymous boundaries, not backend health beyond serving the auth response.

Installed native Chromium was launched using the environment's explicit inherited HTTP(S) proxy, with TLS verification enabled. Public navigation failed with **`net::ERR_CERT_AUTHORITY_INVALID`**. Attempts were bounded to three per desktop/mobile viewport (six total), including the initial cold navigation and attempted reloads; none produced a valid sign-in render. The subsequent reload errors/timeout are consequences of failed initial navigation, not application rendering speed evidence. TLS validation was not disabled and the proxy was not bypassed. The browser failure is a cloud-browser trust/path blocker, not proof of an origin certificate defect or outage: curl on the configured trusted path successfully verified TLS and fetched200.

**Unavailable measurements:** valid cold/warm browser timings, actual login visibility, LCP, CLS, observed long tasks/TBT equivalent, screenshots, browser console and loaded-resource behavior. The JSON preserves exact failures. No screenshot of an authenticated workspace or sign-in success is claimed.

No already-authorized persisted browser session/profile was supplied or exposed by available native cloud tools. The HTTP session result is unauthenticated. Authenticated search/filter/count/pagination/detail/contact performance requires a secure handoff to an already-authorized browser session and working platform CA trust. No new login/session or credential handoff was attempted. A public shell or sign-in page is not authenticated QA.

## Bounded HTTP timing fallback

All requests used `curl --compressed --max-time30` with normal curl-supported Accept-Encoding negotiation, inherited proxy and verified TLS. HTML, JS and CSS each have three fresh-process curl samples: the original sample plus exactly two additional GETs. Known auth-boundary endpoints remain n=1 with no additional API reads. These are not browser cold/warm-cache tests, viewport-specific or mobile-device measurements, field percentiles, or browser page-load times.

|Read|n|HTTP|Median TTFB (range)|Median total (range)|Response bytes|
|---|---:|---:|---:|---:|---:|
|HTML `/`|3|200|237.63ms (114.89–361.69)|237.75ms (115.02–361.81)|725|
|JavaScript `/assets/index-Bq5LuTF9.js`|3|200|155.67ms (84.19–329.40)|225.18ms (184.78–467.07)|422,484|
|CSS `/assets/index-DfvzdE1O.css`|3|200|231.03ms (113.22–263.29)|338.10ms (117.56–355.16)|101,750|
|`/api/auth/session`|1|200|176.19ms|176.31ms|23|
|`/api/health` unauthenticated|1|401|183.22ms|183.88ms|36|
|`/api/opportunities/projects?limit=1` unauthenticated|1|401|126.80ms|126.89ms|36|

The observed path has `server:envoy`, `via:1.1 Caddy` and `x-envoy-upstream-service-time`; curl remoteIP is the cloud proxy. Timings include the cloud proxy, connection/TLS and transit; they cannot isolate origin execution or ordinary-user geography. Every first/repeated request used a fresh curl process/connection; repeated requests do not establish browser cache warmth, viewport or mobile performance. Original sample logs/bodies are preserved. The additional bounded work was exactly six GETs (two per HTML/JS/CSS), with no further browser attempts or protected API reads. HTML and both hashed assets were delivered with `cache-control:no-store`; no `content-encoding` or `vary:Accept-Encoding` appeared in the received headers, and reported transfer bytes equal decoded file bytes. This is **as delivered through this cloud path**, not a conclusion about origin compression or direct-user response behavior. Immutable hashed assets delivered as no-store are a candidate repeat-load cost to verify on an origin-authenticated/nonintercepting observation path; do not claim compression caused a production speed defect from these samples alone.

## Frontend revision distinction

The existing local candidate build is `/workspace/gl3-phase1/web/dist`; no rebuild was run. Local HEAD `78591b308aa829a25157bf3310133ed069434d3b` and merged main prefix`00026c75` both resolve to tree **`125b7dc0ee61a890b1dffff40f3b2891df3be9c1`** in the repository. This establishes source-tree equivalence, not deployment.

- Current public HTML references **`index-Bq5LuTF9.js`**; fetched decoded JS SHA256 **`431066f1f3e872506e9bad693ee5476ad046060cd01bf092a96dfbdbff3c23db`**,422,484bytes.
- Existing candidate dist references **`index-CGjQb7DI.js`**; local JS SHA256 **`7b961176a946db29c5a2aed27e4a97a4238f6ab50dda59cc42913da4a293e4a0`**,423,022bytes.
- JS bytes and filename **do not match**. Thus the public frontend does not match this existing candidate frontend build; current main's frontend changes are not established as deployed.
- CSS name and bytes **match**: `index-DfvzdE1O.css`, SHA256 **`49c75fd2a7fc5900bed849f20b376bbb85cf0e20279569964f89e3c62c2f9ffa`**,101,750bytes. Shared CSS does not establish a full release match.

The deployed backend revision/schema, live workers, source freshness, backup/restore and production release readiness remain unverified by this public surface. No control-plane state is treated as application-health or deployment acceptance. Main remains held as instructed.

## Evidence and blockers

Artifacts in this directory: `public.html`, `public-headers.txt`, `public-curl.json`, `public-browser.mjs/.json/.log`, `http-probes.py/.json/.log`, per-resource response bodies and filtered headers, `asset-comparison.json`, `curl-version.txt`, and aggregate `transport-samples-n3.json` with all nine resource samples and summary statistics; additional sample bodies/headers retain their sample numbers.

- **Failed known outcome:** native Chromium public navigation to `https://app.grid-lens.com/`; platform path certificate validation failed before app rendering. No bypass or silent retry beyond the bounded samples.
- **Blocked coverage:** authenticated workflows/performance; no authorized persisted browser handoff is available and public session isfalse. No login submission or new authentication session was created.
- **Not denied:** public curl reads succeeded. No approval-denied operation was retried or bypassed.
- **Not pending/uncertain:** no mutations, deployments or login actions were attempted; no production action has an uncertain execution outcome.
