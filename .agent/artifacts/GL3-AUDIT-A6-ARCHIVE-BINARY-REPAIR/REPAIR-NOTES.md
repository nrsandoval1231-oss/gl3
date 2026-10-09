# A6 archived state byte-preservation repair

Root identified byte drift in two archived pre-compaction state files. Their working copies were still the original CRLF bytes, while the Git blobs at both `80dbc2f6f5a7a5cc43534ad995501fb63c0c3885` and the product source commit `209caeb1551afa3dbda2650cd8fa64e93f68de2b` had been normalized to LF. The two `before-compact.bin` files already matched their Git blobs. Root's exact identity receipt and failed whitespace-check output are copied byte-for-byte under `ROOT-EVIDENCE/` and hashed in `PRE-REPAIR-PRESERVATION.json`.

Before replacing the two normalized Git blobs, their contents from both commits were saved in `PRE-REPAIR-GIT-BLOBS.zip`. Its receipt lists every ZIP entry's commit, path, byte length, and SHA-256. The four original working files were left unchanged.

The first ordinary `git add` after adding the binary attribute did not update the index entries for the two CRLF `.prior.bin` files. Comparison of raw worktree Git-object hashes with index object IDs exposed the mismatch. The final staging used `git hash-object -w --no-filters` followed by `git update-index --cacheinfo` for each of the four files. Before the repair commit, all four index blob IDs matched the raw worktree object IDs and `git diff --cached --check` passed with the files classified as binary.

Only `.gitattributes` is added as a repository rule, scoped to `.agent/artifacts/GL3-AUDIT-A6-DISPATCH/*.bin` with `-text -diff`. The product and test source at `209caeb` is unchanged by this archive-only repair. No tests, migration, contracts, or runtime checks were repeated because no product source changed. Root retains ownership of final validation and independent review.
