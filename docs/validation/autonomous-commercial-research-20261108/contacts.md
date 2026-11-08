# Contacts lane validation — November 8, 2026

Scope: bounded company contact discovery, planner ranking, and Apollo activation boundary. Synthetic fixtures and a disposable test database only; no live providers, credentials, retained/production data, or deployments were used.

## Implementation

- Company planning is keyed by canonical `CompanyIdentity`; active current memberships and current linked claims for multiple eligible projects are collected into one company candidate. The existing persistence test creates two projects with separate active needs and source-versioned membership evidence, then confirms one durable job for that company, replay deduplication, a new job after a material need change, and 30-day refresh.
- An adversarial same-name case assigns distinct RRC operator numbers `000001` and `000002`; it expects two target company IDs and distinct research digests. The planner does not join on display name.
- Existing public retrieval and append-only evidence/claim handling remain in place. Public contacts are projected through the current suppression ledger. The added company-level suppression replay regression confirms a suppressed account remains contact-empty after planning and completed job replay. Existing alias suppression refresh coverage is included in the run below.
- Contact priority no longer rewards project/need volume, facility MW, dates, or ubiquitous unknown supply/duration fields. Missing buyer-method/direct-method flags are the only contact utility inputs. Explicit MW token parsing uses `Decimal` for descriptive output only; facility MW is not commercial priority for contact work. Deep fetch remains subject to the existing high threshold and fixed URL bounds.
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

Result: **37 passed, 104 deselected**, with one Starlette/httpx deprecation warning. This includes company planner persistence, changed-input digests, active dedupe, stale refresh, conflicting same-name identities, suppression replay, alias suppression after refresh, and public contact worker regressions. No network provider executed; existing public contact tests use deterministic fixture retrieval. Ruff passed on the changed planner, Apollo seam, unit tests, and persistence integration test.

## Limits

The fixtures establish deterministic repository behavior, not broad real-world entity coverage, Apollo access, outbound contact deliverability, buyer authority, or production operation. Cache behavior is covered only through existing durable logical-call/replay contracts; no standalone cache or process-restart experiment was performed in this lane. The last-good-facts and paid-search outage contracts remain owned by shared acquisition/acceptance tests.
