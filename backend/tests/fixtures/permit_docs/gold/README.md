# Permit-document gold set

`gold.jsonl`: one JSON object per line.

```
{doc_id, source, page_text_excerpt, expected_rows: [{equipment_id, type, rating_value, unit, count, drive, state?}]}
```

- 30 entries are short verbatim excerpts (under 3,500 characters) of the text layer of public
  records downloaded on 2026-11-03: Oklahoma DEQ permit memoranda, NMED air-quality applications
  and TCEQ NSR applications. Pages are separated by a form feed. Excerpts keep source typography
  (U+2010 hyphens, `(cid:31)` glyph noise).
- 9 entries have `source` "Synthetic regression case": tiny hand-written negatives and
  positives for the review findings (neighbour-line bleed in capacity tables, rating and noun on
  different lines, RBLC listings, prose plus table describing the same units, list numbering read
  as a count, removed or replaced equipment, a count word on the previous line, a group-title
  drive on the wrong noun). They are not public records.
- `expected_rows` were written by hand from the excerpt text. They were never produced by running
  the parser. `equipment_id` is null for prose rows. `count` is null and `drive` is `unknown`
  unless the excerpt states them. `state` is optional and scored only where present.
- Other negatives: the West Edmond motor-versus-compressor trap, regulatory threshold wording,
  a glossary line, drives named without ratings.

`tests/unit/test_permit_gold.py` has three gates and one report:

1. `test_gold_field_precision`: field-level precision of the fields the extractor asserts,
   each of type, rating, unit, count, drive and state scored independently, at least 0.98; any
   wrong drive fails outright.
2. `test_gold_claims_are_exact`: zero tolerance on `result.claims`. Every demand claim must
   match one expected row exactly and no claim may be left over.
3. `test_gold_set_is_large_enough_and_well_formed`.
4. `test_gold_recall_is_reported` prints recall and asserts only a loose floor.

Limits: 39 entries is below the 50-100 target. No electric-drive evidence exists in the
downloaded TX and NM documents, so electric cases come only from West Edmond and the synthetic
cases. The extractor was tuned while looking at the 30 public excerpts and was fixed against the
9 synthetic cases, so precision here is a development-set number, not a holdout estimate.
