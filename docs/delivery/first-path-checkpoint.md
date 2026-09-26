# First structured-source runtime checkpoint

Controller observed a real public Federal Register retrieval through worker, PostgreSQL, authenticated API, React browse and detail on 2026-09-25. This is an intermediate runtime checkpoint; final candidate validation and independent review are still required after the adapter extension.

- Actual runtime window: 30-day broad EIS NOTICE query, 77 observations persisted. The earlier 90-day access probe contained147 records; it is not the application's runtime count.
- One accepted Signal: Federal Register2026-18765, Roca Honda Mine Project, published2026-09-14. Required MW, activity start/duration and suitable supply remain unknown.
- Controller replay: two successful jobs; final counts77 observations,77 evidence versions,1 project,1 need,1 change. Source status Checked—No Change;0 new/changed;0 parse failures.
- Unauthenticated `/api/opportunities`, `/api/health`, `/api/changes`:401. Direct login200.
- Initial browser login failed403 due to proxy Origin handling. Builder repaired configured trusted origins; real browser login and protected reads then200. Attacker-origin rejection regression added.
- Browser browse/detail shows original publication date. No page errors. Browser Back returns to list.390px page has no horizontal document overflow; source-health internal row clipping was separately flagged for repair.
- Controller backend check at this intermediate state:11 tests passed. Frontend first check found stale generated schema; it must be regenerated and final gates rerun.
- Local snapshot restore succeeded; see `../operations/local-recovery-proof.md`.

Retained raw runtime proof (ignored): `.artifacts/first-path-api-proof.json`, `first-path-replay-proof.json`, `first-path-browse.png`, `first-path-detail.png`, `first-path-mobile.png`. These contain real application observations. Synthetic mutation tests remain separate.

No cloud deployment, PC-off schedule, seven daily cycles, launch breadth or Lead acceptance is claimed.
