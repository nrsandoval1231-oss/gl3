#!/usr/bin/env python3
"""Build a local hash and citation manifest for contact-refresh evidence.

This is an offline reproducibility helper. It reads only the captured Firecrawl
responses in raw/ and writes source-manifest.json. It performs no network calls.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
OUT = ROOT / "source-manifest.json"

# These are publication dates stated in the body of the captured publisher page.
PUBLISHER_DATES = {
    "aws-madison-announcement": ("2024-01-25", "Published:January 25, 2024"),
    "microsoft-fairwater-announcement": ("2025-09-18", "Sep 18, 2025"),
    "microsoft-pecos-datacenter-post": ("2026-06-22", "Jun 22, 2026"),
}

# Filing dates come from captured SEC filing indexes; they are not publication dates.
SEC_FILINGS = {
    "sec-apld-10k": ("2026-07-29", "10-K", "sec-apld-index"),
    "sec-equinix-10k": ("2026-02-11", "10-K", "sec-equinix-index"),
    "sec-microsoft-10k": ("2026-07-29", "10-K", "sec-microsoft-index"),
    "sec-meta-10k": ("2026-01-29", "10-K", "sec-meta-index"),
    "sec-dominion-annual-report": ("2026-03-19", "ARS", "sec-dominion-index"),
}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> None:
    sources = []
    records = {}
    for path in sorted(RAW.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        source_id = record.get("slug", path.stem)
        records[source_id] = record
        if (RAW / f"{source_id}.md").exists():
            for excerpt in record.get("excerpts", []):
                if sha256(excerpt.get("text", "")) != excerpt.get("sha256_utf8"):
                    raise SystemExit(f"excerpt hash mismatch: {path.name}:{excerpt.get('label')}")
            continue
        markdown = record.get("markdown")
        filed = re.search(r"Filing Date\s+(\d{4}-\d{2}-\d{2})", markdown or "")
        publication = PUBLISHER_DATES.get(source_id)
        filing_type = re.search(r"Type:\s*\*\*(.*?)\*\*", markdown or "")
        source = {
            "source_id": record.get("slug", path.stem),
            "url": record.get("url"),
            "page_title": (record.get("metadata") or {}).get("title"),
            "observed_at": record.get("observed_at", "2026-11-13"),
            "publication_date": publication[0] if publication else None,
            "publication_date_status": (
                "explicit date in captured publisher text" if publication else "not stated in captured page"
            ),
            "retrieval": record.get("retrieval", "Firecrawl page scrape; full Markdown retained"),
            "raw_file": str(path.relative_to(ROOT)),
        }
        if publication:
            source["publication_date_evidence_quote"] = publication[1]
        if filed:
            source["filing_date"] = filed.group(1)
            source["filing_date_status"] = "SEC filing index Filing Date field"
            if filing_type:
                source["filing_type"] = filing_type.group(1)
        if isinstance(markdown, str):
            digest = sha256(markdown)
            source.update(
                {
                    "source_text_sha256_utf8": digest,
                    "source_text_chars": len(markdown),
                }
            )
        excerpts = []
        for excerpt in record.get("excerpts", []):
            text = excerpt.get("text", "")
            digest = sha256(text)
            if excerpt.get("sha256_utf8") not in (None, digest):
                raise SystemExit(f"excerpt hash mismatch: {path.name}:{excerpt.get('label')}")
            excerpt["sha256_utf8"] = digest
            excerpts.append({"label": excerpt.get("label"), "sha256_utf8": digest, "chars": len(text)})
        if excerpts:
            source["source_text_mode"] = "verbatim excerpts from Firecrawl-rendered SEC Markdown"
            source["excerpts"] = excerpts
        sources.append(source)
    for path in sorted(RAW.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        record = records.get(path.stem, {})
        meta = record.get("metadata") or {}
        source = {
                "source_id": path.stem,
                "url": record.get("url") or meta.get("sourceURL") or meta.get("url"),
                "page_title": meta.get("title"),
                "observed_at": record.get("observed_at", "2026-11-13"),
                "publication_date": None,
                "publication_date_status": "not stated in the SEC document; SEC filing date is separate",
                "retrieval": record.get("retrieval")
                or "Firecrawl SEC HTML scrape rendered as complete Markdown; raw text retained in raw/",
                "raw_file": str(path.relative_to(ROOT)),
                "source_text_sha256_utf8": sha256(text),
                "source_text_chars": len(text),
                "source_text_bytes": len(text.encode("utf-8")),
                "source_text_mode": "complete Firecrawl-rendered SEC Markdown",
            }
        filing = SEC_FILINGS.get(path.stem)
        if filing:
            source.update(
                {
                    "filing_date": filing[0],
                    "filing_type": filing[1],
                    "filing_date_source_id": filing[2],
                    "filing_date_status": "captured SEC index Filing Date field",
                }
            )
        for excerpt in record.get("excerpts", []):
            source.setdefault("excerpts", []).append(
                {
                    "label": excerpt.get("label"),
                    "sha256_utf8": sha256(excerpt.get("text", "")),
                    "chars": len(excerpt.get("text", "")),
                }
            )
        sources.append(source)
    OUT.write_text(
        json.dumps({"schema_version": "gridlens-contact-refresh-source-manifest-v1", "sources": sources}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT.name}: {len(sources)} sources")


if __name__ == "__main__":
    main()
