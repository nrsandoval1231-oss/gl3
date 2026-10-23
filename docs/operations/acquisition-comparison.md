# M2 native and Firecrawl acquisition comparison

`config/comparisons/production-five-sources.v1.json` fixes the five case identities
and exact source URLs. Each immutable native receipt is one JSON file named for its
`case_id`; it may refer to sibling raw and extracted-text files. Preserve raw bytes,
full extracted text, and parser output. Native byte hashes (`raw_sha256`), extracted
text hashes (`text_sha256`), adapter capture identity, and any linked Evidence ID
and Evidence content hash are separate values. `capture_kind` must say
`COMPLETE_DOCUMENT`, `RECORD_EXCERPT`, or `INCOMPLETE`. Never call a record excerpt
the complete source document, and never truncate text to make it fit Firecrawl.
Raw sizes must remain within the existing native adapter byte bound in the manifest.

Inspect the capture set without provider dispatch:

```powershell
uv run --project backend python scripts/compare_acquisition.py --captures .agent/artifacts/PRODUCTION-M2-NATIVE --output .agent/artifacts/PRODUCTION-M2-ACQUISITION/inspection.json
```

The report file retains the complete bounded texts and fact-match evidence; stdout
prints only its completion state and artifact path.

The inspect path does not dispatch provider calls or write canonical project or
evidence state. Missing, invalid, or incomplete native captures remain visible and
keep the report incomplete. CSV/PDF media is `UNSUPPORTED` for Firecrawl; it remains
usable as native evidence. Eligible exact public HTML can be compared with one
bounded Firecrawl scrape through `extract_public_document` and the shared logical-call
ledger. The comparison preserves the Firecrawl logical-call ID, elapsed time,
provider-reported actual cost when available, and the ledger reservation. Unknown
calls remain unknown and are never retried; completed logical calls replay cached
responses. HTML whose complete native text exceeds Firecrawl's 30,000-character
bound is skipped by this local preflight before provider dispatch; that does not
demonstrate that Firecrawl itself cannot process the source. Selected parsed facts
are checked against literal source text with a match denominator; normalized values
that lack a literal match remain `UNVERIFIED`.

Paid execution requires the exact isolated loopback `pipeline_m2_app` database,
Firecrawl credentials and configured per-scrape cost, plus finite explicit call,
credit, and total cost caps. Example after those prerequisites are independently
verified:

```powershell
uv run --project backend python scripts/compare_acquisition.py --captures .agent/artifacts/PRODUCTION-M2-NATIVE --dispatch --max-calls 1 --max-credits 1 --max-cost-usd 0.01 --output .agent/artifacts/PRODUCTION-M2-ACQUISITION/live-comparison.json
```

The five rows are comparison cases, not five successful acquisitions. Overall
completion requires all five immutable native captures and a terminal Firecrawl
result for each eligible HTML case. At least one real HTML scrape is an operator
milestone gate; fixture tests do not establish it. This tool does not promote
commercial opportunities or alter source configuration.

## Bounded live result — 2026-10-23

The controller ran the documented one-call PUCT HTML comparison in the isolated
`pipeline_m2_app` database, then replayed the same intent from the ledger cache.
The first run completed one paid-provider request in 2,516 ms. Replay returned the
same logical call (`98960a5d-e5fd-4694-b302-26e20ea560ee`) as cached in 63 ms and
created no new call. Both runs returned 16/16 selected literal fact matches for
PUCT. The ledger reservation was `$0.010000`; provider actual cost and actual
invoice remain `UNKNOWN`. Observed account-credit metadata and its delta are not an
invoice or attributable cost measurement.

All five native captures were present and preserved. Native selected-fact
recovery and provider disposition were:

| Source case | Native recovery | Firecrawl result |
| --- | ---: | --- |
| Longhorn / TCEQ 400428 permit summary PDF | 4/4 | `UNSUPPORTED` for PDF; native evidence retained |
| PUCT docket index HTML | 16/16 | First run `COMPLETED`; replay cached the same call |
| TCEQ pending NSR listing HTML | 5/6 | Local preflight skipped 46,127-character text above the 30,000-character bound |
| Oklahoma DEQ public review HTML | 28/28 | Local preflight skipped 57,174-character text above the bound |
| Albuquerque building permits CSV | 24/39 | `UNSUPPORTED` for CSV; native evidence retained |

These outcomes establish one live HTML scrape and a successful immutable replay;
they do not establish five Firecrawl successes. Oversized HTML was not sent, so
those skips say nothing about the provider's ability to process it. PDF and CSV
remain native-only in this comparison.

The controller's TCEQ source inspection was `PARTIAL`: 328 records were fetched,
327 were parsed/scanned, and one detail-document fetch failed with HTTP 404
(`TCEQ-406704`). The source worker's defined scope is pending NSR case-by-case
applications; permits by rule and standard permits are outside that listing. TCEQ
began moving pending-application publishing to its Permit Search Portal on
August 31, 2026, so the listing may thin out. Do not treat this capture as
comprehensive TCEQ permit coverage.

The compact live receipts and report are retained at
`.artifacts/production-pipeline/m2-live-first/receipt.json`,
`.artifacts/production-pipeline/m2-live-replay/receipt.json`, and
`.artifacts/production-pipeline/m2-live-replay/report.json`. The TCEQ boundary
inspection is `.artifacts/production-pipeline/m2-tceq-inspection.json`. These
artifacts retain provenance and hashes; the large native texts are not copied
into this document.
