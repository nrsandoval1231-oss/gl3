# Default Customers: actual retained-source browser evidence

The authenticated application used native ingestion, existing company identities,
and the saved customer API against `gl3_retained_ui_smoke_20261113_13da6025_test`
on loopback PostgreSQL port55439. No API response was mocked and no reference
labels were seeded. This is a two-source smoke, not the complete 20-company evaluation.

The same database and backend served both frontend versions:

- Before: frontend `2cf4f67b`, built with Vite and served through its preview server.
  The bare route selected Shortlist and displayed zero customers.
- After: frontend source committed as `2467dafb`, backend `2336b02a`.
  The bare route requested `shortlist=false&canonical_only=true` and displayed
  DataBank and CyrusOne. Explicit Shortlist remained empty. Returning to All
  customers restored both; DataBank account detail survived reload with the same scope.

[receipt.json](receipt.json) retains the actual group responses, one common
generation ID, eight source hashes and four screenshot hashes. The source bytes
were unchanged before/after capture. Mobile width390 had no horizontal overflow.
The task's read-only provider-ledger check found zero logical calls.

| Before default | After default |
| --- | --- |
| [Desktop](before-default-desktop.png) | [Desktop](after-default-desktop.png) |
| Empty Shortlist | Two canonical customers |

Also retained: [mobile](after-default-mobile.png) and
[DataBank detail](after-databank-detail.png). Astra independently inspected all
four images and verified their hashes; see the [bounded review](../default-customers-20261113-review.md).

## Limits

The comparison isolates frontend defaults on the same current backend; it is
not a full old-backend deployment comparison or production verification. Both
source announcements are historical, required demand remains unknown, and no
verified contact is present. The visible initial-fact “revised” labels and
commercial bonus were independently identified as a separate defect; that
repair is reviewed in a separate branch. These images do not grant commercial
acceptance or assert a customer needs power now.

## Commands and reproduction

The captured run used the private task equivalents of the included
[seed helper](seed_smoke.py), [launcher](launch_smoke.py), and
[browser capture](capture.cjs). Copies add configurable manifest/output paths,
exclusive output creation and an explicit two-source selection so future
coverage growth cannot silently change this fixture. They were syntax checked;
the receipt records the actual captured run, not an additional run of these copies.

From the repository root with the task's existing disposable settings:

```sh
source /workspace/task-runtime/security-env.sh
export GRIDLENS_SOURCE_ROOT=/workspace/gl3-commercial
export GRIDLENS_SMOKE_MANIFEST=/workspace/task-runtime/default-smoke-replay.json
export GRIDLENS_SMOKE_RUNTIME_DIR=/workspace/task-runtime/default-smoke-replay-servers
export GRIDLENS_SMOKE_OUTPUT=/workspace/task-runtime/default-smoke-replay-captures
backend/.venv/bin/python docs/validation/customer-intelligence-20261112/default-native-ui-20261113-final/seed_smoke.py
backend/.venv/bin/python docs/validation/customer-intelligence-20261112/default-native-ui-20261113-final/launch_smoke.py
```

The helpers refuse existing manifest/output paths and use only a newly created
`gl3_retained_ui_smoke_*_test` database. The launcher keeps authentication and
origin validation, trusting only the two fixture origins, with API port18491
and current UI port15491. It leaves its own test processes/database available
for inspection and does not mutate another database.

For the before frontend, use a detached checkout at `2cf4f67b`, its installed
locked dependencies, then run from that checkout's `web/`:

```sh
npm run build
GRIDLENS_API_PORT=18491 node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 15490 --strictPort
```

Finally, in another configured shell:

```sh
node docs/validation/customer-intelligence-20261112/default-native-ui-20261113-final/capture.cjs
```

The initial private attempts are retained in task-runtime logs. One failed the
origin guard because the new fixture origin was not configured; it was corrected
only in the test launcher. Another exposed a shared Vite dependency-cache failure
in the before frontend; the built preview isolated it. A missing npm preview
script was corrected by using Vite's installed CLI. The final new harness also
changed its mistaken `Q4 2026` text expectation to the source-preserving
`by fourth quarter of 2026`. No existing application test was weakened to obtain
the captured pass.
