# Local retained-record coverage snapshot

This is a reproducible export of the local database on 2026-09-26. It is a
coverage and retained-state snapshot, not a qualification audit or launch
review. The export includes persisted observation titles, abstracts, source
metadata, evidence versions and their excerpts/links/dates, and linked
power-need state. It does not fetch original pages or adjudicate quality.

The snapshot contains 92 observations dated 2026-08-26 through 2026-09-25 and
93 retained evidence versions:

| Feed | Observations | Source-declared scope | Linked needs |
|---|---:|---|---|
| Federal Register EIS | 77 | United States; energy, infrastructure, mining | 1 active Signal |
| North Carolina Commerce | 15 | North Carolina; commercial construction, data centers, manufacturing | 2 active Signals and 1 inactive Signal |

These tags describe feed metadata, not demonstrated breadth of discovered
projects. The retained data contains only these two feeds. The Federal Register
scope is nationally declared, but the only linked project location in this
snapshot is New Mexico. North Carolina Commerce is state-specific. Unlinked
observations have no admitted project location in this export. Therefore the
snapshot does not establish broad national or cross-industry project coverage.

The retained state illustrates why source volume and admitted Signal count
must remain distinct: 77 Federal Register observations correspond to one
linked active Signal; 15 North Carolina Commerce observations correspond to
two active and one inactive Signal. The inactive Main Street program record is
a useful review candidate: its retained excerpt describes aggregate results
“since the inception” of the program and thousands of downtown building
rehabilitations, while its linked need is inactive and has no location. This
supports inspecting the record and its admission history; it does not by
itself establish a false positive or explain why it was deactivated.

The export keeps unmatched observations, evidence attribution, and active and
inactive linked state visible. Its limits are explicit: it reports persisted
text only, does not determine whether source claims are true, and does not
measure false negatives because records that were never ingested are absent.
It is not the PRD's review of 30 independently discovered Signals/Prospects.

The ignored sample is `.artifacts/local-review-sample.json` (92 observations,
93 evidence versions; SHA-256
`8abb8ac81e04524054a97d04eb44dc1905e11d85686f15e43a1f943a93486f84`). Recreate
it with:

```powershell
uv run --project backend python scripts/export_review_sample.py --output .artifacts/local-review-sample.json
```

The command refuses to overwrite an existing output. The next useful bounded
work is source-breadth expansion and measurement against specific desired
industries/geographies, followed by a separately scoped review of retained
Signals. Do not treat source metadata tags as observed coverage.
