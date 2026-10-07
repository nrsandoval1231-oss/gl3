# GL3-029 browser prerequisite recovery — October 7, 2026

**Latest full browser run: 38 passed, four failed, zero skipped/flaky, 35.27 seconds. Merge remains blocked.** This supersedes the earlier 37/5 browser result, which remains preserved. Product code is unchanged; tested documentation candidate `398b61f30a9975dbcea63553c3d06bf22794465e`.

## Recovered El Paso

The earlier real HTTP 200 public ArcGIS response remains in `scout-oilgas-body-5.txt`, acquired at 01:45:18 UTC. Its SHA-256 matches the acquisition receipt. The existing source adapter parsed BCTI25-00142; normal canonical ingestion added one rejected Observation and zero Signals in the isolated `gl3_regen_20261007_merge_browser` database. This was retained-response replay, not new retrieval. Original acquisition time remains in the receipt; import time is recorded separately. No access control was bypassed, and the later HTTP 403 receipts were preserved.

The complete mobile health/news/inbox/history browser test now passes with its assertions unchanged.

## Georgia acquisition attempted, evidence admission refused

The existing bounded Georgia adapter ran against the ordinary public Knack listing and Georgia EPD PDF GET routes. It made 29 public GET requests in 38.14 seconds with zero model calls and $0 provider cost. The adapter rejected `926258-nar/download` with `Georgia PDF does not bind the listed facility/application to its site location`. The source is reachable; this is an identity-admission failure, not missing provider credentials. The adapter returned no complete record set and no Georgia evidence was admitted. We did not weaken project matching, relabel historical excerpts as new source documents, or inject fabricated records.

Two live browser failures remain for Georgia air-equipment context and QTS ATL3 buying-chain enrichment. The downstream behaviors remain unvalidated in this corpus.

## Legacy pursuit prerequisites and authority

The two remaining failures are the saved Kramer call-outcome workflow and Clayton/Stassney conflict/refresh/history workflow. The legacy API intentionally excludes commercial-need snapshots; genuine legacy research rows are required. Existing retained artifacts contain historical TDLR URLs and excerpts, but no complete retained HTML suitable for canonical source replay.

The existing legacy worker performs anonymous TDLR public-search form POST requests before reading detail pages. Original instructions prohibit form submission; the later narrow RRC download approval does not cover TDLR. A specific authorization question is pending for that public-record search only, with the existing 350-second, 48-request, 12-candidate run bounds. No TDLR POST has been sent. After the 38/4 browser run, three exact Austin records (Kramer `2026-109172 EP`, Stassney `2026-119402 EP/BP`) were acquired with three successful public GETs and canonically imported into the isolated browser database: three new Observations and three accepted Signals. This prepares actual city evidence, not saved legacy research rows or resolved conflicts; no subsequent browser pass is claimed for this additional preparation. No paid-provider setup, outreach, deployment, or protection bypass is authorized.

Read [the safe receipt](gl3-029-browser-recovery-20261007.json) for acquisition and validation artifact hashes. The previous full backend (1,229 passed/one optional skip), migration preservation, replay and OpenAPI results remain source-equivalent; no product changes require rerunning them solely for this documentation checkpoint.

Historical temporary procedures are archived as non-executable text in `docs/validation/procedures/gl3-029-browser-{elpaso-replay,georgia-acquisition,austin-preparation}-20261007.py.txt`. They target the named isolated database and are not general operational launchers. Independent review verified all eight receipt hashes and the preparation chronology; no material corrections were identified.
