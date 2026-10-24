# Production hardening release plan — 2026-10-24

## Authority and observed host

**Production cutover is BLOCKED / NOT EXECUTABLE.** The verified
`/etc/gridlens/start-gridlens.py` wrapper only starts the full Compose service
set. It does not support the selective candidate start, one-shot browse rebuild,
and worker/browse write-hold sequence required for a safe canary and guarded
rollback. Its normal all-service command is not approved for canary use. Do not
invoke it for this release. Production remains NO-GO until an authorized,
protected-wrapper procedure for that sequence is prepared, independently
validated without production mutation, and separately authorized for the exact
candidate.

The repository candidate's local rehearsal is development evidence only. The
helper in `scripts/rehearse_release.py` accepts local inputs only and has no
production target or deployment mode. It demonstrates local behavior, not
execution or support by the protected production wrapper.

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
used as a workaround for the missing selective sequence. It was not run during
preparation.

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
   procedure blocker below.
4. **Recheck the host immediately before a future change.** Using the approved
   secret wrapper, inspect compose service/image identities, the running
   database/schema, job/worker state, backup completion and provider/automation
   controls. Save only protected evidence. Stop if any identity differs from
   the authorized preflight or if backup, service, schema, or quiescence proof
   is incomplete.
5. **Production cutover — BLOCKED / NOT EXECUTABLE.** Do not start cutover with
   the currently verified all-service wrapper. Before any future authorized
   cutover, an authorized controller must prepare and validate a protected
   selective-start sequence that drains services, captures and preserves the
   prior compatible browse generation, keeps worker/browse writes held, runs
   the candidate's one-shot browse rebuild, proves retained-data equality and
   candidate-cache validity, and only then permits API reads. The local helper
   proves this behavior only in its isolated development environment; it does
   not prove the production wrapper can execute the sequence. Changing the
   protected production wrapper/configuration or testing a cutover mutates
   production and requires owner deployment authorization. No such
   authorization exists. Until this prerequisite is closed, the remaining
   cutover/rollback steps are a requirements checklist, not executable
   instructions, and release status remains NO-GO.

   The required candidate one-shot operation is:

   ```bash
   uv run python -m gridlens.jobs.browse rebuild
   ```

   It must run after candidate migration and before any candidate API reads,
   within the future protected selective sequence. Require guarded proof that
   retained data is unchanged and the candidate browse generation is valid;
   preserve the captured prior compatible generation for guarded rollback.
   The available wrapper does not support or authorize this sequence.

6. **Future authorized cutover checks.** Preserve a
   protected byte-for-byte compose checkpoint and runtime-env metadata. Keep the
   database and its existing Postgres volume/image in place. Drain/stop `api`,
   `worker`, and `browse` according to the approved host wrapper. Before
   stopping or changing any candidate service, capture the current browse
   generation UUID, policy fingerprint, input revision, and validity from the
   prior-image-compatible state. Confirm the generation is unexpired and its
   input revision remains available; retain that exact generation through the
   canary window. If no compatible, unexpired generation can be preserved,
   do not begin cutover because guarded application rollback may be blocked.
   Keep worker and browse writes/maintenance held until canary acceptance or
   completion of a guarded rollback. Take a post-stop retained-data snapshot
   and prove quiescence. Run the candidate
   `migrate` service once through the verified compose procedure, then verify
   migration head and retained-data equality. Start the candidate API and web
   with the existing runtime secret injection. Keep worker and browse write or
   maintenance loops paused through the canary; start their services only if
   the approved procedure proves those loops remain held. If that hold cannot
   be demonstrated, stop before cutover. Do not
   change ingress, database image, provider keys, scheduled automation, or
   runtime configuration as part of this release.
7. **Verify and stop on uncertainty.** Verify exact running API/web image IDs,
   schema `0041_evidence_packages`, authenticated session, health, customer,
   opportunity/workspace and intelligence read endpoints, web root, saved
   browse availability, worker/browse health, and unchanged retained snapshot.
   Confirm provider dispatch remains zero and compare runtime-env metadata to
   the preflight. Retain private receipts. Any ambiguous migration, snapshot,
   or startup outcome is `UNKNOWN`; preserve state and follow the approved
   recovery authority. Never downgrade the database or restore over the live
   database as application rollback.
8. **Application rollback only after compatible derived-cache restoration.** If
   candidate verification fails, keep the migrated database at its current
   forward schema and keep worker/browse writes paused. Use the generation UUID,
   policy fingerprint, input revision, and validity captured before candidate
   cutover; do not discover or substitute a generation after the candidate has
   run. The prior image must restore that exact UUID
   using `python -m gridlens.jobs.browse rollback --generation <UUID>`; its
   existing guard rejects a pruned generation, expired generation, changed
   canonical input revision, or policy mismatch. Do not directly update the
   browse pointer, rebuild a cache with the prior image, downgrade a migration,
   or restore the database. If the retained generation cannot be restored,
   record rollback as blocked; a derived-only rebuild needs separate tested
   authority and write holds remain in place pending an authorized recovery
   path. Then verify authenticated reads and retained-data equality, and
   record the outcome. Database restore or migration downgrade is a separate
   recovery event requiring its own explicit authorization and plan.

The all-service startup wrapper invocation is verified, but is not approved for
canary. Selective start, candidate one-shot rebuild, write holds, and guarded
cache-proof steps have not been validated through that wrapper. Changing or
testing the protected wrapper/configuration requires owner deployment
authorization; none was granted. Fresh host preflight, backup execution,
candidate staging, and any production operation remain pending. No deployment
was performed while preparing this plan.
