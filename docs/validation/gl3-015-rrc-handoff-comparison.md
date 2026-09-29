# GL3-015H — RRC GoDrive handoff comparison

## Decision

**GO for one separately authorized, bounded same-host handoff probe.** This is a recommendation only; H made no network request and does not change G’s result: its current file hash and compatibility remain UNKNOWN after the one 302.

## Evidence compared

The deterministic comparison script checks every raw source file in D’s retrieval-ledger inventory against its recorded byte count and SHA-256, then checks each of G’s four captures against G’s access receipt. All 15 D ledger entries and all four G receipt captures match. The exact results are in [`comparison.json`](../../.agent/artifacts/GL3-015H/comparison.json); rerun read-only with `uv run --project backend python .agent/artifacts/GL3-015H/compare_handoff.py`.

The retained D listing and G listing both contain exactly one current `daf420.dat` row at index 0 / row key `8187`, modified `9/28/26 9:45:30 AM`, advertised `2.28 MB`. Their HTML bodies are each 298,699 bytes, but differ by SHA-256: D `d7283089c8d488e0e8cddb85ee0b48d77f134fbd7039bfa85a5b4009c7e29153`; G `ea792a69eccf3ef2e6fe68e941744ceb5712773af9352992252a56fdf2aa7dcf`. Both expose the same JSF form structure: `fileList` POST to `/webclient/godrive/PublicGoDrive.xhtml` with `fileTable_selection`, `fileList_SUBMIT`, and `javax.faces.ViewState`; plus `j_id_3e` with `j_id_3e_SUBMIT`, `javax.faces.ViewState`, and the `j_id_3f:j_id_3f` Download button. ViewState values are not recorded here.

D’s ledger reports two successful selections/downloads for that folder and file, each HTTP 200 `application/force-download`, 2,391,338 bytes, SHA-256 `c0215842369f14d6e725b011649ffa0076f373344e3ce5bb0d2ed411fce79cd6`. Both retained attachment files have that same verified body hash. D does not preserve each request’s method, posted form fields, intervening selection response, response headers, `Location`, or redirect sequence. Therefore D proves the route can return those exact bytes, but cannot establish whether its successful flow crossed the exact G redirect or whether the same two-POST sequence was used.

G records an official index GET and folder-link GET (HTTP 200), then a JSF selection POST to `https://mft.rrc.texas.gov/webclient/godrive/PublicGoDrive.xhtml` (HTTP 200 `text/xml;charset=UTF-8`, 1,157 bytes, SHA-256 `e946ec4bf51be0bcb91f451d64c4473fd2eb7c0cfee3f9934a0e4b74aa51057f`). A second POST to that JSF URL, from the same client/session, submitted the Download command and returned HTTP 302 with relative `Location: /servlets/fileServer`, content length 0, and the empty-body SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. It was not followed. The full per-request times, URL, status, content type, size, hash and raw capture paths are retained in G’s access receipt. No current attachment bytes or current hash exist.

## One bounded follow-up proposal

A separate packet may authorize a single manual hop only after the fresh same-session download POST returns HTTP 302 with exactly the relative location `/servlets/fileServer`:

- Allowlist only the existing official index URL, `https://mft.rrc.texas.gov/link/5f07cc72-2e79-4df8-ade1-9aeb792e03fc`, `https://mft.rrc.texas.gov/webclient/godrive/PublicGoDrive.xhtml`, and `https://mft.rrc.texas.gov/servlets/fileServer`.
- Disable automatic redirects. Make exactly one explicit HTTPS `GET` to the resolved same-host file-server URL, reusing only the ephemeral cookies from that fresh public GoDrive session. Do not retain cookies or ViewState values. The `GET` is the follow-up policy; D does not prove what method its browser/client used after any redirect.
- Use a 20-second request timeout, one-hop maximum, 5,000,000-byte response cap (read at most one sentinel byte beyond), and 12,000,000-byte total-run cap. Reject any other host/path, missing/changed session, non-200 response, another redirect, HTML/XML/login/error body, empty body, or body over the cap.
- Accept only a non-HTML/XML file response with `application/force-download` or an attachment `Content-Disposition`, then retain it under ignored `.artifacts/` with UTC, request/response metadata, bytes and SHA-256. Compare length to the fresh row’s advertised size as a plausibility check, not as a fixed exact byte count.
- If the received hash equals the already accepted F hash, report same-hash evidence only. If it is new, run the independent G compatibility verifier and sample check against those exact bytes; do not bypass or alter F’s pin.

If that one GET fails any condition, stop with REDIRECT/UNKNOWN; do not try another path or method. The public file-server response contract and D’s exact successful request sequence remain UNKNOWN until this bounded hop is observed. G remains **REDIRECT / UNKNOWN**; no source activation or parent GL3-015 completion follows.
