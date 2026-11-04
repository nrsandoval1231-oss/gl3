# Parsers

Parse structured files, web pages, and public documents into source-linked observations. Keep content hashes and extraction locations. Parse failures must preserve the previous accepted state.

## permit_docs

`permit_docs/` is the deterministic, offline permit-PDF extraction core (`permit-doc-extract-v1`): canonical text layer with page/line geometry, page router, header-keyed table and narrative extractors, an exact-span verifier, and a schedule renderer that emits `equipment-schedule-lines-v4` text plus per-line provenance. Entry point: `extract_permit_document(pdf_bytes, *, document_hash, company, facility, as_of)`. It has no network, LLM or database access. Only compressor or pump rows with an explicit stated drive become demand claims; engines, turbines, generators and heaters are kept as supply/other. See [the engineering note](../../../../../docs/engineering/permit-document-extraction-20261103.md).
