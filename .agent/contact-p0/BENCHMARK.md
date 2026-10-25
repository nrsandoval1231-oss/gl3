# C3: isolated benchmark and resumable backfill tooling

Base/worktree/authority are as in BUILD.md. Owner: Luna; full lane.
Allowed: `scripts/company_contact_enrichment.py`, focused script tests in a new
`backend/tests/unit/test_company_contact_tools.py`; no backend runtime/UI edits.
No shared database mutations: benchmark writes only exact loopback isolated
`contact_p0_benchmark`; test script fixtures only pure unit functions.

Contract provided by C2:
`discover_company_contacts(session, company_identity_id: UUID, *, candidate_urls=(), now=None)`;
existing durable Job kind `company_contact_discovery`, checkpoint has
company_identity_id and candidate_urls. Coordinate the final enqueue API with Terra.

Implement read-only inventory using `_current_customer_claims`, current eligible
active needs, stable company IDs and explicit distinct-company denominators by
tier and industry. Backfill priority Lead, high-value Prospect (rank), Prospect,
Signal; stable cursor or manifest ensures resumability. Include actual company
names, tiers/industries/projects, known contact coverage, unresolved-project count.
Default read-only transaction; refuse non-loopback execution in benchmark mode and
require exact expected database name for any apply. No migrations or live mutation.

Benchmark inputs contain production company IDs and URL hints only, never contact
values. Run the actual async worker path if practical; otherwise report callable
path distinctly. Persist checkpoint after each company, resume skips completed
companies, validate snapshot/manifest identity, include failures and elapsed,
counts of phone/email/named roles/direct/generic/none and provider cost UNKNOWN
unless measured. No false 0-dollar claim for unmeasured paid calls. Verify replay
does not duplicate claims/evidence/contact methods and refresh preserves methods.

Metrics distinguish named relevant professional from actual source-confirmed
project decision-maker, company contact method from direct buyer contact, URL-only
route from usable email/phone, and missing named buyer vs no usable method.
Handoff `.agent/artifacts/CONTACT-P0/C3-COMPLETION.json`, commands/exits/times;
two materially distinct repair attempts. Do not certify/push/merge/deploy.

Final controller execution used a fresh contact_p0_final restore. Earlier failed
pilot/benchmark databases and receipts remain isolated. C3 validation includes
both same-checkpoint resume and fresh-checkpoint re-enqueue, with identical job
IDs and unchanged company/claim/evidence counts. C4 scope is the existing
CompanyContacts.tsx panel and customer-accounts.spec.ts; builder verification is
separate from real authenticated API/browser proof over the production clone.
