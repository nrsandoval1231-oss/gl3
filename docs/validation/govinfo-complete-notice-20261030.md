# Bounded GovInfo notice capture — October 30, 2026

Repository candidate based on main `d54646c1600ff4f658d765fa0acf749a4166803c`. This is evidence acquisition, not a deployed engineering extraction or demand model.

## Measured problem and change

The existing Federal Register PDF companion reader retained only the first 1,200 normalized characters of a notice. In the actual June 12, 2024 notice `2024-12869`, the compressor rating appears at character 1,784 of the old title-bounded text, beyond that excerpt. The captured PDF is 229,868 bytes and two pages; its SHA-256 is `4d5d8293eebb47e41705b0b9f2aa027a6a898820c73913f6b33d7683b99127b6`.

The candidate retains a bounded complete target notice from its full title up to its validated matching Federal Register footer, with page markers and a page-range citation. It excludes adjacent notices and rejects ambiguous boundaries, unreadable intervening pages, wrong footers and oversized text instead of silently truncating. Existing byte/page/run/deadline limits remain. URL, document number and publication-package date must agree. The raw PDF hash remains the evidence identity.

The [actual PDF and provenance manifest](../../backend/tests/fixtures/govinfo-complete-notice/provenance.json) support an offline regression through the real PDF reader. This is one historical positive fixture, not measured broad source coverage. It describes a proposed electric compressor at Station 302 in Montgomery County, Texas, rated 18,340 hp. Rating basis, efficiency, current status, electrical MW, utility supply and procurement are not established.

## Integration and verification boundary

Only newly captured companion evidence receives the complete text. Existing same-hash evidence remains immutable, including earlier truncated excerpts; this change does not backfill them. Ordinary ingestion eligibility, unchanged-record behavior, interpretation, qualification, company/contact attribution and worker transaction/fencing remain unchanged. It does not make Federal Register O&G notices newly eligible for collection or publication.

Validation covers real-PDF notice boundaries, synthetic adversarial inputs and ordinary ingestion persistence/replay. The PR description and check suite record exact tested commits, independent review and full CI results. At receipt creation those final gates remain pending. Sol 6.1/high architecture, three Luna 6/low builder lanes and Astra 6/high review use the native OpenAI harness; no separate repository launcher was found.

A bounded Oklahoma public-viewer investigation confirmed its official API configuration, but the documented vendor metadata endpoint returned HTTP 403. No search POST or document-ID guessing followed. That protocol remains unverified; the GovInfo improvement reuses an existing accessible source instead.

No new dependency, migration, provider activation, production data operation or deployment. Next: verified source-native equipment extraction and demand binding, with source-specific eligibility, current timing, entity identity and independently tested abstention. Full-text retention alone does not create a demand record.
