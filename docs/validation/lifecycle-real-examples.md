# Asset lifecycle validation examples

These bounded examples exercise classification and timing only. They are not claims of national
coverage, an open power gap, or Prospect/Lead qualification. Source facts remain distinct from the
derived GridLens interpretation.

## Data center — Meta Temple, Texas campus

* **Pre-permit/formation:** Meta's March 31, 2022 announcement identifies Temple as a new data-center
  location and says construction was beginning. Source: [Meta announcement](https://about.fb.com/news/2022/03/metas-new-data-center-in-temple-texas/).
* **Permit/construction:** the same announcement reports construction; GridLens classifies that event
  as `construction`. It does not infer unreported planning, electrical, or commissioning milestones.
* **Commissioning/utility:** no source was accepted for this bounded example, so those phases remain
  unknown rather than being invented.

This illustrates why a later building permit would normally monitor/enrich the known campus timeline
when site and project identity corroborate it, rather than create a project merely because Meta is named.

## Upstream — Oklahoma reported drilling record calculation

The deterministic test uses the real-world field shape published in the Oklahoma Corporation
Commission's [well-data system](https://www.occ.ok.gov/divisions/oil-gas/og-online-data): operator,
county, API/well identity, permit date and later spud/completion milestones. The checked calculation
uses a reported permit anchor of `2026-01-10` for API `35-011-12345` in Blaine County and produces a
**derived**, explicitly labeled `2026-07-09`–`2027-07-04` first-production/power window under
`upstream-production-v1` (180–540 days). This repository does not claim that illustrative API/date
pair is a live OCC result; live record retrieval remains a limitation. A reported spud on `2026-04-01`
would update the deterministic window to `2026-05-31`–`2026-11-27` (60–240 days).

## Fixed O&G — Colonial Terminals, Austell

The retained real Georgia EPD review fixture identifies Colonial Terminals Operating Company LLC's
Austell terminal, Application 30031, and cites the adjacent Colonial Pipeline Atlanta Junction.
GridLens classifies a terminal permit/application as fixed-infrastructure regulatory evidence, not an
upstream-well clock. The source text says the application proposes no production-process or equipment
change, so existing qualification correctly rejects it as a new opportunity. Source:
[Georgia EPD draft permits](https://epd.georgia.gov/draft-title-v-permitsamendments-other-draft-permits).

## Current limitations

Migration 0006 records project identity provenance, removes only lifecycle dates unsupported by
retained event-date fields, and resets projections affected by that repair. Run the explicit
`uv run --project backend python scripts/replay_lifecycle_history.py` after migration to rebuild lifecycle events from
accepted interpretations whose assessment is bound to a retained evidence hash. Replaying twice is
idempotent; old event rows remain as history, and superseded rows are marked in the API timeline.
Unbound legacy assessments are reported as skipped rather than inferred. Timing v1 uses transparent
broad ranges, not learned operator/basin distributions. No source-specific upstream adapter or live
OCC example is added in this slice.
