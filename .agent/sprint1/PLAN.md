# Intelligence Sprint 1

Owner directive 2026-10-25: implement immediately, six concurrent Luna builders,
independent Astra review, draft PR; no production writes, paid calls, or deployment.
Base origin/main 3ce9e8a68a6b988d1d8bfd8597e150f19ae36498.

## Architecture and shared interfaces

Extend existing company identities, project memberships, buying-chain claims,
corrections, contacts, research and fenced PostgreSQL jobs. No new dashboard.
Imports preserve immutable original rows and unverified assertions separately;
they never directly award qualification or overwrite accepted evidence.
Strong company/project matching requires independent signals; ambiguous matches
remain proposals and are reversible. Current territory is TX/OK/NM physical sites.

Parser interface in ingestion/workbook_import.py:
`read_workbook(path, *, column_mapping=None) -> ImportPreview`;
Pydantic ImportRow fields sheet, row_number, raw(dict), normalized(dict), errors(list[str]);
ImportPreview fields filename, content_hash, rows(list[ImportRow]), report(dict).
Normalized keys: company_name, domain, project_name, address, city, state,
external_id, contact_name, title, email, phone, profile_url, demand_mw,
supply_mw, required_date, duration_months. Missing values remain missing.

Persistence interface intelligence/external_imports.py:
`stage_import(session, preview, *, actor) -> dict`;
`rollback_import(session, batch_id, *, actor) -> dict`;
`import_history(session, *, limit=50) -> list[dict]`.
Only isolated staging DB execution this sprint. Row provenance includes file hash,
sheet, row number, original values. No automatic promotion of imported contacts.

Ownership:
A parser/fixtures: ingestion/workbook_import.py, tests/unit/test_workbook_import.py,
backend dependency/lock if openpyxl needed.
B persistence/matching: external_imports.py, models.py, migration0042, own tests.
C research/planner: enrichment_planner.py, company_contact_discovery.py and own tests.
D graph/contact safety: company_graph.py, contact_assertions.py, migration0043,
contact_models.py and own tests. D coordinates model metadata registration with B.
E power: power_enrichment.py and own tests, existing domain integration if needed.
F UI: CompanyContacts.tsx, CompanyGraph.tsx, client.ts, own browser tests.
Sol owns API routes, CLI, generated contracts, integration, benchmark and docs.
Builders share one isolated worktree with exclusive files; no overlapping writes.

## Acceptance and next steps

- [x] Workbook/CSV preview: multisheet, mapping, mixed rows, errors, dedupe, bounds.
- [x] Staging history/reversal and explainable multi-signal matches; no weak overwrite.
- [x] Canonical graph and contact correction/suppression with verification distinctions.
- [x] Ranked incremental research using durable existing jobs and company reuse.
- [x] Evidence-backed power ranges; unknown supply never zero.
- [x] Existing UI integration and desktop/mobile verification.
- [x] Real four-workbook isolated import/report, 25 existing-project benchmark if a
      safe retained local snapshot exists; unavailable measures explicitly UNKNOWN.
- [ ] Focused then integrated gates, migration/drift, independent Astra review/repair.
- [ ] Deployment/rollback instructions and reviewable draft PR; no deploy/merge.

Runtime advertises gpt-6.1-sol/high, gpt-6-luna/low, gpt-6-astra/high; eight slots.
Tokens and aggregate elapsed acceptance time UNKNOWN until measured.

## Review repair checkpoint

Initial source6132ce1 received independent Astra REQUEST_CHANGES for seven material
findings. Repairs cover site/domain contradiction vetoes, canonical source validator
reuse, source/identity relationship bindings and unverified manual relationship
status, reversible retraction, supply estimate labels, globally unique positional
raw columns, and direct-job digest/refresh preservation. Regression checks pass.
Final full tests, independent re-review and PR/CI receipts remain separate gates.

Commercial acceptance stays open: unmatched workbook reconciliation, accuracy
labels, direct buyer methods/authority, independent mailbox verification, confirmed
power assumptions and sales outcomes. No production release action authorized.
