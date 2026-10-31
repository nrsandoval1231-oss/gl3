# Current release and browse recovery procedure

**Status: repository procedure; production execution is on hold.** This guide describes current code and required release/recovery evidence. It does not authorize deployment, protected-host access, generation writes, ingestion, paid research or credential changes. Dated receipts establish only their named images, schema and environment. Current protected wrapper/companion contents, image identities, schema and browse state remain unverified until an authorized host inspection.

## Readiness and endpoint requirements

Current project results (`/api/opportunities/projects`) and company/group results (`/api/opportunities/groups` and group project/open routes) require a valid saved generation regardless of `SAVED_BROWSE_ENABLED`. That flag still selects saved versus canonical evaluation on certain legacy need/list/map/detail paths. Setting it false is **not** a recovery fallback for the ordinary project/company UI. Missing, policy-mismatched, invalidated or expired generations fail closed with qualification-pending HTTP503. Keep generation maintenance available during ordinary operation; inspect the selected image's actual route behavior before proposing any fallback.

Runtime policy binds exact source-registry bytes and relative paths/bytes of backend Python files, not a Git label or row count. API, ingestion worker and browse worker must use the same validated backend artifact/policy. A prior image needs a generation valid under its own policy and the current canonical input revision. Do not disable policy, privacy, revision or clock fences to serve stale results.

## Protected wrapper operation contract

The repository selective-wrapper generator preserves the captured protected environment/Infisical/Compose prefix and rejects mismatched input byte/AST identity, noncanonical generation UUIDs and arbitrary command suffixes. An input-hash rejection is a stop condition; do not replace expected hashes merely to make an unknown host wrapper pass. The current candidate adds these narrow operations:

| Companion operation | Browse CLI suffix within its fixed Compose context | Effect |
|---|---|---|
| `browse-status` | `gridlens.jobs.browse status` | Reads current generation readiness |
| `stage-browse` | `gridlens.jobs.browse stage-recovery` | Writes derived rows and a recovery receipt |
| `inspect-browse <canonical-UUID>` | `gridlens.jobs.browse inspect-recovery --generation <UUID>` | Reads candidate readiness and CAS metadata |
| `publish-browse <canonical-UUID>` | `gridlens.jobs.browse publish-recovery --generation <UUID>` | Guarded derived-pointer publication |

Existing `stop-app`, `migrate`, `rebuild-browse`, `start-canary` and `start-workers` retain fixed suffixes. These names are an operation contract, **not standalone host commands**. The updated companion has not been installed or verified on production by this work. Read-only verification must establish the actual installed prefix, operation map and selected image capabilities before any future authorized execution. Never use the old `rollback-browse` / `rollback --generation` lane, an all-service startup as a selective canary, or direct database pointer edits.

`scripts/rehearse_release.py` is frozen as a legacy schema 0041-only local rehearsal and requires explicit `--historical-0041-only` acknowledgement before resource access. Its historic rollback command and receipts do not certify current schema 0049 or selected current/prior images. Current recovery requires an independently verified isolated rehearsal with the actual image pair, current backup and supported lane; do not relax that helper's schema checks or transfer its old PASS.

## Future release sequence — requires separate authorization

1. **Read-only preflight.** Record actual image IDs/source manifests for API/web/worker/browse, current schema, wrapper/Compose identities, effective nonsecret provider controls, worker state and active/prepared generation identifiers, policies, revisions and validity. Do not infer deployed state from merged main. Inspect current schema before selecting migration work; no older migrate image, replay of an applied revision or downgrade is an application rollback.
2. **Recovery proof.** Through the established separately authorized procedure, hold canonical writers and browse maintenance, preserve private configuration/image pins, take a fresh verified backup and prove a complete isolated restore. Rehearse the exact candidate/prior artifacts against that current data and forward schema, including authentication, suppression, evidence and provider-accounting retention. A historical restore or a captured generation UUID alone is insufficient.
3. **Candidate stage and publication.** Under the exact candidate backend/policy and authorized protected context, stage derived browse data, retain its returned UUID, inspect `ready` immediately before publication, then use guarded publication. Staging and publication are writes even though they do not rewrite canonical evidence. Do not trigger ingestion/research/backfill to fill missing projections. Record policy, integrity/count completeness, input/full revisions, active/prepared pointers and time window.
4. **Canary.** Pair candidate API/web with the valid candidate generation while ingestion and browse maintenance remain held. Verify source/image identity, schema, authenticated read boundaries, project/company counts and cohorts, search/filter/sort/pagination/detail/Back, contact privacy and evidence, responsive layout and console/network behavior. Public sign-in HTTP200 is insufficient. Preserve quiesced canonical/provider-ledger proofs; source/provider activation is outside this procedure.
5. **Completion or hold.** Resume only previously authorized services after exact-candidate acceptance, then check heartbeat and generation maintenance under unchanged provider controls. Record images, policy/generation and current readiness. Canonical hashes need not remain identical after normal workers resume. If any gate fails or is uncertain, keep the protected maintenance/canary hold and apply the separately rehearsed rollback decision below.

## Current-data rollback and CAS boundaries

Retain prior API/web/backend artifacts that can read the current forward schema and suppression ledger. Preserve canonical evidence, entity IDs, contact/history and provider accounting; never restore an older database over new history or downgrade privacy migrations to roll back application code. An image predating required suppression support must not expose contact surfaces or run refresh workers.

Recovery staging captures input revision, full revision, active pointer and prepared pointer. Inspection/publication also require the exact runtime policy, digest/integrity/count agreement, a complete nonempty generation already valid and at least 60 seconds of remaining validity. Publication serializes with builders, locks browse state, atomically selects the candidate and clears preparation. Displaced generations remain retained. Guard failure means stop and diagnose; it does not permit pointer override.

A receipt staged before candidate publication normally becomes stale when publication changes the active/prepared pointers, even if canonical input revisions are unchanged. A previously captured UUID may also expire, be pruned or have the wrong policy. Do not reuse a stale receipt as rollback proof.

If candidate acceptance fails after publication, keep writers/maintenance and ordinary traffic held in the established protected context. Select the rehearsed prior backend artifact without running its migration service. Under **that prior artifact's actual runtime policy**, stage a fresh derived generation from **current canonical data**, inspect readiness and guarded-publish it through supported operations. Then start its paired prior API/web canary and verify authenticated reads, suppression and current-data preservation before accepting traffic or releasing workers. Exact order and capabilities must first be proven with the actual prior image and isolated backup. If it cannot stage/publish safely or the guard refuses, recovery is blocked: retain the hold and report the failed gate. No zero-downtime or recovery-time guarantee is established here.

Publication retries return `already_published` only while the candidate still satisfies validity and revision checks. This is not permission to use an expired or policy-mismatched generation.

For detailed privacy and receipt semantics, see [contact suppression and recovery](contact-suppression-rollback.md). [Operations authority](README.md) links dated deployment evidence; [local runtime](local-runtime.md) supplies disposable development setup. Historical [B1 rollout notes](saved-browse-b1.md) and [October24 preparation](hardening-release-plan-20261024.md) retain context, not current recovery commands or production authority.
