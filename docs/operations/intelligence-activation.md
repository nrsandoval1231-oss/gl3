# Intelligence activation and rollback

This is an activation package for review, not an activation receipt. No provider,
source schedule, notification destination, production migration or deployment has
been enabled by the integration build. The existing approved DigitalOcean,
Cloudflare and Infisical arrangement remains the deployment substrate.

## Configuration to review

The concrete safe overlay is
[`intelligence.disabled.env.example`](../../deploy/digitalocean/intelligence.disabled.env.example).
All model caps and enable controls are zero/OFF, including
`BUYING_CHAIN_PUBLIC_RESEARCH_ENABLED`. Model IDs are empty. Credentials
stay in the existing secret manager and backend runtime environment; never put
keys in the web image, logs, Git or the reviewable configuration diff.

Before any activation, record the exact candidate/release SHA and migration head,
current running SHA, enabled registry source IDs, actual runtime flags and every
applicable finite count/USD cap. Provide separately pinned fast-extraction and
reasoning model IDs supported by the deployed account, and a verified TypeSafe
model/contract. Verify pricing and output bounds for those exact IDs. Missing
pricing or an unverifiable worst-case reservation blocks dispatch. An unknown
measurement remains unknown; a configured estimate is not a measured charge.

TypeSafe dispatch also requires an explicit billing attestation bound to the
exact configured model and `systemone-v1` contract: set
`INTELLIGENCE_TYPESAFE_BILLING_VERIFIED=true`,
`INTELLIGENCE_TYPESAFE_BILLING_MODE=input_only`, matching
`INTELLIGENCE_TYPESAFE_BILLING_MODEL_ID`, a reviewed
`INTELLIGENCE_TYPESAFE_BILLING_POLICY_ID=typesafe-total-input-ceiling-v1`, and a nonempty
`INTELLIGENCE_TYPESAFE_BILLING_REFERENCE`. That evidence must document both
input-only billing and a finite maximum total billable input token count including
the provider wrapper. Set that count in
`INTELLIGENCE_TYPESAFE_MAX_TOTAL_BILLABLE_INPUT_TOKENS` and set
`INTELLIGENCE_TYPESAFE_TOTAL_INPUT_BOUND_VERIFIED=true` only for that exact
model/contract/policy. Every TypeSafe reservation charges the full configured
ceiling. The serialized client request cannot bound the opaque wrapper. Current
official API schema evidence does not establish billing semantics or a total
input ceiling, so the default remains unknown and blocked.
Any positive TypeSafe output rate blocks dispatch. The client has no documented
and enforced output-token bound; a configured token number or USD cap does not
prove one. Do not add or assume an undocumented transport field. If TypeSafe
documents output billing, keep dispatch blocked until an enforceable bound and
its full output charge are implemented and verified. Model, contract, policy,
reference and rates are included in call identity so a changed attestation cannot
reuse an earlier reservation.

The smallest rollout is one already-retained, source-permitted need and its most
valuable unresolved question, in evaluation/advisory mode with a finite approved
request count, output-token limit, per-call cost ceiling, daily/monthly USD caps,
and global/provider/model/source/project limits. Use one active provider call at
a time for the pilot. This is a proposed rollout, not owner budget authorization.
No model output directly accepts facts, changes identity, raises tiers or sends
outreach. Routing remains blocked until separate evaluation and routing approval.

Use the existing Infisical binding documented in
[deployment](../../deploy/digitalocean/README.md). Verify only safe metadata inside
the actual API and worker containers: required environment variable names present,
model/configuration IDs and feature flags. Do not print, hash or copy secret values.
Compose explicitly forwards `OPENAI_API_KEY`, `TYPESAFE_API_KEY` and optional
`FIRECRAWL_API_KEY` to backend services; the web image receives none. A configuration
test with synthetic sentinels proves forwarding syntax only. Actual runtime
propagation still requires safe presence-only inspection on the deployment host.
A present key does not prove provider health or account/model compatibility. A paid
probe is a bounded logical call and needs the same authorization and reservation.

### Scanned Federal Register PDF OCR

OCR remains unavailable with the example overlay: its feature, vision, and exact
input-token preflight switches are false; source/retention references and model
pricing are empty or zero; and the OCR task is absent from the contract allowlist.
It also requires a separately verified finite upper cost bound for the input-token
count endpoint and a nonempty reference documenting that bound. A positive cap
alone does not establish the count endpoint's maximum charge; do not dispatch until
the count contract, pinned model, policy, and bound reference are reviewed together.
Set INTELLIGENCE_OCR_PREFLIGHT_COST_BOUND_VERIFIED=true only with that evidence and
record its reference in INTELLIGENCE_OCR_PREFLIGHT_COST_REFERENCE. Both values are
bound to the exact count body, model, contract version, and policy in the durable
preflight intent; measured cost remains UNKNOWN unless provider accounting supplies it.
Enabling it requires a separately approved finite upper bound for both the token
count preflight and the response, plus exact account-supported model and verified
input/output rates. The preflight itself transfers the same inline PDF and reserves
its own shared-ledger intent before dispatch. Its counted input tokens are not
billable usage. A timeout after dispatch is UNKNOWN and cannot trigger a blind
second count or response.

The authenticated same-origin request accepts only a need UUID and an Evidence UUID
already linked to that exact need. It cannot accept a URL or bytes. The worker only
supports an exact Federal Register GovInfo PDF path with the FR document number
matching its parent Observation external ID; it checks public DNS, disables
redirects, caps the PDF at 750,000 bytes and five pages, uses a finite isolated
parser, and requires the original PDF Evidence hash. The semantic Observation hash
is separately bound as stale-context state and is not expected to equal the
alternate PDF's byte hash.

When source and retention allowlists and a nonempty retention reference explicitly
permit capture, the byte envelope is write-once under Evidence provenance before
the model call. The full source bytes remain private to that provenance field.
Public Evidence serialization boundaries reviewed for this feature are:
`intelligence/project_state.py::_provenance` (a six-field metadata allowlist),
`api/app.py::EvidenceOut` (no provenance field), and
`api/app.py::export_opportunities` (CSV includes evidence URLs and hashes, not
provenance). `api/intelligence.py::_history_view` applies the strict transcript
and follow-on serializers; job views expose identifiers/status only. OCR history
exposes a bounded page transcript from the LogicalCall result, never the capture
envelope. The transcript carries `OCR_UNVERIFIED` and `ADVISORY_ONLY`; it does not
alter accepted facts or Leads. An optional grounded follow-on must be a separate
ledger call and quotes remain unverified until an independent source check.

The worker state sequence is deliberately narrow: queue an exact need/evidence
intent; fetch and validate GovInfo bytes outside the acquisition transaction;
commit the immutable capture; reserve and dispatch the bounded input-token count;
revalidate the source, capture, request digest, and current policy; reserve and
dispatch the response; validate every page and the 64 KiB result bound; then
publish only its LogicalCall pointer into Evidence provenance. The count intent
binds the exact count-body digest, model, contract version, policy, and verified
upper-cost reference. A completed count can be reused only when all bindings
match. A stale source/context ends as stale; missing or invalid bytes fail closed;
unknown outcomes after dispatch remain unknown and are never blindly retried.
Grounded follow-on repeats its own request, count, response, context, and transcript
version checks in separate ledger calls, then stores candidates as `OCR_UNVERIFIED`
with canonical promotion prohibited and independent verification required.

## Migration and release

1. Obtain a fresh backup and preserve outstanding logical-call statuses, reserved
   exposure, queued jobs and last-good evidence. Record safe counts and digests.
2. Apply declared migrations to a restored isolated database first. Run repeated
   upgrade and schema drift checks; compare original evidence/project/need fields.
3. Deploy the exact independently accepted code and forward migrations with all
   providers, collection, monitoring and research switches still OFF/zero. Follow
   the existing deployment command with secret-manager injection; image recreation
   without injection does not prove runtime credentials survived.
4. Verify authenticated reads, unknown states, API/worker identity, source coverage,
   queue visibility and last-good commercial state before the bounded activation.
5. Enable only the agreed pilot contracts/source/need and finite caps. Capture actual
   call IDs, response identity, evidence/version citations, observed usage/cost or
   UNKNOWN, restart recovery and the owner-visible next action. A valid UNKNOWN or
   Signal is acceptable; do not create a Lead to make the pilot appear successful.

Do not run all existing queued work as part of the pilot. Review parked work and
its evidence/context versions. A changed model, prompt or policy is a distinct
logical intent; it is not permission to repeat an uncertain prior paid request.

## Stop and rollback

Disable the provider/contract/research controls first; stop the intelligence worker
and monitoring planner. Keep canonical evidence, prior accepted claims, model-call
history and all reserved/uncertain exposure. `SENT_OUTCOME_UNKNOWN` is never refunded
or retried merely because a worker stopped. Reconcile only with an attributable
operator decision and supporting provider evidence.

OCR uses the existing `intelligence_process` kind and shared logical-call ledger;
park/checkpoint it with other intelligence jobs during rollback. Preserve its
private write-once capture and OCR call history. The explicit overlay clears OCR
flags, pricing, source IDs, and retention reference. Do not delete captured bytes or
retry uncertain preflight/response calls as part of rollback.

Buying-chain public research uses the existing `jobs` table with kind
`buying_chain_research`. Its public acquisition switch defaults OFF; retained-only
relationship extraction remains available. Preserve job checkpoints and retained
buying-chain evidence during rollback.

Before running a pre-integration worker, park the new job kinds so older code cannot
mistake them for source ingestion. After worker stop, the reviewed operation is:

```sql
BEGIN;
SELECT id, kind, status, checkpoint FROM jobs
WHERE kind IN ('intelligence_process', 'project_monitor', 'signal_adjudication', 'evidence_shadow', 'buying_chain_research')
  AND status IN ('queued', 'running') FOR UPDATE;
-- Preserve the returned job identities/statuses in the rollback receipt first.
UPDATE jobs SET status = 'paused', lease_owner = NULL, lease_until = NULL,
  error = 'INTELLIGENCE_ROLLBACK_PAUSED'
WHERE kind IN ('intelligence_process', 'project_monitor', 'signal_adjudication', 'evidence_shadow', 'buying_chain_research')
  AND status IN ('queued', 'running');
COMMIT;
```

Restore the prior accepted API/web/worker images with automatic migration execution
skipped; first verify that code's forward-schema compatibility on a restored copy.
An older Alembic tree may not recognize new revision IDs, so an unconditional old
`upgrade head` is not a rollback. Do not downgrade/drop the call ledger or watch
tables in production. If code compatibility is unproven, keep providers/planners
disabled on the current accepted code until repaired rather than deleting history.

Re-enable only after exact-candidate gates and review. Resume safe NOT_SENT work
through current eligibility checks; uncertain calls require reconciliation. Restore
tests must prove that outstanding reservations survive and dispatched calls do not
replay, not merely that `/health/ready` responds.

## Operational acceptance evidence

Use the [evaluation tooling](../validation/intelligence-evaluation.md) to freeze
data/labels and report the four routes reproducibly. Its receipt validator checks
structure; it cannot establish that a submitted cloud receipt actually happened.

Collect actual scheduled-cycle IDs/timestamps, source due/check receipts, deployed
SHA/configuration identity, PC-off execution evidence, persistence/restart receipts,
alerts/failures, backup and verified restore evidence. Seven consecutive actual
scheduled days and the PRD 95% due-source success requirement cannot be replaced by
accelerated runs. The independently discovered real commercial need and owner Lead
review remain separate acceptance evidence. Fixture tests and local backup drills
are local technical proof only.

### Read-only restore proof and operational receipts

Run the metadata snapshot against the source database, preserve its JSON separately,
restore the backup into an isolated database with dispatch disabled, then run the
same command against that restored database and compare it with `--compare`. The
tool streams deterministic digests and counts over retained evidence text and
provenance, complete job lease/checkpoint/error state, logical-call intent/context,
result and accounting fields, budget rows, and watch policy/cursors. Content is
hashed in process; it does not emit evidence text, prompts, credentials, or provider
results. It deliberately excludes credentials and settings tables. A mismatch or an
unknown migration head fails the comparison. A restore rehearsal must not dispatch
jobs. A duplicate intent continues to reuse its existing logical-call ID, and a
`SENT_OUTCOME_UNKNOWN` call must never be replayed.

`OPERATIONAL_RECEIPT_FILE` selects the optional read-only JSON receipt in API and
worker containers. Both receipt path variables are blank by default, and Compose
mounts `/dev/null` until explicitly configured. Enable the mount only after the
backup command has created the configured host path as a regular file; then recreate
API and worker containers so the receipt is mounted read-only. The absent default remains UNKNOWN. The host backup command
writes a version-1 receipt atomically only after its existing upload command returns
successfully. It records UTC time, object reference, and optional deployed SHA; it
does not claim a verified restore. A separate comparison may be recorded with the
before/after snapshot digests, tool version, UTC comparison time, and attributable
reference. The application labels that `REPORTED_MATCH`, keeps authenticity
`UNVERIFIED`, and leaves `last_verified_restore_at` UNKNOWN. It does not authenticate
cloud storage, a PC-off schedule, or owner acceptance. Daily budget counters are
reported from persisted UTC ledger rows; absent rows and unknown monetary amounts
remain UNKNOWN. Detail rows are capped at 5,000 while financial aggregates cover
the full ledger.

An optional `commercial_review` receipt section can record a bounded human review
without adding a table or workflow. It requires a reviewer label, UTC-capable
`reviewed_at`, frozen sample and context SHA-256 digests, and 1–100 cases. Each
case carries a case ID, need UUID, one or more exact evidence UUID/content-hash
references, and a `SUPPORTED`, `CONFLICT`, `UNRESOLVED`, or `OTHER` decision. The
reader rejects extra fields so raw evidence text cannot be smuggled through this
receipt. The API reports these labels as `REPORTED`; independent-label status stays
`UNKNOWN`, quality verification `UNVERIFIED`, and acceptance `UNKNOWN`. Owner
candidate notes and completed model work do not become independent labels or
accepted leads through this mechanism.

Example, after creating the isolated restore and ensuring no worker is running:

```powershell
cd backend
uv run python scripts/intelligence_snapshot.py --database-url-env DATABASE_URL --output ..\before.json
# Restore backup to an isolated DB with providers and workers disabled.
uv run python scripts/intelligence_snapshot.py --database-url-env RESTORE_DATABASE_URL --compare ..\before.json --reference local-restore-rehearsal-YYYYMMDD --output ..\restore-comparison.json
```
