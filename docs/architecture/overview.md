# Architecture — initial ingestion slice

The application follows the PRD's single-backend boundary. React/TypeScript calls FastAPI; the separate Python worker reads durable PostgreSQL jobs. SQLAlchemy owns transactions and Alembic versions the schema. A scheduler only enqueues due sources; the worker remains the authoritative ingestion executor.

Collection is independent of LLM services. Adapters retrieve bounded public source windows and parse source records. The ingestion service retains evidence and interpretation state before applying deterministic Signal interpretation. Failed interpretation remains visible and retryable. No LLM or paid acquisition service is required for the initial path.

Project identity initially uses publisher/source stable record identity. Distinct records remain separate rather than merging on similar names. This deliberately under-matches cross-publication identity until stronger evidence exists. Alternate JSON/PDF representations of an explicitly identical government document share underlying identity and must not be counted as independent corroboration or a new opportunity.

`domain/qualification.py` owns Signal admission; ingestion never awards a Prospect or Lead. A specific development event can justify a question about power, while MW, dates, supply suitability and buying responsibility remain unknown. Generic policy, directories and raw facility listings do not suffice. Prior evidence is preserved on revisions; negative changes can remove a need from the active list without deleting its history.

Authentication is server-side. The local private-workspace login uses a password hash and signed expiring HttpOnly session cookie. Browser writes check their origin against explicit trusted origins. Production requires TLS, secure cookies, secret configuration and deployment validation; local operation does not certify that deployment. Frontend contract types are generated from OpenAPI response schemas.

Runtime health separates attempts from verified success and publication age. Unchanged retrieval updates check time without changing the source publication date or material-change digest. Jobs use PostgreSQL locking, lease ownership and fencing; final proof must cover stale workers as well as per-record persistence.

Deterministic interpretation reruns on identical source content so a corrected rule can reclassify an earlier mistake without deleting evidence. A same-content correction is recorded as reclassified, not a fabricated source cancellation. Repeating unchanged rules produces no material event. Worker fence reads refresh cached ORM state under the database lock, including for a long-lived worker session.

Current local topology: PostgreSQL 127.0.0.1:55439, API 127.0.0.1:8000, React development server 127.0.0.1:5173. The unrelated existing database on 5432 is untouched. Permitted source samples and runtime exports remain under ignored `.artifacts/`; this is local storage, not a managed object-store deployment.

Unbuilt/ungated capabilities remain explicit: cloud PC-off scheduling, broad launch coverage, bounded model research, Prospect/Lead evidence gates, commercial feedback workflow and seven-day reliability. See delivery/milestones.md and the Finish Contract rather than inferring those capabilities from folder names.

## GL3-017 buying chain

Merged as PR #7. An explicit authenticated project-detail action performs one
bounded enrichment pass in the API process. It starts with accepted evidence for
the existing physical Project ID; Chicago can read its exact official contractor
row, and a user can supply up to four additional public evidence URLs.
Conservative extraction retains separate organization involvement, current
person/role, and personal project relationship claims. No general search
crawler, new queue, agent framework, registry source, or qualification write is
introduced.

Project-bound immutable evidence and claim versions preserve source quotes and
history. A small run record reports partial/unknown outcomes. The UI separates
DIRECT, ROLE_SUPPORTED and UNKNOWN and keeps the evidence inspectable. See the
[contract and validation limits](../validation/gl3-017-buying-chain.md). Saved-cloud
browser checks in that record passed; direct live retrieval was not proven there.

## GL3-018 admission and acquisition

Merged as PR #8. `domain/signal_admission.py` owns standalone admission policy
`signal-admission-v1`. Persistence and API reads both apply it. Official permits,
project-specific official utility filings, and explicit temporary-power
solicitations can admit a Signal. News is supplemental to one supported physical
project. Planning and entitlement stay research context. `power_needs.admission_basis`
retains the policy version, origin, reason, source, and evidence hash. Migration
`0009_signal_admission` closes unsupported active needs and keeps their prior
active state, tier, projects, links, observations, and evidence.

Source-specific acquisition stays in the existing Chicago and Georgia adapters.
Chicago includes Express Electrical Work. Georgia reads Title V, SIP, and
synthetic-minor narratives and drafts and keeps bounded page-cited generator
excerpts. The registry remains 13 sources. No utility-docket, procurement, or
RRC connector was added. See
[admission and acquisition](../sources/gl3-018-admission-and-acquisition.md).
