# GL3-015G — RRC current-file compatibility

## Decision

**REDIRECT / compatibility UNKNOWN.** The exact current RRC GoDrive listing and JSF selection were retrieved, but its download-button response was HTTP 302 to `/servlets/fileServer`. GL3-015G disabled redirects and allowlisted only the official index, exact public folder link, and exact JSF path. It stopped at that response. No current binary, new hash, or current permit rows are available to test.

The listing advertised one `daf420.dat` row 0, `2.28 MB`, modified `9/28/26 9:45:30 AM`. See the [bounded access ledger](../../.agent/artifacts/GL3-015G/access.json) and [source access report](../sources/texas-rrc-current-file.md). The 302 and zero-byte body are retained in ignored `.artifacts/GL3-015G/raw/`; the response metadata names its SHA-256 and exact path.

## Independent compatibility verifier

The verifier in [verify_rrc_compat.py](../../.agent/artifacts/GL3-015G/verify_rrc_compat.py) is independent of the accepted GL3-015F adapter and does not weaken or bypass its file-hash pin. It checks the candidate bytes directly for CRLF, known segment classification, fixed 212/510-byte root/permit rows, ASCII mapped text fields, adjacent pairing, unique number-plus-sequence keys, approved `A` status, root/detail identifiers and dates, valid required calendar dates, API county prefix, and preserved zero dates. It counts but does not interpret other known segment families or opaque `0x85` lines. An unknown non-`0x85` family or invariant violation returns REDIRECT.

Offline hostile response/profile tests are in [test_rrc_current_access.py](../../.agent/artifacts/GL3-015G/test_rrc_current_access.py). They cover ambiguous/missing index listings, login/XML pages, absent ViewState, changed listing rows, malformed JSF partial updates, redirects, oversize responses, HTML/XML masquerading as attachment data, invalid/new record families, malformed dates, status/key/adjacency failures, duplicate revisions, and API handling.

The verifier was independently run on the already accepted GL3-015F archive as a verifier baseline: hash `c0215842369f14d6e725b011649ffa0076f373344e3ce5bb0d2ed411fce79cd6`, 29,494 physical lines, 29,459 classified segments, 35 opaque lines, and 884 unique permit revisions. This is a baseline self-check only; it is **not** evidence about the inaccessible current file. No ten-record sample for a new current hash can be produced while its bytes remain unavailable.

## Next bounded step

Before any further attachment request, compare this observed JSF selection and download-button sequence with the successful D retrieval procedure documented in `.agent/artifacts/GL3-015D/retrieval-ledger.md`. Record whether the request method, session state, and server response contract differ. Only then should a separate packet decide whether `/servlets/fileServer` can be allowlisted with a bounded response contract. No G follow-up is authorized here. Until a new bounded packet passes retrieval, retain current-file access, content hash, compatibility, and sample as UNKNOWN. No source activation, service integration, database write, production/power inference, or parent GL3-015 completion follows from this result.
