# D3 — Dormant controlled scanned-PDF extraction

READY after E/D2/B3 shared dispatcher freeze. Sol architecture direction MODIFY,
then implement dormant; no second tribunal. Owner full A-G includes difficult
PDF/OCR extraction, so missing code is not excused by missing activation credentials.

Reuse existing worker/ledger/OpenAI Responses and original Evidence. Own narrow
govinfo_pdf.py/capture helper, guarded provenance write and serialization exclusion,
intelligence_jobs.py/provider/grounded validator/worker/settings, API request wiring
and generated types only as needed, focused tests/runbook. No new platform/table,
general raw store, canonical promotion, real provider calls or production effects.
G1 owns ops/alerts/deployment receipts, coordinate settings (G1 uses getattr only).

Exact already-linked GovInfo PDF only; explicit source/retention allowlist EMPTY by
default. HTTPS exact GovInfo path/document ID, no redirects/private destinations,
<=750000 bytes and <=5 pages, MIME/PDF magic, finite isolated parse/wall deadline,
SHA256 bytes equals exact original PDF Evidence.content_hash. Source changed/hash
mismatch returns stale/UNKNOWN and normal acquisition is required. Capture is a
write-once bounded namespaced envelope in existing provenance, containing bytehash,
original URL/pagecount/retention policy/reference, base64 and retrievalUTC. Preserve
on all provenance merges; never replace capture with different bytes. Explicitly
exclude binary capture from EVERY public API/projection/log. Never use arbitrary
model URL or upload from request path. Commit capture before advancing work.

Official verified docs (2026-10-18):
https://developers.openai.com/api/docs/guides/file-inputs
https://developers.openai.com/api/docs/guides/token-counting
https://developers.openai.com/api/reference/resources/responses/subresources/input_tokens/methods/count
Controller refreshed official count reference18:20UTC; ignored copies under
.artifacts/INTELLIGENCE-20261018/openai-count-reference.{html,txt} and guide.md.
Count body documents model/input/instructions/text/tools (plus other optional
context fields); store/max_output_tokens are not count-body fields. Build count
request from the exact effective input/config/schema whitelist; omit response-only
parameters while binding their output cap in reservation policy. No conversation,
previous response, hosted tools, file URL/ID or external fetch. Inline input_file
detail auto|low|high is supported; bind the same exact detail in count and response.
Responses input_file supports filename + data:application/pdf;base64,..., optional
detail; PDF context includes page images, so serializedbytes tokenbound IS INVALID.
Use exact input-token count preflight for the same pinned model/request/detail or
a documented verified conservative model-bound. No guessed SKU, price or maxcontext.
Preflight itself is external data transfer and must be authorized/accounted before
dispatch. Implement explicit defaultfalse preflight/vision/retention gates and
verified upper cost bound (zero/unset blocks ALL calls). A count preflight can use
its own shared logical intent/caps; output counted_input_tokens is NOT billable
token usage. Unknown timeout/dispatch keeps exposure and prevents blind secondcount.
Reserve actual response upper cost from counted input + capped output at verified
prices under all scopes. Reject count/request/model/detail changes or stalecount.
Keep provider URL fixed; inline bytes only; store:false/tools:[]; strict page schema.

Store page-indexed transcript in bounded LogicalCall.result_payload (<=64KiB), not
ordinary Evidence: model transcript cannot become canonical source support. Require
all expected pages present, original documenthash/call linkage; oversized/missing
text returns UNKNOWN/failed without truncation. Grounded follow-on is a SEPARATE
logical extraction call, using retained transcript reference/version. Quotes match
transcript only and stay OCR_UNVERIFIED pending independent source check. Neither
OCR nor matching transcript quote accepts facts, identity, buyer, gap or Lead.

Wire an authenticated exact-need/evidence request or bounded existing extraction
continuation, same durable queue/budgets; API never retrieves/calls. Show queued/
unknown/unavailable truthfully via existing history. Avoid raw engineering controls
in daily workflow. No arbitrary file endpoint or automatic all-record OCR.

Tests alloff/zero/noinputcount probes; allowlist/path/hash/retention/oversized/page
bounds; immutablecapture and no APIbytes; countmismatch/unknownrestart/stalefence;
actual fake Responses body+strict full transcript; separate grounded followon and
OCR_UNVERIFIED/no promotion. Isolated fixture PostgreSQL, no actual providercalls.
Two materially distinct repairs then canonical reconstruction. Focused gates and
artifact; controller final rerun/review. Actual OCRaccuracy/accountcompatibility,
data-egress permission and finite activation budget remain external prerequisites.
