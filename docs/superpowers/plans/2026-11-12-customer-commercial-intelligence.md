# Customer commercial intelligence implementation plan

> **For agentic workers:** use bounded subagent-driven implementation with independent Astra integration review. The owner supplied execution authority and review boundaries; routine decisions proceed without additional approval.

**Goal:** Extend existing canonical customer accounts with supported capacity, precise timelines, commissioning scenarios and clear commercial actions.

**Architecture:** Keep canonical company/project/need identities. Extract versioned deterministic facts through existing ingestion and research acceptance, retain immutable package receipts, and freeze publication inputs in existing browse generations. Read grouped customer intelligence in bounded batches; rank before pagination.

**Tech stack:** Existing FastAPI, SQLAlchemy/PostgreSQL, Python Decimal, React/TypeScript and Playwright. No production deployment or provider activation.

**Spec:** [Audited architecture and contract](../../engineering/customer-commercial-intelligence-20261112.md).

## Global constraints

- Preserve identity, source provenance, privacy/suppression, need-scoped Pursuits and current authentication.
- No universal campus percentage, invented precision or unsupported contact methods.
- No new identity model, live research during navigation, or retained/production database writes.
- Keep typed capacity bases separate and abstain on unsupported overlaps.
- Preserve indexed matching and generation policy/recovery fences.

## Review focus

- Multiple phases and duplicate announcements must not inflate capacity.
- Source revisions and weaker contradictory articles must not erase verified facts.
- Quarter/year and operational dates must not become exact energization dates.
- Frozen-generation facts must remain coherent under privacy and identity changes.
- Ranking must apply to all matching accounts before LIMIT/OFFSET.

## Tasks

### 1. Audit and contract

- [x] Inspect main, merged PRs, PR189, migrations, source models and performance evidence.
- [x] Commit audit, fact contracts, gaps and historical evaluation baseline.
- [x] Obtain independent Astra architecture review and incorporate constraints.
- [ ] Publish controlled draft PR with explicit verification limitations.

### 2. Facts, aggregation and changes

**Files:** `domain/customer_intelligence.py`, `intelligence/customer_intelligence.py`, existing ingestion/research acceptance and saved-browse hooks, `customer_results.py`, focused unit/integration tests.

**Interfaces:** `extract_customer_facts(text, *, project_id, source) -> dict`; `resolve_customer_intelligence(projects, *, as_of) -> dict`; retained package adapter and frozen generation read.

- [ ] Write failing tests for typed capacity, overlap, weak evidence, source precision and abstention.
- [ ] Implement pure extraction/resolution, then verify those tests.
- [ ] Write integration tests for current source binding, immutable receipts and snapshot publication.
- [ ] Integrate batched generation hydration, account DTOs and pre-pagination priority.
- [ ] Extend existing material snapshots with short typed fields, semantic comparison and quiet normalization; test revisions/replay.
- [ ] Run identity, privacy, matching, source and generation regression tests; commit as a bounded PR.

### 3. Commissioning

**Files:** `domain/commissioning.py`, commissioning tests and model documentation.

**Interface:** `estimate_commissioning(inputs, *, config=None) -> dict`.

- [ ] Read engineering references and document applicability.
- [ ] Write failing tests for explicit equipment ratings, concurrency, sequence, scope overlap, configurable versioning and insufficient evidence.
- [ ] Implement Decimal peak test-load scenarios with all input references and limitations.
- [ ] Connect to customer details without equating a scenario to verified rental demand; verify and commit.

### 4. Customer experience

**Files:** existing header, ProjectResults, CompanyView, global search, API client and workspace styles; relevant browser tests.

- [ ] Reconcile selective PR189 components with current main authentication, stale labels and API contracts.
- [ ] Add customer commercial contract types and compact cards, progressive details, supported named contacts and precise dates.
- [ ] Verify search, back/reload, responsive layouts and Pursuits using existing real-backend journeys.
- [ ] Capture before/after screenshots at approved viewport sizes; independent visual review and bounded PR.

### 5. Commercial acceptance

**Files:** retained real-source evaluation fixtures/excerpts, reproducible runner/results, performance evidence and delivery record.

- [ ] Independently research and review 20 real organizations with primary sources and honest missingness.
- [ ] Run extraction separately from structured calculation checks; report precision, recall, missingness, coverage and limitations.
- [ ] Measure bounded queries and latency at representative volumes; compare indexed ingestion benchmarks.
- [ ] Run complete required CI, migration/drift, authentication, browser and generation recovery gates.
- [ ] Obtain independent exact-candidate Astra acceptance; retain unresolved findings and readiness limits. No merge of failing work and no production deployment.
