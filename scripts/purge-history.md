# Purge `.agent/artifacts` from Git history

This procedure removes `.agent/artifacts` from every commit. It rewrites commit hashes. Do not force-push. This repository change does not publish rewritten history.

The working tree already stops tracking the directory and `.gitignore` ignores it. A normal clone of current history still downloads the old blobs until this rewrite is published, and publishing it is a separate owner decision.

## 1. Backup bundle

From a clean clone of the repository, before `git filter-repo`:

```bash
git bundle create ../gl3-pre-purge.bundle --all
git bundle verify ../gl3-pre-purge.bundle
```

Keep `../gl3-pre-purge.bundle` outside the repository. It is the copy you can clone if the rewrite is wrong. `git clone ../gl3-pre-purge.bundle gl3-restored` recreates the pre-purge commits.

## 2. Rewrite in a mirror clone

`git filter-repo` refuses to run in a normal working clone. Use a fresh mirror:

```bash
git clone --mirror . ../gl3-purge.git
cd ../gl3-purge.git
git filter-repo --path .agent/artifacts --invert-paths
```

`--invert-paths` drops that path and keeps everything else. Confirm the path is gone:

```bash
git rev-list --all --objects | grep -F '.agent/artifacts' || echo "path absent"
```

Do not run `git push --force`, `git push --force-with-lease`, or `git push --mirror`. Leave the rewritten mirror local until Nick decides, in writing, to publish it.

## 3. Branches whose tips still contain the directory

As of main `3f55750`, these remote tips contain `.agent/artifacts` in the tree. Shared ancestry means a history rewrite touches their parent commits as well, not only the tip diff.

- `origin/main`
- `origin/acceptance/gl3-stage2-source-quality-20261009`
- `origin/codex/portfolio-cleanup-20261005`
- `origin/docs/canonical-interactive-ui-2026-10-01`
- `origin/docs/evidence-graph-jev-architecture`
- `origin/docs/gl3-stage1-baseline-20261009`
- `origin/docs/oct-1-runtime-status`
- `origin/docs/sync-post-pr21-20261002`
- `origin/feat/bay-area-jurisdiction-policy-states`
- `origin/feat/commercial-pursuits`
- `origin/feat/ercot-public-impact-rfi`
- `origin/feat/evidence-graph-jev-shadow`
- `origin/feat/gl3-020-runtime-recovery`
- `origin/feat/gl3-023-city-permits`
- `origin/feat/gl3-026-national-intake`
- `origin/feat/gl3-027-priority-flare-intake`
- `origin/feat/gl3-029-autonomous-pursuit-research`
- `origin/feat/gridlens-focus-experience`
- `origin/feat/sps-proposed-tariff-provenance`
- `origin/feat/texas-large-load-25194`
- `origin/feat/todays-power-pursuits`
- `origin/fix/gl3-029-scheduler-retry-boundaries`
- `origin/fix/jupiter-scoped-lifecycle`
- `origin/fix/pin-permit-interpretation-clock`
- `origin/fix/repository-audit`
- `origin/fix/texas-tceq-permitting-pause`
- `origin/integration/gl3-reviewed-policy-prs-20261009`
- `origin/repair/fact-decision-replay-20261009`
- `origin/repair/gl3-audit-integration-20261008`
- `origin/repair/gl3-auth-20261007`
- `origin/repair/gl3-facts-entry-20261008`
- `origin/repair/gl3-facts-workflow-20261008`
- `origin/repair/gl3-governance-delivery-20261007`
- `origin/repair/gl3-lifecycle-delivery-20261007`
- `origin/repair/gl3-public-browse-20261008`
- `origin/repair/gl3-query-performance-20261008`
- `origin/repair/gl3-research-delivery-20261007`
- `origin/repair/gl3-source-controls-20261007`
- `origin/repair/gl3-stage3-recall-20261009`

`origin/HEAD` points at `origin/main` and is not a separate branch. Any later branch created from these commits also carries the blobs until it is rebased onto a rewritten history.
