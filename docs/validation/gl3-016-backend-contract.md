# GL3-016 backend contract

Authenticated `GET /api/opportunities?tier=Signal&search=...` returns the existing
project/need card plus stable `project_id`, `signal_display_decision` (`SHOW`,
`REVIEW`, `HOLD`, or `null`), `signal_display_decision_state`, decision source,
and reason. `null` with `unadjudicated` means a legacy record remains visible.
PowerNeed tier and project lifecycle are separate fields and remain independent.

Authenticated `GET /api/signals/decisions` returns current `show`, `review`,
`hold`, and `unadjudicated` counts per current active Signal opportunity
(records, not physical project cards). Authenticated, same-origin
`POST /api/signals/decisions/adjudicate?limit=100`
performs an explicit bounded backfill over retained current Signal evidence.
The response reports processed and decision counts. Evidence and policy
versions are retained as separate decision rows; the API uses the server-owned
policy version, and an unchanged completed
decision is not called again. Missing-key REVIEW may be followed by an appended
decision once a key becomes available.

Ambiguous records call `POST https://api.typesafe.ai/v1/systemone` with bearer
`TYPESAFE_API_KEY`, model `jev-1.13.0`, and six factual Noul questions. The
bounded state includes retained source, date, and available project/lifecycle
facts. Jev does not choose a display label. GL3 maps factual probabilities to
the display policy and stores model version, dimensions, reason, policy, source,
and adjudication time. Missing key, malformed response, timeout, and provider
errors yield inspectable REVIEW. Missing-key REVIEW is retried only on later
normal adjudication after a key appears or explicit backfill; provider-error
REVIEW is retried only by explicit backfill under a new policy version.
Deterministic HOLD covers explicitly negative project status, scoped transient
event grammar, and like-for-like equipment replacement;
deterministic SHOW is limited to linked, dated explicit construction at named
high-value facility types.

A linked official Taylor planning withdrawal persists a deterministic HOLD on
its current evidence version and takes precedence over historical SHOW. A
conflicting Taylor revision persists REVIEW and leaves application/project
status UNKNOWN. The explicit backfill also creates these rows for retained
pre-GL3-016 Taylor revisions. Earlier evidence and decisions remain retained.

Austin permit phases with only a numbered Phase N difference consolidate only
when the full normalized source scope, exact source address, geography, and
asset type agree. Distinct labeled buildings remain separate; no uncertain
historical rows are migrated.

The production credential was absent during this slice; no live Jev request was
made. Thresholds are initial policy constants and have not been tuned against
the frozen editorial corpus. `gl3-016-human-corpus.json` binds all 63 human
card decisions to 81 record IDs; `gl3-016-jev-corpus.json` commits the
source-backed input state for those 81 current evidence versions. The request
boundary applies its normal text limits to that retained state. Both identify the
same GL3-015 API export SHA-256. The bounded Jev fixture is not a replacement
for the retained full source evidence.
