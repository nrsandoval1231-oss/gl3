# GL3-025 · concise evidence-backed briefs

An authenticated user can explicitly request a concise advisory brief for one
active PowerNeed. The request queues durable worker work; reading a detail or
browse card never calls the model. A successful result is cached against the
current retained public evidence, need fields, policy/schema version, and
configured model. Browse cards display the cached one-sentence hypothesis with
an explicit stale label when the current fingerprint cannot be confirmed.

The Responses API call uses strict JSON Schema output, a bounded input and
output, a timeout, and `store: false`. The model only selects one or two IDs
from server-curated source facts. The server renders the exact fact text,
citations, activity-specific verification question, unknowns, and next step;
the model cannot write factual prose or assign a company role. Structured
permit fields use explicit labels such as proposed land use, recorded event,
and LP business name (role unverified). Other records use neutral source
description/event labels, with an exact-source-quote fallback for unstructured
evidence. Combining marks and malformed blank placeholders are rejected from
rendered advisory facts. Only retained public project/evidence fields and
accepted project-scoped relationship excerpts are submitted. Private notes and
credentials are excluded. Required unknowns are server-authored.

Brief generation is advisory. It cannot edit claims, tier, admission, ranking,
or display decisions. Unknown MW, rental demand, fuel fit, commissioning/current
status, utility sufficiency, and buying authority remain unknown unless the
existing evidence path establishes them. A daily request reservation is made
before calling the provider. An interrupted reserved request is terminal and
requires an explicit user retry because payment may be ambiguous. The last
successful version and its source citations remain retained across replacement
or provider failure.

`OPENAI_API_KEY` is read as a secret setting; `OPENAI_BRIEF_MODEL` defaults to
`gpt-4.1-mini`; `BRIEFS_DAILY_REQUEST_LIMIT` defaults to eight. Existing
`TYPESAFE_API_KEY` now uses the same `.env`-aware secret settings path for Jev
and pursuit research. Focused tests mock all provider calls. Controller validation used three real retained official-source projects and unchanged replay; see the receipts below.

Browse fingerprint recomputation uses the same relationship evidence as detail
generation for cards with a cached brief, so relationship changes mark the
summary stale. Cards without a cached brief return immediately without a
relationship lookup; the initial implementation may perform relationship
fingerprinting for each cached card during the existing bulk card response.
The policy is v4 and schema v3 after live quality review showed that
source-excerpt validation alone did not prevent unsupported prose.


## Controller acceptance evidence

Base `ba660ee41ee48dc45ac2dd49ccd2c9502cfb8f7f`, branch `feat/gl3-023-city-permits`, extending draft PR15. Tests used fresh `gl3_025_test` and migration databases; runtime used `gl3_025_accept`, cloned from the accepted024 database. Originals and credentials remain preserved.

- Full local gates: Ruff, mypy, 527 pytest passes / one existing missing-probe skip, frontend typecheck/build, clean and repeated migrations plus drift check, 15 relevant browser passes, and diff check. Four historical-corpus browser cases remain excluded exactly as in024; this isolated corpus does not contain their air/data-center/pursuit fixtures.
- Real OpenAI `gpt-4.1-mini`: Dallas TRICORE warehouse permit, Houston MERICHEM laboratory conversion, and Rhythm of Life Cannabis LLC cultivation application all produced current briefs. Three unchanged POST replays returned cached results without new jobs or budget use. No invented buyer authority, rental load or tier promotion.
- Two earlier outputs were rejected for malformed citation/prose; two later technically valid outputs were rejected by controller quality review. Their receipts remain preserved. The final v4 policy / v3 schema contract asks OpenAI to select one or two useful fact IDs. The server renders exact fact wording, cited source links, an activity-specific verification question, unknowns and next step. It is not unconstrained LLM narrative or autonomous research.
- Ten total OpenAI request reservations were used in this isolated validation day (four initial attempts, three v3 examples, and three final v4 examples); final output token usage is in LIVE_BRIEFS. Dollar cost is UNKNOWN. Default daily limit remains eight; this isolated local validation environment is configured with a bounded limit of twelve after review required three regenerations. Unchanged refresh is free of model calls.
- One bounded TypeSafe request succeeded using the `.env`-aware key path. It did not write a Signal decision.
- Core-table hashes stayed identical across generation:19 projects/needs,2,151 observations/evidence versions,16 buying-chain claims/22 evidence rows.18 visible opportunities remain; the below-floor record remains excluded, and unknown sizes remain explicit.

Receipts: `.agent/artifacts/GL3-025/{LIVE_BRIEFS,CORE_PARITY,TYPESAFE_CONNECTION,VALIDATION}.json`, validation-final logs, real UI screenshot, and independent REVIEW. Model/API outages leave existing evidence available; daily budget, stale and failed states are explicit. Read-only card/detail access never triggers paid generation. Local worker must run for queued explicit requests. No merge, deploy, cloud scheduling or real Lead acceptance is claimed.

Independent review-r1 found generic permit wording on an application and an A-to-B-to-A stale-status race. A bounded senior repair changed the wording, invalidated prior cached wording via policy v4, and preserves a current A cache when an obsolete B job finishes. Both regressions and final live application wording are verified; prior review and receipts remain preserved.


Final independent Sol review: PASS on candidate manifest `17b07879e30fa1e2d63007702f0a42ac2fb58fa9038903215ceae28d52ae74a2`. Full changed-file inventory: `.agent/artifacts/GL3-025/CHANGED_FILES.txt`. Source/test bytes are frozen; governance receipts are excluded from the product manifest.
