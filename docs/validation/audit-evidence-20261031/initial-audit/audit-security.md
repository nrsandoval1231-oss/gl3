# Security, dependencies and operations scoped audit — 2026-10-30

Audited current-main snapshot `/workspace/gl3-audit-main`, supplied/pinned by coordinator to `593cfd516d82a12b66558f53b975ad6c2b711517`. Initial inspection of saved d54646c was superseded; findings below rechecked on current snapshot. No code or deployment changes, credential inspection/changes, production database access, provider execution, migrations, ingestion or login attempts. Read AGENTS, canonical product/UI/architecture/checkpoint/finish instructions and maintained operations guides. No `.agents` directory exists in snapshot. Latest canon is six-layer Autonomous Power Demand Intelligence; legacy 300 kW and qualification compatibility is not target product identity.

## Confirmed findings

### P3 / low — maintained recovery/deployment documentation gives contradictory operational truth

References: `docs/operations/runtime-configuration.md:41`, `docs/operations/runtime-recovery.md:3`, `docs/operations/local-restore-drill.md:74`, `deploy/README.md:3` and `deploy/README.md:7` versus `docs/operations/README.md:20` and `.agent/CURRENT_STATE.md:7-11`.

Reproduction: follow documentation map to runtime configuration/recovery and read statements that approved startup wrapper, production restore/rollback commands and secret assembly are UNKNOWN and production is on hold; then follow operations authority which says protected wrapper was verified, and checkpoint which records fresh backup/isolated restore plus same-data rollback in progress. These are maintained entry points rather than clearly isolated archive reports. The historical October 20 observation is appropriately dated, but accompanying present-tense UNKNOWN/hold statements contradict later maintained authority.

Impact: an incident responder cannot distinguish a missing recovery procedure from a dated evidence limit, and can choose alternate preparation or repeat discovery unnecessarily. This audit does not claim the production mechanism is unsafe; fresh operational verification remains unavailable.

Recommended fix: retain dated receipts as history, replace present-tense stale unknown/hold assertions with explicit links to authoritative versioned operational runbook and latest completed release/rollback state. Update checkpoint after completion; never infer deployment from merged main.

### P3 / low hardening gap — publicly served app HTML has no anti-framing policy

References: `deploy/nginx.conf:1-20`, specifically static location `:17-19`; live raw response `/workspace/security-audit-evidence/live-headers.txt`, captured 2026-10-30 23:12:33 UTC, HTTP 200. Neither Content-Security-Policy with frame-ancestors nor X-Frame-Options was present; index HTML contains no CSP meta (which cannot enforce frame-ancestors anyway). Repository nginx config sets neither.

Reproduction: `curl --dump-header headers.txt --output index.html https://app.grid-lens.com/`; inspect response headers. This validates absent header defense, not a working authenticated clickjacking exploit. Cross-origin iframe browser reproduction was delegated to coordinator and was not performed by this reviewer. Strict SameSite session cookies reduce authenticated cross-site framing exposure. No mutation API exploit established.

Impact: sign-in/public app shell can be embedded by an unrelated origin absent an independent browser frame restriction; avoid presenting this as demonstrated data access or credential theft.

Recommended fix: explicitly deny framing via CSP `frame-ancestors 'none'` (or intended same-origin policy), optionally X-Frame-Options for legacy support, then browser-test permitted workflows. A general CSP should be tested against app asset/connect requirements separately.

## Fresh dependency checks

- `npm audit --prefix web --json` on current snapshot: exit 0; 0 advisories at all severities. Artifact `security-audit-evidence/npm-audit-current.json`.
- `uv export --project backend --locked --extra dev --no-emit-project --format requirements-txt --output-file /workspace/security-audit-evidence/backend-requirements.txt`, followed by pinned `pip-audit==2.10.1 -r ... --disable-pip --no-deps --format json`: exit 0, 47 dependency entries, 0 vulnerabilities. Artifact `security-audit-evidence/backend-audit.json`.
- `pip-audit==2.10.1 -r tools/brand/requirements.txt --format json`: exit 0, 13 dependency entries, 0 vulnerabilities. Artifact `security-audit-evidence/brand-audit.json`.
- All tool/cache directories redirected to `/tmp`; initial default-cache failures were read-only-filesystem errors, subsequently resolved with cache overrides. No approval denial. These advisory audits do not scan running OS/container images or guarantee absence of vulnerabilities.

## Auth/privacy/migrations inspected; no confirmed bypass found in scoped inspection

- `backend/src/gridlens/security.py:96-120,128-141`: cryptographically random opaque session, only digest persisted, expiry/revocation/credential fingerprint checked. `api/app.py:1375-1383`: HttpOnly, Secure-default, SameSite=Strict cookie. Authentication middleware dependencies present on inspected ordinary data and intelligence endpoints. Login rate limits use transaction advisory lock/global+client persisted buckets, source IP only trusted behind configured proxy CIDRs.
- `backend/src/gridlens/api/intelligence.py:577,650-677`: all four route groups require session. No public user mutation surface reintroduced in inspected paths.
- `intelligence/contact_suppressions.py`: expected-version/idempotency append services and fail-closed corrupted chains; `saved_browse.py:481-507` applies contact suppression before compact generation contact actions are stored. This inspection does not replace integration suppression tests or demonstrate all graph/projection privacy boundaries.
- Migrations reach 0049 in snapshot. `0045_contact_suppressions.py:49-57` refuses destructive downgrade when suppression history exists; 0048 similarly refuses loss of recovery receipts. Same-data image rollback must preserve forward-schema compatibility rather than assuming Alembic downgrade safe.
- `security.py:133-134` deletes long-expired sessions on valid-token checks, including authenticated GETs; only no-cookie public request was used here. Do not inject credentials into a strict no-production-writes audit without recognizing this implementation behavior.

## Coverage limits / blockers

No current deployed SHA/schema, running image inventory, actual host configuration, provider budgets/keys, backup cadence/off-host retention, alerts, restore or rollback outcome independently verified: no authorized host session available to this reviewer. Exact action would be read-only inspect release/image/schema receipts on production host; status unavailable, not denied or pending approval. Never infer deployed revision from HTML timestamp or source checkpoint. Public HTTP 200 proves app shell availability only, not authenticated live QA.

No container build/runtime CVE scan or restoration drill performed by this reviewer. Parent owns complete isolated backend/browser/test gates. Historical CI counts in checkpoint are not claimed as current test results. No high/critical security defect validated in this bounded review; this is not a comprehensive penetration-test pass.
