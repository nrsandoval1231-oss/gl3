# Remaining ingestion reliability audit — October 31

## Revision and restrictions

Audited exact requested main `00026c758ece2bc41eea88c478cbb0112f9e0de5` via clean `/workspace/gl3-phase1` HEAD `78591b308aa829a25157bf3310133ed069434d3b`. Both resolve to source tree **125b7dc0ee61a890b1dffff40f3b2891df3be9c1**. `git status --short` was empty. No source edits, jobs, ingestion/backfill, DB writes, external retrieval, production/provider calls or full suites were performed. Read AGENTS, relevant current product boundaries and recovery/source documentation; this work follows the existing cloud-runtime constraints. All outputs are outside checkout.

## Conclusion

**Two confirmed P2 reliability/coverage gaps; neither is a newly discovered parser regression or evidence of a missing production filing.** Both are already disclosed by the registry. Treat their implementation as explicitly scoped follow-on recovery features, not as proof the deployed source is broken. No P0/P1 defect was established in this scoped review.

### P2 — Flare discovery cannot recover an outage beyond three days or refresh later status changes

References:

- `config/sources/registry.v1.json:27-34`: daily collection, three-calendar-day submitted-date window, explicitly no historical backfill or older-filing status monitoring.
- `backend/src/gridlens/ingestion/adapters/rrc_flare_exceptions.py:282-283`: derives the window from **today**, not last successful acquisition.
- Same file `:314-317`: sends only those submitted-date filters.
- Same file `:187-191`: filing identity and mutable application status are retained, so status correction support exists when a row is actually reacquired.
- `backend/src/gridlens/ingestion/adapters/__init__.py:92-93`: ordinary dispatch does not supply a historical date/window.

**Reproduction, actually executed:** `reproduce.py` uses `httpx.MockTransport` exclusively and an official-shaped synthetic result built by existing repository fixture helpers. On October 1, filing 35964 with submittal October 1/Submitted is returned by the September 29–October 1 query. The mocked publisher changes that same filing to Approved by October 6. October 6 retrieval asks only October 4–6 and returns zero. Adding prior-success/checkpoint metadata still requests October 4–6 and returns zero. See `reproduction.json` for captured form dates and counts. This also demonstrates that a submission made during a longer outage and outside the current rolling window cannot be found by retrying the ordinary adapter.

**Business effect:** retained application status can remain older than the publisher; missed submissions are not automatically discovered once overlap expires. These applications do not establish physical flaring or electrical demand, so this is evidence/discovery freshness risk, not demonstrated lost qualified MW/revenue.

**Recommended bounded follow-on:** persist a source acquisition coverage cursor separate from schedule receipts; enqueue finite nonoverlapping missed-submittal windows with explicit bounds/checkpoints/retries. Add a separately budgeted retained-filing status lane, preserving immutable changes and source-derived IDs. Do not merely enlarge the three-day window: that never solves indefinite late status corrections. Acceptance cases should cover five-day outage, late Approved/Cancelled changes, zero-result interval completion, >500-row segmentation, restart replay and no duplicate observations. Until implemented, report both checked-current-window and unrecovered/unchecked historical coverage distinctly.

**Classification:** confirmed designed limitation / missing recovery feature. Registry disclosure is accurate. No actual production filing or outage was examined.

### P2 — Drilling acquisition advances to current/prior month without catching missed archive months

References:

- `config/sources/registry.v1.json:80-85`: current-month daily plus previous-month EOM only; explicitly warns about longer outages and missing older-month correction monitoring.
- `backend/src/gridlens/ingestion/adapters/rrc_drilling.py:508-522`: computes exactly one previous EOM and current `daf420.dat`; no acquisition coverage cursor or missed-archive loop.
- Same file `:160-169`: safe amendment consolidation uses lowest sequence, with latest same-sequence input preferred.
- `backend/src/gridlens/ingestion/service.py:3252-3294`: older sequence recurrences retain exact evidence without replacing newer current projection.

**Reproduction, actually executed:** the offline script replaces only the download boundary with a synthetic valid snapshot and captures requested products. At October 1 the adapter requests `daf420.dat.09-30-2026` and `daf420.dat`; at December 1 it requests `daf420.dat.11-30-2026` and `daf420.dat`. No October EOM is requested on recovery. The script calls the real parser and real snapshot-to-record consolidation; no ingestion is run. This confirms requested-window behavior, not a claim about actual public archive contents or missing wells.

**Business effect:** an October permit/amendment present only in October products can be absent from recovery after the overlap is passed. Older retained source fields can remain stale unless later evidence separately resolves them.

**Important counter-evidence:** do **not** claim drilling has no targeted monitoring. `backend/src/gridlens/intelligence/rrc_well_research.py:27-32,155-209,283-290` implements separately enabled/budgeted exact W-1/completion research (two active jobs, 24/day, seven-day refresh) for retained eligible active projects. It can enrich known wells; it cannot discover previously missed projects absent from retained identities, and its actual enablement/success was not inspected. This audit did not establish that all older native corrections are missed.

**Recommended bounded follow-on:** persist fully acquired month coverage and recover missing official EOM products serially under existing budgets/deadlines, fenced jobs and idempotent immutable evidence. Keep recent discovery independent so a missing historical product cannot starve current collection. Mark inaccessible archive intervals as coverage gaps; never imply recovered completeness. Verify out-of-order amendment safety, same-sequence source correction, missing EOM handling, month rollover and interruption-resume fixtures. Assess exact-well research independently rather than duplicating it.

**Classification:** confirmed designed limitation / missing catch-up feature, already accurately disclosed. Specific lost history and production impact remain unproven.

## Checks and rejected hypotheses

- Existing bounded fixture selection: **11 passed, 55 deselected in 0.33s**. Command in repository root:
  `DATABASE_URL=postgresql+psycopg://audit@127.0.0.1/audit_test APP_PASSWORD_HASH=placeholder SESSION_SECRET=offline-audit PYTHONPATH=backend/src /workspace/gl3/backend/.venv/bin/python -m pytest backend/tests/unit/test_rrc_flare_exceptions.py backend/tests/unit/test_rrc_drilling.py -k 'status_update or latest_amendment or retrieve_uses or nonapproved' -q --tb=short`
  Output: `focused-tests.log`. Dummy settings only; these cases do not connect to PostgreSQL. Repository conftest blocks external networking and paid keys.
- Reproduction command: same dummy settings and `PYTHONPATH`, interpreter plus `/workspace/gl3-remaining-audit-20261031/ingestion/reproduce.py`; output `reproduction.json`. This script uses MockTransport and patched download boundaries only.
- Rejected allegation: status changes cannot alter flare evidence. Existing test confirms stable filing ID with changed evidence hash.
- Rejected allegation: rollover necessarily overwrites a newer drilling amendment. Existing lower-sequence rule and ingestion guard protect it; bounded tests pass.
- Do not equate scheduler missed-obligation bookkeeping with historical data acquisition: `_reconcile_due` in `jobs/worker.py:363-435` creates schedule due checks, while RRC adapters independently select today's acquisition windows. No live scheduler operation was tested.

## Remaining uncertainties / blockers

No denied, pending or uncertain action in this lane. Production enablement, exact source health, actual missed filing counts, external archive retention/accessibility, exact-well monitoring runtime performance and complete DB correction propagation were **not verified**. These require separately authorized read-only runtime/source examination or isolated DB integration work. No production repair/backfill is authorized by this report.
