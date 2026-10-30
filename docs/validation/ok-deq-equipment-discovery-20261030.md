# Oklahoma equipment-facility discovery — October 30, 2026

This candidate follows PR153 and adds official source evidence intake, not verified equipment demand. No production operation, paid provider, migration, new source registration or UI change was performed.

## Source finding and implementation

The existing Oklahoma DEQ public-review adapter discarded ordinary compressor-station rows before downstream intelligence could inspect them. It now retains facility names explicitly containing **compressor station** or **gas processing plant**, alongside all existing matches. Company names alone do not trigger this additional filter. No drive, equipment rating, load, buyer or procurement assertion is generated.

A read-only public HTTP capture of the [official listing](https://applications.deq.ok.gov/PermitsPublicReview/) was retrieved on October 30 at approximately 05:46 UTC (minute precision). The original capture is 563,719 bytes, SHA-256 `fbf0fddcc7614d0d7eef5465f1e628bb48de171f8c127c8733c01dce9c4fbb05`. On those exact bytes the prior adapter retained **7 rows**, and this candidate retained **46 rows**, an increase of **39 discovery records**. This single capture does not establish ongoing coverage, opportunity precision or power demand. It stays below the unchanged 400-record / 2 MB response bounds.

The retained [fixture](../../backend/tests/fixtures/ok-deq-oil-gas-discovery-excerpt.html) and [manifest](../../backend/tests/fixtures/ok-deq-oil-gas-discovery-manifest.json) include three source-reported compressor-station rows and one unrelated brick-plant control. Header/row text is copied from the original, with CRLF normalized to LF; the original hash and normalized fixture hash are separate. Astra independently compared the original capture and selected content. The full capture is outside the tracked repository; the fixture does not represent the full listing.

Examples are Natural Gas Pipeline Co of America / Compressor Station 102, ET Gathering & Processing / Lippencott Compressor Station, and EnLink / Silver Compressor Station. Their dates are **public-comment windows**, not construction, commissioning or electricity demand dates. Renewal and existing-facility rows remain historical/contextual evidence, not new-demand claims.

The existing worker dispatch, source health, retries, HTTP allowlist, immutable evidence and replay semantics are reused. Ordinary ingestion retains the three example observations and evidence versions; repeated unchanged ingestion adds neither duplicate evidence nor a PowerNeed/equipment package. The legacy assessment rejects all three absent additional supported equipment or power facts.

## Validation

On the integrated PR153 repair base `8414fbc48e7a7be4401050e1e37b624c52fa669c`:

- Discovery, regional source, equipment parser and ingestion/replay checks: **59 passed in 4.20 seconds** using a disposable database and disabled providers.
- Source-specific and regional pure tests independently run by Astra: **28 passed** before the final integration; source code did not change afterward.
- Ruff lint and formatting passed, **415 files**. API schema, frontend, arithmetic, dependencies and migrations are unchanged by this slice.
- Full exact-head CI is required; the PR description and check suite record the final result. Local focused results alone are not the full gate.

The implementation used Sol 6.1/high architecture/coordination, Luna 6/low isolated implementation, and Astra 6/high independent review through the native OpenAI collaboration harness. The source intake and preceding PR153 repairs used three disjoint Luna lanes in this task.

## Explicit remaining work

Detail pages embed a document viewer; this static fetch did not retrieve engineering attachments. Public JavaScript exposes a separate vendor query/download protocol that needs its own bounded acquisition tests. No private endpoint or authenticated bypass was used. Do not infer absence of public document availability from this limited retrieval.

The official Texas Federal Register CP24-8 notice was rechecked and supports a historically proposed 18,340 hp electric compressor, but rating basis and efficiency remain unknown. It does not establish defensible electrical MW or current procurement. Two Pennsylvania replacement notices were useful out-of-region negative controls, not additional regional coverage.

Next: bounded attachment acquisition and a larger independently labeled TX/OK/NM engineering corpus; then source-native extraction into strict unverified candidates, independent database/entity verification, and deterministic demand modeling. Preserve unknowns, duplicates, changing drive/configuration and project timing. Buyer attribution and portfolio totals remain later work.

The source candidate subsequently integrated final PR153 repair `5030a2a2ca54c72ec9ca17cd3505f42df166c618`, preserving structured contradictory schedules and versioned binding history. The only merge conflict was the current checkpoint; both source scope and repair status are retained. Source behavior is unchanged. A new integrated exact-head CI run is required; the PR records its final result.
