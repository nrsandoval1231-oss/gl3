# TITLE-02 continuing activation controller (draft)

This host controller remains uninvoked. Nick's actual approval record authorizes both the six fixed public-data validation jobs and continuing public-data scope for titles on authenticated request and Jev updates limited to the three selected observations, with the existing shared $50/month aggregate and narrower limits. The controller validates that record by exact SHA-256 and verifies the six-job and rollout receipts. It does not ask for an invented second user authorization.

The host operator still needs to prepare the fixed mode-0600 `continuing-activation-gate.json` in the exact release folder after the passing rollout, final tests/review, and six-intent receipt exist. The gate is a release evidence record, not new permission. Its required fields are:

```json
{
  "release_gate_passed": true,
  "revision": "<40-char candidate revision>",
  "full_candidate": "<64-char reviewed source candidate>",
  "images": {"api": "sha256:<64>", "web": "sha256:<64>"},
  "authorization_sha256": "0859fcbb3c97c846abc3598355324e6d08207d520321d45c2f6b7353c1a6fb11",
  "scope_sha256": "ce5b146ab3759a9af012ad521c15450c9621a64abc387c9999a4eb071d453cfc",
  "activation_sha256": "5f6d5a44e6e740aed583d1269babdaa21eb9a2cfd954e952047cd499526608d5",
  "activation_controller_sha256": "<final title02-activate-runtime.py hash>",
  "git_manifest_sha256": "<release manifest hash>",
  "build_evidence_sha256": "<build-evidence.json hash>",
  "rollout_receipt_sha256": "<title02-rollout receipt hash>",
  "candidate_compose_sha256": "524f2ba0ae7178dbae3fea4666eaaec19f225468b17227fa900d06a48c99971b",
  "six_intent_receipt": {
    "host_receipt_sha256": "<host-receipt.json hash>",
    "journal_sha256": "<six-intent journal hash>",
    "gate_sha256": "<six-job controller gate hash>",
    "scope_sha256": "ce5b146ab3759a9af012ad521c15450c9621a64abc387c9999a4eb071d453cfc",
    "activation_sha256": "5f6d5a44e6e740aed583d1269babdaa21eb9a2cfd954e952047cd499526608d5"
  }
}
```

The host receipt itself does not have a top-level image field. The six-job controller gate binds the API image, revision, full candidate, scope/activation hashes and normal-worker-disabled state; the host receipt binds worker restart and completion results; the journal has the six fixed intents and each `completed_fixed_job` result. The controller joins these by exact job IDs and validates three title jobs, three Jev jobs, completed statuses, output/result shapes, null actual costs, and the reviewed Jev estimate reservations. It does not infer `kind` from result events; it associates results to the fixed intents.

## Pinned rollout and configuration checks

The pre-rollout Compose hash is not used as the deployed Compose hash. The rollout receipt's `prior_compose` path must point to the unique, regular pre-rollout backup under `/etc/gridlens`; its normalized text must match the reviewed baseline hash. The controller derives candidate Compose by applying exactly the two image-tag replacements made by the rollout script, checks the derived hash against the recorded candidate hash above, and compares active Compose text to that exact result. The actual post-replacement Compose hash was confirmed by the parent as `524f2ba0…99971b`.

Compose is inspected in memory with `docker compose config --no-env-resolution --no-interpolate`; output is neither written nor printed. The check retains the explicit browse `INTELLIGENCE_ENABLED=false` / `JEV_ENABLED=false` overrides and verifies the API/worker/browse runtime-file anchors. Web is not expected to have `DATABASE_URL`; only API, worker and browse database URLs are compared. The actual database must still be `gridlens_restore_20261014` on the canonical named volume, and `SHOW data_directory` must equal `PGDATA` beneath `/var/lib/postgresql` with no shadowing mount.

Before activation, each of the three selected source/evidence/need/project relationships is rechecked against current enabled source state, current observation/evidence hash, accepted interpretation, original URL, project anchor, and the exact title/Jev request inputs. The six results are checked against their fixed journal intents, `jobs`, textual checkpoint JSON, associated `logical_calls` (job ID, fingerprint, provider/model, evidence/context digests, status, reservation and null actual charge), title versions or Jev decisions. The same checks run after services return. All global/provider/model/source/project daily/monthly caps are compared across API, worker and browse before and after. The pre-activation queue check fails closed on any queued/running title or Jev work so enabling the ordinary contract never exposes older held backlog.

## Cutover and recovery behavior

The script changes only the named reviewed nonsecret keys in `runtime.env`, after an exclusive mode-0600 byte backup and before atomic replacement. It never edits Compose, builds images, modifies credentials, or writes the database. It uses the existing Infisical startup wrapper, `--profile saved-browse`, `--no-build`, `--no-deps`, and only `api`, `worker`, and `browse`; the existing web and database containers are verified unchanged. It holds the `jobs` SHARE-lock fence while draining the worker and validates API health, nginx config/reload, candidate image IDs, and a fresh worker heartbeat.

The startup wrapper has no subprocess timeout. On Ctrl-C the host process waits until the detached startup/Compose command exits before any recovery, avoiding a race with a still-running Compose client. On a caught failure after a possible runtime-file replacement, recovery stops API and browse admission, drains/stops the worker under the SHARE fence, and checks for unresolved accounting or queued title/Jev jobs. It restores only if runtime bytes equal either the original bytes or this controller's proposed bytes. It restarts the same candidate only when runtime restoration, drain, accounting and no-backlog checks all pass. Otherwise it leaves services stopped for explicit operator recovery. It never cancels jobs, alters reservations/checkpoints, replaces the database, or replays a provider call.

The private final receipt is not guaranteed across host/process/power loss. An absent or unfinished receipt, a retained private log/backup, an unknown service state, or an unproven rollback is an operator-recovery condition and must not be represented as success. No activation/controller command has been run for this draft.
