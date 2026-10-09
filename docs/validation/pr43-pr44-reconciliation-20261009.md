# PR 43 / 44 post-merge reconciliation — October 9, 2026

## Verified repository state

Both requested PRs had already merged before this review. PR 43 merged at 16:22:40 UTC; PR 44 was integrated with PR 43, retargeted to main, and merged at 16:52:05 UTC. No restack or repeat merge is required.

| PR | Final head | Target base | CI run | Tested merge | Actual merge | Identical tested/merged tree |
| --- | --- | --- | --- | --- | --- | --- |
| 43 | 73105afd115839f9917027f75091761f9334c9fa | 48e7121f65c6d78c6245622df8cf80af48c43bc5 | 37956827770 | c6a556796c5baa6fee2c34af976a0a73f164b0f2 | 13b02939f17d31a063b691beadee64573c6e7c41 | 9a56a2ed445959af0ca6a70a5d9c3bd7436357bd |
| 44 | 3499ccbb5641e5f5b19e00090f13401787356686 | 13b02939f17d31a063b691beadee64573c6e7c41 | 37960073195 | 914f2d6459bdcea43ea3ab9ae90e2b22b21b9cbf | cb9cb3cedf2c211a8f917557dada82a70c546f8f | 8998bdaa20a8a0163bcb675ba08a597dc7777602 |

The backend job checkout logs explicitly bind each tested merge to the head/base pair above. Git commit objects confirm that each actual merge has the same parents and tree as its tested candidate. This is stronger evidence than a successful head badge alone.

PR 43 CI: 1,471 backend tests passed, one skipped, seven warnings; 62 browser tests passed. PR 44 CI: 1,472 backend tests passed, one skipped, seven warnings; 81 browser tests passed, one skipped. Both backend and web jobs succeeded, including lint/types, dependency audits, fresh/repeated migration and schema drift checks, frontend build, and authenticated browser coverage. These are hosted CI results, distinct from the earlier local counts in the PR bodies.

## Independent-review reconciliation

PR 43's retained PASS receipt is .agent/artifacts/GL3-AUDIT-A6-UI-STATUS-DISPATCH/a6-selected-interval-independent-review.json, bound to daedade06adc0dbe18fb09c46a5dcfc2444681f5 / tree 75e002ec439e8c303bb185dfd9daeafd5c4c4abe. GitHub comparison to final head 73105afd shows only the integration-status sentence in .agent/CURRENT_STATE.md changed. Application code, tests, schemas and governing specifications are unchanged.

PR 44's description reports a PASS receipt for 604732856c6ca5e7700a5e064fc7bf655122eeef / tree bdfa9b7eb8516c34746ebfcef00a7889c4aad2cc, SHA-256 8d91840a50937b971b01cf0b7ae7e0f2fc876dd886c00d9f320086e79d1125bb. Comparison to final head 3499ccbb likewise changes only .agent/CURRENT_STATE.md. The final PASS receipt itself was not found in the merged tree or PR discussion; the committed controller completion and gates files still say independent review pending. Do not represent that historical receipt as independently inspected. Earlier failed reviews remain historical evidence and must not be overwritten.

## Substantive finding and bounded repair

The fact-decision endpoint looked up an existing idempotency key within a Need before checking the fact-version path parameter. Its digest excludes that path parameter. A retry with the same key and payload against a different fact could therefore return HTTP 200 with the first fact's prior decision, even for a nonexistent target.

The repair requires the stored decision's fact_version_id to equal the requested fact version before replay. Mismatch returns HTTP 409. Existing stored hashes and same-target retries remain compatible. No migration, backfill, history rewrite, provider activation or deployment is involved.

A local execution of the actual extracted route, with a stubbed database boundary, reproduced same-target 200 / wrong-target 200 before the change and same-target 200 / wrong-target 409 after it. This bounded reproduction is not a database integration test. The added real-API PostgreSQL regression exercises both a second persisted fact and a nonexistent target, checks same-target replay, verifies the second fact stays draft, and verifies no extra decision event is written. Its authoritative run belongs to the follow-up PR's exact-candidate CI.

## Reviewed behavior and remaining limits

- Migration 0017 adds fact versions, decisions and workflow events; UPDATE/DELETE triggers enforce append-only history. Upgrade does not rewrite original tables. Downgrade is destructive to these new histories and was not run here.
- Qualification requires live source support and exact activity/facility scope. Accepted facts retain attribution and effective intervals. Timing corrections bind current source hashes; full-window suitable supply and conservative gap arithmetic control Lead reassessment. Workflow status does not award qualification.
- Status recovery freezes the request and key, replays the persisted event, and checks exact event identity, version and hash against Need read-back. Competing current status stays separate; missing, foreign or out-of-window events stay unconfirmed.
- Retained-data parity (1,167 records, 1,149 groups, 17 searches, 24 pages, 24 original-table fingerprints, unchanged original dump) is recorded in the existing local controller evidence. This review did not access the owner's retained database or independently rerun those fingerprints.
- Existing regression coverage includes scope isolation, immutable history, correction/retraction, stale source timing, partial effective intervals, saved historical cards, concurrent writes, response loss, foreign events and seven status filters plus UNKNOWN.

## Commercial acceptance remains open

Authentic source retrieval/parse/persistence/repeat readiness; representative source-quality review; seven consecutive daily operating cycles; owner-reviewed real Lead with supported MW/start/duration/suitable-supply gap and buying path; canonical original PNG/HTML and owner visual acceptance; production deployment and operational/restore evidence. Recorded synthetic/local tests do not satisfy these requirements. Original-data reconciliation is not newly certified here. Paid providers and external outreach remain separate.

Sources: [PR 43](https://github.com/nrsandoval1231-oss/gl3/pull/43), [PR 44](https://github.com/nrsandoval1231-oss/gl3/pull/44), [43 CI](https://github.com/nrsandoval1231-oss/gl3/actions/runs/37956827770), [44 final CI](https://github.com/nrsandoval1231-oss/gl3/actions/runs/37960073195).
