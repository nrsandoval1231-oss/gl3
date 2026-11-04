# Permit-document gold set

`gold.jsonl`: one JSON object per line.

```
{doc_id, source, page_text_excerpt, expected_rows: [{equipment_id, type, rating_value, unit, count, drive}]}
```

- `page_text_excerpt` is a short verbatim excerpt (under 3,500 characters) of a public record's
  extracted text layer: Oklahoma DEQ permit memoranda, NMED air-quality applications and TCEQ
  NSR applications, as downloaded on 2026-11-03. Pages are separated by a form feed (`\f`).
  Excerpts keep source typography (for example U+2010 hyphens and `(cid:31)` glyph noise).
- `expected_rows` were written by hand from the excerpt text. They were never produced by running
  the parser. `equipment_id` is null for prose rows (the extractor assigns synthetic ids).
  `count` is null and `drive` is `unknown` unless the excerpt states them.
- The set deliberately includes traps and negatives: the West Edmond motor-versus-compressor
  rating case, regulatory threshold wording, a glossary line, drives named without ratings, and
  RBLC database listings of other facilities.
- Known limits: 30 excerpts is below the 50-100 target; no electric-drive evidence exists in the
  downloaded TX and NM documents, so electric cases come only from West Edmond; the extractor was
  tuned while looking at these same documents, so precision here is a development-set number.

`tests/unit/test_permit_gold.py` fails when field-level precision of the extractor's asserted
fields drops below 0.98 or when any extracted drive is wrong. Recall is reported, not gated.
