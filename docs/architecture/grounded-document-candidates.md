# Grounded document candidates

The grounded dossier worker receives at most 24 current need-linked documents
and a serialized request capped at 45,000 bytes. Its passage text comes from
retained Evidence titles and abstracts, with immutable hashes, extraction
locations, publication metadata, page markers, accepted operator facts, and the
current accepted source-claim projection. The accepted claim projection uses
the existing current-need predicates and participates in the request digest.

Oversized retained passages are suffix-trimmed and marked partial, preserving
the original prefix offsets. RRC's opaque base64 tail remains in immutable
Evidence for audit but is excluded from passage text with its omitted offsets
reported. If non-passage metadata alone exceeds the request limit, the worker
fails closed. Scanned documents without retained OCR provenance are marked
`unavailable_ocr`; a retained transcript requires matching original document
hash, method/version, transcript hash, and explicit `unreviewed` status.

Model output is only a candidate bundle. Every cited quote must match the exact
retained passage, evidence hash, section, and page. Quantity candidates preserve
source kW/MW value and decimal precision; dates preserve day, month, quarter, or
year precision. Speaker, organization, and role are independently nullable and
accepted only when explicitly present in the quote. Conflicts and unresolved
questions remain visible when there are no candidates. New candidates do not
become accepted facts or alter qualification, route, or commercial next action.

Before publishing a response, the worker rebuilds the request context and
compares it with the captured digest, including accepted claims and monitoring
watch revision. A changed context retains the provider response in history as
stale, blocks current effects and feedback, and queues at most one deduplicated
reassessment when the current source context remains usable.
