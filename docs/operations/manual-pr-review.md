# Manual pull request review while branch protection is unavailable

Observed October 7, 2026 at 20:23 UTC: the repository is private, and GitHub's read-only `GET /repos/nrsandoval1231-oss/gl3/branches/main/protection` returned HTTP 403 with “Upgrade to GitHub Pro or make this repository public to enable this feature.” Keep the repository private. No GitHub-enforced required checks or review rules are configured or claimed by this procedure.

Until branch protection can be enabled under the existing plan, use this manual gate for every pull request:

1. Keep the pull request in draft while implementation is in progress. Record its immutable head commit SHA and Git tree SHA when review begins.
2. The controller runs and retains all applicable backend tests, frontend tests and browser checks, type/lint checks, migration checks, dependency audits, and other packet-specific gates against that exact commit. Verify each check conclusion names the recorded SHA.
3. An independent reviewer examines that same commit and tree, including changed-file scope, acceptance criteria, failures, and unresolved comments. Record the review outcome and evidence against the SHA/tree.
4. Resolve all review comments and inspect the pull request's review state and check conclusions. Immediately before any separately authorized merge, compare both the head SHA and Git tree to the reviewed values. A moved head, rebase, or changed tree invalidates the prior gate and review; rerun them on the new exact candidate.
5. Retain the final SHA/tree, check links and conclusions, review record, and merge authorization with the release evidence. This is a human procedure, not a substitute claim that GitHub required or enforced the checks.

If repository plan or visibility changes later, recheck protection through GitHub and replace this manual procedure only after required rules are configured and verified. Do not change visibility or billing as part of this procedure.
