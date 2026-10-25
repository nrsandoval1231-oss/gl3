# Intelligence Sprint 1: operator guide and delivery boundary

This extends the existing GridLens application, canonical company identities,
buying-chain evidence/corrections, PostgreSQL jobs, and power schedule engine.
It does not create a second contact store or a dashboard. The owner authorized
local staging and a reviewable PR, not production writes, paid activation, merge,
or deployment. Commercial P0 acceptance remains open.

## Local imports

Run from the repository root with the backend's locked environment. Excel support
adds openpyxl; CSV uses the standard library. Preview does not need a database.

```powershell
uv sync --project backend --locked --extra dev
uv run --project backend python scripts/import_intelligence.py preview `
  'C:\Users\nrsan\OneDrive\Desktop\Data Center\Cleanview.xlsx' `
  --output .artifacts/sprint1/preview.json
```

The four owner workbooks were found in `C:\Users\nrsan\OneDrive\Desktop\Data Center`:
Cleanview.xlsx, DC Leads.xlsx, texas dc leads.xlsx, and
US_Data_Center_Project_Tracker_August_2026.xlsx. They are read in place; neither
workbooks nor original private rows belong in Git. Reports with raw values must
also stay ignored. A future contact workbook/CSV can use the same pipeline;
25,000 synthetic rows are exercised by the parser and PostgreSQL staging tests.

Review worksheet detection, original headers, mapped columns, row kinds, errors,
and exact/probable duplicate groups. Summary and guide sheets remain retained
metadata, not projects. Developer and Owner are distinct parties; the supplied
`config/import-mappings/project-tracker.json` explicitly selects Developer for the
import's company assertion while retaining Owner and all other original columns.
It does not establish who controls procurement. Capacity units/ranges and unknown
placeholders are handled conservatively; campus/IT capacity never becomes
temporary construction or commissioning demand. A completion date is not a
required-power date.

Stage only into a separately restored loopback database with a staging/test name.
Set DATABASE_URL through the existing local environment, never in a tracked file.
Apply migrations there first from the backend directory with `uv run alembic upgrade head`.

```powershell
uv run --project backend python scripts/import_intelligence.py stage `
  'C:\Users\nrsan\OneDrive\Desktop\Data Center\US_Data_Center_Project_Tracker_August_2026.xlsx' `
  --mapping config/import-mappings/project-tracker.json `
  --expected-database-name sprint1_staging --actor local-operator `
  --output .artifacts/sprint1/staging-report.json
uv run --project backend python scripts/import_intelligence.py history `
  --expected-database-name sprint1_staging --output .artifacts/sprint1/history.json
uv run --project backend python scripts/import_intelligence.py rollback `
  --batch-id '<batch UUID from report>' --expected-database-name sprint1_staging `
  --output .artifacts/sprint1/rollback.json
```

Original rows, normalized assertions, matching reasons and import events persist.
Rollback deactivates a batch while preserving its source/history. Same-file replay
does not recreate rows. Truncated previews cannot be staged. Reports contain
bounded row samples; complete originals are in external_import_rows. Company
matches require corroborating identity signals, and project matches require a
corroborating site or evidenced company relation. Ambiguity, invalid data and
unmatched records are visible. Canonical facts/qualification are never overwritten
by an import. A staged assertion is not a newly admitted sales opportunity.

## Research, contacts and power

The existing `company_contact_discovery` worker remains the executor. Planning is
deterministic, ranks a bounded rotating company cohort, persists its scan cursor,
and reuses company research across projects. Changed source/project/need inputs
and stale evidence are distinct scheduling reasons. Existing leases, fences,
timeouts, checkpoints, retry limits, source-version checks, and paid call ledger
remain authoritative. Imported assertions never count as verified contacts.

Direct public HTML/document retrieval is the first available adapter. The existing
Python adapter bounds bytes, text, pages, redirects, DNS/SSRF exposure, subprocess
wall time and contact-page fanout. Access restrictions are terminal. Existing
retained evidence and completed jobs supply reuse. Firecrawl remains the existing
optional governed adapter, with no new activation or credits authorized here.
Self-hosted Firecrawl was not present/configured and was not installed. Playwright
remains useful for UI validation; it is not added as a server crawler dependency.
Government/utility and company sources continue through existing ingestion and
public-document adapters. No autonomous outreach occurs.

Apollo is not a required dependency and has not been activated; a new authorized
Apollo connector is not implemented by this candidate. Existing Jev/OpenAI
integration settings are preserved. Neither provider was invoked in validation.
The research planner uses heuristics, not calibrated match probabilities or
predicted sales values. No new research framework or infrastructure is introduced.

The existing contacts endpoint now adds clearly separated imported assertions.
GET `/api/companies/{id}/graph` exposes current, evidence-backed identity aliases,
project roles and relationship assertions. Relationship assertion/correction
helpers require retained version-bound evidence and attribution. The UI uses the
generated graph contract inside the existing contact panel, with desktop/mobile
states and source links. It does not redesign navigation or brand assets.

POST `/api/contact-assertions/{claim_id}/corrections` supports suppression,
replacement and retraction with expected-version, idempotency and same-origin
checks. Existing canonical buying-chain corrections remain the history. Source-free
operator contact reports stay unverified; source-backed replacements require
literal current evidence. Inferred emails and DNS/MX never establish a verified
mailbox. Independently verified mailbox state is explicitly UNKNOWN_UNSUPPORTED:
this candidate does not pretend the existing ledger supplies that authority.

GET `/api/projects/{id}/power-enrichment` projects exact accepted project/need/site
schedules through the existing power engine. It preserves unknown supply, ranges,
phase boundaries, provenance and estimate/hypothesis labels. It changes no tiers.
Rental value arithmetic is available only with an explicit sourced rate in the
domain API; no default rate or valuation is invented. Fuel availability stays
unknown unless an authoritative future integration provides it.

## Deployment and rollback

Do not deploy this sprint automatically. Before an owner-authorized deployment,
bind the final reviewed commit, passing CI, dependency audit, backup/restore
receipt and target schema; independently approve the real-data reconciliation and
any provider budget. Apply migrations 0042 (imports), 0043 (relationships), and
0044 (planner cursor) on a restored copy before considering production.
These are additive tables/nullable state; production data was not migrated here.

Keep the worker's existing discovery setting disabled until separately authorized.
No scheduler/provider configuration change is part of release installation.
The old application does not need the new import/relationship tables; prefer an
application rollback with forward schema retained so appended evidence/history
survive. Stop/reconcile in-flight fenced jobs before changing worker versions.
Revert application images/config to the recorded prior release and rebuild derived
browse state through the existing operator procedure. Do not restore a whole
production DB or downgrade/delete history as an automatic rollback action.
Schema downgrade is for disposable rehearsal only after confirming new tables
contain no needed records; it removes this sprint's tables/state.

## Remaining acceptance

Real import counts, benchmark results and exact test/review outcomes are in
`docs/validation/intelligence-sprint1/REPORT.md`. Source import is working, while
promotion of unmatched workbook rows into independently supported canonical
projects is deliberately not automatic. No workbook row by itself demonstrates
an open rental-power requirement. Low company/contact coverage, independent
identity accuracy labels, mailbox deliverability, buying authority, and real
commercial outcomes remain open. These gaps prevent a production-readiness or
full Sprint 1 completion claim.
