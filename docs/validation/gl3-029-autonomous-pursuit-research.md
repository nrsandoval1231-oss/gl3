# GL3-029 autonomous pursuit research — candidate validation

**DRAFT / NOT MERGE-READY.** Local implementation and fixture gates pass. Required
original retained PR #23 corpus validation is blocked. Nick explicitly authorized
publishing a draft on October 4, 2026 despite that remaining gate. No acceptance,
cloud deployment or production-proof claim is made.

Baseline main: `6c8bdf3e3163adde078f8543d43c0256bc11eb82`, verified again through
GitHub's branch API after local validation. Branch:
`feat/gl3-029-autonomous-pursuit-research`.

## Implemented flow and authority

Durable questions use one new table, existing PostgreSQL jobs/fences, canonical
Source/Observation/Evidence, existing Project/PowerNeed matching, buying-chain
semantics and shared commercial evaluation. Retained facts → at most two ranked
questions → bounded source acquisition → normal admission/quarantine → canonical
projection → deterministic reevaluation → immutable receipt/history → at most one
child. The worker never assigns pursuit disposition or qualification tier.

Typed public reports require an exact grammatical project/site subject, supported
activity predicate and date provenance. Contradictions remain conflicts; corrections
preserve old evidence. Public phase, supply, load and timing reports can answer a
question without positively qualifying a need. Construction does not establish
commissioning; permanent energization alone does not establish sufficient supply.

A narrow official-permit parser implements existing PRD Prospect/Lead criteria.
Separate exact-activity demand and unsuitable supply support Prospect. Lead additionally
requires MW/start/duration ranges, explicitly zero suitable supply throughout that
interval, and supported buying role. Canonical corrections and read-only API gate
replay remove obsolete qualification. Hypothetical, historical, conditional, quoted,
conflicting, campus/nameplate and wrong-activity claims cannot qualify.

Routing prefers retained evidence, registered exact-record adapters, eligible public
pages, then configured URL-only Firecrawl discovery. Each question records planned,
checked, unavailable and skipped routes, generated/attempted/completed queries,
source checks and accepted/rejected citations. Default caps are three searches, ten
URLs, five documents, 750,000 bytes per document, 180 seconds, zero model calls and
zero paid-search budget. Searches cannot spend after the document budget is exhausted.
Reservations are not billing receipts; actual provider cost stays unknown without
billing evidence. Question, policy, registry/source selection, semantic evidence and
content/version fingerprints prevent unchanged work. Current canonical support is
rechecked before cache reuse. Saved targets outside the shortlist are reprojected in
one bulk pass; unchanged fresh results do not schedule more acquisition.

Morning changes count unique saved evaluation versions correlated with completed
research; concurrent operator contributions are not falsely attributed solely to
research. Commercial state and evidence tier remain separate.

## Exact local validation

| Gate | Final result |
|---|---|
| Backend `ruff check src tests` | PASS |
| Ruff migrations/scripts | PASS |
| Backend `mypy src` | PASS, 77 source modules |
| Backend `pytest tests` | **995 passed, 1 skipped, 1 warning; 129.60 seconds** |
| Frontend typecheck | PASS |
| Frontend production build | PASS |
| Frontend audit, high threshold | PASS, **0 vulnerabilities** |
| Current OpenAPI versus checked-in contract | Exact match |
| Full browser suite | **38 passed, 0 failed; 46.0 seconds** |
| Migration checks | **8 passed** |
| Existing fixture preservation | **8 rows across 7 tables**, identical digests |

The existing skip is `test_nc_commerce.py`'s optional local-access probe: its local
artifact is absent. The warning is the existing Starlette/httpx deprecation. No
failing tests were waived or disabled. Diagnostic failures were repaired and the
full suite rerun. An initial browser launch used an unwritable uv cache; the final
run used the workspace cache and passed.

The 237-file code/test manifest is
`.agent/artifacts/GL3-029-RESEARCH/CODE-MANIFEST.json`, SHA256
`6df8caa02aa730354c6215df241ef415164bbfe0ac7802af6c1d8bd57b982cd2`.
The final code bytes match this manifest. Tests ran on the working candidate before
its publication commit; receipt HEAD fields still name the earlier local checkpoint,
so use this content manifest, not those older HEAD labels, to identify tested code.

Full backend logs: ignored `.artifacts/autonomous-research/resumed-backend-final.log`.
Browser receipt: ignored `.artifacts/synthetic-browser/gl3_synthetic_browser_11e476561701/`
(JSON, logs and screenshots). The runner creates a distinct synthetic database and
uses canonical ingestion, the existing worker and unchanged existing browser
assertions. It fixes missing fixture setup; it is **not original retained-corpus or
live-source proof**. The original six previously failing workflows now pass.

Migration `0014_pursuit_research_questions` follows `0013_jev_scan`; old migrations
were not edited. Checks cover clean upgrade/repeat/drift, existing 0013 setup and
upgrade/repeat/drift, plus preservation of Source, Observation, two historical
Evidence versions, Project, PowerNeed, Pursuit and call note. All eight fixture rows
in seven tables survive. Receipt: ignored
`.artifacts/autonomous-research/resumed-migrations-final.json`.
The original runtime was not upgraded or seeded.

## Fixture transitions and replay

Canonical worker fixtures cover RESEARCH→ACTION NOW/WATCH/REJECT, WATCH→RESEARCH,
insufficient-evidence no-transition, Signal remaining Signal despite ACTION NOW,
Signal→Prospect and Prospect→Lead only after official gates, corrections/demotion,
age-out, wrong-activity supply rejection, and exact 299/300/301 kW floor handling.
Examples are synthetic, not the real named projects:

| Before | New admitted evidence | Result |
|---|---|---|
| RESEARCH / Signal | Exact permit adds reachable project contractor path | ACTION NOW / Signal |
| WATCH / Signal | Exact permit adds relevant electrical construction activity | RESEARCH / Signal |
| RESEARCH / Lead | Dated exact-project completion or adequate activity supply | REJECT / Signal |
| RESEARCH / Signal | Official exact activity demand plus unsuitable supply | Prospect; pursuit reevaluated separately |
| Prospect | Official interval, duration, zero suitable supply and buying role | Lead; no worker-assigned promotion |
| RESEARCH | Bounded checks without a supported answer | UNRESOLVED; no invented fact |

Tests cover immutable old evidence, same-URL correction, cross-URL content reuse,
current-source cache invalidation, policy/source fingerprint invalidation, no repeated
transition on unchanged replay, active cap, one child/no grandchildren, interrupted
request/lease failures and no external I/O during retained-only enrichment.

## Separate adversarial review

Independent reviewers found and repaired publisher/relationship admission bypasses,
stale contact retention, correction/deduplication hazards, blocking acquisition locks,
lease/error visibility, incidental-subject phase transfer, hypothetical/historical
qualification, dated-heading freshness leakage, optional/investigative temporary
scope, source/policy reuse gaps, shortlist starvation, unit/range floor handling,
and false corpus/harness success or duplicate metrics. Repairs have regressions and
were independently reprobed. A final narrow review confirmed the intentional
nonpolling public-source refresh exception without relaxing admission. No remaining
material finding was reported in those reviewed areas; this is not overall acceptance.

## Real retained corpus: blocked

The preserved `gridlens` runtime remains `0007_signal_decisions`, with 13 Sources
and zero Observations, Evidence, Projects and PowerNeeds. Authorized searches of the
workspace, PR23 discussion/reviews, issues, all 13 branch trees, full history, PR21
links, releases, Actions artifacts and tags found no restorable original archive.
Older September 25 PC snapshots are not established as the PR23 corpus. This executor
did not access the PC or another environment.

The historical [PR23 report](GL3-029-commercial-pursuits.md) records backup SHA256
`828beace65cd2b06182f30e4713857656a993d3969c8cbecb02e6ee40ff8a886`, 16,960 Evidence,
1,168 active Signal needs, 50 scopes/53 needs and 9 ACTION NOW / 19 RESEARCH / 22 WATCH
/ 0 REJECT. These historical metrics were **not reproduced here**.

| Required original-corpus case | State |
|---|---|
| Austin data-center construction | BLOCKED: original retained pursuit absent |
| Austin explicit temporary-power permit | BLOCKED: original retained pursuit absent |
| Chicago data-center conversion | BLOCKED: original retained pursuit absent |
| O&G | BLOCKED: original retained pursuit absent |
| Low-quality/unresolvable case | BLOCKED: original retained pursuit absent |

Per-case queries, admitted findings, transitions, tier changes, costs, runtimes and
baseline/replay metrics are unavailable. Zero cases ran; this is not zero-cost
successful corpus validation. The new manifest/harness pins an isolated baseline,
caps aggregate execution, checks preserved history and rollback replay, and labels
operator-attested provenance separately from independently established proof.
See [validation tools](../../scripts/README-pursuit-research-validation.md).

## Provider and acquisition limits

No OpenAI, TypeSafe or Firecrawl key is configured here; no credentials were created
or changed, no paid/model calls were made. Runtime Jev architecture is unchanged and
non-authoritative. Exact adapter refresh currently supports Austin/Chicago. Other
families need eligible direct public pages or configured discovery; unavailable routes
are explicit. RRC form-based downloads and generic PDF extraction are not performed.
Strict grammars leave unsupported wording unknown; the Lead subset handles explicit
zero suitable supply, not arbitrary complex supply schedules. Existing synchronous
DNS resolution has a soft wall-clock limit. These are visible limits, not proof that
missing facts are false.

A separate fresh direct-source smoke made three bounded public GET queries and two
exact Austin retrievals: $0, zero models, 6.628 seconds active request time, 62.060173
seconds elapsed. It made zero canonical admissions/database writes. Chicago's exact
address filter returned no rows; Clayton's capped sample was a retaining-wall permit,
not data-center power proof. This is source-access smoke only.

**No external commercial outreach occurs.** No emails, calls, commercial forms,
external CRM records, purchases, account login or access-control bypass.
**Cloud deployment remains a separate milestone.** Do not merge until required
retained-corpus and operational acceptance gates have been completed and reviewed.
