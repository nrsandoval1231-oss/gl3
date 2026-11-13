# Retained commercial source integration contract

This extends the existing ingestion, evidence, buying-chain and account projection paths. It introduces no customer table, global brand-name resolver, external research on navigation, or new runtime provider. It is a candidate contract; source acceptance and production readiness require separate receipts.

## Document and observation versions

The offline `retained-company-projects` adapter reads immutable public-source captures and derives project/site/activity relations. It does not read reference labels to construct application records. Ambiguous, undated, withdrawn or unsupported relations remain on HOLD. The source remains inactive in evaluation; this change does not activate a publisher.

Adapter schema v2 distinguishes three hashes:

- Full document version: canonical SHA-256 over URL, title, exact abstract, normalized publication date and its precision, **and the raw `publication_date_metadata` value**. The raw metadata is part of the retained record and identity-reconstruction context. A metadata correction therefore creates a new source version even when it normalizes to the same day or remains unparseable.
- Body hash: SHA-256 of exact UTF-8 abstract, independently checked against source-local spans. Span offsets are Unicode code-point positions, half-open; SEC identity proof offsets are explicitly UTF-8 byte positions instead.
- Observation semantic hash: the established ingestion normalization hash. Interpretation and assessment semantic hashes must match that observation; the assessment evidence hash must match the immutable full document version.

For a document assembled from retained artifacts, the adapter preserves the single unique raw `publication_date_metadata` string when the artifacts agree; when values conflict or are multiple, it stores `null` rather than choosing one. The publication-date reconstructor first accepts a valid ISO date or ISO datetime (including a `Z` timezone suffix) from that raw field, storing the resulting calendar day as `publication_date` with day precision. If the field is absent, conflicting, or invalid, reconstruction may still use a standalone date header or a recognizable geographic dateline in the first three abstract lines. A dateline must have a validated city/state prefix, a dash before the date, and no prose suffix other than an optional time. A date embedded in article prose is not a publication date. If neither source yields an exact day, the native document does not satisfy the adapter's exact-day admission boundary. `observation_date` remains capture time and is never a fallback publication or project-event date. Reconstructors must verify raw metadata equality, full record hash, and normalized date from retained body text before trusting a native record.

Capture/recheck time and scraper request IDs do not create new document versions. Observation dates describe collection, not a project milestone. Repeated unchanged retrieval must preserve canonical IDs and avoid duplicate changes.

## Publication boundaries

Native project aliases require exact retained text spans and a fresh interpreter reparse. Capacity and timeline claims require a local project subject and ownership of the particular amount/event predicate; another site's amount cannot inherit the selected site's sentence prefix. Operational and ready-for-service targets remain different from first electrical energization.

Organization claims enter the existing buying-chain reconciliation path. A publisher name alone does not establish project involvement. An explicit project developer/customer relation must bind the native site. Regulatory publisher identity requires already retrieved SEC legal-issuer, EIN and official-domain evidence; it does not turn a bare brand into a global alias. Legal-form conflicts, competing identities, suppression and retractions remain authoritative.

`project_customer` is additive. Data-center selection prefers existing owner roles, then an explicit project customer, then an operator. Oil-and-gas selection keeps its existing operator/owner order. Conflicting preferred identities remain unresolved. The historical exported `CUSTOMER_ROLES` subset remains compatible; account producers derive the complete current set from the central role order.

## Customer presentation and rollback

Saved browse generations carry the existing canonical company/project/need IDs. Cards read those generations without external research. Supported typed build capacity is separate from `PowerNeed.required_mw`; legacy estimated/inferred temporary-power values are excluded from primary cards. Versioned commissioning scenarios require documented test-load/concurrency inputs; campus MW alone yields Insufficient data.

Reported operational deadlines may provide a capped, explicitly labeled timing proxy in deterministic priority v2. They do not populate energization. Opportunity potential and evidence confidence remain separate.

No migration is introduced. Rollback restores the prior application source, keeps the retained source inactive, and rebuilds the saved generation through existing recovery controls. Existing evidence is retained; rollback must not delete canonical entities or erase history. Rebuilding any retained/production generation requires separate operational authorization.

## Bounded native revision continuity

A changed capacity quote can preserve an existing project-scoped company ID using only the immediately prior buying-chain run. The new claim must independently have current accepted source support, with the same project, exact raw organization spelling/legal form, role and relationship, and source URL. Prior evidence supplies identity lineage only; it never becomes current fact support. Conflicting current identities, correction records and privacy/suppression controls block continuation.

This fallback is restricted to the native retained-company-projects source contract. It inspects at most 64 immutable Evidence versions for the same Observation, refusing malformed/over-limit history or any adverse status version. That also catches an older withdrawn version replayed from the cache. A later reinstatement may therefore get a new provisional project-scoped identity; the system does not infer uninterrupted identity lineage. Strong or reviewed global identities and person links retain their existing proof rules. No new identity ledger or customer model is introduced.

Unsupported cross-excerpt phase inheritance and proximity-based project renaming are absent. The adapter retains the exact physical site descriptor and accepts an alias only through a source-bound naming relation. Status-only adverse records traverse existing rejected-observation handling so prior needs and memberships can be withdrawn without inventing capacity or demand.
