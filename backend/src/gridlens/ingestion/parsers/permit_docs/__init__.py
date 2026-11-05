"""Deterministic, offline permit-document extraction core (no network, LLM or database)."""

from gridlens.ingestion.parsers.permit_docs.pipeline import (
    PermitExtractionResult,
    extract_from_canonical,
    extract_from_pages,
    extract_permit_document,
)
from gridlens.ingestion.parsers.permit_docs.schedule import VERSION

__all__ = [
    "VERSION",
    "PermitExtractionResult",
    "extract_from_canonical",
    "extract_from_pages",
    "extract_permit_document",
]
