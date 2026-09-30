# GL3-019 cloud validation — 2026-09-30

**Original candidate:** acquisition totals are superseded by [the Austin/Houston continuation](gl3-019-acquisition-continuation.md).

Documentation was updated first in `56d7cb9`, from freshly fetched remote main
`7f241748f421697877b54ba3f87eb5b0b3e839e1`. Implemented code candidate:
`426c2e670bc4b5b705675fd42e2e590287942195`. The final reporting commit changes
only documentation/evidence; [the manifest and results](gl3-019-live-evidence.json)
bind every changed backend, frontend, test and registry file by SHA-256.

## Root cause and repair

GL3-018 retained Chicago contractor fields as line-oriented evidence, while
GL3-017 recognized those fields only in freshly retrieved structured JSON.
Without that redundant request, retained-only extraction produced no candidates.
Georgia draft identity lived in companion PDFs outside the accepted parent
summary used by enrichment. The UI displayed relationships but no useful permit
profile. This slice connects those retained fields to the existing action and
shows source-attributed facts directly in project detail.

Acceptance caught and repaired two provenance defects: older live JSON could
make current native fields appear superseded merely because quote formats differ;
and identical excerpt text could reuse a row bound to a superseded original
Evidence ID. Current accepted source versions are now authoritative for retained
claims, and their source hash participates in enrichment evidence identity.
No old history was overwritten. No contact or power qualification was fabricated.

## Live ordinary-worker acquisition and replay

All runs used real application retrieval in the saved cloud executor and an
isolated PostgreSQL database, `gl3_019_live`. No fixture replaced live responses.

| Source | Live result | Repeat |
| --- | --- | --- |
| Chicago | 1,528 complete bounded rows; 16 Signals, 1,512 rejected | 1,528 unchanged; count-checked pagination |
| Georgia | 19 listing records, 38 PDFs; 9 Signals, 10 rejected | 19 unchanged |

The final source health for both is Checked—No Change. Chicago had intermediate
HTTP/count failures; ordinary later retries recovered. Those failures did not
remove accepted projects. Georgia retained 417 technical excerpts/facts with
147 explicitly omitted excerpts and 19 missing full application links. These
are measured source-window results, not national or all-time completeness.

Final replay preserved 1,547 observations, 1,623 evidence versions, 25 projects,
25 needs, 61 relationship claim versions, 50 enrichment evidence versions and
54 run versions. Extra historical versions reflect extraction/version repairs,
not new underlying projects. Duplicate observation keys, evidence versions,
project identities and claim fingerprints were all zero. Every selected-project
immediate enrichment replay kept claim/evidence/run counts unchanged.
There are 29 current organization candidates across the 25 projects, zero named
people in organization/person relationship claims and zero public contact details.
All 25 needs remain Signals with required MW and suitable supply UNKNOWN;
there are no Prospects or Leads.

## Manual project review

The before column reproduces the prior prose-only retained path using the same
live retained excerpts. It is not a claim that GL3-017 could never find these
organizations through a successful separate live JSON request.

| Real project | Before → after retained candidates | Permit-derived results |
| --- | --- | --- |
| 400 S LaSalle, Chicago 3451848 | 0 → 5 | Data-center conversion Phase 3/3, MEP upgrades, site, case, parcel, application/issue dates; ABCO ELECTRICAL CONSTRUCTION &, Bonus Electric, Kelso-Burnett, ARCO/Murray, Legacy GI TC 400 Lasalle LLC |
| QTS ATL3, Augusta, SIP-30169 | 0 → 1 | QTS Atlanta III, LLC explicitly proposes construction; draft site 2883 Gordon Highway; greenfield data-center scope; source application date and comment deadline |
| QTS Fayetteville I, LLC, application 30027 | 0 → 1 | Draft permit facility entity, 1435 Hwy 54 West, scope of operation with 572 emergency generators and 11 fire pumps; no rental-MW inference |
| 333 E Huron, Chicago 3459792 | 0 → 3 | Hospital temporary-electrical-service example: Gurtz Electric, Power Construction, Northwestern Memorial Hospital. This is not a data center. |
| DMG Mori, Chicago 3442494 | 0 → 3 | Manufacturing renovation: Kelso-Burnett, Accend Construction, DMG Mori Federal Services. This is not a data center. |

LaSalle's exact permit fields also retain `KRESTEL, CHRISTOPHER D` with source
role `ARCHITECT`. The name is displayed as a permit-listed party; employer,
current employment title, business email/phone and buying authority are not
inferred. Truncated source names (such as ABCO's field) are not silently expanded.
Agency narrative authors, director names and agency phone numbers are not turned
into project contacts. Construction proponent, draft facility entity and verified
owner/operator are deliberately distinct. No newly verified ROLE_SUPPORTED person
is claimed; existing role, unsupported-role and stale-role regression tests remain.

Primary sources and exact quotations are in the linked JSON, including:

- [LaSalle exact official permit](https://data.cityofchicago.org/resource/ydr8-5enu.json?$where=id%3D%273451848%27&$limit=1)
- [QTS ATL3 draft, page 1](https://epd.georgia.gov/document/document/sip-30169-draft/download)
- [QTS ATL3 narrative, page 1](https://epd.georgia.gov/document/document/sip-30169-nar/download)
- [QTS Fayetteville draft, page 1](https://epd.georgia.gov/document/document/30027-draft/download)

## Validation gates

- Ruff, including migrations: passed. Mypy: passed, 44 source files.
- Backend: **386 passed, one pre-existing skipped NC local-access fixture**.
- PostgreSQL: empty database upgrade to head, repeated upgrade and schema drift
  check passed. No new schema/migration or persistence framework was introduced.
- Generated OpenAPI/TypeScript contracts updated; frontend typecheck and production
  build passed; npm audit reported zero vulnerabilities.
- **11 Playwright tests passed**: authentication, browse/detail, mobile health,
  grouping/admission, unsupported/empty relationships, evidence disclosure,
  navigation races, failed enrichment preservation and the new permit summary.
  A new real-source browser case clicks enrichment for LaSalle and QTS ATL3 and
  verifies retained fields, DIRECT organizations and UNKNOWN personal relationships.
  Other interaction scenarios use explicitly synthetic API fixtures.
- Desktop real data-center permit screenshots were manually inspected. Existing
  mobile checks passed; no claim of exhaustive visual/device coverage.
- Independent Sol review: no blocking findings on exact code candidate; 83 focused
  unit tests passed on the reviewed backend, final frontend typecheck and diff
  checks passed. No source-fetch, TLS/DNS/IP restriction or browser protection was
  weakened. No test assertion was removed to obtain a passing result.

Earlier checks exposed a missing optional-array guard in frontend compilation;
`permit.facts ?? []` now matches the generated contract. Initial browser attempts
inside the nested execution sandbox could not launch Chromium. The approved
outside-execution-sandbox run kept Chromium's own sandbox enabled. The first
browser run used an empty application database; final runs used the isolated live
corpus. The real-project browser test then caught the source-version bug described
above; final results include its repair.

Local logs, source-probe bodies, scripts and screenshots remain in ignored
`.artifacts/gl3-019/` and `web/test-results/`. The local cloud Playwright config used
`/usr/bin/chromium` with `chromiumSandbox: true`, API port 8019, web port 5199;
application source and checked-in Playwright defaults were not weakened.

Hosted GitHub main run 36770147719 did not start because account payments failed
or the spending limit needed increasing (verified check annotation). Hosted checks
for this new draft are reported separately at PR time; local validation is not a
claim of hosted CI success. No merge or deployment occurred.

## Remaining boundaries

No commissioning-specific connector, proven commissioning rental package, current
RRC ingestion, national coverage or full air applications. The RRC official index
and linked daily portal returned HTTP 200, but a paginated file listing is not a
verified current complete drilling feed. Drilling permits remain an explicitly
approved early-production Signal direction; production timing, load and fuel
suitability stay UNKNOWN. See [scope and access findings](../sources/gl3-019-permit-enrichment.md).
