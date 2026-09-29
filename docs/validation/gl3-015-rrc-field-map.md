# GL3-015E — RRC daily permit field-map validation

## Decision

**GO for the named type-01/type-02 fields on this exact retained archive.** The observed offsets and core field meanings pass full-snapshot and cross-record checks. This is a version-pinned read-only parser proof; it does not activate a source, certify every manual field, classify the 35 `0x85` lines, or establish completion/production records. A separate adapter packet may proceed only using the profile and quarantine constraints below.

## Evidence and reproducible check

The input archive is the ignored local file `.artifacts/GL3-015D/raw/rrc-daily-permit-current-month.bin`, 2,391,338 bytes, SHA-256 `c0215842369f14d6e725b011649ffa0076f373344e3ce5bb0d2ed411fce79cd6`. Its official drilling-permit manual is the ignored local `drilling-permit-daily-manual.pdf`, 162,000 bytes, SHA-256 `760a25367df8fb3bd7b240a41d9471953e2ee1eab1878d5367c673548adec874`. The public manual URL is [RRC Drilling Permit Master + Trailer Manual](https://www.rrc.texas.gov/media/zgccdjpi/drillingpermitmasterpluslatitudeslongitudes_oga049m_july1.pdf). The exact field profile is [field-map.json](../../.agent/artifacts/GL3-015E/field-map.json); the validator is [validate_rrc_field_map.py](../../.agent/artifacts/GL3-015E/validate_rrc_field_map.py).

Run from the `gl3-015` checkout:

```powershell
uv run --project backend python .agent/artifacts/GL3-015E/validate_rrc_field_map.py --receipt .agent/artifacts/GL3-015E/validation.json
```

The completed run is retained in [validation.json](../../.agent/artifacts/GL3-015E/validation.json) and [validator-output.json](../../.agent/artifacts/GL3-015E/validator-output.json). It used only Python standard-library code and made no network, application, or database calls.

## Field offsets and semantics

Offsets are zero-based, half-open byte spans in the downloaded file. Mapped fields are ASCII; numeric identifiers stay strings to preserve zeroes. Text display trimming never changes raw evidence. The official manual’s `POS` values are one-based starts.

| Field | Segment | Observed byte span | Manual field / meaning | Evidence |
|---|---|---:|---|---|
| Record type | 01, 02 | `[0,2)` | RRC tape record ID | All 884 roots and 884 permit rows have the expected ID and fixed length. |
| Status/permit number | 01, 02 | `[2,9)` | Seven-digit W-1 status/permit number; modern approved applications use the same number | 884/884 root/detail key matches; 884 unique number + sequence pairs. Manual printed II.2, II.4, II.18–II.19. |
| Sequence | 01, 02 | `[9,11)` | Original is 99; each amendment decrements the prior sequence | Counts: 99=647, 98=190, 97=43, 96=4. Every 98/97/96 row has a nonzero amended date; all 99 rows have zero amended date in this snapshot. Manual II.5 and II.19. |
| Reported county / lease | 01 | `[11,14)`, `[14,46)` | Operator-reported W-1 fields | Manual II.5–II.6. |
| Approved county / lease | 02 | `[11,14)`, `[14,46)` | RRC-approved fields | Lease bytes match root in all 884 pairs. County differs in three pairs; manual defines root county as operator-reported and permit county as approved, so the two meanings are kept distinct. Manual II.19. |
| Application status | 01 | `[100,101)` | `A` means approved | All 884 root rows are `A`; manual II.2 and II.7. |
| Permit number / issue date | 01 | `[112,119)`, `[119,127)` | Assigned at approval; approval date | Number matches status number and type-02 permit number in all 884 pairs; issue date matches type-02 issue date in all pairs. Manual II.3 and II.10. |
| Application received | 01 / 02 | `[58,66)` / `[121,129)` | W-1 received in Austin, `CCYYMMDD` | Root and permit values equal and valid calendar dates in all 884 pairs. Manual II.6 and II.23. |
| Permit issued | 02 | `[129,137)` | Date W-1 was approved, `CCYYMMDD` | 884/884 valid dates; agrees with root issue date. Manual II.23. |
| Permit amended | 02 | `[137,145)` | Date permit amended, `CCYYMMDD` | 237 valid nonzero dates; zeros retained literally. Manual II.23. |
| Permit extended | 02 | `[145,153)` | Date permit extended, `CCYYMMDD` | No nonzero values in this snapshot; zeros retained. Manual II.24. |
| Spud | 02 | `[153,161)` | Date drilling started, `CCYYMMDD` | 189 valid nonzero dates; zero rows do not assert that drilling did not start. Manual II.24. |
| API8 | 02 | `[502,510)` | Eight-digit wellbore number; manual describes 3-digit county + 5-digit unique suffix | All 884 are digits and API county prefix matches approved county. Manual II.17 and II.32; repeat-value caveat below. |
| Well number | 02 | `[48,54)` | Six-character W-1 well number | Manual II.14 and II.11. |

All nonzero mapped date values parsed as real calendar dates. The source’s `00000000` is retained as zero/no encoded date; it is not converted into an asserted negative lifecycle event. The supported normalized milestone meanings are application receipt, permit approval/issue, amendment, extension, and spud as defined by the manual.

## Offset reconciliation and limits

The manual’s type-02 layout on printed II.13–II.17 shows a leading record ID at POS 1 and another record-ID field at POS 3, with permit number beginning at POS 5. The downloaded type-02 records are exactly 510 bytes and contain `02` at bytes `[0,2)` followed immediately by the seven-digit number at `[2,9)`; there is no second `02` at bytes `[2,4)`. The daily-file profile therefore uses `observed_start = manual_POS - 3` (zero-based), two positions earlier than the PDF layout. In contrast, type-01 root fields map directly as `observed_start = manual_POS - 1`.

This explains and validates the offset adjustment for the fields in the profile, rather than silently shifting them: 884/884 root/detail keys match; root and permit received dates and issue dates match 884/884; API county prefixes match 884/884; all ten GL3-015D sample identities and fields reproduce exactly. The mapping is bound to the two SHA-256 values above; it must not be applied to a different RRC file/version without revalidation.

The PDF is not a complete serialization contract for this download. The root layout includes a filler to nominal position 510 while daily root records are 212 bytes; only mapped root fields through position 120 are validated. Printed II.17 places `RRC-TAPE-FILLER` at POS 503 overlapping `API-NUMBER` at POS 505. That filler is **UNKNOWN/unmapped** and excluded; API8 is mapped to the observed final eight bytes and cross-checked against the approved county prefix. No other type-02 filler or trailing fields are asserted.

The archive contains 29,494 CRLF physical lines: 29,459 classified segments, plus 35 lines beginning with byte `0x85`. The 0x85 lines’ meaning is **UNKNOWN**; the validator counts and quarantines them without decoding. It rejects malformed fixed lengths for type 01/02 and rejects non-CRLF input. Other segment families include variable record lengths (for example type 08 has eight observed lengths; type 11 has 24), and their fields are outside this profile.

API8 has 868 distinct values among 884 permit records, with 16 repeated-value groups. Thirteen repeats are the same permit number at different sequences; three groups appear under different permit numbers. The manual describes API as a unique wellbore identifier, but this archive does not establish the relationship in those three cases. Therefore API8 is not used as a permit-revision key or to join permits; status/permit number plus sequence is the validated record key. Do not infer pad/site/project grouping, first production, power need, or opportunity status.

## Next packet boundary

Issue a separate adapter packet limited to the hash-pinned type-01/type-02 profile, permit-number-plus-sequence identity, and explicitly defined dates. Preserve the raw archive outside Git, preserve zero date strings, count/quarantine unknown rows without interpreting them, and expose the source hash/profile version. Keep pending applications, completion, production, future file versions, and the unmapped manual fields UNKNOWN until separately validated. No source activation follows from this proof.
