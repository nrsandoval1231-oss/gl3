# Isolated validation: published person contact methods

**Result: PASS for the bounded C29 retained-data replay and native source retrieval.** This proof validates three literal, company-published email methods for an existing electrical contractor in an isolated database. It does not change the frozen production census, establish purchasing authority, or prove the authenticated production UI.

The company is **Masters Electrical Services, Ltd** (canonical identity `080d8642-719f-4451-94aa-d88c17158bd7`), associated in the proof with project `79162cd1-4ac4-4dc1-8ff5-6f3e12aec653`. The fresh-clone native run observed the company's public team page at `2026-10-25 18:04:02 UTC` and the public contact page at `18:04:03 UTC`. The three published team-page emails and roles are listed in the [contact CSV](person-method-contacts.csv); no phone method was observed on the two pages. Purchasing authority for this power package remains UNKNOWN.

## What was verified

The retained phase passed same-job replay: the projection digest and row counts remained stable, the existing job ID was reused, and the associated account remained unchanged. The native R1 phase ran the existing discovery waterfall against a separate fresh clone restored from the same verified original snapshot. It completed the exact job, made two native HTTPS observations, added one isolated contact-discovery job, made zero paid provider calls, recorded zero provider cost, left the logical-call ledger unchanged, and created no company identity. The isolated account-contact API returned HTTP 200 with authentication; its unauthenticated route returned HTTP 401. This is API evidence, not a production-browser UI pass.

**Attempt history:** the first native attempt after retained validation correctly reused an already-known named contact under Level 1. The helper expected a fresh retrieval and stopped at that assertion before any HTTP retrieval or provider call. The R1 proof uses a separate fresh original-dump clone, so the normal pipeline could observe the official pages. No pipeline bypass or contact-value hint was used. Because the phase explicitly targeted two known official URLs, this is not a no-hint autonomous benchmark.

## Evidence and limits

The [sanitized proof JSON](person-method-proof.json) contains selected counts, source observations, exact source/report hashes, and protected-table aggregate comparisons. It excludes raw protected-row maps, biographies, and source passages. Both the retained and native reports bind to candidate base `3ce9e8a68a6b988d1d8bfd8597e150f19ae36498`; the native report's six frozen C28 source/test hashes were checked against the corresponding files.

This is isolated known-source validation, not an update to the separate 185-company production census or its coverage denominator. It makes no claim of a production deployment of these methods, direct buyer status, a no-hint benchmark improvement, or production authenticated UI acceptance. The production authenticated contact UI remains UNKNOWN.

The bounded C31 display correction now uses the latest valid method verification date in the existing opportunity card, matching the company panel's policy. Methodless professionals use a separately labeled source-check date; unknown dates stay unknown. Root verified all three real name/email pairs, source links, unconfirmed purchasing authority, dates, normal password login, mobile/desktop layout and persistence after reload through Cua. The restored browse generation was rebuilt using the existing retained-data maintenance command; no ingestion or provider call was needed. See [desktop proof](person-method-desktop.png), [mobile proof](person-method-mobile.png) and the [candidate validation receipt](person-method-validation.json). These screenshots show an isolated restore, not production.

The frozen C28 backend passed 3,026 tests and 7 subtests, with 3 skips; Ruff, formatting, full Mypy and unchanged generated API contracts passed. Frontend typecheck/build passed after the C31 runtime change. Browser regression execution and independent combined-candidate review remain separate release gates; their exact-candidate outcomes are recorded outside this source-proof snapshot.

[Download the three-contact CSV](person-method-contacts.csv) · [Read the machine-readable proof](person-method-proof.json)
