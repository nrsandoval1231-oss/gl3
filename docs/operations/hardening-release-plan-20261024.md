# Production hardening release plan — 2026-10-24

> Historical preparation receipt. After this document was written, the owner
> authorized the audit repairs, local validation, PR resolution and controlled
> deployment. The [audit completion release record](audit-completion-release-20261024.md)
> now governs that release. References below to absent deployment authority and
> pending repository integration describe the earlier preparation state; they
> are not a new approval requirement. Credential disposition, residual image
> findings, corpus gaps and unknown provider outcomes remain unresolved unless
> separately supported by current evidence. This note does not assert a cutover.

## Authority and observed host

**Production cutover remains NO-GO; host installation and runtime are not
done.** The currently installed `/etc/gridlens/start-gridlens.py` wrapper only
starts the full Compose service set, and its normal all-service command is not
approved for canary use. A local side-by-side companion and isolated Compose
canary sequence have now been prepared and passed their bounded checks, but the
companion has not been installed or executed on the protected host. Host
installation, production execution, or any protected production modification
requires fresh owner deployment authorization for the exact candidate.

Gate A remains NO-GO because credential ownership and residual image risk are
unresolved and deployment authority is absent. Gate B remains INCOMPLETE because
the original 446-record corpus and M6 requirements are open and Albuquerque
remains `SENT_OUTCOME_UNKNOWN`. Passing the repository candidate gates cannot
convert either gate into acceptance or make the release GO.

The offline-only `scripts/stage_release_wrapper.py` prepared a private,
side-by-side selective-wrapper companion from only the exact controller-observed
source bytes. It preserves the existing protected startup wrapper and exposes
only explicit named operations: stop app services, one-shot migrate, one-shot
browse rebuild, API/web canary start, worker/browse release, and UUID-guarded
browse rollback. It rejects an existing output, changed source bytes/AST/command
suffix, a default all-service start, and arbitrary arguments. It is not
installed or executed on the protected host, does not select a prior image,
and does not authorize or perform any host action. The staging CLI completed
against the exact private wrapper and wrote the private companion successfully.
`.artifacts/hardening-20261024/wrapper-staging-proof.json` records
`PASS_OFFLINE_WRAPPER_PROVENANCE`: private JSON/main-prefix guards, environment
and Infisical prefixes preserved, and the static operation map matches the
isolated Compose proof. The wrapper was not installed or executed.

The repository candidate's local rehearsal and Compose canary are development
evidence only. The helper in `scripts/rehearse_release.py` accepts local inputs
only and has no production target or deployment mode. The isolated Compose
canary proof demonstrates the required service sequence on a fresh local
database, not execution on or installation to the protected production host.

The latest supplied read-only host receipt is
`.artifacts/hardening-20261024/production-readonly.json` (2026-10-24
20:00:49 UTC). It reports `/etc/gridlens/compose.app.yaml`,
`/etc/gridlens/runtime.env`, project services `db`, `migrate`, `api`, `worker`,
`browse`, and `web`, plus `gridlens-ingress`. The image IDs then observed were:

| Service | Observed image | Observed Docker image ID | Revision |
|---|---|---|---|
| API, worker, browse, migrate | `gridlens-api:release-ca013d4c2dc8` | `sha256:b6faa6c62d8936983c82d3be4e0d10c13ded83a1f3918e27edf08a09c44c0b92` | `ca013d4c2dc8084a708ff5cfc092ec20b1d8c61b` |
| Web | `gridlens-web:release-fae481db749b` | `sha256:f98096d263bf5fa8f3cd3439bc76239acbcb63aacae020a9b16a66ee56f44095` | `fae481db749b2e71dfb41ee63547c3fa1f6b1170` |
| Database | `postgres:18.6` | `sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336` | Not applicable |
| Ingress | `caddy@sha256:d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f` | same pinned digest | Not applicable |

The `sha256` values in the service rows are Docker image IDs from inspect;
they are not asserted to be registry manifest digests.

That receipt reports compose SHA-256
`1dc62cb8bb5d0e408ff3bc4944a0a940d3ee3d2cbaef4f1ba85acb192af17032`.
The production schema was separately reported at `0041_evidence_packages`.
These are dated observations, not confirmation of the host's present state.
Before any future action, the controller must replace the current identities
with a fresh protected read-only observation and fill the candidate fields below
from the frozen candidate manifest and exact host image inspection.

| Required release identity | Fill from fresh controller evidence |
|---|---|
| Candidate Git SHA | `UNKNOWN — controller fills after freeze` |
| Candidate API image reference and image ID/digest | `UNKNOWN — controller fills` |
| Candidate web image reference and image ID/digest | `UNKNOWN — controller fills` |
| Current API and web image IDs/digests | `UNKNOWN — refresh host observation` |
| Current and target migration revisions | `UNKNOWN — refresh host observation` |
| Current compose SHA-256 and runtime-env protected metadata | `UNKNOWN — controller records without secret values or hashes` |
| Backup path and SHA-256 | `.artifacts/hardening-20261024/production.dump` / `99fe6e61f198d45ae3f4f489e7cbb6c3207a6211316438cfe996f636b3ab1fe7`; private restore receipt pending |
| Approved secret injection wrapper and exact compose invocation | Verified wrapper identity below; candidate execution still requires authorization |

The runtime-env file may contain secrets. Never print it, put it in a shell
transcript, check it into the repository, or replace it from a saved copy. The
controller verified that `/etc/gridlens/start-gridlens.py` is a root-owned
mode `0600` wrapper with SHA-256
`1cedfc857f6e29e818098f5fbd2e7ae3c691221467864779e350768b1dfd1920`. Its
redacted AST confirms it injects Infisical credentials and runs Docker Compose
using the actual compose and runtime files, with
`COMPOSE_PROFILES=saved-browse`. Its `--validate-only` mode reported that
private setup is present without authenticating or starting services. Do not
print or copy its credential inputs.

The supplied private PostgreSQL 18 dump is
`.artifacts/hardening-20261024/production.dump`, SHA-256
`99fe6e61f198d45ae3f4f489e7cbb6c3207a6211316438cfe996f636b3ab1fe7`; it restores
at `0041_evidence_packages`. The helper requires that schema both before and
after candidate migration and verifies the migration is repeat-safe. The
private auth fixture is stored as JSON and must be converted into a private
dotenv file for the helper without printing any value.

The controller-side local rehearsal invocation is:

```powershell
uv run --project backend python scripts/rehearse_release.py `
  --dump <private-authorized-postgres18-custom.dump> `
  --dump-sha256 <verified-64-character-sha256> `
  --api-image <exact-candidate-api-image-ref> `
  --web-image <exact-candidate-web-image-ref> `
  --revision <frozen-40-character-git-sha> `
  --prior-api-image <exact-prior-api-image-ref> `
  --prior-web-image <exact-prior-web-image-ref> `
  --test-env <private-auth-only-test-env-file> `
  --output <new-private-output-directory>
```

Provider values and other source settings are discarded; provider keys are
forced empty and automation/call budgets are zero. The helper writes private
table count/hash snapshots, logical-call hashes, and phase events without row
data. It binds image refs to inspected content IDs and revision labels.

The wrapper's only verified start command is:

```bash
COMPOSE_PROFILES=saved-browse python3 /etc/gridlens/start-gridlens.py
```

It starts all services from `/etc/gridlens/compose.app.yaml` using the
wrapper's protected Infisical context and `/etc/gridlens/runtime.env`. This
all-service invocation is **not approved for candidate canary** and must not be
used as a workaround. It was not run during preparation.

## Release gates

1. **Freeze and authorize.** Freeze source and explanatory docs. Record exact
   Git SHA, API/web image IDs and labels, target schema, current host images,
   and current compose hash. Require owner authorization for that exact
   candidate. Any changed candidate restarts candidate-bound validation.
2. **Verify recoverability.** Through the approved secret context, take a fresh
   PostgreSQL backup without changing production. Record its path, size and
   SHA-256 in the protected receipt. Copy it to private storage and run the
   local helper against that exact dump, expected digest, candidate and prior
   images, private test env-file, and a new private output directory. Require
   `PASS_CANDIDATE_REHEARSAL`, schema `0041_evidence_packages`, unchanged
   retained-table and logical-call proofs, candidate API/web read smoke, and
   prior API/web forward-schema read smoke. Import and worker loops must not be
   dispatched. The helper's success cleans only its exact created containers
   and network; a failure preserves them for diagnosis.
3. **Controller validation.** Complete exact-candidate build, scans, migration
   repeat/drift checks, full local gates, CI and independent Sol review. Record
   final results against the frozen SHA and image digests. The rehearsal is one
   gate and does not close unrelated launch, provider, corpus, or Finish
   Contract requirements.
   A green repository review or local rehearsal does not clear the production
   host-install/runtime gate below. Gate A remains NO-GO while credential
   ownership and residual image risk are unresolved. Gate B remains INCOMPLETE
   while the original 446-record corpus, M6 requirements, and Albuquerque
   `SENT_OUTCOME_UNKNOWN` remain unresolved.
   Source candidate `d33fb65201771364bc52c801e37667f8f1e01ddb` has local
   full gates PASS (backend 2,928 passed/2 skipped; browser 197 passed/1
   skipped), combined affected tests 30 passed, and GitHub run `40131919486`
   PASS (backend 2,929 passed/1 skipped; browser 197 passed/1 skipped). These
   results predate this final documentation reconciliation. The integrated
   documentation-complete SHA still requires final exact-candidate gates and
   follow-up independent review; do not transfer these results to a changed SHA.
4. **Recheck the host immediately before a future change.** Using the approved
   secret wrapper, inspect compose service/image identities, the running
   database/schema, job/worker state, backup completion and provider/automation
   controls. Save only protected evidence. Stop if any identity differs from
   the authorized preflight or if backup, service, schema, or quiescence proof
   is incomplete.
5. **Production cutover — HOST INSTALLATION/RUNTIME NOT DONE; NO-GO.** Do not
   use the installed all-service wrapper for canary. The local companion and
   isolated Compose proof do not authorize host installation or execution.
   Only after fresh exact-candidate owner deployment authorization and host
   preflight may the approved companion be installed/executed. That operation
   remains future work; no production action has occurred.

   The companion accepts only these named operations and fixed Docker Compose
   argument suffixes. The prefix (Docker executable, protected environment,
   compose file and project context) comes from the captured wrapper; these
   suffixes are not standalone host commands.

   | Named operation and arguments | Fixed Compose argument suffix |
   |---|---|
   | `stop-app` | `stop api worker browse web` |
   | `migrate` | `run --rm --no-deps migrate` |
   | `rebuild-browse` | `run --rm --no-deps browse uv run python -m gridlens.jobs.browse rebuild` |
   | `start-canary` | `up -d --no-build --no-deps api web` |
   | `start-workers` | `up -d --no-build --no-deps worker browse` |
   | `rollback-browse <canonical-UUID>` | `run --rm --no-deps browse uv run python -m gridlens.jobs.browse rollback --generation <UUID>` |

   If separately authorized, perform one ordered sequence:

   1. Preserve the protected compose checkpoint and runtime-env metadata. Stop
      application services with `stop-app`, leaving the existing database in
      place. With worker/browse stopped, capture the current prior-image browse
      generation UUID, policy, input revision and validity. Confirm it is
      unexpired and compatible; capture the retained-data and provider/ledger
      hashes. If any proof is missing, stop before migration.
   2. Run `migrate` exactly once. Prove schema state and retained-data equality
      against the pre-migration snapshot.
   3. Run `rebuild-browse` exactly once before any candidate API reads. Prove
      retained data and provider/ledger hashes are unchanged, candidate browse
      generation is valid, and the captured prior generation/input revision
      remains preserved for guarded rollback.
   4. Run `start-canary` only. Keep worker and browse absent. Verify exact
      candidate API/web identities, authenticated API reads, web health, and
      retained-data/provider/ledger proofs while worker/browse remain absent.
      Accept the canary only if every check passes; on uncertainty or failure,
      keep workers held and follow the rollback path below.
   5. After canary acceptance, run `start-workers`; verify worker heartbeat and
      all five application services. The retained-data/provider hashes were
      checked before worker release; do not require them to remain identical
      after normal worker activity begins. Retain private receipts.

   The isolated proof is
   `.artifacts/hardening-20261024/compose-development-2-d33fb65/receipt.json`
   (`PASS_COMPOSE_CANARY`, revision
   `d33fb65201771364bc52c801e37667f8f1e01ddb`). It exercised fresh-database
   migration and rebuild, API/web canary while worker/browse were absent,
   worker/browse release and heartbeat, five-service health, stop with only DB
   remaining, zero jobs/calls/budgets/business records, and owned-project
   cleanup. It proves local Compose behavior only. Gate A stays NO-GO for
   unresolved credential ownership and residual image risk; Gate B stays
   INCOMPLETE for the original 446 corpus, M6 requirements, and Albuquerque
   `SENT_OUTCOME_UNKNOWN`.

6. **Rollback on failed or uncertain canary.** Keep workers/browse held and the
   database at its current forward schema. Select the prior-image composition
   through the separately authorized protected process; do not run migration
   during rollback. Run `rollback-browse <captured-UUID>` to restore only the
   captured generation. Its guard rejects a pruned/expired generation or
   changed policy/input revision. Then run `start-canary` with prior API/web
   images and verify authenticated reads and retained-data equality while
   worker/browse remain absent. If guarded restoration or reads fail, keep
   workers held and record rollback BLOCKED pending a separately authorized
   recovery. Never directly change the browse pointer, rebuild with the prior
   image, downgrade schema, or restore the database as application rollback.
   Only after the prior-image canary passes may `start-workers` release normal
   activity. Never require identical retained/provider hashes after that
   release.

   No stage above is currently authorized for production. Any ambiguous
   migration, snapshot, wrapper, or service result is `UNKNOWN`; preserve state
   and stop. Database restore or migration downgrade requires its own explicit
   authorization and plan.

The all-service startup wrapper invocation is verified but not approved for
canary. The selective companion and canary sequence passed local preparation
and isolated Compose checks; neither was installed or executed on production.
Host installation/runtime, fresh host preflight, backup execution, and any
production operation remain pending and require new owner deployment
authorization. No deployment was performed while preparing this plan.
