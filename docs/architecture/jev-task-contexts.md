# Jev task contexts and bounded routing

Jev's eight catalog contracts receive a bounded, task-specific projection of the
active power need, accepted operator facts, project identity, permitted source
state, retained evidence, and the question or relationship each contract is
allowed to assess. The request digest includes that transmitted context. The
worker reconstructs it before dispatch and after a provider response; a changed
candidate, citation, source permission, accepted fact, or question makes the
result stale and prevents it from being applied.

`MATCH_ADVISORY_V1` asks one question under each exact existing candidate
project UUID. It includes deterministic match decision, reason, matched facts,
identity facts, and current evidence ID. The response must contain exactly the
same UUID key set and is retained under `match_advisories`. With no eligible
candidate, the job ends as explicitly unresolved/not applicable without a
provider call. No candidate is created, merged, or accepted by this advisory.

`BUYER_ROLE_HINT_V1` uses up to three current named buying-chain party UUIDs and
their exact source citations. Each subject receives its own question and result
under `buyer_role_advisories`; no party substitution or aggregation is allowed.
Missing subjects produce an explicit UNKNOWN advisory without a provider call.
`MATERIALITY_V1` receives accepted semantic before/after events and an explicit
missing-state marker, so metadata changes alone cannot establish materiality.

Only `RESEARCH_PRIORITY_V1` and `LLM_ROUTE_V1` can affect queue scheduling, and
only when bounded routing is currently enabled under the same evaluated policy
ID and explicit authorization. Before an effect, the worker rechecks current
context, source permissions, contract allowlist, provider/model policy, and all
finite caps. A priority result assigns an ordinal hint to already queued,
fresh, eligible intelligence work. An LLM route can enqueue an extraction or
dossier job only for a configured unresolved commercial question, or leave a
`NONE` or `HUMAN_REVIEW_REQUIRED` marker. Queue
ordering retains the existing age bucket and construction-permit preference;
the hint only orders eligible intelligence jobs within those fairness groups.
Every job independently repeats the context and cap checks before provider
dispatch. Advisory and evaluation modes never apply these scheduling effects.

These contracts return advisory data only. They cannot change canonical facts,
project identity, evidence qualification, opportunity scores, outreach, or
provider permissions.
