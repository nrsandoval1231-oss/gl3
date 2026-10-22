# Retained news interpretation and reassessment

Implementation checkpoint: October 20, 2026, `rss-project-v9` and `signal-admission-v2`. The [owner decision](../decisions.md#owner-decision-october-20-2026-site-specific-news-may-create-discovery-signals) permits dated, site-specific news discovery Signals. This describes repository behavior, not deployed behavior; see [operations status](../operations/README.md).

Ordinary RSS processing preserves immutable observations/evidence, evaluates title plus retained summary, then applies admission, project matching and qualification separately. Supported event families include physical-site acquisition/sale, committed project financing, project power arrangements, conversion, filings, construction, expansion and substantial restoration. A bound US project site is required; speculative, non-US, company-level, unrelated HR and resolved same-activity cases remain excluded. A headquarters or utility territory does not establish the project site.

Existing supported project/site matches are considered before creating a standalone discovery. Similar names and state alone do not merge projects. Unknown or conflicting phases/sites remain visibly unresolved; ambiguous items do not count as admissions. Corrections retain prior decisions, withdraw obsolete support and preserve independent current support and legitimate historical links.

A milestone never supplies temporary MW, duration, commissioning scope, a supply constraint or purchasing authority. Site-sale and grid-funding events with no supported power phase use `project-discovery` explicitly. They remain Signals despite other accepted facts until an actual power activity is supported and reconciled. Closure and fact history remain available. Known activities retain the existing Prospect/Lead gates; no phase editor or automatic phase inference was added.

## Bounded operator reassessment

Run from the repository root with configured local dependencies. The default reads a supplied local retained-record JSON file, writes a decision report, opens no database and performs no retrieval or paid call:

```powershell
uv run --project backend python scripts/reinterpret_news.py --input .artifacts/news-capture.json --output .artifacts/news-preview.json --limit 100
```

Apply reads current retained RSS observations and matching immutable evidence. It defaults to rejected interpretations, accepts a UUID cursor, and caps each page at 500. Database-name mismatch is rejected before connecting. Both target selection and an exact expected name are required for application writes:

```powershell
uv run --project backend python scripts/reinterpret_news.py --apply --database-target test --expected-database-name gridlens_test --limit 100 --output .artifacts/news-apply.json
# Separately authorized application action only; never run automatically:
uv run --project backend python scripts/reinterpret_news.py --apply --database-target application --expected-database-name exact_authorized_database_name --limit 100 --output .artifacts/news-apply.json
```

Use the reported `next_cursor` as `--after-observation-id` for the next bounded page. `--include-accepted` is a separate explicit apply option for a policy/evaluator change affecting accepted records. Earlier interpretations remain in `previous_decisions`; unchanged evidence/evaluator/admission identity reuses the current decision. Production replay requires separate owner authorization for the exact database and bounded action. None was executed by this remediation.

## Evidence and limits

Controller replay of the frozen 219-article capture admitted 15/15 labeled useful events and five known training cases, rejected 190/190 clear negatives and all nine uncertain cases, and left demand/supply fields unknown for every admission. Earlier frozen candidates failed positive holdouts (v7: 0/3; v8: 1/5); those receipts and labels remain preserved. All positive holdouts have now been used for development. This result is deterministic regression evidence, not untouched generalization proof. Prior PR #96 reviewer overlap is unknown.

A separate local backup clone contained 200 retained RSS records. Bounded reassessment created 20 discovery Signals; unchanged replay left project/need/job/interpretation counts and interpretation digest identical, preserved all 18,016 evidence versions and 16,694 observations, and added no paid logical calls. This local checkpoint does not authorize or prove production replay, deployment, future-source coverage or a real commercial Lead. The parser uses retained snippets, not full-article research. Current exact-candidate gates and independent review remain separate from these checkpoint results.

The superseded v6 narrative is [archived unchanged in Git](../../.agent/archive/AUDIT-20261020/pre-news-admission-project-interpretation.md).
