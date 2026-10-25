# C2: asynchronous company contact discovery

- Repository/worktree: `gl3-contact-p0-20261024`; PR122 branch `fix/contact-intelligence-recovery`.
- Base: `93437131a6b0fa84300732426a5698c0bb99100b`. Full lane, one Luna primary builder.
- Objective: automatic, source-verified discovery on canonical company IDs via
  existing fenced jobs, append-only buying-chain evidence and company contact API.
- Allowed: new narrow `intelligence/company_contact_discovery.py`, optional
  `ingestion/adapters/company_contact_public.py`; narrow changes to
  `intelligence/buying_chain.py`, `intelligence/company_contacts.py`,
  `jobs/worker.py`, `settings.py`, existing acquisition/provider integration,
  related backend unit/integration tests. Optional API additive status only.
- Excluded: migrations/new contact store, canonical PRD, identity name merges,
  qualification/Power Gap, external side effects, credentials, unrelated UI.
- Dependencies: Sol approved reuse of current Job, BuyingChainEvidence/Claim/Run,
  identity links and correction-aware current owner/developer memberships.
- Invariants: customer stays owner/developer for data centers; contractors remain
  associated chain. Search results are URL hints; only literal retrieved source
  evidence verifies contact methods/person/role. No inferred emails, authority,
  phone type or deliverability. A company website cannot prove project ownership.
- Waterfall: reuse fresh current contacts; resolve exact self-identified official
  site from accepted evidence/candidate search URLs; official contact/team pages;
  publicly evidenced relevant professionals; reliable public evidence; Research
  Required. Allow bounded candidate URL input for benchmark, with no contact values.
- Acquisition: native public HTTPS first, existing SSRF/access/deadline guard.
  Firecrawl search/map/extraction only through existing configured authorization,
  budgets/logical-call accounting. Disabled/missing key returns explicit unresolved.
  No unauthenticated alternative search provider or bypass of access restrictions.
- Enqueue after company identity without awaiting network; failures never block
  ingestion. Prioritize Lead, high-value Prospect, Prospect, Signal; cap batches.
- Checkpoint: canonical company/anchor/version/policy/refresh epoch, checked URLs,
  attempts/failures/reasons/metrics; idempotent enqueue/replay; freshness TTL;
  bounded retries, concurrency and request budgets; interrupted paid effect UNKNOWN.
- Preserve previous claims/methods and operator retractions on all partial/failed
  runs. Latest BuyingChainRun is a full merged snapshot, never contact-only loss.
- Acceptance: targeted unit tests and PostgreSQL integration for exact canonical
  sharing, literal evidence/provenance, stale/missing/ambiguous domains, named role
  vs authority, dedupe/replay, unchanged and partial refresh, retraction,
  eligible-only async admission, lease/fence/interruption/provider failure.
- Validation: `uv run ruff check src tests`; `uv run ruff format --check src tests`;
  `uv run mypy src`; focused pytest. Controller performs final gates and review.
- Repair budget: two materially different attempts, checkpoint unresolved effects.
- Handoff: `.agent/artifacts/CONTACT-P0/C2-COMPLETION.json` with exact files,
  commands/exits, limitations, UTC start/finish and timings if measured. Tokens and
  model config identity UNKNOWN unless available. Builder does not certify/merge.

## Architecture clarification and specialist assignment

Initial Luna inspection found membership-only accounts would not receive contacts
through a newly created project-scoped identity. Sol approved a source-bound
bridge: `basis=current_membership` on the existing identity link, requiring the
same project and literal `project_organization` citation whose BuyingChainEvidence
retained_evidence_id is the exact current accepted membership Evidence ID. Check
each evidence's own hash domain, current membership/correction state and ambiguity;
no company-name merge. Invalidate the link's projection on membership retraction.
`identity_reconciliation.py` is additionally allowed. Terra is assigned this
bounded integration problem because Luna returned material uncertainty before edits.

One independent Luna may implement C3 scripts only, using the posted callable
contract, while Terra owns backend files. Integration and final validation remain
serialized. No workers share mutable DB targets: Terra uses contact_p0_test;
controller/benchmark uses contact_p0_benchmark. No code commit by workers.

## Evidence-driven reconstruction and final scope

After two incomplete integration repairs, Sol reconstructed PRD28/29 and owned
the material canonical integration. This is a hard integration escalation, not
routine controller implementation; a different fresh Sol must independently
review the final candidate. C2 additionally owns existing
`buying_chain_extraction.py`, `identity_reconciliation.py`,
`ingestion/adapters/pursuit_acquisition.py` and their focused tests. The final
policy is company-contact-discovery-v9. Its handoff records real-layout false
positive correction, valid-anchor selection, stable replay fingerprints, a
savepoint proving SQL queue failure isolation, and hard deadline propagation.

The controller restored failed pilots separately and used a fresh
contact_p0_reviewed database for final coverage. It is separate from both the
contact_p0_test destructive fixture database and contact_p0_app browser regression
database. The twenty-company manifest has IDs and URL hints only. Source hashes,
per-company terminal persistence and original-row fingerprints are required.
Luna also owns the existing CompanyContacts panel and its focused browser test:
verified methods first, role/evidence dates, source links and unknown authority;
no new navigation, palette, layout or design system. All application edits are
frozen before final gates and fresh independent review.
