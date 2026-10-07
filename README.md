# GridLens 3

**October 7, 2026 status:** PR24 remains draft on main `ec72912`. The unchanged five-category gate passes all five freshly regenerated real cases on tested code `92f7689`: six explicit UNRESOLVED blockers, zero failures/promotions, 15 Evidence rows preserved, exact replay. The authorized RRC download supplied one canonical early drilling Signal; its research inspected retained native bytes without claiming a live refresh. Final gates: 1,229 backend tests passed/one optional skip, 36 browser regressions and five actual-database browser groups passed. Original PR23 proof and six historical live-browser prerequisites remain distinct and unavailable. No merge or deployment. See [latest results](docs/validation/gl3-029-five-category-20261007.md) and [current state](.agent/CURRENT_STATE.md).

**Focused live proof:** two fresh native Chicago checks returned unchanged permit evidence, so the requested new-fact resolution was not demonstrated. Application discovery credentials/cost reservations are unconfigured; no source, answer or positive result was fabricated. Keep PR24 draft pending this proof. See [exact result and next step](docs/validation/gl3-029-live-fact-proof-20261007.md).

GridLens 3 is a private, evidence-backed workspace for discovering emerging commercial power needs. The current local candidate registry enables 20 public sources spanning municipal planning notices, construction permits, air permitting/regulatory records, government/economic-development publications, public documents, and industry news. The system preserves source observations and evidence history, groups supported records into project-oriented Signal cards, and keeps unsupported commercial facts explicitly unknown.

Main includes PR15 at `ce6b8fc` (city permits, cultivation Signals, commercial filtering and cited OpenAI-assisted briefs). GL3-026 adds Boston permits, an All Signals view, consolidated source-sector filters and a live registry-backed source selector. Firecrawl assisted nationwide source discovery; routine Boston acquisition uses the official CKAN API. See [GL3-026 validation](docs/validation/gl3-026-national-intake.md). National completeness and deployed daily cloud operation remain unproven.

The standalone Cannabis Watch is removed; cannabis and publisher evidence remain in the ordinary inbox. Opportunity titles use project-bound company evidence with the role shown; unknown companies fall back to the activity and site. The visible commercial floor is 300 kW inclusive with no maximum: confirmed smaller activity is hidden from opportunity views, while unknown-size Signals remain marked unknown. Campus totals and nameplate or operating capacity do not establish temporary-power need. See the dated [PRD amendment](docs/product/PRD.md).

## Today’s Power Pursuits

The next working slice adds persisted daily Austin/RRC pursuits, bounded official-source research, separate action statuses and owner call outcomes. Open `?view=pursuits`; see [startup and scheduler limits](docs/operations/power-pursuits.md) and [real-source validation](docs/validation/gl3-021-power-pursuits.md). Unknown rental demand, load, fuel, duration and buying authority remain unknown. This feature does not promote tiers or establish cloud operation.

## GL3-028 evidence graph slice

GL3-028 is merged to `main` via PR #21 at merge commit `43424be`. It adds authenticated current-project state projection, evidence-backed material-change history, and an explicit zero-authority EvidenceJudge shadow command. Jev remains separate from signal adjudication, and normal ingestion does not call it. Migrations `0012` and `0013` add project state revisions, shadow attempt records, and durable bounded-scan position. See the [final PR #21 correctness report](docs/validation/PR21-CORRECTNESS-REPAIR.md), [accepted validation evidence](.agent/artifacts/PR21-REPAIR/VALIDATION.json), [retained review](.agent/artifacts/PR21-REPAIR/REVIEW.json), [browser evidence](.agent/artifacts/PR21-REPAIR/BROWSER.json), [preservation evidence](.agent/artifacts/PR21-REPAIR/PRESERVATION.json), and [operator limits](docs/operations/power-pursuits.md). Final local gates recorded 703 backend tests passed with one existing environment-dependent skip and 12 migration checks passed. This is a merged implementation claim only; cloud deployment and unattended production operation remain separate open milestones.

## GL3-029 autonomous pursuit research candidate

The isolated current-main candidate adds durable bounded research questions, retained-first acquisition, canonical evidence admission, deterministic reevaluation, and inspectable receipts. It preserves evidence/tier authority, explicit UNKNOWN, budget/replay controls, canonical category evidence proof, and no-outreach boundaries.

Historical candidate `7768f2a` passed technical gates and recorded R4 corpus acceptance of **3/5**. Austin data-center and explicit temporary-power cases passed only under the narrow owner amendment; Chicago passed meaningful investigation. O&G and low-quality/unresolvable did not pass. Those results do not establish acceptance of the current branch. PR24 remains draft. The October 7 owner amendment authorizes fresh traceable corpus validation; the five regenerated commercial cohorts and final candidate gates now pass as documented in the [October 7 report](docs/validation/gl3-029-five-category-20261007.md). Historical proof remains distinct. See [historical acceptance](docs/validation/gl3-029-autonomous-pursuit-research.md) and [current closure record](docs/validation/gl3-029-closure-20261006.md).

[October 7 delivery checkpoint](docs/validation/gl3-029-delivery-checkpoint-20261007.md) lists published code/procedures, locally retained raw artifacts, and the unconfigured/unapproved Firecrawl next step.

## Product model

GridLens follows:

**Discover → preserve evidence → resolve project → investigate power need → qualify → prioritize → act → update.**

- **Signal:** sourced event with a defensible reason to investigate a possible power need.
- **Prospect:** actual power requirement plus supported evidence that suitable supply may be insufficient or unavailable when required.
- **Lead:** supported unresolved power need with MW range, start window, duration range, supply-gap explanation, likely buying organization/role, and next action.

Current production-like local behavior is intentionally conservative: Signals do not inherit MW, timing, buyer, utility-shortage, or rental-need claims that the evidence does not support.

## Current source coverage

The current local candidate registry contains 20 enabled sources, including:

- Austin commercial building/electrical permits with a bounded 2026 data-center backfill; Seattle and Chicago permits.
- Texas RRC current-month drilling file plus official prior-month EOM overlap, with amendment history and unknown production timing.
- Texas RRC flare/vent exception applications from the public SWR 32 query, with a complete count-checked three-day submittal window. List records remain intake evidence; they do not prove actual flaring or a power project.
- Boston issued building permits, retrieved through a rolling 90-day, count-checked official CKAN query.
- Houston’s four latest linked weekly permit workbooks, with reporting lag and limited fields explicitly retained.
- Bounded Dallas monthly and El Paso new-commercial permits, plus Massachusetts Cannabis Control Commission cultivation applications; each retains its source-specific site, date, and role limits.
- Georgia Draft Title V air-permit filings and supporting public documents.
- Federal Register environmental-impact notices with eligible GovInfo PDF evidence.
- North Carolina Commerce project announcements.
- Taylor, Texas Development News and Development Notices, including bounded archive revisions.
- Data Center Dynamics, Utility Dive, Manufacturing Dive, Construction Dive, Oil & Gas Journal, and MJBizDaily publisher feeds.

Permits are the primary discovery path and news is supplemental. Coverage is not yet nationally complete. See [source coverage](docs/sources/coverage.md) and the [local Signal verification](docs/delivery/local-signal-verification.md) for measured limits.

Acquisition priorities are Dallas, Austin, Houston, El Paso and California; the commercial order is data-center construction, data-center commissioning, then oil and gas. Other sources remain enabled. California routes are discovered candidates, not enabled coverage. See [priority and flare intake scope](docs/sources/gl3-027-priority-flare-intake.md).

## Run locally

Requirements: Python 3.11, uv, Node.js 22+, npm, and PostgreSQL 15 or later. From PowerShell at the repository root:

```powershell
uv sync --project backend --extra dev
npm --prefix web ci
uv run --project backend python scripts/setup_local.py
```

The setup script reads PostgreSQL connection values from the ignored `.artifacts/local-postgres/connection.env`. It writes ignored `.env` and `.artifacts/local-auth.txt`; the latter contains the generated local password. Do not commit either file.

Start the services in separate terminals:

```powershell
uv run --directory backend alembic upgrade head
uv run --project backend uvicorn gridlens.api.app:app --app-dir backend/src --host 127.0.0.1 --port 8000
$env:PYTHONPATH = (Join-Path $PWD 'backend/src')
uv run --project backend python -m gridlens.jobs.worker
npm --prefix web run dev
```

Open http://127.0.0.1:5173 and use the password in `.artifacts/local-auth.txt`.

## Validate

```powershell
uv run --directory backend ruff check src tests
uv run --directory backend mypy src
uv run --directory backend pytest tests
npm --prefix web run typecheck
npm --prefix web run build
npm --prefix web audit --audit-level=high
```

GL3-019 passed 418 backend tests (one existing missing-fixture skip), Ruff/mypy, frontend typecheck/build, clean/repeated migrations with no drift, live replay/provenance audits and 13 browser checks (11 repository checks plus two saved-cloud live acceptance cases). See [the validation report](docs/validation/gl3-019-acquisition-continuation.md); the additional live cases remain captured acceptance artifacts, not repository tests. The prior GitHub billing block is historical: main run `37164959427` and PR24 run `37222313567` both completed successfully with backend and web jobs on October 4. This does not establish browser, retained-corpus or deployment acceptance.

Runtime status and bounded in-place source recovery are available through `python -m gridlens.jobs.runtime` with the backend environment. See [runtime recovery](docs/operations/runtime-recovery.md) for registry reconciliation, selected checks, retry behavior and operational limits.

## Containers and deployment

Run `uv run --project backend python scripts/setup_compose.py`, then `docker compose --env-file .env.compose up --build` for local container operation.

Cloud scheduling is **not yet deployed or accepted**. The scheduler manifest is preparation only. Production still requires authorized hosting/secrets, PC-off scheduled ingestion, operational alerts, backup/restore proof, and seven measured daily cycles.

## Product and operations

- [Product requirements](docs/product/PRD.md)
- [Frozen UI canon](docs/design/UI_CANON.md)
- [Architecture](docs/architecture/overview.md)
- [Source coverage and limitations](docs/sources/coverage.md)
- [Local Signal verification](docs/delivery/local-signal-verification.md)
- [Signal card review](docs/delivery/signal-card-review.md)
- [Local recovery proof](docs/operations/local-recovery-proof.md)
- [Current agent state](.agent/CURRENT_STATE.md)

## Project buying chain and merged GL3-019

Project detail now has a bounded Buying Chain enrichment action. It reuses the physical Project ID and retained evidence, reads exact Chicago permit contractor fields, and accepts up to four additional public evidence links. Organization involvement, a person's current organization role, and personal project assignment remain separate evidence claims. ROLE_SUPPORTED never means a person is assigned to the project or controls its temporary-power purchase. Missing facts remain UNKNOWN.

GL3-017 through GL3-019 are merged; this is not a deployment claim. GL3-018 live acquisition produced 25 permit-backed Signals across Chicago and Georgia, with no proven Prospects or Leads. See [GL3-018 validation](docs/validation/gl3-018-validation.md). Earlier GL3-017 network failures remain historical validation records.

GL3-019 prioritizes **data-center construction temporary power**, then **data-center commissioning temporary power**, then **oil and gas temporary power**. Permit-derived project/site, scope, dates and organizations should be useful directly from retained evidence. Drilling permits are valid early production Signals without an already-proven power gap; production date, load and fuel suitability stay unknown unless supported. Upstream wells and fixed O&G infrastructure retain separate lifecycles. News stays supplemental.

GL3-019 repaired permit enrichment using existing evidence and persistence. GL3-023 adds bounded Dallas monthly, El Paso NewCommercial, and Houston weekly Sold Permit acquisition, with source-specific event semantics and role-attributed enrichment. Each route has limited geographic, permit-type, and date coverage; current permit activity, commissioning, rental demand, fuel fit, and buying authority remain UNKNOWN unless separately supported. See [GL3-023 city permit coverage and limits](docs/sources/gl3-023-city-permits.md). The discontinued Dallas open-data dataset remains disabled.
