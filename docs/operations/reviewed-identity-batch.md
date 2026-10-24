# Reviewed company identity batches

`gridlens.intelligence.reviewed_identity_batch` applies an explicitly reviewed
mapping from selected project-scoped company claims to one already selected,
currently evidenced company identity. It does not search by company name or
merge projects. Keep private claim IDs and source details in a local manifest;
do not commit production manifests or reports.

Each `map` manifest names a `batch_id`, a `target` anchor, and one or more
`items`. The target anchor contains the selected `company_identity_id`, its
`claim_id`, `project_id`, current `link_id`, current `evidence_id`, and exact
`evidence_hash`. Every item contains `claim_id`, `project_id`,
`entity_type: "company"`, expected `current_link_id`, expected
`current_identity_id`, `evidence_id`, `evidence_hash`, `target_identity_id`,
`reviewed_by`, and a specific `reason`. The target identity on each item must
equal the identity in the target anchor. IDs and hashes must come from the
reviewed source records; names alone do not authorize a mapping.

Run from `backend` with the application's configured local database:

```powershell
$env:PYTHONPATH = "src"
python -m gridlens.intelligence.reviewed_identity_batch dry-run C:\path\to\private-map.json
python -m gridlens.intelligence.reviewed_identity_batch apply C:\path\to\private-map.json --expect-digest <dry-run-digest>
```

Dry-run reads current claims, links, corrections, and evidence, then prints a
JSON report and digest without writing. Apply repeats all checks under one
transaction and refuses a changed digest, stale or conflicted claim, changed
link, changed source hash, or invalid target anchor. Prior links are marked
`superseded` through `link_claim_to_identity`; a repeat with the same reviewed
manifest is an idempotent no-op.

For a reviewed inverse, prepare a separate private manifest with
`operation: "rollback"`. Each inverse item carries the current mapped
`current_link_id` and `current_identity_id`, the exact prior
`restore_link_id`, that prior identity as `target_identity_id`, and fresh
reviewer/reason attribution. Keep the claim, project, and current evidence ID
and hash explicit. The inverse uses each exact superseded link as its restore
anchor, so a many-to-one remap can restore multiple distinct prior identities.

```powershell
python -m gridlens.intelligence.reviewed_identity_batch dry-run C:\path\to\private-inverse.json
python -m gridlens.intelligence.reviewed_identity_batch rollback C:\path\to\private-inverse.json --expect-digest <dry-run-digest>
```

Rollback creates new reviewed current links and supersedes the mapped links;
it never deletes identities, claims, projects, or link history. The controller
owns any production evidence review, manifest, apply, and browse rebuild.
