# Native RRC P5 company-route recovery — October 27, 2026

## Actual official-source evidence

The Railroad Commission of Texas [Oil & Gas Directory — Operator Contact page](https://www.rrc.texas.gov/oil-and-gas/research-and-statistics/operator-information/oil-gas-directory-operator-contact/) linked the [October 27 Excel directory](https://www.rrc.texas.gov/media/rnckkl2o/oil-and-gas-directory-10-27-26.xlsx). The downloaded XLSX was 808,328 bytes with SHA-256 `8c3d3c8aed8afdfb1dacb51557034aadad8e890ed1d32989a06ff7a0d948b40f`. A separate pinned-IP/TLS retrieval from the production host returned the same size and hash; its receipt is retained with the release controller's source evidence.

The workbook contains one `Oil and Gas Directory` worksheet, 7,560 uniquely numbered organization rows, and the exact columns `Org Number`, `Org Name`, `Phone`, `Emergency`, and `P5 Status` among its full 14-column header. Six additional contact rows have no operator number and are skipped because they cannot be joined to a canonical RRC identity. The workbook header reads `10/27/2026 12:01:48 PM`; its time zone is unspecified. A fresh retrieval of the landing page states that information is updated nightly and that downloadable files contain data as of October 27th, 2026. An earlier observation recorded July 10, 2026; that date was not reproduced in the fresh retrieval and is not treated as current page evidence. The landing statement, workbook header timestamp, filename date, and retrieval observation time remain distinct provenance fields. None of these dates establishes independent phone verification or a project's power-need timing.

## Frozen cohort source coverage

The unchanged frozen 25 contains 21 RRC upstream project records and four TDLR data-center registrations. Exact six-digit operator-number joins and the existing legal-suffix-only `_brand_key` comparison found:

| Measure | Result |
| --- | ---: |
| Frozen RRC project rows with an exact P5 operator-number row | 21 / 21 |
| Unique RRC operator numbers in those project rows | 17 |
| Unique operators whose P5 organization name matches the source-backed name | 17 / 17 |
| Unique operators with a ten-digit normal `Phone` value | 17 / 17 |
| Distinct normal phone values among those operators | 17 |
| P5 statuses among those operators | 15 `Active`, 2 `ActiveExtension` |

The phone values are in the ordinary organization `Phone` column. The parser does not retain or use the separate `Emergency` values. One shared company route can therefore cover multiple selected project records when they have the same source-backed operator identity; project-record coverage and unique methods remain separate counts.

The October 26 API baseline had four existing generic company routes, all on the four TDLR records, and no RRC route among the 21 RRC records. The source supports a potential generic-route increment of 21 RRC project rows and 17 unique methods. This is source-row availability, not an observed persisted 25/25 result. The full frozen 25 has not yet been replayed through the new worker path on a retained real-data clone.

## Implemented behavior and boundaries

`rrc_operator_directory` follows only the fixed official RRC page to one dated XLSX on the same exact HTTPS host. It uses public-IP pinning, original-host TLS/SNI, `trust_env=False`, no redirects, a 25-second retrieval deadline, byte limits, ZIP expansion and row bounds, strict worksheet/header/status checks, and fails closed on duplicate operator rows. It requires one exact operator number, a unique `_brand_key` legal-suffix match, an `Active` or `ActiveExtension` P5 status, and a valid normal `Phone` value before producing a generic company route.

The P5 row, raw workbook SHA-256, filename date, workbook header timestamp/date, landing-page freshness statement, and original observed time are preserved in the cited evidence excerpt. The 24-hour in-process cache preserves the original observation time; replay does not move evidence `last_seen_at`. New claims use the normal append-only company-route writer and current privacy projections. No person is named, no role is inferred, and no emergency number, direct buyer, authority, power load, gap, or qualification is promoted.

## Verification

The adapter parser was run against the actual downloaded workbook and returned 7,560 uniquely numbered rows with the hash above. Unit tests use clearly synthetic workbooks for bounds, parsing, cache, identity, status, ambiguity, and normal-phone-only behavior. A PostgreSQL job-path regression uses a synthetic P5 snapshot to verify claim/evidence persistence, company projection, original observation timestamps, no person promotion, and method suppression. A separate regression verifies the contact-planner retrieval-policy change queues one new bounded job and that unchanged re-planning deduplicates while `INTELLIGENCE_ENABLED=false`.

The synthetic job test establishes software behavior only. Frozen-cohort persisted contact coverage, production job execution, direct callability, independent deliverability, and decision authority remain unmeasured by this change.
