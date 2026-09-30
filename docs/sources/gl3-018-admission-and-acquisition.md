# GL3-018: authoritative admission and deeper acquisition

The owner-approved rule supersedes earlier source-matrix statements that news or
planning alone creates a Signal. News is supplemental evidence. A qualifying
physical-project permit can admit a Signal with unknown MW. Project-specific
first-party utility filings and explicit temporary-power solicitations are also
approved evidence origins. Source authority alone does not establish a power
need, suitable supply, or a Prospect/Lead. Official planning, entitlement,
economic-development announcements and environmental-review notices remain
research context until qualifying evidence exists; standalone planning admission
is an unresolved owner decision.

Evidence and previous interpretations remain retained. New admission is enforced
when needs are persisted and when opportunities are read. Legacy unsupported
needs are deactivated by the additive admission migration, without deleting
projects, evidence, links, or earlier tier/fact values. Supplemental news requires
one supported physical-project/activity match; ambiguous sites and phases remain
UNKNOWN. News is never relabeled as a permit or linked to a fabricated permit.

## Acquisition scope

No new state or nominal source was added. The registry remains 13 sources.

- **Chicago**: the existing official Socrata route now includes Express Permit
  Program rows whose `work_type` is exactly `Electrical Work`, alongside existing
  construction/renovation rows. Retained fields include scope, case, parcel,
  contractor names and source roles. Row citations select the exact official ID.
  The unchanged bounds are a 30-day issue window, two-day modification overlap,
  1,000 rows/page, 20 pages, 2 MB/response and 20 MB/run. Small/residential and
  routine electrical work can be collected without passing commercial admission.
  An explicit temporary-service amperage is not converted into MW.
- **Georgia**: the existing official EPD/Knack listing includes draft Title V,
  SIP and synthetic-minor permits. The historical stable source ID is retained.
  Narratives and draft permits are retrieved with existing identity/site checks.
  The current live listing leaves every application-link field empty; this slice
  cannot claim full-application retrieval. Public notices remain unfetched links.
  Full PDF text is scanned for bounded generator/engine technical excerpts with
  exact page/URL attribution. Each PDF retains at most 24 technical excerpts of
  600 characters, in addition to the existing 16,000-character general excerpts.
  Omitted technical excerpt counts are explicit. The original PDF hash is retained
  alongside the extraction-version hash, so revised extraction preserves earlier
  persisted excerpts. Source power quantities use decimal kW/1,000 conversion;
  regulatory quantities are labeled separately and no quantity is automatically
  classified as an equipment rating. Per-unit versus
  aggregate and historical versus current scope remain unassigned unless the
  verbatim source states them. No count × rating or rental-demand total is inferred.

Georgia bounds remain 5 listing pages/500 records, 2 MB/list response, 50 PDFs,
4 MB/PDF, 200 pages/PDF, 5,000 PDF pages/run and 30 MB/run. Requests remain
bounded and redirects disabled. Buying-chain SSRF/DNS/IP/TLS controls are unchanged.

This slice does not introduce a utility docket, procurement, commissioning,
RRC, or national air-permit connector. SAM credentials were neither requested
nor configured. Procurement and utility admission policy is testable but their
live ingestion remains a coverage gap.

## Commercial interpretation

Installed/proposed standby equipment is not temporary rental demand. Campus
operating load, equipment nameplate and construction/commissioning requirements
remain distinct. A missing energization date is UNKNOWN, not proof of a utility
supply gap. Prospect/Lead qualification still requires supported activity-specific
demand and unsuitable/unavailable supply; no score automatically promotes a tier.

Source failures and bounded partial work must be visible. Enabled status,
completed/failed/empty outcomes, coverage limits, and missing document/excerpt
counts belong in source health. Real-run results and exact reviewed records are
recorded separately in `docs/validation/gl3-018-validation.md`.
