# Opportunity intelligence projection and research

Status: implemented core extension; full October 21 directive and live acceptance remain incomplete. This is not production activation authority.

## Canonical ownership

`Project` identifies the physical work; `PowerNeed` identifies its scoped power activity. Current `BuyingChainClaim` and its evidence identify organizations, people, roles and contact methods associated with a project. The new aggregate references these identities without merging projects or inventing another customer store. Global cross-project company/person identity reconciliation remains a gap: a normalized name is not proof that two legal organizations are the same.

Immutable observations, interpretations, evidence and accepted operator fact versions remain the fact authorities. `domain/opportunity_intelligence.py` assembles presentation, never writes facts or assigns qualification. Its typed fields distinguish supported values, estimates, conflicting claims and unresolved research. Failed requests are not evidence that information is unavailable publicly. Completeness counts supported fields independently of qualification.

Current direct owner/operator claims identify the customer. Contractors remain buying-chain parties. Rental intermediaries are excluded from recommended contact paths. Employment alone does not establish project responsibility, and no relationship establishes temporary-power purchasing authority automatically. Call/email actions require a matching current public-contact source URL, exact retained passage and literal contact value. No guessed contact methods are generated.

## Reads and persistence

`CompanyIdentity` and `PersonIdentity` provide stable IDs while `BuyingChainClaim` remains the project-scoped source of names, roles, contacts and citations. Current supported claims receive unique project-scoped IDs without a name-based cross-project merge; person IDs require a current cited role or assignment. `IdentityIdentifier` records strong legal/company or official person identifiers with the exact buying-chain evidence version and reason. `BuyingChainIdentityLink` binds one claim to one identity with its own source version and reason; link corrections supersede the prior link and retain its history. Cross-project reconciliation requires the identifier literal in a relevant citation that remains current in `buying_chain_view`. Direct corrections require an attributed reviewer. Names, employer, and contact strings cannot create a cross-project link. Current buying-chain projections expose the IDs through one batched read, without merging contacts across projects. Identity does not grant project responsibility or purchasing authority.

- Existing authenticated `GET /api/opportunities/needs/{id}` includes `intelligence_card`.
- Authenticated `GET /api/opportunity-intelligence?need_ids=...` accepts 1–20 UUIDs and returns one aggregate per current eligible need. Inactive/missing needs are omitted; this is not a historical endpoint.
- Reads reuse canonical projection and bulk buying-chain retrieval, bulk project identity lookup and a ranked latest-30-question window per need. Existing evidence preflight and complete response byte bounds apply after expansion.
- Reads perform no acquisition, provider invocation or job scheduling. Existing consistent-read transactions keep the multi-query aggregate coherent.
- Exact commercial evaluations persist the aggregate in existing versioned Pursuit snapshots. An omitted optional projection cannot erase an unchanged saved aggregate. Current detail is reconstructed from persisted canonical inputs so stale snapshots do not restore retracted facts. Not every legacy/grouped snapshot carries an aggregate; no bulk backfill is triggered.
- Additive owner/display provenance is excluded from the established semantic research fingerprint. The legacy operator-reference authority and hashes are preserved. Evidence and fact changes still invalidate canonical evaluations.

## Execution

The existing same-origin authenticated autonomous-research POST accepts `complete_intelligence: true`. It evaluates the exact selected need, including targets outside the first 50 commercial cards. The card exposes this action only when autonomous execution is enabled. Completion is asynchronous; the response reports queued work and the card offers status refresh.

Expanded planning includes actionable records and prioritizes conflicts, end-user identity, scoped power need/load/timing, buyer path, supply and duration. It reuses existing durable research questions/jobs, leases, idempotency, source routing, freshness, bounded retries and daily caps. Existing acquisition source permissions and logical-call spending controls remain authoritative. Up to two active questions per pursuit remains the limit. No new provider or orchestration runtime is introduced.

`OPPORTUNITY_ENRICHMENT_ENABLED` defaults to false. When enabled, existing automatic scheduling uses the expanded planner; it does not independently enable research, a provider, or a positive budget. Explicit `complete_intelligence` requests also use the expanded planner without changing global activation. Existing non-enriched scheduling preserves its ordering. Optional suitability questions are not automatically scheduled because there is no complete canonical resolver for them yet.

Jev remains bounded advisory judgment in existing task contracts. OpenAI naming/brief research remains under its existing contracts and ledger. This change does not add a new autonomous general-purpose synthesis agent or authorize calls. Successful research status accepts the receipt's post-acquisition evidence fingerprint; failed/stale attempts retain their receipts and prior verified findings.

## Power semantics

Only the current qualified canonical gap enters the normalized aggregate. Both source-backed range and accepted operator scalar shapes are supported. Code checks finite, nonnegative values, ordered ranges and residual arithmetic:

`gap = [max(0, demand_min − supply_max), max(0, demand_max − supply_min)]`

The gap retains its existing scoped start/duration, qualification version and source/fact identifiers. Conflicts suppress a single accepted value. Current source-reported activity load can populate a descriptive field but cannot establish temporary-generation demand or promote qualification. Facility demand never substitutes for scoped power demand; unknown supply never becomes zero.

This is interval-scoped normalization of the existing calculation, not a new phased demand/supply schedule solver. Facility total demand, fuel, voltage and load-profile completion, richer procurement/milestone synthesis, and structured person/contact corrections still need implementation and acceptance. Identity persistence is now present, while broad identity evaluation and any card-level identity aggregation remain outside this bounded slice.

## Interface

The existing Pursuit Workspace Overview renders the aggregate with supported identity/power facts, buying chain, next action, grouped research gaps and expandable evidence. Existing tabs, fact correction/review and Back navigation remain available. New contact actions are real verified links. No new navigation, decorative map or imagery is introduced. Existing title/brief status requests remain separate; eliminating that waterfall is a further optimization.
