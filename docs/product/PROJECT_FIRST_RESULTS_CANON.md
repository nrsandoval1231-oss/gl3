# GridLens — Project-First Results Canon
Status: OWNER-APPROVED product and UI direction · 2026-10-27
Authority: Complements and amends [AUTONOMOUS_INTELLIGENCE_CANON.md](AUTONOMOUS_INTELLIGENCE_CANON.md) on the presentation of opportunities. Supersedes company-first, account-table-first, KPI-dashboard-first and technical-workflow-first UI prescriptions in current design/product documents. Historical evidence, commercial integrity and backend rules remain authoritative.

## Product promise

**Extraordinary autonomous intelligence. Effortlessly simple commercial results.**

An ordinary GridLens user opens the app to see **which specific project or asset matters, who operates/owns it, what changed, why it might need power, and whom to contact.** The user does not conduct research, log actions or interpret raw government records. GridLens continues to research automatically and transparently separates verified facts from hypotheses.

**Company-aware engine; project-first interface.** Retain canonical organization/account identities, buying-chain links, physical-project identity, separate power-need identities, evidence versions, and incremental ingestion. Public browsing centers on a unique **real physical project/site/asset or independently supported site-level power package**, not an account total or one card per permit. Multiple projects can belong to the same operator; multiple permits can support one project. Do not collapse distinct wells into one "project" merely because an operator is shared; do not flood the UI with permit clones.

## Ordinary user experience

- Default landing screen: compact canonical GridLens G/L lockup, **Search opportunities**, and exactly three primary domain filters: **All | Oil & Gas | Data Centers**. No four KPI placeholder blocks, empty aggregate widgets, visible internal research queues, raw power-needs workflows, Operations/diagnostics tabs, audit UUIDs or long permit dumps.
- On desktop, a clean project list with concise detail on selection. On mobile, readable project cards followed by a dedicated single-project view; no permanently fixed multi-column table, horizontal scroll or always-open diagnostics.
- Keep Signals and autonomous Research capabilities available through secondary routes/internal navigation when useful; do not turn them into routine work the user must perform. Administrative diagnostics and exceptional correction/suppression/privacy remain internal and protected.
- Default priority is commercially actionable projects. Underlying Signals, Prospects and Leads retain their canonical evidence semantics, but do not show unsupported numerical confidence or imply that a high ranking proves temporary power demand. Let low-evidence items appear only when relevant through discovery/search, with unambiguous "Signal" treatment.
- A compact card prioritizes: **asset or project name; operator/developer; location; meaningful project milestone with correctly named date; power relevance/qualified gap where supported; contact path; one-line rationale; next action.** Hide irrelevant/missing fields rather than showing multiple "Not established" placeholders. A missing verified contact is plainly indicated without a fake call or email link.
- Tap/open provides additional commercial detail and an unobtrusive **View sources** disclosure. Preserve complete evidence, source links, timestamps, unresolved conflicts, backend audits, source recency, and safe navigation without placing raw implementation metadata in the default presentation.
- Show `Oil & Gas` in the user interface. This is **not** a cosmetic rename of the current `industry_group=industrial` server filter. Provide a genuinely source-backed Oil & Gas category with matching API and browse semantics. Do not silently include general industrial projects unrelated to Oil & Gas. Preserve existing fixed-infrastructure energy assets (midstream, compression, processing, SWD/produced water, gathering, field electrification) when supported by classification. Explicitly decide where general energy/utility assets fit; do not mislabel them as oil and gas.

## Oil & Gas result: well or infrastructure project

**Headline:** verified operator legal/display name plus source-backed **lease / well name and well number**, or the actual named compressor station, gathering system, SWD, processing facility or field-electrification project. Distinguish the well from the W-1 permit number. Show county, state, and known site coordinates when supported.

Commercial summary fields, presented only when supported:

1. Operator and relevant ownership/operating relationships; stable RRC operator number where available internally.
2. Actual well/lease name and number (not "Texas W-1 permit #######" as headline); API/well identifiers if verified and suitable for drilldown.
3. **Spud date** ("Drilling started"), **drilling/completion milestone date** ("Drilling completed" or "Well completed" only if source semantics support it), and verified producing/status milestones with their different meanings. If there is only an original permit issue date, label it **Permit issued**, never **Drilled**.
4. Current lifecycle: permitted / spudded / drilling / completed / producing / infrastructure development, with source-backed state and as-of date.
5. Commercial inference: likely on-site/field power use case and the evidence supporting it; MW, timing, duration, fuel availability and residual gap only where support exists. A drilling permit by itself is not an established generator rental demand.
6. Best published business contact: relevant asset/area/project or operations/commercial decision maker, name, role, organization, verified method (email/phone) and last-verified/source status. Separate direct named methods, company contact routes, role-only leads and buyer authority. Never invent phone numbers, emails, names or authority.
7. One sentence: "Why this might matter" and the next commercially meaningful action.

### RRC enrichment and lifecycle truth

The existing `backend/src/gridlens/ingestion/adapters/rrc_drilling.py` parser already extracts `operator`, `operator_number`, `lease`, `well`, `issued`, `received`, `amended` and permit status. Reuse these; verify that permit fields survive normalized projects, saved browse and the API. The present parser **does not establish spud date or drilled/completed date**. Source those as independent events from appropriate official RRC well/completion/production records if accessible, preserving source-specific definitions and original dates. Join deterministically on credible well/permit/API identifiers and location, with conflict handling; never infer well identity from similar operator names or county alone. "Unknown" is not a substitute for fabricated lifecycle progress.

## Data Center result: campus/facility or separately actionable phase

**Headline:** source-backed campus or facility project name and actual owner/developer, with operator and customer/project relationships distinctly identified. Permit applicant, GC, electrical contractor or EPC is **not** automatically the customer.

Commercial summary fields, presented only when supported:

1. Campus/project name, developer/owner/operator, location/site.
2. Project type or phase, verified construction-start/major milestone dates, estimated and confirmed energization windows clearly separated.
3. Facility/IT load or service capacity separately from **temporary construction/commissioning load**, committed utility/on-site supply and any **supported residual power gap**. Never equate facility load or equipment capacity to rental MW. Record known fuel availability and time-to-power constraints where justified.
4. GC/EPC/MEP, commissioning contractors and other buying-chain participants, with verified role and contact/source provenance.
5. Named buyer or practical company contact method where actually established, short power relevance and one recommended outreach action.

## Contact actions and autonomous research

- **Call / Email** controls are enabled only for genuinely verified public/licensed business methods, with their role/organization clear. Generic switchboard, inquiry route, named but methodless professional, and validated buyer contact are distinct classes. An official generic route is still useful, but never label it as a verified direct buyer.
- Missing contact info triggers existing **bounded and prioritized** automatic investigation, not a visible user task. Deduplicate previous successful research, retain suppression and privacy rules, respect provider terms and budgets, surface concise "Contact not yet verified" if no usable method is supported.
- A contact's presence does not prove authority to procure rental generators. Source-grounded role and buyer-authority are separate claims.
- No outreach, paid provider activation, user data deletion or production database write is authorized by this direction alone.

## System and query contracts

- Create or adapt a **project-first materialized/read-optimized projection** on the current saved browse generation, preserving revision consistency and stable project/asset identity, without expensive source/model retrieval during normal reads. One row = meaningful physical project/site/power package, not one source document and not one account; deduplicate repeated permits, preserve independent needs as nested detail. Use canonical `CompanyIdentity`, `Project`, `PowerNeed` and retained membership/evidence.
- Search across operator/developer, lease/well number, campus name, county/city, actual project aliases and relevant underlying source IDs, keeping safe, bounded pagination and cohort fencing.
- Category filtering, count units, sorting and pagination must agree: project count must be distinct physical projects; it must never be presented as company count or power-need count. Filter counts and list cardinality must remain consistent. Use priority based on grounded commercial opportunity, not permit volume or sheer age.
- Reserve unknown values as nullable/explicitly absent in the API and render only useful text. A project can exist as a signal without a qualified power gap or published contact; such items should not masquerade as "Action now" sales leads.
- Initial historical ingestion once; source-specific **incremental** scheduled updates thereafter, material change recognition, idempotent research, retained evidence and finite budgets. Preserve TX/OK/NM boundaries and existing qualification, provenance, privacy, source health and deployment controls.

## Implementation order

1. **Inventory actual current production code and source coverage.** Inspect `Workspace.tsx`, `CustomerAccountsQueue.tsx`, `OpportunityTable.tsx`, opportunity/customer projections, model/schema, RRC adapters, data-center lifecycle, contact results and existing React/mobile tests. Capture before snapshots. Determine what data is real, available or unverified.
2. **Build reliable backend project-first reads.** Preserve entity IDs, matching and evidence history; expose operator/lease/well and defensible event dates. Implement true Oil & Gas domain filtering without relabeling unrelated industrial rows. Add data-center domain projection and correct count units.
3. **Replace default experience.** Remove the four placeholder KPI tiles, quick-filter wall, default diagnostic controls, raw permit grids and per-account floods. Present compact cards/details, vertical tabs and verified contact actions. Keep secondary source detail and administrative routes available but unobtrusive.
4. **Improve contact and milestone enrichment.** Target actual source gaps with bounded research; never promote assumptions to facts.
5. **Reconcile live docs and tests.** Update current PRD and architecture language that mandates account-first UI or KPI-dense layout; retain history as historical. Keep the approved brand assets, typography, colors and usable mobile navigation.
6. **Verify before release.** Run backend/FE/tests, migrations where changed, authenticated desktop/tablet/mobile flows, independent Astra review, production-safe deploy, backup/rollback and postdeploy smoke tests. Do not claim the product is shipped merely because a branch or PR exists.

## Required real-world acceptance examples

- **Pioneer upstream wells:** show operator and each independently supported lease/well identity with separate site/event, not raw W-1 permit IDs or a single 83-permit wall. Permit issue must **not** render as spud or completion. If those dates cannot be sourced, omit drilling dates and explain in detail.
- **EG AI Rice data-center campus:** present owner/developer, actual campus, location and current supported phase first, with buyer/contact path if supported; power/gap/timing unknowns remain honest.
- **Distinct wells, same operator:** separate assets; repeated evidence for same well is consolidated; cross-company aliases and corporate parents are not merged by name alone.
- **Industrial exclusion:** `Oil & Gas` does not show non-O&G general industrial or utility items without an attributed O&G asset relationship.
- **Commercial truth:** unsupported direct buyer phone/email, MW gap, need date or confidence is absent, not invented. Generic business routes have correct labels and action links.
- **Responsive QA:** 390 px, 768 px and desktop; search/filter/pagination/deep links; no horizontal overflow; no KPI placeholder or visible machinery by default.
- **Operational safety:** repeat ingestion does not reperform initial history; retained project identities, suppressions, and old evidence survive updates; no paid calls, production data mutations or outreach unless separately authorized.

## Success criterion

A user can identify a real project, understand its power relevance and find the supported contact route in seconds—without reading permit records, entering status updates or decoding internal workflows. Measure **verified actionable projects, actual relevant contacts, source-backed milestones and gap coverage**, not raw permit or account totals.
