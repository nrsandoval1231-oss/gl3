# Contacts lane validation — November 8, 2026

Scope: bounded company contact discovery, planner ranking, and Apollo activation boundary. Synthetic fixtures and a disposable test database only; no live providers, credentials, retained/production data, or deployments were used.

## Implementation

- Company planning is keyed by canonical `CompanyIdentity`; active current memberships and current linked claims for multiple eligible projects are collected into one company candidate. The existing persistence test creates two projects with separate active needs and source-versioned membership evidence, then confirms one durable job for that company, replay deduplication, a new job after a material need change, and 30-day refresh.
- An adversarial same-name case assigns distinct RRC operator numbers `000001` and `000002`; it expects two target company IDs and distinct research digests. The planner does not join on display name.
- Existing public retrieval and append-only evidence/claim handling remain in place. Public contacts are projected through the current suppression ledger. The added company-level suppression replay regression confirms a suppressed account remains contact-empty after planning and completed job replay. Existing alias suppression refresh coverage is included in the run below.
- Contact priority no longer rewards project/need volume, facility MW, dates, or ubiquitous unknown supply/duration fields. Missing buyer-method/direct-method flags are the only contact utility inputs. Explicit MW token parsing uses `Decimal` for descriptive output only; facility MW is not commercial priority for contact work. Deep fetch remains subject to the existing high threshold and fixed URL bounds.
- `public_site_policy.py` requires an exact HTTPS hostname with a current non-revoked human terms-review reference and explicit `direct` or `firecrawl` mode. It does not certify terms or infer permission for subdomains. No host approvals are shipped. Direct acquisition first fetches `/robots.txt` without redirects or environment proxies, using a pinned public IP, one shared deadline, and a 65,536-byte cap; the target GET reuses that same IP. The robots parser supports exact user-agent groups and path-prefix `Allow`/`Disallow`; unsupported directives, wildcard/end-anchor patterns, escaped/ambiguous target paths, redirects, access errors, and oversized robots files fail closed. A 404/410 robots response means no file and is allowed. Callbacks reserve each robots and target request before I/O; the contact job persists a maximum of 14 such requests. Buying-chain jobs persist a separate maximum of eight request reservations under the fenced lease and preserve them across retry/reclaim.
- Apollo seam is deliberately disabled and makes no request. It reports `activation_blocked: apollo_access_and_license_not_verified`; there is no live connector in this scope.

## Apollo official documentation checked read-only

Current official documentation as observed November 8, 2026:

- [People Enrichment](https://docs.apollo.io/reference/people-enrichment): `POST /api/v1/people/match`, API-key endpoint access or OAuth `people_match`; 1–9 credits/person depending on returned data and options.
- [API Pricing and Credits](https://docs.apollo.io/docs/api-pricing): endpoint and returned-data dependent usage; plans may differ, including legacy plan variation.
- [Organization Enrichment](https://docs.apollo.io/reference/organization-enrichment): `GET /api/v1/organizations/enrich`; 1 credit per organization.
- [People API Search](https://docs.apollo.io/reference/people-api-search): `POST /api/v1/mixed_people/api_search`; listed at 0 credits and does not return email addresses or phone numbers; endpoint has a 50,000-result display limit.
- [Authentication](https://docs.apollo.io/reference/authentication): Apollo users use an API key sent in `x-api-key`; docs recommend calling `auth/health` to verify a key.

The public docs do not establish this workspace's account, key, endpoint permissions, plan, credit balance, or commercial/data-use authorization. No account/key was inspected, no endpoint was called, and no prices/rights/entitlements are assumed. Public official-site research remains available independently of Apollo.

## Checks

Commands executed from this worktree with `PYTHONPATH=backend/src;backend/tests/integration`, test database `phase2_contacts_test`, application URL `phase2_contacts_app_test`, and synthetic test-only auth settings:

```powershell
python -m pytest -q backend/tests/unit/test_enrichment_planner.py backend/tests/unit/test_apollo_contacts.py backend/tests/integration/test_enrichment_planner_persistence.py backend/tests/integration/test_account_privacy_refresh.py backend/tests/integration/test_buying_chain.py -k 'contact or company_reuse or same_name_companies or alias_contact_suppressions'
```

Result: **37 passed, 118 deselected**, with one Starlette/httpx deprecation warning. This includes company planner persistence, changed-input digests, active dedupe, stale refresh, conflicting same-name identities, suppression replay, alias suppression after refresh, and public contact worker regressions. No network provider executed; existing public contact tests use deterministic fixture retrieval. Ruff passed on the changed planner, Apollo seam, unit tests, and persistence integration test.

Additional focused policy/planner run:

```powershell
python -m pytest -q backend/tests/unit/test_public_site_policy.py backend/tests/unit/test_enrichment_planner.py backend/tests/unit/test_apollo_contacts.py
```

Result: **26 passed** across policy, planner, and Apollo unit files. It covers exact-host and mode checks, expiry/revocation/duplicate and malformed approvals, subdomain/wildcard rejection, credential-bearing URL refusal, robots longest-prefix/tie handling, user-agent group precedence, unsupported syntax and ambiguous paths, denied hosts before network/callback, no redirects, status refusals, alternating-DNS simulation proving same-IP reuse between robots and target retrieval, shared-deadline reuse, private pinned-IP rejection, and request-budget exhaustion before target GET. The tests use synthetic approvals and MockTransport; no external request was made.

The persisted request-budget integration test passed across an actual fenced-job reclaim: prior reservations survived a new fence, and the next call was rejected at the cap. The company-job suite additionally verifies one canonical identity over two source-versioned projects, separate same-name identities under conflicting stable identifiers, changed-input digest/replay behavior, suppression after completed replay, and alias suppression after refresh.

## Limits

The fixtures establish deterministic repository behavior, not broad real-world entity coverage, Apollo access, outbound contact deliverability, buyer authority, or production operation. Cache behavior is covered only through existing durable logical-call/replay contracts; no standalone cache or process-restart experiment was performed in this lane. The last-good-facts and paid-search outage contracts remain owned by shared acquisition/acceptance tests.
