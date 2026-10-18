# Live receipt/note save-readback

Production owner reported authenticated pursuits median 665 ms/max 717 ms afterPR 80,
but a receipt/note save caused 17–18s qualification pending. Reproduction confirms
both recognized receipt INSERT and note INSERT incremented the global revision,
cleared future preparation and forced a full rebuild. A second red regression
proved that each commercial page loaded the same canonical buying chain twice.

## Dependency and trigger decision

Canonical qualification/research/ranking/grouping consumes bound Evidence,
Interpretation, reviewed CallFactVersion/Decision, workflow, lifecycle, buying-chain
and other canonical tables. `current_research_state` reads typed current evidence,
not `Pursuit.snapshot`. Receipt and note data is read live for cards, history,
counts, notes and budgets. A recognized save changes **zero saved-row inputs**;
there is no derived generation to refresh or clone. Exempt saves therefore leave
input/full revision, current pointer and prepared pointer unchanged. Read-time
revision/policy/interval fencing remains unchanged.

Migration 0024 replaces workspace trigger wiring with:

- Receipt INSERT: existing exact `commercial-need:<need UUID>`/project scope,
  default research fields, array project_ids, and an empty or receipt-only object
  snapshot. Unknown columns/default shapes fail closed.
- Receipt UPDATE: stable ID/identity/project/research/other row fields, array
  project_ids, object snapshots and identical snapshot roots after removing
  `commercial_triage`. Only that receipt bucket and group presentation project_ids
  may change. The bucket's contents are opaque presentation/history, **not**
  schema-validated accepted commercial facts. They cannot grant current tiers.
- Unknown/mixed root changes, malformed values, scope/identity/research changes,
  unrecognized inserts, receipt DELETE/TRUNCATE and document changes remain full
  invalidations. Every row in a transition table must be recognized for exemption.
- Note INSERT/UPDATE/DELETE remains live-only; TRUNCATE stays full. A separate
  accepted fact/workflow/evidence mutation in the same transaction still uses its
  canonical invalidator. Rollback reverts both live data and unsafe invalidation.

This does not turn note outcome `Qualified` or stored receipt `Lead` into current
qualification. A fixture explicitly proves a fake Lead in the receipt bucket
leaves current canonical Signal cards unchanged. Current GET notes, counts, history
and byte/row limits stay live. Canonical evaluation/research POST selection remains
unchanged; this fixes post-save pending, not population selection inside those POSTs.

## Canonical chain reuse

`opportunity_projection` may export its existing canonical chain results into a
call-local output dictionary. Commercial cards use those exact results, fetching
only missing projects. Callers never inject precomputed authority. There is no
cross-request cache, new public response shape or UI change. Complete payload
comparisons and a call-count regression guard this separately from save handling.

## Validation and benchmark method

Final focused PostgreSQL/clock suite passes 93 tests; a test-only SQLAlchemy JSON
literal bind error was corrected and its mixed-bulk regression passes. An earlier
86-case suite also passed. Additional actual concurrent receipt UPDATEs during
full/future publication and boundary selection pass. Coverage includes mixed
safe/unsafe bulk statements, unknown inserts/roots/research/scope/identity,
malformed receipts, note bulk update/delete/truncate, rollback with current/ready
pointers, failed preparation, canonical races, expiry, read-your-write and restart.

Migration 0024 upgrade/repeat/check/down 0023/up/check passes. An actual Alembic-
migrated schema, not only metadata-created test schemas, accepts recognized
receipt+note commits and preserves the generation in a new session. Its first
harness used expire_on_commit=True and was corrected to the application's False
setting. Ruff/mypy 104 source files pass. Full regression, independent review and
exact-head CI are recorded with the final PR handoff.

The runner creates/drops only a random schema in an explicit `*_test` PostgreSQL
DB.1×/2× means 1,461 projects/15,874 dated evidence and 2,922/31,748, one active
need/project, synthetic unique addresses/~1 KB abstracts. It reproduces legacy
pending by temporarily restoring prior trigger wiring, then installs the new
wiring in that disposable schema. No production mutation or credential is used.
It separately compares duplicate-chain behavior (suppressing only the output
collector so the legacy second load runs) with reuse on identical inputs, requiring
complete payload digest parity except the response evaluation timestamp.

Save/readback measures an actual recognized receipt saved-at SQL UPDATE and note
INSERT/commit followed by a fresh-session saved page and own-note check. It excludes
canonical evaluation POST selection, HTTP/auth/network/rendering. Driver BEGIN is
excluded from SQL counts. Counts/checksums must remain equal. It uses 10 sequential
and 20 four-writer calls, then saves during future publication and again after
preparation; the prepared pointer must survive. No system/production clock changes
or real production midnight verification are claimed.

[Initial 1×](diagnostic-1461.json) / [2×](diagnostic-2922.json) used one receipt
version and ran with regression load. They reproduced 19.662s /33.143s pending;
1× save+readback p95 reached 1.100s and four-writer p95 1.172s. The 1× script used a
synthetic saved-at label; the final runner uses a real ISO timestamp and adds prior
metadata-only receipt history. These diagnostics remain visible, not final-history
acceptance. Fixture timings do not establish a production SLO.

## PC rollout

PC task owns backup/deployment/authenticated QA. Stop retained maintenance and
keep the browse switch false; apply 0024/repeat/check, rebuild with the final code
fingerprint, compare canonical/saved retained-corpus pages, restart maintenance
and activate the existing switch. Verify actual save/readback and retry budgets
on an isolated retained copy, persistence/restart, concurrent reads and legitimate
live authenticated GETs. Unknown/source changes must still return explicit pending.
Collection/scheduling/autonomous research/paid AI remain OFF and budgets zero.

Rollback uses the final image with the switch false. Keep additive schema/evidence
and trigger migration in place. If reverting an image, stop maintenance and recreate
API/web only with `--no-deps`; never run an older migration container against 0024.
No production deployment or live speedup is claimed by this cloud task.

## Final repeatable-read/history results

Both runs bind runtime fingerprint
`browse-b1-v1/ranking-v1/ad047f83d7c67455c5edfd0f319e10edcd2aa01ac5f2e340d001e67857cbf9cc`.
The final runner starts repeatable read before its freshness assertion and GET
payload, matching API isolation ordering. It includes50 receipt workspaces, with
20 /40 synthetic prior metadata-only versions each. Earlier harness runs were
repeated after correcting this ordering; final artifacts are these two files.

| Measurement |1× p50 / p95 / max (s)|2× p50 / p95 / max (s)|
|---|---:|---:|
|Receipt+note commit|0.003 /0.004 /0.004|0.003 /0.005 /0.005|
|Commit + fresh readback|0.148 /0.204 /0.204|0.242 /0.404 /0.404|
|Four writers: commit|0.018 /0.090 /0.090|0.011 /0.025 /0.025|
|Four writers: commit + readback|0.745 /0.992 /0.992|0.658 /0.780 /0.780|
|Duplicated-chain GET|0.315 /0.437 /0.437|0.262 /0.296 /0.296|
|Reused-chain GET|0.147 /0.233 /0.233|0.218 /0.340 /0.340|

Legacy-trigger pending rebuilds took12.051s /23.545s. All new recognized save
readbacks remained current with the same generation ID and no pending responses.
GET statements fell45→38; persistence+readback used41 statements, including two
writer statements and one extra harness freshness assertion. Future preparation
completed in13.055s /28.068s despite saves at publication and afterward, retaining
its prepared pointer. Full canonical/saved final payload parity and evidence
counts/full-row checksums matched. [1× raw](fixture-1461.json) /
[2× raw](fixture-2922.json).

Chain reuse removes7 queries, but2× GET p95 increased in this small shared-host
sample despite a lower median; it does not establish a uniform latency gain.
Small-sample p95 is a conservative observed order statistic and can equal max.
The original loaded diagnostics retain larger readback tails. No production SLO
or whole-evaluation-POST speedup is claimed.

Local full collection passed **1,838 /1 skipped**, seven warnings/seven subtests,
before the last8 cases. The93-case expanded focused suite, the strengthened two
concurrent receipt/boundary cases and a positive-chain fixture pass. The latter,
also independently reproduced, retains a canonical Acme contractor organization
and identical complete payload when comparing collector reuse with the former
fresh-chain fallback. Independent review found no correctness blocker. Final
exact-head CI remains the merge gate and is recorded in the PR handoff.
