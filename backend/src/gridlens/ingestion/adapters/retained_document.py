"""Exact-source, offline importer for the reviewed F17 retained PDFs."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

SOURCES: dict[str, dict[str, Any]] = {
    "f17-stack-city-claim": {
        "path": "stack-city-claim-original.pdf",
        "sha256": "ccc92aea483b84f9afe0436e2fb9d515cf2fe99a05e19a1f270a0c4fd53a6deb",
        "url": "https://santaclara.legistar.com/View.ashx?GUID=41D90CA3-8232-4978-9508-DB1418113E87&ID=1349150&M=E2",
        "publisher": (
            "City of Santa Clara agenda attachment; claimant 1220 Santa Clara Propco, LLC / STACK"
        ),
        "publication_date": None,
        "event_date": "2024-06-24",
        "event_date_label": "Claim document date; later included in the April 7, 2026 agenda",
        "wrapper_date_evidence": {
            "packet_printed_date": "2026-04-02",
            "agenda_meeting_date": "2026-04-07",
            "basis": "Dates printed in retained city agenda packet; not the claim publication date",
        },
        "spans": ((14, 18), (20, 21)),
        "site_cue": "1200 Memorex Drive",
        "activity": "utility-service",
        "project_cue": "SVY02A",
        "location": "1200 Memorex Drive, Santa Clara, CA",
        "location_cues": ("1200 Memorex Drive", "Santa Clara"),
        "rationale_kind": "stack_claim",
        "required_terms": ("18 MVA", "2028", "28 MVA", "31 MVA"),
    },
    "f17-stack-cec-filing": {
        "path": "stack-cec.pdf",
        "sha256": "33d0ed5f40f21fbcd74502a4c92d8c0373ac73c417e8b3046a7deba965806340",
        "url": "https://efiling.energy.ca.gov/GetDocument.aspx?tn=261716",
        "publisher": "California Energy Commission docket 25-IEPR-03; STACK party submission",
        "publication_date": "2025-02-12",
        "event_date": "2025-02-11",
        "event_date_label": "Date of STACK letter in CEC filing",
        "spans": ((1, 6), (16, 18), (40, 40), (50, 52)),
        "site_cue": "1200 Memorex Drive",
        "activity": "utility-service",
        "project_cue": "Memorex Junction",
        "location": "1200 Memorex Drive, Santa Clara, CA",
        "location_cues": ("1200 Memorex Drive", "Santa Clara"),
        "rationale_kind": "stack_cec",
        # The retained draft table extracts its MVA header apart from the
        # numeric rows, so require both source rows and the table unit header.
        "required_terms": (
            "vastly underserved",
            "draft",
            "table e1 - available capacity schedule",
            "(mva)",
            "28 10 20",
            "31 10 30",
        ),
    },
    "f17-crusoe-impact": {
        "path": "crusoe-impact-publisher-linked.pdf",
        "sha256": "38ca3db4c94206be9e8b2ee1e3b5fa1239b00948c50b3ac0e102e6d7f1773619",
        "url": "https://cdn.prod.website-files.com/6855c1aa175582ee23e0aa19/6aa975443d2a8405e214f067_Crusoe_2025_Impact%20Report2_web_optimized.pdf",
        "publisher": "Crusoe 2025 Impact Report; publisher-linked PDF",
        "publication_date": None,
        "event_date": "2025-12-31",
        "event_date_label": "Report status date, generally as of December 31, 2025",
        "spans": ((2, 2), (15, 16), (19, 19)),
        "site_cue": "Abilene Stargate",
        "activity": "bridge-power",
        "project_cue": "Abilene Stargate",
        "project_suffix": "campus",
        "location": "near Abilene, Texas",
        "location_cues": ("Abilene", "Texas"),
        "location_pattern": r"near\s+Abilene,\s+Texas",
        "rationale_kind": "crusoe_bridge",
        "release_date_evidence": {
            "date": "2026-05-28",
            "basis": (
                "Publisher blog displayed report release date; its modified date is "
                "2026-09-15; exact PDF byte publication date remains unknown"
            ),
            "blog_modified_date": "2026-09-15",
            "blog_url": "https://www.crusoe.ai/resources/blog/crusoes-2025-impact-report",
        },
        "required_terms": ("temporary", "bridge power", "grid upgrades catch up"),
    },
}
MAX_BODY_BYTES = 80_000_000
MAX_EXCERPT_CHARS = 80_000


def extract(source_id: str, root: Path) -> dict[str, Any]:
    """Verify exact original bytes and return one bounded, cited source record."""
    policy = SOURCES.get(source_id)
    if policy is None:
        raise ValueError("Unreviewed retained source")
    source_path = root / policy["path"]
    size = source_path.stat().st_size
    if size > MAX_BODY_BYTES:
        raise ValueError("Retained document exceeds the reviewed size limit")
    # Bound memory independently of stat() in case the retained file changes
    # between the metadata check and the read.
    with source_path.open("rb") as handle:
        body = handle.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("Retained document exceeds the reviewed size limit")
    if not body.startswith(b"%PDF-"):
        raise ValueError("Retained document MIME or size is outside policy")
    digest = hashlib.sha256(body).hexdigest()
    if digest != policy["sha256"]:
        raise ValueError("Retained document hash mismatch")
    reader = PdfReader(bytes_stream(body))
    excerpts: list[str] = []
    citations: list[str] = []
    for start, end in policy["spans"]:
        if end > len(reader.pages):
            raise ValueError("Reviewed page span exceeds document length")
        text = "\n".join(
            reader.pages[index - 1].extract_text() or "" for index in range(start, end + 1)
        )
        if text.strip():
            excerpts.append(text)
            citations.append(f"PDF pp. {start}-{end}")
    excerpt = "\n\n".join(excerpts)
    if len(excerpt) > MAX_EXCERPT_CHARS:
        raise ValueError("Reviewed-page extraction exceeds the text limit")
    if not excerpt.strip():
        raise ValueError("No text extracted from reviewed page spans")
    normalized = re.sub(r"\s+", " ", excerpt).casefold()
    # PDFs sometimes insert whitespace inside unit abbreviations while
    # extracting; this normalizes only typography, preserving MVA as MVA.
    normalized = re.sub(r"(\d+)\s*m\s*v\s*a\b", r"\1 mva", normalized)
    if policy["project_cue"].casefold() not in normalized:
        raise ValueError("Reviewed pages do not contain the expected literal project cue")
    if not all(term.casefold() in normalized for term in policy["required_terms"]):
        raise ValueError("Reviewed pages lack one or more required source-context passages")
    location_match = re.search(re.escape(policy["site_cue"]), normalized, re.IGNORECASE)
    if location_match is None:
        raise ValueError("Reviewed pages do not contain the expected literal site cue")
    if source_id.startswith("f17-stack"):
        project_parts = [
            value
            for cue, value in (
                ("SVY02A", "SVY02A"),
                ("Memorex Junction", "Memorex Junction"),
            )
            if cue.casefold() in normalized
        ]
        name = f"{' / '.join(project_parts)} data center"
    else:
        project = re.search(re.escape(policy["project_cue"]), excerpt, re.IGNORECASE)
        if project is None:
            raise ValueError("Reviewed pages do not contain the expected literal project cue")
        name = f"{project.group(0)} campus"
    location = policy["location"]
    # The canonical location is accepted only when its literal street/city cues
    # are present in the selected source text; it is never appended as a new claim.
    if not all(part.casefold() in normalized for part in policy["location_cues"]):
        raise ValueError("Selected source pages do not support the physical-site location")
    if policy.get("location_pattern"):
        location_match = re.search(policy["location_pattern"], excerpt, re.IGNORECASE)
        if location_match is None:
            raise ValueError("Selected source pages do not support the reviewed location phrase")
        location = re.sub(r"\s+", " ", location_match.group(0)).strip()
    title = f"{name} — retained filing/report"
    abstract = f"{policy['publisher']}\n\n{excerpt}"
    provenance = {
        "path": policy["path"],
        "sha256": digest,
        "publisher": policy["publisher"],
        "reviewed_spans": citations,
        "source_site": location,
        "project_name": name,
        "activity": policy["activity"],
    }
    if policy.get("wrapper_date_evidence"):
        provenance["wrapper_date_evidence"] = policy["wrapper_date_evidence"]
    if policy.get("release_date_evidence"):
        provenance["release_date_evidence"] = policy["release_date_evidence"]
    return {
        "document_number": source_id,
        "title": title,
        "abstract": abstract,
        "html_url": policy["url"],
        "publication_date": policy["publication_date"],
        "event_date": policy.get("event_date"),
        "event_date_label": policy.get("event_date_label"),
        "extraction_location": "; ".join(citations),
        "source_hash": digest,
        "retained_document": provenance,
    }


def bytes_stream(body: bytes):
    from io import BytesIO

    return BytesIO(body)
