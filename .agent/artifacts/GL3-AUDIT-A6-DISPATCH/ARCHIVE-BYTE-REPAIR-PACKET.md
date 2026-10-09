# A6 archive byte-preservation repair

Root preflight found two inherited-state .prior.bin files have original working CRLF bytes but normalized LF Git blobs at80dbc2f6f5a7a5cc43534ad995501fb63c0c3885. Two before-compact archives match. Source/test/contract candidate remains frozen; no full final validation has started. Actual root failed observations: .artifacts/root-a6-archive-bin-identity.json and root-a6-builder-diff-check.log. Original working bytes remain intact.

One Luna owns only narrow .gitattributes classification for .agent/artifacts/GL3-AUDIT-A6-DISPATCH/*.bin (-text -diff), re-staging the four unchanged archived files, and a separate repair artifact. Preserve all old normalized Git blob bytes in a binary ZIP with hashes before re-stage; preserve current working bytes exactly. Do not edit product, tests, migration, generated contracts, existing101-log manifest/completion, or parent intent. Add receipt of before/after hashes, source invariance, raw failure/proof hashes, exact new head/tree and clean worktree. git diff --check must pass with archives classified as binary; never strip historical EOF bytes to pass. Two materially different repair attempts; no push/merge/deploy/providers/original-data mutation. Root full gates and independent review follow the repaired frozen source-equivalent candidate.

UTC dispatch: 2026-10-08T20:39:06.942014+00:00
