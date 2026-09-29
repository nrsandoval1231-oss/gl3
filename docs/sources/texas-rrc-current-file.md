# Texas RRC current daily permit file — bounded access result

## Access decision

**REDIRECT for the download path; current file hash and compatibility remain UNKNOWN.** The official source index and exact public GoDrive folder were reachable. The same-session JSF listing and row-selection event succeeded. The single bounded download-button request returned HTTP 302 with `Location: /servlets/fileServer` and an empty body. GL3-015G allowlisted only the official index, the exact public folder link, and the exact GoDrive JSF path; it disallowed redirects. The target was not followed, and no second file pull was attempted.

## Reproduction and retained evidence

From the repository root, a user-authorized access attempt is explicit:

```powershell
uv run --project backend python .agent/artifacts/GL3-015G/probe_current.py --fetch
```

The probe follows no redirects, uses a 20-second request timeout, reads at most 5,000,001 bytes per response to detect the 5 MB bound, caps the run at 12 MB, and allows at most two file pulls. It captures the official index, same-session listing, JSF selection response, and failed download response under ignored `.artifacts/GL3-015G/raw/`; it writes HTTP metadata to `.agent/artifacts/GL3-015G/access.json`. It retains no credentials.

For this run, UTC was `2026-09-29T11:50:44Z`. The official index GET returned 200 (`text/html`, 109,439 bytes; SHA-256 `d6a9db95abaa2478d4b4c40eafb03701bd50c05e4da46a3489ffe0865619ff37`). The exact current folder GET returned 200 (`text/html`, 298,699 bytes; SHA-256 `ea792a69eccf3ef2e6fe68e941744ceb5712773af9352992252a56fdf2aa7dcf`). It advertised exactly one `daf420.dat` row at index 0, modified `9/28/26 9:45:30 AM`, size `2.28 MB`.

The same-session row-selection POST returned 200 (`text/xml`, 1,157 bytes; SHA-256 `e946ec4bf51be0bcb91f451d64c4473fd2eb7c0cfee3f9934a0e4b74aa51057f`). The following download-button POST returned HTTP 302 on the exact JSF endpoint, `Location: /servlets/fileServer`, zero bytes. The empty failed response is retained as `20260929T115044281199Z-permit-1.dat`; no attachment hash exists. Total response bytes read were 409,295.

Raw response files are local and ignored. The tracked receipt contains per-request method, URL, status, content type, `Location`, response length, UTC, SHA-256, and raw evidence path. It contains no ViewState value or cookies. The 302 response is the stop condition; this packet did not follow it or try another route.

## Boundary

No current archive bytes were obtained. Therefore the new current-file hash, current-file type counts, permit sample, and compatibility result are **UNKNOWN**. This access attempt does not change the accepted GL3-015F hash pin or activate an RRC source. A follow-up packet would first need to explicitly validate the public file-server handoff under a bounded allowlist before requesting another attachment.
