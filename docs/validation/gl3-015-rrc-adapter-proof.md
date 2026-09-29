# GL3-015F — Offline RRC daily-permit adapter proof

## Decision and boundary

**GO for offline parsing of the one exact SHA-pinned September 2026 archive under profile `rrc-drilling-permit-master-daily-v1-observed`.** This does not enable a source, create application observations, establish upstream-commercial meaning, or authorize future RRC file versions.

The parser accepts bytes only alongside the expected SHA-256 and profile ID. It reads only the validated type-01/type-02 spans in the [GL3-015E field profile](../../.agent/artifacts/GL3-015E/field-map.json), pairs adjacent DAROOT/DAPERMIT rows, and keys a revision by status/permit number plus sequence. An intervening opaque or known segment fails the parse instead of dropping its pending root; this approved snapshot profile also rejects any root status other than `A`. API8 is retained but is not a revision or join key. Receipt, issue, amendment, extension, and spud dates remain separate labeled fields. `00000000` remains the literal source value with normalized date `null` and no asserted negative event.

Other recognized segment families are counted and not interpreted. The 35 physical lines beginning `0x85` are retained as opaque line-number/length/hash quarantine metadata; their meaning remains **UNKNOWN**. No pad, operator, production, electrification, power demand, opportunity tier, or timing estimate is derived.

## Reproduction

Run from the repository root:

```powershell
uv run --project backend python .agent/artifacts/GL3-015F/validate_rrc_daily_permits.py
uv run --project backend pytest backend/tests/unit/test_rrc_daily_permits.py -q
uv run --project backend ruff check backend/src/gridlens/ingestion/adapters/rrc_daily_permits.py backend/tests/unit/test_rrc_daily_permits.py .agent/artifacts/GL3-015F/validate_rrc_daily_permits.py
uv run --project backend mypy backend/src/gridlens/ingestion/adapters/rrc_daily_permits.py
```

The documented command is read-only: it reads raw bytes from ignored `.artifacts/GL3-015D/raw/`, verifies source and manual hashes, parses the retained archive, and compares ten prior D sample identities and mapped values. It prints deterministic counts and hashes to stdout and never overwrites tracked receipts. The tracked `sample.json` and `validation.json` are frozen evidence for the candidate; `COMPLETION.json` records their exact hashes.

To export a new timestamped proof outside Git, explicitly choose an ignored output directory:

```powershell
uv run --project backend python .agent/artifacts/GL3-015F/validate_rrc_daily_permits.py --output-dir .artifacts/GL3-015F-proof
```

That optional mode refuses directories outside the repository's ignored `.artifacts/` tree and writes `validation.json` plus `sample.json` only there. Raw source files are not copied into Git.

## Evidence result

The accepted input is 2,391,338 bytes, SHA-256 `c0215842369f14d6e725b011649ffa0076f373344e3ce5bb0d2ed411fce79cd6`; the official manual is 162,000 bytes, SHA-256 `760a25367df8fb3bd7b240a41d9471953e2ee1eab1878d5367c673548adec874`. Evidence cites the [RRC daily permit manual](https://www.rrc.texas.gov/media/zgccdjpi/drillingpermitmasterpluslatitudeslongitudes_oga049m_july1.pdf) and physical source lines for every parsed record.

The run must report 29,494 physical lines, 29,459 classified segments, 35 opaque unknown lines, 884 permit revisions with 884 unique number-plus-sequence keys, and ten matching D sample records. API8 collisions remain visible as values but do not collapse records. County values retain their distinct reported-versus-approved labels.

## Focused behavior coverage

Tests cover unsupported profile/hash mismatch, malformed CRLF and known lengths, non-ASCII mapped bytes, root/detail key mismatch, interrupted roots, non-approved status rejection, required and calendar-invalid dates, county/API prefix mismatch, duplicate revision rejection, distinct sequences sharing API8, literal zero-date handling, citations, segment counts, and opaque unknown-row handling. The tests use synthetic bytes with explicitly patched test-only hash/profile pins; the retained source proof is separately bound to the official archive hash.

This is a local parser artifact only. Source registry, service, domain, database, API, UI, network retrieval, and source activation are out of scope. Parent GL3-015 remains open.
