# Bay Area jurisdiction policy reconciliation — October 7, 2026

Inspected main `94c3acb7b36c6d5d04a77a0ec445e793e05120a4` and open PRs
28–31. Main has Source/Observation/Evidence/Interpretation provenance and
project lifecycle handling, but no jurisdiction-policy contract. The open
Texas readiness, RFI and tariff PRs are independent and are not imported here.

## Delivered boundary

`gridlens.domain.jurisdiction_policy` validates four manually reviewed JSON
records in `config/policies/`. It uses the existing vocabulary of sources,
observations, dated evidence and scope, but does not overload project lifecycle
or introduce a database table. There is no existing generic jurisdiction field
to reuse safely: Evidence links to an observation; Interpretation is an
observation assessment, while lifecycle events require a physical project.

This is a callable contract and CLI, not an enabled feed or a database backfill.
No project matching, denials, supply gaps, tier changes, UI or deployment is added.
Future integration should retain raw versions in Observation/Evidence and place
the validated policy payload in Interpretation.assessment, outside project
qualification. Do not route jurisdiction-only material through project discovery.

## Reviewed states

| Record | Preserved evidence | Evaluated state |
|---|---|---|
| San Francisco 261021 | Reported October 6 approval; official Mayors Office, blank enactment fields; citywide, 45 days | pending_verification |
| Oakland 27-0050 | Reported October 6 approval; direct page Passed/final action October 6; indexed view In Council/blank final action; draft minutes | pending_verification |
| Santa Clara SVP intake | October 6 staff report says no new data-center applications since 2023; exact start unknown | reported_constraint |
| Santa Clara policy work | Working group began August 12, 2026; staff expects work toward end 2027 | in_development |

URLs and extraction locations are retained with each record. October 7 is the
review/retrieval date, not an enactment date. The direct/indexed Oakland mismatch
is evidence lag or representation conflict, not a proved chronology. Oakland's
supplemental legislation attachment timed out and then returned Gone. Its
recommendation title's immediate-effect wording is not treated as an enacted
effective clause. No end date is calculated from the reported 45-day duration.

Santa Clara's November 2023 limitations letter was identified as an attachment
but not retrieved. Its capacity rationale is attributed in the record limitations;
the exact restriction wording, exceptions and reopening date remain unverified.
Late-2027 policy work is neither an intake reopening date nor a moratorium expiry.

## State transitions and authority

An official status label or reported vote never activates a moratorium.
Activation requires a reviewed enactment record and a reviewed effective clause
with an explicit start and exclusive end. Future start produces
`enacted_not_effective`; within the retained interval, `operative`; on the exclusive
end, `expired`. Those are projections of the retained evidence, not assertions
that no later amendment, repeal or extension exists. Retain prior source/status
observations when reviewing a subsequent snapshot. No automatic extension exists.

The evidence kind is a human-review assertion, not an automated authenticity
check. Only a reviewer who inspected authoritative enactment/effective text may
assign these kinds. Never relabel draft minutes or a recommendation as enacted.
The code checks linkage and category, not the legal truth of arbitrary input text.

For non-moratorium context, future dates return `requires_refresh`; a staff report
does not establish that an intake pause or policy work continues indefinitely.
Dates before the snapshot are rejected to avoid using later knowledge historically.

## Validation

24 focused tests pass, including 18 initial missing-contract failures and two
review-driven failures before the future-context repair. Ruff and mypy pass.
The CLI validated the reviewed Oakland record and returned pending_verification.
Independent review identified indefinite future projection of non-moratorium
states; repaired with two regression cases.

Runtime is Python 3.12.14 with Pydantic 2.13.5, while the repository pins Python
3.11. This checkout contains selected files retrieved at the pinned main SHA;
the full repository suite, PostgreSQL integration and production ingestion were
not run. Existing product code is unchanged. Draft publication does not claim
merge readiness or live-feed acceptance.

Run from `backend`:

```sh
python -m pytest -q tests/unit/test_jurisdiction_policy.py
python -m ruff check src/gridlens/domain/jurisdiction_policy.py tests/unit/test_jurisdiction_policy.py
python -m mypy src/gridlens/domain/jurisdiction_policy.py
uv run python -m gridlens.domain.jurisdiction_policy ../config/policies/oakland-27-0050.json --on 2026-10-07
```
