# GL3-024 — commercial Signals validation

Accepted locally on October 1, 2026, on `feat/gl3-023-city-permits`, extending draft PR15. Base: `118d4197d0091ae73564a38130b4e0c20e72509d`; fetched main remains `07c0886be65c90ec2ee88a30098fa4f57f925577`. No merge or deployment.

## Result

Cannabis Watch is removed. Official Massachusetts cultivation application events join ordinary Signals. Supported companies title cards, details, grouped records and saved pursuits, with applicant, owner/occupant and unverified listed-business roles preserved. The commercial minimum is inclusive 300 kW, with no maximum. Confirmed smaller work is excluded from active opportunity/pursuit views; raw evidence and history remain. The stated default retains unknown-size Signals with a readable unknown label. All 18 visible records currently have unknown activity-specific load; none proves 300 kW rental demand.

## Actual coverage and replay

| Source | Retained records | Retained Signals | Verified limits |
|---|---:|---:|---|
| Dallas | 89 | 5 | Linked June–August monthly commercial new-construction reports; issue dates June 1–August 28. Not all building/electrical permits. |
| El Paso | 67 | 0 | New-commercial ArcGIS dataset and bounded rolling window; actual lifecycle fields insufficient. Geocoding Status is not permit status. |
| Houston | 1,543 | 3 | Four weekly sold-permit workbooks; sale dates August 17–September 13. Two remain visible after the 35 kW job is excluded. Exact detail preserves Buyer separately from Owner/Occupant. |
| Massachusetts CCC | 452 | 11 | Whole-file cultivation applications; pending/reopened site-specific events within 120 days; snapshot at most 30 days old. No national or Texas cultivation coverage claim. |

Official [CCC catalog](https://masscannabiscontrol.com/open-data/data-catalog/) and [application export](https://masscannabiscontrol.com/resource/l_applications_all_details.json) were independently retrieved. HTTP200, 8,075,059 bytes, 1,989 total rows, 452 cultivator rows; snapshot updated September 22. SHA256 `a46b79846534783ab78121e4a2acfb6dc30c10207bfc7d7af153efa9c8d637f3` matched repeated fetches. Only whitelisted business, site and event fields persist; unrelated tax, financial and background fields do not. The source is self-reported and makes no completeness or timeliness guarantee. It proves an application event, not construction or rental demand.

All four actual ordinary-worker source runs succeeded. Unchanged replay added zero new/changed records and preserved core content digests. Two enrichment cycles over all 19 projects retained identical 16-claim/22-evidence digests. The raw Houston `26017927:Building Pmt:2026-09-01` 35 kW record and its evidence remain stored but absent from active opportunities and pursuit candidates. No Prospect or Lead is established.

## Real project/UI proof

- Rhythm of Life Cannabis LLC: application `MCN284034`, license identifier `MC284034`, 616 Douglas Street, Uxbridge. September 3 resubmission is distinct from the June 15 original filing. The applicant business, listed business email/phone, site, status and citations are visible; named person, buyer and authority remain unknown.
- MERICHEM TECHNOLOGIES LLC: Houston `26051624`, 8930 Gulf Fwy A. The title uses validated Owner/Occupant detail, separate from the listed Buyer.
- TRICORE BUILDERS INC: Dallas `2210211015_174492520-001`, 10851 Miller Road. LP Business Name remains role unverified; Robert Akins remains the separately listed applicant person.
- KEETER INVESTMENTS LLC: the existing Dallas pursuit at 2444 Fabens Road updates through ordinary refresh to the company-first, role-unverified title. Its ID, project links, saved notes and historical evidence are preserved. The refresh queue is empty after successful completion.

Company-name searches and detail views were inspected. Screenshots/accessibility captures are retained under `.agent/artifacts/GL3-024/ui`, including the corrected readable unknown-size label. All current Signals are in REVIEW because no adjudication was invented.

## Validation and review

Final manifest: `16710394699673efaa8d3b7efead4d103abfb9c61b92db827fd951b51a9a6b58` (300 files). Independent Sol PASS is in `.agent/artifacts/GL3-024/REVIEW.json`.

- Ruff and mypy: pass.
- Full backend pytest: 503 passed, one existing missing-probe skip.
- Clean migration, repeated migration and drift check: pass on a new isolated database.
- Frontend typecheck and production build: pass.
- Relevant desktop/mobile browser tests: 14 passed.
- Official ingestion replay, enrichment replay, admission/floor regressions, persisted pursuit refresh and diff check: pass.

Four unchanged browser cases require historical air/data-center/pursuit corpora absent from this isolated city database; they are explicitly excluded, not counted as passing. Validation ran locally, not through GitHub Actions. Failed attempts and prior review findings remain under the GL3-024 artifact directory. Repairs covered real field names, conservative numeric parsing, pursuit filtering, stale cached headings, legacy browser selectors and banner contrast. Final gate logs are under `validation-final`.

## Preservation and remaining limits

Task acceptance `gl3_024_accept` is a consistent clone of the prior city database; tests use `gl3_024_test`. The source builder used separate scratch/test databases and a separate worktree. Original edits, databases and credentials remain preserved. Task PostgreSQL/API/web use loopback ports 55423/8023/5193; worker auto-refresh is off.

Cultivation coverage is Massachusetts applications only. City source windows remain limited; there is no citywide electrical or national coverage claim, no data-center-specific example established by this corpus, and no proven rental requirement or buying authority. Cloud scheduling, operational launch and the parent Finish Contract remain open.

## Changed application, test and documentation files

- `README.md`
- `backend/src/gridlens/api/app.py`
- `backend/src/gridlens/domain/collection_watch.py`
- `backend/src/gridlens/domain/commercial_presentation.py`
- `backend/src/gridlens/domain/permit_interpretation.py`
- `backend/src/gridlens/domain/signal_admission.py`
- `backend/src/gridlens/ingestion/adapters/__init__.py`
- `backend/src/gridlens/ingestion/adapters/ma_cultivation.py`
- `backend/src/gridlens/ingestion/adapters/retained_permits.py`
- `backend/src/gridlens/ingestion/registry.py`
- `backend/src/gridlens/ingestion/service.py`
- `backend/src/gridlens/intelligence/buying_chain_extraction.py`
- `backend/src/gridlens/intelligence/pursuits.py`
- `backend/tests/integration/test_collection_only_ingestion.py`
- `backend/tests/integration/test_ma_cultivation_ingestion.py`
- `backend/tests/integration/test_pursuits.py`
- `backend/tests/unit/test_commercial_presentation.py`
- `backend/tests/unit/test_ma_cultivation.py`
- `backend/tests/unit/test_publisher_rss.py`
- `backend/tests/unit/test_pursuit_public.py`
- `config/sources/registry.v1.json`
- `docs/product/PRD.md`
- `docs/sources/coverage.md`
- `docs/sources/ma-ccc-cultivation-applications.md`
- `docs/validation/gl3-024-commercial-signals.md`
- `web/src/api/client.ts`
- `web/src/api/generated.ts`
- `web/src/api/openapi.json`
- `web/src/app/App.tsx`
- `web/src/features/opportunities/projectCards.ts`
- `web/src/styles/app.css`
- `web/tests/first_path.spec.ts`
- `web/tests/project_cards.spec.ts`

Governance, source receipts, screenshots, failed attempts and validation logs are retained separately under `.agent/artifacts/GL3-024`; prior GL3-023 delivery evidence is unchanged.
