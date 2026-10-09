# Texas data-center permitting pause

Reviewed October 7, 2026 against GL3 main `94c3acb7b36c6d5d04a77a0ec445e793e05120a4`.

## Source facts

| Field | Verified representation |
| --- | --- |
| Issuing authority | Governor of Texas |
| Implementing agency | TCEQ |
| Directive date / effective date used | September 21, 2026; governor directs action that day |
| Geographic scope | Texas statewide; not limited to ERCOT territory |
| Subject | Permits related to data-center projects |
| Completion condition | ERCOT completes its audit/review; necessary information is acquired before state agencies advance regulatory approvals |
| TCEQ implementation | Construction-stormwater notice pauses associated applications, explicitly including TPDES Construction General Permit coverage, until further notice from the governor's office |
| October 19, 2026 | TCEQ compliance-reporting deadline; no expiration or automatic release |
| MW threshold | None specified in these sources; do not import 25 MW or 75 MW thresholds |

Primary sources:

- [Governor's announcement, September 21](https://gov.texas.gov/news/post/governor-abbott-directs-tceq-to-halt-data-center-permits).
- [Signed letter to TCEQ Executive Director Kelly Keel](https://gov.texas.gov/uploads/files/press/TCEQ_Data_Center.pdf), pages 1-2.
- [TCEQ construction-stormwater implementation notice](https://www.tceq.texas.gov/permitting/stormwater/construction), Special Notice. The notice has no independently verified publication date; the review date is not a publication or effective date.
- TCEQ's general [stormwater page](https://www.tceq.texas.gov/permitting/stormwater) also carries the issuance-pause notice.

The implementation notice remains present on October 7. Searches of official governor and TCEQ sources did not identify a rescission or release. This is a bounded verification result, not proof that every agency record or project has been checked. The construction-stormwater notice is explicit guidance for that program; it does not establish each other permit program's detailed procedures.

## GL3 behavior

Existing `Project`, `Evidence`, `Interpretation`, and lifecycle projections already represent sourced project facts; they should not be overwritten by a statewide directive. Main has no dedicated statewide permitting-policy model. A small source-reviewed domain record is returned as additive top-level `policy_context` in the existing project-state response. No database migration or new ingestion feed is required.

Policy context is separate from `state.utility_service`, lifecycle, and research claims. The record retains authority, dates, scope, release condition, reporting deadline, three source URLs, extraction locations, and verification date. It is not an Evidence row claiming a project event.

A regional scope match requires a data-center asset with accepted lifecycle support and an existing SUPPORTED site whose terminal state is TX/Texas (optional ZIP). El Paso remains in statewide scope. Unknown asset/site, conflicting site, and unrecognized location forms require verification; an incidental Texas street name never matches. Known other asset types receive no data-center policy context. Location parsing is deliberately conservative and does not geocode or prove jurisdiction.

Every result leaves `project_permit_status=UNKNOWN`. It does not establish a specific application's hold, denial, revocation, cancellation, construction shutdown, rental demand, MW, gap, tier, start or duration. Existing issued local permits remain source facts. ERCOT interconnection restrictions and 16 TAC §25.194 remain separate mechanisms.

`status=directed_pause` describes the retained reviewed snapshot. `verified_on` bounds its currency, and requests on other dates carry `current_status_verification=requires_refresh`. There is no automatic expiry, presumed audit completion, or live-policy monitoring claim. Recheck official release guidance and project permit records before a commercial conclusion; update the reviewed record when authoritative new evidence becomes available.

## Regression coverage

Focused tests cover authority/provenance, statewide scope including El Paso, unknown/conflicting geography, no backdating, no MW threshold, October 19/20 without expiry, snapshot currency, and returned-record isolation. An isolated SQLite test exercises the real project-state projection and verifies lifecycle/need preservation, unknown utility status, and rejection of formerly accepted evidence. SQLite coverage does not substitute for the PostgreSQL integration suite.

Validation in this workspace: 16 focused tests passed, changed Python files passed Ruff, and production modules compiled. Removing the project-state integration makes its regression fail with missing policy context; restoring it returns all 16 checks to green.

The full backend command `python -m pytest -q --tb=line` recorded 873 passed, 1 skipped, 1 failed, and 374 setup errors. The errors report an unavailable/unconfigured PostgreSQL test database. The failure is `tests/unit/test_rrc_drilling.py::test_retained_reconstruction_rejects_deeply_nested_json_as_source_parse_error`: expected malformed-content error, received segment-count error. Its test and parser content match unchanged main (ignoring the downloaded snapshot's extra trailing newline). This runtime is Python 3.12.14, whereas the project requires Python 3.11; no claim of full supported-runtime or PostgreSQL acceptance is made. The narrower unit run recorded 869 passed, 1 skipped, the same RRC failure and one database setup error. The existing Starlette/httpx deprecation warning was also present. These limitations are retained for PR review rather than expanding this policy change into an unrelated parser repair.
