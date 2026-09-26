Build GridLens in https://github.com/nrsandoval1231-oss/gl3.

Take ownership of implementation and validation. Deliver working software and retained evidence, not another planning-only handoff.

STARTING STATE

The inspected main commit is 07b05b3e7de5b4a67ad9ae8aebd1cd918ba4b128. It contains product requirements, folder ownership guidance, an ingestion strategy, frozen UI references, and approved brand assets. It does not yet contain a runnable application.

Recheck the current branch, remote, SHA, dirty work, and repository instructions before changing anything. Preserve existing work. If the repository has advanced, reconcile against actual implementation rather than rebuilding completed work.

Read:
- AGENTS.md
- docs/product/PRD.md — authoritative 42 requirements and milestone gates
- docs/sources/ingestion-strategy.md
- docs/decisions.md
- docs/design/UI_CANON.md
- docs/design/BRAND_ASSETS.md
- Applicable folder READMEs
- Existing .agent state, if present

This is a clean-sheet implementation. Do not import code, schemas, migrations, pipelines, tests, or architecture from previous GridLens repositories. Do not import their qualification rules.

OBJECTIVE

Implement the first usable ingestion-backed application slice:

Real public source → durable job → preserved observation and evidence → supported project/power need → authenticated Signal browse/detail → visible source health.

Begin with one complete source path, then exercise the same architecture with one structured source, one web publication, and one document source. These three source types are an initial implementation checkpoint, not satisfaction of the full launch gates.

EXECUTION

Follow the owner’s engineering control system. Initialize minimal .agent state, dependency-aware Work Graph, Finish Contract, and bounded packets if absent. Run the single required opening Tribunal for this new implementation, then proceed. Use one Luna builder for the initial dependent path; introduce parallel work only when ownership and dependencies are genuinely independent. Use Sol for architecture and required independent review; reserve Astra for exceptional escalation.

Keep governance compact. Continue through safe READY work without routine permission questions. Do not stop after scaffolding, writing documents, or obtaining a green test count.

BUILD SEQUENCE

1. Validate initial sources.
Create docs/sources/coverage.md from actual access checks and inspected samples. Record publisher, endpoint, geography, industries, source family, useful events, power relevance, access/retention limits, cadence, pagination, collection windows, stable identifiers, readiness evidence, and limitations.

Distinguish proposed, access-tested, validated, disabled, and active sources. Discover records without supplying project names. A source’s accessibility alone does not establish useful discovery.

2. Establish the minimum runnable foundation.
Use the specified React/TypeScript frontend, Python/FastAPI backend, separate worker from the same Python package, PostgreSQL, SQLAlchemy, Alembic, and durable PostgreSQL jobs.

Provide pinned dependencies, migrations, safe environment examples, local startup commands, and meaningful CI gates. Generate frontend API types from the backend contract. Enforce server-side authentication on private data and actions.

3. Complete one real ingestion path.
Implement registry validation, retrieval, parsing, evidence persistence, checkpoints, bounded retries, leases, idempotency, and recovery. Preserve source identity, content hash, retrieval time, publication/event dates when available, permitted artifacts or excerpts, and extraction location.

Keep collection independent of model availability. Preserve collected evidence when interpretation cannot finish.

4. Expose useful results.
Apply the PRD Signal gate: dated linked evidence, identifiable project/company/site, and a concrete reason to investigate a power need. Raw facility records and generic company entries must not automatically become opportunities.

Keep projects separate from their individual power needs. Preserve uncertain identity and missing facts. Provide a specific next question or action.

Implement authenticated Signal browse/detail and source health using persisted backend data. Prospects and Leads may have honest empty states until their gates are implemented and supported.

5. Extend and verify.
Exercise structured, web, and document sources through the same adapter boundary. Add coverage only when retrieval, parsing, persistence, replay, changed-record handling, and visible failure are proven.

PRODUCT AND DESIGN BOUNDARIES

Follow the frozen navy UI and existing brand assets. Use the horizontal lockup once in the top-left header. Preserve browse context when returning from detail. Support responsive layout, keyboard access, loading, empty, error, unknown, and conflicting states.

Reference-screen projects and numbers are fictional; never seed them as live discoveries.

Never:
- Treat campus operating MW as construction or commissioning demand.
- Promote unknown utility availability into evidence of insufficient supply.
- Fabricate MW, dates, contacts, buyers, confidence probabilities, or discoveries.
- Replace publication dates with retrieval dates.
- Count unchanged replay as a new discovery or Today change.
- Hide parser failures behind HTTP success.
- Introduce n8n as a second authoritative ingestion system.
- Use Cleanview’s paid API.

Keep qualification and arithmetic deterministic and backend-owned.

REQUIRED PROOF

Validate the exact final candidate with applicable lint, types, build, migration, integration, and browser checks. Demonstrate:
- Real retrieval through persistence and authenticated presentation.
- Identical replay creates no duplicate observations, projects, needs, or digest changes.
- Changed records retain prior evidence.
- Login pages, malformed responses, and unexpected empty parses fail visibly.
- Legitimately unchanged sources retain original publication dates.
- Interrupted jobs recover safely.
- Similar names at different locations do not cause unsupported merges.
- Unknown supply does not cause promotion.
- Unauthenticated API access is rejected.
- Source failures preserve the last accepted data.

Retain permitted real-source samples separately from synthetic/adversarial fixtures. Report actual discoveries and limitations.

AUTHORITY AND COMPLETION

Prepare cloud deployment and scheduling configuration, but do not push, merge, deploy, purchase services, create accounts, communicate externally, or use paid services without existing explicit authorization. Continue independent local work while external prerequisites remain unresolved.

A local scheduler test does not complete Milestone A: its exit gate requires a real scheduled cloud source check while the owner’s PC is off. Do not mark that milestone complete prematurely.

Keep the full launch gates open: 12 independent feeds across five families, two national structured sources, three industries, the 30-record quality review, seven scheduled daily cycles and reliability requirements, restore proof, and Nick-reviewed real Lead evidence.

Deliver:
- A runnable application and exact startup instructions.
- Source coverage and real ingestion evidence.
- Exact candidate identity, changed files, validation commands/results, and runtime proof.
- Updated milestone and .agent handoff artifacts.
- Required independent review tied to the candidate.
- A concise account of what works, what remains unverified, and the next READY packet.

Complete and validate the first ingestion-backed slice before expanding. Then continue through authorized READY packets in milestone order; never substitute a scaffold, screenshot, or test count for a working product.