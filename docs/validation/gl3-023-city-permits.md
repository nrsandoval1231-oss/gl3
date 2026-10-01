# GL3-023 local city-permit validation

Branch: `feat/gl3-023-city-permits`. Base: `07c0886be65c90ec2ee88a30098fa4f57f925577`, fetched current main with PR13 and PR14 merged. GL3-022 was reserved. This slice uses a fresh worktree and separate PostgreSQL 18.6 cluster on loopback port 55423; original checkout, two pre-existing untracked files, databases and credentials are preserved. The acceptance database is `gl3_023_accept`; integration and clean-migration databases are separate.

## Actual official-source results

| Source | Verified bounded coverage on October 1, 2026 | Retained permits | Signals |
|---|---|---:|---:|
| Dallas | June–August published monthly commercial new-construction rows; issue dates June 1–August 28 | 89 unique IDs from 95 rows | 5 |
| El Paso | NewCommercial GIS layer; rolling 90-day query, actual issue dates August 4–September 29 | 67 unique IDs from 68 features | 0 |
| Houston | Four latest linked weekly sold-permit workbooks; sale dates August 17–September 13 | 1,543 | 3 |

No citywide electrical coverage or complete historical archive is claimed. El Paso access, counts and pagination work from this machine; its short descriptions do not establish supported project activity. Its retained records are visible through the existing ingestion filter. A readable source is not a qualified Lead.

Dallas examples: warehouse at 10851 Miller Rd, hospital at 6455 Forest Park Rd, light manufacturing at 2444 Fabens Rd, laboratory at 9432 Walnut St, and water-treatment plant at 6900 McCallum Blvd. Houston examples: laboratory conversion `26051624` at 8930 Gulf Fwy A, generator replacement `26017927` at 8439 2/3 Market St D, and warehouse crane foundation `26056841` at 16741 Blue Ridge Commerce Dr. No data-center-specific project was established in this bounded corpus.

The authenticated UI was inspected for Dallas warehouse and Houston generator/laboratory records. Dallas shows TRICORE BUILDERS INC separately from applicant Robert Akins, with the relationship UNKNOWN. Houston exact detail preserves its Buyer, Owner/Occupant, address and phone as distinct facts, with buyer entity type and authority UNKNOWN. Generator capacity in source text is not promoted into rental load. Screenshots are retained in the slice artifacts. Eight physical projects remain Signals; none is a Prospect or Lead. They appear under REVIEW because unavailable adjudication is not SHOW.

## Validation evidence

The first complete controller run caught three overbroad warehouse-admission regressions (475 tests passed, three failed, one existing skip). The failed output is preserved; the tests were not weakened. A bounded repair excluded ordinary restaurant conversion and generic tenant improvements while retaining concrete supported construction. Final gate results and exact candidate identity are recorded in the linked receipts below.

Independent official-source replay checked all three ordinary worker paths and retained identical observation, evidence, project, need and change digests. Twice-run project enrichment retained five buying-chain claims and eleven buying-chain evidence rows without duplicate identities or claims. Mutable observation timestamps are excluded only where the existing repository replay policy explicitly excludes them. See `REPLAY.json` for exact digests and policy.

Nine relevant existing browser tests ran against this three-city database, including the added El Paso filter assertion. Four existing tests requiring historical Chicago/Georgia/Austin/RRC acceptance data were not run; they remain unchanged. Full backend pytest is mandatory and separate from this browser-corpus limit. The one backend skip is the existing missing local North Carolina access-probe fixture.

- [Exact candidate manifest](../../.agent/artifacts/GL3-023/candidate_manifest.json)
- [Controller gate commands, UTC times and exit codes](../../.agent/artifacts/GL3-023/VALIDATION.json)
- [Independent ingestion and enrichment replay](../../.agent/artifacts/GL3-023/REPLAY.json)
- [Official-source research](../../.agent/artifacts/GL3-023/SOURCE_RESEARCH.json)
- [Independent review](../../.agent/artifacts/GL3-023/REVIEW.json)
- [Coverage and reproducibility](../sources/gl3-023-city-permits.md)

Local acceptance does not establish deployment, national completeness, scheduled operation, commissioning demand, fuel fit, buying authority or the parent launch Finish Contract. Delivery is a focused draft PR only; merge and deployment are excluded.

## Final controller result

Final frozen application/test/document manifest: `429f84b2de761564191abaf6bfa2d5c589fb47f18bb20e900ab09b91ec486c0e`. All required local checks passed: Ruff, mypy, full pytest **481 passed / one existing skip**, frontend typecheck/build, new empty database migrations, repeated migration, Alembic drift check, nine relevant browser tests, and diff whitespace check. The manifest was recomputed after validation and remained identical.

The ordinary queued pursuit-research job succeeded. Readback proved one Dallas manufacturing pursuit (COM-NEW-26-000129) with no research errors. This proves the eligible city path through the existing queue; it does not claim a Houston or El Paso pursuit was selected. [Pursuit runtime receipt](../../.agent/artifacts/GL3-023/PURSUIT_RUNTIME.json).

Supplemental Dallas investigation found the public DallasNow Accela entry point readable (HTTP 200), along with the official Online Records and forms pages (HTTP 200). The latter lists Backup Generator Permit, Temporary Utilities Electric/Gas and Electrical Permit Checklist forms, which are application documents rather than issued-record feeds. The official legacy project-number search route returned `ConnectTimeout` from this machine. No login, CAPTCHA or security control was bypassed; interactive record/report execution remains unverified, not universally unavailable. Exact URLs and response hashes are in [DALLAS_ALTERNATIVES.json](../../.agent/artifacts/GL3-023/DALLAS_ALTERNATIVES.json).

Independent Sol review: **PASS** for the final manifest. The earlier returned-type FIX is retained as REVIEW-r1.json; acquisition and retained readback now both reject absent or conflicting permit type. No application or explanatory-source-document edits followed acceptance. Governance and validation receipts are bookkeeping outside the application manifest.

## Changed files

- `.agent/CURRENT_STATE.md`
- `.agent/WORK_GRAPH.md`
- `.agent/packets/GL3-023.md`
- `README.md`
- `backend/src/gridlens/domain/permit_interpretation.py`
- `backend/src/gridlens/domain/pursuits.py`
- `backend/src/gridlens/domain/signal_admission.py`
- `backend/src/gridlens/ingestion/adapters/__init__.py`
- `backend/src/gridlens/ingestion/adapters/dallas_permits.py`
- `backend/src/gridlens/ingestion/adapters/el_paso_permits.py`
- `backend/src/gridlens/ingestion/adapters/houston_permit_details.py`
- `backend/src/gridlens/ingestion/adapters/houston_permits.py`
- `backend/src/gridlens/ingestion/adapters/retained_permits.py`
- `backend/src/gridlens/ingestion/registry.py`
- `backend/src/gridlens/ingestion/service.py`
- `backend/src/gridlens/intelligence/buying_chain.py`
- `backend/src/gridlens/intelligence/buying_chain_extraction.py`
- `backend/src/gridlens/intelligence/pursuits.py`
- `backend/src/gridlens/jobs/worker.py`
- `backend/tests/integration/test_buying_chain.py`
- `backend/tests/integration/test_ingestion.py`
- `backend/tests/unit/test_city_permits.py`
- `backend/tests/unit/test_retained_permits.py`
- `config/sources/registry.v1.json`
- `docs/sources/coverage.md`
- `docs/sources/gl3-023-city-permits.md`
- `docs/validation/gl3-023-city-permits.md`
- `web/src/app/App.tsx`
- `web/tests/first_path.spec.ts`
- `.agent/artifacts/GL3-023/`: source, replay, validation, review, timing and UI evidence; archived prior state and failed attempts.
