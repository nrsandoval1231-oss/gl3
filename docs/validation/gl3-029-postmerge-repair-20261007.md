# GL3-029 postmerge scheduler and retry repair — October 7, 2026

PR24 merged at `94c3acb7b36c6d5d04a77a0ec445e793e05120a4` at 04:51:38 UTC. Three automated P1 comments arrived at 04:51:28 UTC, immediately before merge. This report covers their separate repair on `fix/gl3-029-scheduler-retry-boundaries`. **Locally validated and independently reviewed; not merged or deployed.**

Product/test candidate: `9d86e1359556feb56612d76a57991ea4282ecc28`. Later documentation/publication commits preserve these exact product/test bytes. The [safe evidence manifest](gl3-029-postmerge-repair-20261007.json) records hashes of locally retained check receipts. All validation below was run in this executor for this repair; GitHub CI is not its substitute.

## Reproduced findings and minimal changes

| Finding | Regression before repair | Final behavior |
|---|---|---|
| [Unsaved needs beyond the shortlist](https://github.com/nrsandoval1231-oss/gl3/pull/24#discussion_r4203172196) | 51 eligible synthetic needs, no saved Pursuit: the 51st was absent | Discover active needs outside the UI shortlist through the existing canonical bulk evaluator. Unsupported active needs stay excluded. Grouped unsaved siblings remain represented by the existing card; separately saved targets remain reevaluable, including closures. |
| [Unexpected failures bypass backoff](https://github.com/nrsandoval1231-oss/gl3/pull/24#discussion_r4203172208) | Actual worker exception created an immediate replacement at each of four retry indices | Reuse the existing 1/6/24-hour retry deadline and classifications, then exhaust unchanged retries. Persist FAILED result disposition and preserve partial receipts. Unknown external effects remain blocked, including forced changed-input scheduling. |
| [Exhausted leases restart](https://github.com/nrsandoval1231-oss/gl3/pull/24#discussion_r4203172212) | Fifth expired lease with no inflight marker immediately created another question | Persist RETRIES_EXHAUSTED; unchanged automatic attempts remain suppressed after 24 hours. Explicit refresh or changed evidence may reopen a question only when no ambiguous effect remains. |

Eight reproducing cases failed on merged code, then all eight passed after the minimal patch. Five additional boundary cases cover both unknown-effect markers, unsupported/grouped discovery, saved grouped closure, and a former worker failing after an actual successor lease. All **13 new cases pass**. The successor's status, lease and receipt remain untouched.

The repair changes three production files plus integration tests. Existing PostgreSQL jobs, canonical evaluation, qualification, evidence admission, buying-chain rules, budgets and UI are reused. No provider, migration, schema, source adapter or general orchestration capability was added. Planning remains read-only; scheduling still enforces two active blockers and the daily cap.

## Exact local checks

| Check | Result |
|---|---|
| `uv run --directory backend ruff check src tests` | Passed |
| `uv run --directory backend mypy src` | Passed; 77 source files |
| `uv run --directory backend pytest tests` | **1,245 passed, 1 skipped, 1 warning; 151.29 seconds** |
| Research-validator subset | 71 passed, 0.53 seconds; overlaps the full suite |
| `npm --prefix web run typecheck` | Passed |
| `npm --prefix web run build` | Passed |
| `npm --prefix web audit --audit-level=high` | Passed; zero vulnerabilities |
| Full Playwright suite | **42 passed, zero failed/skipped/flaky; 44.382 seconds** |
| Additional real-database research UI | Five groups passed: authentication, Chicago/O&G/low-quality question trails and citations, mobile reload; no API mocks |
| OpenAPI | Exact checked-in/runtime match |
| Separate adversarial review | No material findings on frozen product/test candidate after requested extra coverage |

The skip is the existing optional NC Commerce local-access probe, absent in this executor. The warning is the existing Starlette/httpx deprecation. Mypy retains its existing untyped-body note. No failing gate is waived. Initial test-line lint failures were fixed before the final checks.

Full browser validation used a verified isolated copy of the existing regenerated legacy corpus. The actual existing worker serviced one queued refresh and stopped, with zero worker errors. One explicitly validation-only “Not reached” note was appended; no call occurred. Only the jobs and call-note inventories gained one row each; all prior rows remain. The separate five-group UI inspection used the existing final research corpus.

## Migration and preservation

No schema change is needed; Alembic remains at `0014_pursuit_research_questions`. An isolated copy of the pristine source corpus was downgraded to 0013, upgraded to head, upgraded again and checked for drift. A separately created clean database was upgraded, upgraded again and checked for drift. All seven commands passed, including the preparation downgrade. All **28 table inventories** in the populated copy matched exactly before/after.

Both source-to-validation copies were made through pg_dump/createdb/pg_restore and verified against full inventories. Source databases were not reset or modified. Browser inspection preserved all existing rows; replay writes were rolled back. Historical question receipts are not retroactively rewritten by this repair.

## Real-corpus planning and exact replay

This repair reuses the previously authorized regenerated corpus; it does not claim original PR23 retained-corpus recovery or a new live acquisition experiment. On the final research corpus:

- Read-only planning returned **11 cards in 0.2689 seconds**, with all 28 table inventories unchanged.
- The five selected Austin construction/temporary-power, Chicago, O&G and low-quality cases created **zero questions** within their recorded freshness window, preserving exact replay hash `9b5f4cf96a602e1bfac8661877e5e6408727ae72d7f81a112bab8ccecc1ceaf7`.
- Planning the full eligible set created **two questions** within the existing eight-question daily cap. A second pass using current canonical projections created **zero**, with identical evaluation/question state. Both passes were rolled back.
- No acquisition or model call occurred in this replay. Evidence tiers and canonical evidence were unchanged.

An initial diagnostic incorrectly reused pre-enrichment cards on the second full-set pass. It created no duplicate questions but changed an evaluation input hash by replaying stale buying-chain context. The corrected harness reprojects current canonical inputs as the hourly worker does. The failed diagnostic and corrected receipt are retained; the failed diagnostic is not presented as passing evidence.

## Review and limitations

The independent reviewer checked discovery, grouping, supported projection, saved closures, retry deadlines/exhaustion, unknown effects, fences and receipt preservation. Requested boundary tests were added and verified; final review found no material defect. Full-suite results then completed successfully on unchanged product code.

Discovery scans all active need IDs, increasing local projection work with corpus size; measured timing above is for this small corpus, not a scale guarantee. Existing historical unclassified failures retain their original receipts rather than being silently migrated. All future failures processed by these paths receive the corrected retry classifications.

Prior GL3-029 positive autonomous new-fact-resolution proof remains open. Six previously investigated blockers remain explicitly unresolved; this repair does not invent an answer or claim a new promotion. Fresh regenerated evidence is not original retained PR23 proof.

**No external commercial outreach occurs.** No new credentials, paid-provider activation, purchases, third-party login, access-control bypass or deployment occurred. **Cloud deployment and unattended production proof remain separate milestones.** This repair is published only as a draft; merging requires explicit approval.
