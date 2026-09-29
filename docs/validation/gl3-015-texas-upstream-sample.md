# GL3-015D RRC sample validation

Source: RRC nightly Drilling Permit Master + Trailer current-month GoDrive archive `daf420.dat`, retrieved 2026-09-29 01:06:53.605521 UTC and repeated 2026-09-29 01:34:03.826780 UTC. Both responses are 2,391,338 bytes, SHA-256 `c0215842369f14d6e725b011649ffa0076f373344e3ce5bb0d2ed411fce79cd6`. Raw responses, listings, and official manuals are retained locally under ignored `.artifacts/GL3-015D/raw/`; hashes and byte counts are catalogued in `.agent/artifacts/GL3-015D/retrieval-ledger.md`. machine-readable counts and all ten sampled records are in `../../.agent/artifacts/GL3-015D/sample-validation.json`.

The rows below are real records from the official feed. Row numbers are one-based lines in the retained file; each type-01 root record immediately precedes its type-02 permit detail. Stable sample identity is the source status number + sequence plus the API8 value; API8 is repeated across some permit records and must not alone be treated as revision-unique. “—” means blank/zero in this record, not an inferred date.

| File rows root/detail | Status number / seq | API8 | County code | Lease | Well | Received | Issued | Amended | Spud |
|---:|---|---|---|---|---|---|---|---|---|
| 1/2 | 0918584 / 99 | 00132879 | 001 | MUSTANG | 1 | 2026-09-10 | 2026-09-14 | — | — |
| 11/12 | 0917422 / 98 | 00349418 | 003 | FEE 'BV' | 2712WB | 2026-09-10 | 2026-07-29 | 2026-09-16 | 2026-09-17 |
| 54/55 | 0877584 / 98 | 00348541 | 003 | UNIVERSITY 8-14 | H 4LS | 2026-08-10 | 2022-03-07 | 2026-09-11 | 2022-07-21 |
| 150/151 | 0918767 / 99 | 00349452 | 003 | UL BLUE WATER 36-25 A | 1JM | 2026-09-17 | 2026-09-18 | — | 2026-09-23 |
| 220/221 | 0918769 / 99 | 00349453 | 003 | UL BLUE WATER 36-25 C | 1DN | 2026-09-17 | 2026-09-18 | — | — |
| 288/289 | 0918771 / 99 | 00349457 | 003 | UL BLUE WATER 36-25 D | 1WB | 2026-09-17 | 2026-09-22 | — | — |
| 356/357 | 0918527 / 99 | 00305265 | 003 | LOGSDON, ETAL -D- | 4 | 2026-09-09 | 2026-09-14 | — | — |
| 368/369 | 0918290 / 99 | 00943443 | 009 | ANDREWS 'D' | 1 | 2026-08-31 | 2026-09-08 | — | — |
| 386/387 | 0918736 / 99 | 01336315 | 013 | LBJ A | 1H | 2026-09-17 | 2026-09-23 | — | — |
| 433/434 | 0918737 / 99 | 01336316 | 013 | LBJ B | 2H | 2026-09-17 | 2026-09-23 | — | — |

Validation: 29,494 physical lines; 29,459 classified segments; 35 lines start with byte `0x85` and their meaning is UNKNOWN (unclassified and not semantically interpreted). 884 type-01 and 884 type-02 records; 884 adjacent root/detail pairs checked and 884 status-number/sequence matches. All 884 permit segments have nonzero API8; 868 distinct API8 values. 189 permit segments have nonzero spud date. The earlier dictionary-based pair-count value 16 in the first JSON draft was a faulty key-collision check and is superseded by the complete adjacent-pair result above; raw bytes were not modified. The prior line count had incorrectly been described as entirely classified; this is corrected above. Manual/file offsets differ in some DAPERMIT columns, so these samples prove bounded field extraction only for the identified parser profile and do not certify a production-ready parser.

Citation: RRC [daily permit manual](https://www.rrc.texas.gov/media/zgccdjpi/drillingpermitmasterpluslatitudeslongitudes_oga049m_july1.pdf) defines the application/permit sequence and the spud date as the date drilling started. Refer to the source-access report for cadence, other source families, and explicit gaps. These records do not prove completion, first production, operator/project grouping, power demand, fuel availability, or a commercial opportunity.
