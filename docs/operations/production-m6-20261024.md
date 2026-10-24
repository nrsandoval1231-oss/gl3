# M6 isolated operator commands

The M6 evidence-package and commercial-assessment operator scripts accept the
isolated `pipeline_m6_app` database only when its URL uses loopback host
`127.0.0.1`, `localhost`, or `::1`, port `55443`, and has no query options.
The existing M3/M4 and test database rules remain in place. The database name
is fixed in each script's guard; do not add a configurable database override.

The retained-field extractor accepts a bare `Permit:` label as a reported
`permit` fact. Its value must still match the cited retained title or abstract
span. Buyer, required load, timing, duration, and supply remain unknown unless
separately established by supported evidence. The retained record excerpt does
not establish full-document coverage, and an applicant or owner is not
automatically the buyer.

## Five-project runtime checkpoint

The isolated database was copied exactly from accepted M5 data. Three native
source jobs added 116 retained evidence records: Oklahoma DEQ 7, Albuquerque
13, and Texas electric-generating-unit permits 96. The database now has 578
evidence records and 14 Signal projects. Oklahoma yielded no qualified project;
no Oklahoma project was manufactured to fill the regional sample.

The frozen selection contains Longhorn, VoltaGrid, DAL130, Prime Data Centers
(Texas), and Albuquerque permit BP-2024-36995 (New Mexico). Longhorn reused its
exact prior Jev and Sol results. Four new Jev calls and four new Sol attempts
exhausted the bounded call count; no new Firecrawl request was necessary for
these native excerpts. The prior Firecrawl PUCT pilot is a separate project.

| Project | Jev latency ms | Sol latency ms | Sol result | Next evidence question |
|---|---:|---:|---|---|
| Longhorn | 218 | 6936 | VALIDATED / UNRESOLVED | Commissioning or test-power timing |
| VoltaGrid | 202 | 6562 | VALIDATED / UNRESOLVED | Commissioning or test-power timing |
| DAL130 | 155 | 3922 | VALIDATED / UNRESOLVED | Temporary-load MW |
| Prime | 155 | 6157 | VALIDATED / UNRESOLVED | Utility online date |
| Albuquerque | 170 | UNKNOWN | SENT_OUTCOME_UNKNOWN | No returned assessment |

All five evidence packages are `COMPLETE_ADVISORY`, with `RECORD_EXCERPT`
coverage. DAL130 has a cited project-scoped Circle T Owner LP owner association;
the other selected projects remain without a resolved account. None establishes
buyer authority, temporary rental demand, or a Lead. Historical Albuquerque
permit status and recently retrieved data must not imply current construction.

Every completed Jev/Sol stage replayed with keys disabled and zero changes to
the protected business, job, and provider-call tables. The original M5 database
and prior retained rows remain unchanged. Raw frozen selection, policy, stage
receipts and failed-attempt evidence are retained outside Git in
`.agent/artifacts/PRODUCTION-M6/`.

## Unknown provider outcome and recovery boundary

Albuquerque Sol call `e786e4e0-e73a-4c34-9161-10d82e4d67f1` has one durable
attempt and status `SENT_OUTCOME_UNKNOWN`. The operator ended after 46.518
seconds with `ProviderResponseError`; no response ID, output, or usage was
returned. The 45-second transport deadline is consistent with the elapsed time,
but the persisted error lacks a specific transport cause. A timeout is therefore
an inference, not a confirmed cause. The job's terminal `succeeded` marker means
the wrapper finished recording an outcome; its checkpoint is `unknown` with
validation `UNKNOWN`, and it does not prove a successful assessment.

Do not retry, change the request identity, clear the ledger, or release its
reservation merely to obtain a fifth success. Retain the call until definitive
provider reconciliation is available. The request used `store:false` and no
response ID was returned, so the local record cannot retrieve its response.
M6 five-chain acceptance remains OPEN.

## Cost evidence

The four successful Sol calls have conservative usage estimates of $0.0093325,
$0.00955, $0.0057725, and $0.007395 respectively. Five Jev reported-usage
estimates total $0.00018627. These figures are estimates, not invoices; the
unknown Sol call retains a $0.079085 reservation and unknown usage. Actual
invoiced cost is UNKNOWN. The frozen policy allows at most 11 total logical
calls including three prior calls, with a $1.15 global reservation ceiling.
No new paid dispatch is authorized by a successful local replay.

## Readiness

Authenticated SQL/API readback completed in 2.477 seconds with the exact five
current evidence/need/project chains, five Jev packages, four validated Sol
results, one explicitly unknown Sol result and 11 total calls. It verified
Circle T's cited owner association and the separate unresolved projects.
Protected-table hashes before and after were identical. Authentication used
the ordinary isolated opaque-session lifecycle; auth-only records were excluded
from the protected business-table comparison and never exported.

The first API pass found an expired saved-browse generation (HTTP 503). Existing
provider-disabled derived-browse rebuild published 14 rows; the identical helper
then passed all checks other than the expected unknown-provider finding.
Both attempts remain retained. This does not demonstrate unattended browse
maintenance; the local acceptance server has automation disabled.

The additive result-view readback completed in 2.548 seconds and preserved the
same original and M6 business-table hashes. The live local browser shows
DAL130's advisory next question and unresolved fields, and Albuquerque's
explicit unknown-outcome retry block. The selected Prime and VoltaGrid facts
resolve to their exact retained source spans; no new provider request is involved.

This remains an incomplete M6 runtime checkpoint. The assessment presentation
is implemented; 44 focused API/unit/integration cases and 21 browser cases pass,
including completed and UNKNOWN 390px fixtures. Final frozen-candidate gates and independent review
are pending. Their exact receipts and review are retained with the candidate
under `.agent/artifacts/PRODUCTION-M6/`. The original 446-record QA export remains
unavailable. Parent directive and Finish Contract acceptance, merge, and
production deployment remain open.

The bounded [saved assessment view](production-m6-result-view.md) presents the
retained advisory output and selected citations in the existing Commercial
Assessment tab. Its validation is separate from the missing fifth provider
result and cannot close that live acceptance gate.
