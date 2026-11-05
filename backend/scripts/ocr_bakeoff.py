#!/usr/bin/env python3
"""Offline OCR bake-off over recorded transcripts. Makes no network or provider call.

    uv run python scripts/ocr_bakeoff.py \
        --gold tests/fixtures/ocr_bakeoff/gold_set.json \
        --recordings tests/fixtures/ocr_bakeoff/recordings.json [--json out.json]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gridlens.intelligence.ocr_bakeoff import render_markdown, run_bakeoff, scores_as_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--recordings", type=Path, required=True)
    parser.add_argument("--json", type=Path, help="also write machine-readable scores here")
    args = parser.parse_args()
    scores = run_bakeoff(args.gold, args.recordings)
    print(render_markdown(scores))
    if args.json:
        args.json.write_text(json.dumps(scores_as_json(scores), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
