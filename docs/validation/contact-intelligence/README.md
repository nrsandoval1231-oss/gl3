# Historical PR122 company contact intelligence: implementation and evidence

> This is the dated PR122 benchmark and implementation record. Its code defaults, 30-day blanket planner suppression and earlier browser workflows are superseded by the [Autonomous Intelligence Canon](../../product/AUTONOMOUS_INTELLIGENCE_CANON.md). Current default-on bounded unpaid planning and independent paid-provider gates are documented in [runtime configuration](../../operations/runtime-configuration.md). These historical benchmark methods are not a current verified contact feed or current-candidate coverage result.

This continues [PR122](https://github.com/nrsandoval1231-oss/gl3/pull/122). PR #122 merged as `3ce9e8a68a6b988d1d8bfd8597e150f19ae36498`; the bounded v12 production census and automatic follow-up are summarized in the [production release report](PRODUCTION_RELEASE.md). The implementation guide and benchmark history below remain useful context for how the capability was built and validated.

The commercial P0 remains OPEN. Source-published company methods are useful research routes, but do not establish purchasing authority, email deliverability, reachability, or a direct buyer relationship. No outreach was performed. Production authenticated contact UI remains UNKNOWN; this release does not claim full commercial acceptance.

## Final isolated live result

The final no-hint20company trial uses policyv12 at backend commit
`ba0e52cc6c5069dc42a9080606f1474e9a8c516f`, followed by a UI-only date correction
at `d3c4d5ffb1fbf205a00e48dd87f575e9b35f3ad7`. All190backend/runtime source hashes
and backend test bytes remain identical. Independent acceptance and remote CI are
recorded separately against the final PR122 head; this packet does not self-certify.

| Measure | Actual result |
|---|---|
| Companies processed | 20real existing canonical companies |
| Published methods | 4/20companies (20%);6phones and7business emails |
| Relevant named professionals | 3at2companies; authority unconfirmed |
| Direct buyer methods | 0 |
| Without email/phone | 16 |
| Research Required | All20 |
| Qualification coverage | Signal4/20; Lead/Prospect N/A (zero denominators) |
| Industry coverage | Data center1/4; upstream3/16 |
| Worker elapsed sum | 102.844seconds |
| Operator time | 169.109seconds including pilot review pause |
| Final trial usage | 20completed searches,40credits;0uncertain calls |

The four companies are EG AI, EOG Resources, Active Iron Energy and Citation
Oil & Gas. EOG tax/JIB addresses and Citation's owner-relations inbox are published
business routes, not verified procurement channels. Published methods remain
company routes unless a relevant person's relationship and method are separately
verified. Publication is distinct from deliverability, reachability and authority.

Use the [twenty-company contact sheet](benchmark-v12-company-contacts.csv),
[complete results and failure reasons](firecrawl-v12-results.json),
[preservation/replay proof](firecrawl-v12-data-preservation.json),
[authenticated browser proof](firecrawl-v12-browser-proof.json), and
[local validation/source binding](firecrawl-v12-validation.json).
Same and fresh checkpoints reuse the exact20job IDs; company/contact/evidence/job
counts and hashes are unchanged, with0additional paid calls. All original protected
rows also survive API/UI readback. Rejected directory-publisher methods are absent.

The [region check](firecrawl-v12-region-scope.json) shows all20sampled companies
have Texas memberships. The snapshot has1eligible NM project with no current
company relationship and no eligible OK project. OK/NM company coverage is not
proven. No qualification or company was invented to broaden this sample.

Four live trials used80accounted searches and160observed credits (2614to2454),
exactly the approved isolated cap. See [usage](firecrawl-authorization-usage.json).
No further paid dispatch is authorized within that cap. Actual cash billing is
UNKNOWN; no plan, recharge or new enrichment service was activated.

Full local gates passed3017backend tests and7subtests (3skips),201browser tests
(1skip), Ruff/format/Mypy, fresh/repeated/restored migrations and drift, API
OpenAPI/types generation, frontend types/build, dependency audits and brand checks.
The UI-only correction was frozen before all frontend gates started; exactly two
web files changed during the backend run, whose bytes stayed identical. Final CI
must independently verify the exact final PR head.

## Existing repair and remaining root causes

The PR122 base (`93437131a6b0fa84300732426a5698c0bb99100b`) already repaired
literal email/phone extraction and normalization, contact retention across refresh,
source provenance, identity continuity, the authenticated company contact API,
and its existing company/need panel. Its empty development database was not a
production coverage measurement. No competing contact database was necessary.

Read-only production inspection found 532 identity rows but only 235 current
eligible primary customer companies. All were Signals: four data-center companies
and 231 upstream operators. Their primary-company projection had no email or phone.
The 63 existing contact claims belonged to general/electrical contractors; they
remain in the buying chain and are not replacements for the owner/developer.
See [the point-in-time inventory](production-inventory-20261025.json).

The missing work was automatic public discovery and a source-bound path from
membership-only companies to the existing buying-chain projection. Real pilots
also exposed invalid run persistence, an inner unresolved result reported as
complete, overbroad fax filtering, official-site footer variations, and a stale
first project hiding a valid later company anchor. A retained real roster caught
marketing copy being parsed as a person; that failed result was rejected and the
benchmark restarted from the original snapshot. Repeated-manifest testing then
exposed a self-changing discovery fingerprint. Independent review additionally rejected the first frozen candidate because a
shared retained record could attach a contractor to the owner identity. The
repair requires the claim's own typed relationship at both write and read time.
These failures are retained as failed attempts, rather than counted as commercial
success.

Live validation also exposed a starved official navigation queue, directory-subject
JSON-LD mistaken for site publisher identity, and learned URLs changing empty-input
request identity. These are fixed without a shared-parser/schema/contact-store
change. Actual visual inspection caught an older organization-claim date overriding
the method summary; it now uses the latest valid method verification and retains
separate role/source checks for methodless professionals.

## Historical PR122 automatic pipeline

`COMPANY_CONTACT_DISCOVERY_ENABLED` defaults to false. When explicitly enabled,
buying-chain identity reconciliation enqueues existing durable Jobs without
performing network work inside ingestion. A separate bounded planner reaches
existing company memberships. Existing queue leases, fences, public acquisition
admission and logical-call accounting remain authoritative.

The waterfall is:

1. Reuse current source-verified records; preserve supported prior contacts.
2. Use retained contact URLs, prior verified pages, or one configured Firecrawl
   URL search. Search results are hints, never contact evidence.
3. Retrieve a bounded set of public HTTPS pages and require exact company
   self-identification before accepting official-site methods. Follow same-host
   contact/leadership pages within the shared request/deadline budget.
4. Extract literal published company emails/phones and relevant named roles.
   Generic switchboards are not assigned to named professionals. Exact-number
   public RRC lookup is an additional source-specific fallback, with its own
   operator-name/number/field checks; agency and emergency numbers are rejected.
5. Preserve the company and report Research Required when a method or buyer
   assignment is missing. Provider/access failures do not establish success.

Discovery creates no new CompanyIdentity. A membership bridge requires the exact
current project membership Evidence, the claim's own organization/typed relationship
quote, and independent hash checks. A shared source record containing both owner
and contractor cannot assign the contractor the owner's identity. The same guard
is applied when reading older links. Valid strong identifiers and attributed
review retain precedence; similar names are not merged. Source changes or membership
retractions invalidate the projection. Results append to retained claim/evidence
history and the latest complete claim snapshot; refresh cannot replace the chain
with a contact-only subset. Contact information is read by canonical company ID
across related project/need contexts and qualification tiers.

Buyer roles use the existing categories for owner energy/construction,
procurement, commissioning, field/facilities operations and associated
contractors. Data-center owners/developers remain the customer. Public employment
and a potentially relevant role remain distinct from a source-confirmed project
decision-maker or purchasing authority.

The job bounds include four attempted public URLs, a 35-second deadline capped by
the caller's shorter deadline, at most sixteen local anchor candidates, two
failed-job attempts for the same fingerprint, a 30-day refresh epoch, and a
default 25-company planning page. Source-specific public acquisition rate and
concurrency limits also apply. Checkpoints retain inputs, source context, checked
URLs, provider call identity, outcomes and reasons. Interrupted paid effects remain
UNKNOWN and prohibit blind redispatch.

## Earlier native benchmark

The original production database was read only. A custom-format dump was restored
into a new local loopback PostgreSQL18.6 cluster. The final benchmark uses a clean
restore, separate from earlier failed pilots and destructive test fixtures. The
snapshot SHA-256 is
`6e0d699e4065acb9caf1a1fd61a25a4a75d7ff2f3bf4509d89df2c887fb86e65`.

See [the manifest](benchmark-manifest.json), [per-company results](benchmark-results.json)
and [preservation/replay evidence](data-preservation.json). The selection includes
all four available data-center companies, the four upstream companies with most
associated projects, and twelve evenly spaced by name from the remaining 227
operators. Every company is Signal because no higher-tier companies exist in this
snapshot. Neither qualifications nor the denominator were changed to improve the
sample.

The native benchmark has **assisted domain selection**: fourteen companies have
public-search URL hints and six have none. It exercises actual source retrieval,
verification, queue execution, persistence and company projection. It does not
prove a live autonomous Firecrawl search. Manifests contain company IDs/metadata
and URL hints only, with no contact values. Fixtures are excluded from coverage.

Coverage is measured as distinct companies with a verified email or phone; named
roles, generic routes and direct person methods are reported separately.
Research Required stays true when relevant direct buyer information is absent,
even if a generic company method is available. Higher-tier percentages are N/A
when their denominator is zero. The production baseline remains 0/235; the
benchmark improvement exists only in the isolated restore.

The final native run processed twenty companies in **32.969 seconds**, including
enqueue and worker execution. **Three companies (15%)** have usable methods:
EOG has two company phones, Citation has four office phones, and EG AI has one
published business email. Three relevant named professionals have no direct
methods. Seventeen companies have no usable method. Generic methods occur at
three companies; direct buyer methods are zero. Data-center coverage is 1/4,
upstream coverage 2/16. All twenty still require buyer research. Lead and Prospect
coverage is N/A. Replaying both the original and a fresh checkpoint reuses the
same twenty job IDs and leaves company, claim, evidence and job counts unchanged.
All original row fingerprints survive; no duplicate company was created.

## Authorized live discovery follow-up

The owner subsequently approved the proposed **160 existing-plan Firecrawl
credit** isolated trial. The first no-hint run used the same twenty companies on
a fresh restore of the original production snapshot. All twenty searches
completed, the observed balance fell from 2,614 to 2,574 (**40 credits**), and no
uncertain provider call remained. Original protected rows survived unchanged.

That v9 run produced only **1/20 usable companies (5%)**, with two EOG company
phones and one relevant named role, zero emails and zero direct buyer methods.
It proved live provider execution but failed the commercial recall comparison
against the assisted native benchmark. See [the complete first live result](firecrawl-v9-results.json).
The original assisted result is retained separately; its contacts are not carried
into later benchmark restores.

Real source evidence exposed a queue defect: four returned search URLs filled
the entire four-fetch allowance, so a verified official site's contact link
could never be added. Citation's management page exposed its contact page as
the first parsed link, yet the live run never fetched it. The v10 candidate
prioritizes verified same-host contact navigation, including contact URLs already
queued, ahead of staff/detail pages and lower-priority unvisited search hints.
It retains the four-attempt, 35-second and one-search limits and all identity,
provenance, deadline and UNKNOWN checks. Its search emphasizes contact methods
and excludes unusable social-result hosts. No shared HTML parser, schema or UI
change is needed.

The matched v10 trial completed twenty searches for forty additional credits,
balance2,574to2,534, cumulative80/160. Its apparent10/20 coverage is **rejected**: six
third-party operator-directory profiles inherited the directory publisher's email
and listed phones. A matching profile Organization JSON-LD row with a same-host
URL is not proof that the target company publishes the website. See [the rejected
trial and affected companies](firecrawl-v10-rejected-results.json). All original
protected rows survived, but retention does not make attribution correct.

The v11 repair requires site-level publisher identity and rejects conflicting
root Organization/legal-footer identities before extraction or navigation. A
profile URL remains a subject record even if its id uses a root fragment. Genuine
root/footer and first-person homepage support remain; ambiguous sources fail
closed. The affected database/API and pure-source suite has138passing tests. The clean v11 matched trial found4/20usable companies,6phones/7emails and
3relevant named professionals, with0direct buyer methods and no directory
publisher leakage. It consumed40credits, cumulative120/160. See [the partial
v11 result](firecrawl-v11-partial-results.json). Original rows survived, but a
fresh no-hint checkpoint created four redundant jobs: learned contact URLs had
entered the request fingerprint/payload, and strict manifest binding rejected
them. Resumability acceptance was withheld; replay made no new paid call.

The v12 repair keeps caller inputs stable and resolves derived known URLs only
in worker execution, preserving strict manifest checks and real source fences.
Its140affected tests and static checks pass. The final matched trial and functional
replay now pass as reported above, using40morecredits, cumulative160/160. Failed
and partial trials and intentionally interrupted gates remain separate; the v10
apparent50% is never counted as accepted coverage.

## Firecrawl and cost

The existing Firecrawl v2 integration is reused behind its existing enabled
contract, finite cost/request budgets, secret, job fence and durable logical-call
ledger. Its search request uses the documented
`sources: [{"type":"web"}]` shape. The local runtime key was verified with a free
credit-metadata request; the03:14production inventory had no runtime key. Recheck
production configuration before release. Key availability is not
spend authorization. No commercial people-data provider was introduced.

The original native run used public retrieval with provider keys cleared;
ledger inspection measured zero paid dispatches and $0 provider cost for that
run. Four authorized live trials measured eighty dispatches and160credits; the
final trial used forty. Actual cash billing is UNKNOWN. The isolated ledger uses
$0.01/search as a conservative replacement-cost reservation based on the
[published Hobby overage price](https://www.firecrawl.dev/pricing), not a claim
about this account's billing rate. Finite daily/monthly limits include the
snapshot's prior reservations plus only the authorized new exposure, and active
concurrency is one. No owner-unlimited mode, new service or auto-recharge is used.

## Historical UI, validation and release gate

The existing Graphite & Sage company detail composition is retained. Contacts &
Buying Chain puts a verified email/phone before methodless named roles, with
mailto/tel actions, official contact-page links, source evidence, affiliation,
verification/check dates and Research Required. No navigation or palette redesign
is included.

Final candidate validation must include backend checks, PostgreSQL persistence
and migrations, API contract generation, frontend typecheck/build, browser
regressions, and authenticated desktop/mobile readback of the actual benchmark
data. Replay must preserve company/contact/evidence identity and all original
rows. Negative cases cover stale/retracted sources, provider failure, UNKNOWN
dispatch, interrupted jobs, ambiguity and ingestion isolation. PR122's final
candidate receipts and fresh independent review carry the exact gate outcomes;
builder handoffs alone are not acceptance.

The first v9 full gate (`ff66a6d`) was rejected for one clock-sensitive browse
maintenance test: after publishing the recovered current view, maintenance may
also prepare its next interval and return `prepared`. The test-only correction
forces both documented outcomes, preserves strict initiating-publication,
sanitized-error and dirty-503 checks, and verifies recovered current revision
and row presence. Subsequent v9 and current v12 full local gates pass; the failed
clock assertion remains historical evidence. Independent acceptance is separately
bound to the final PR head.


The release-hold statements in this historical implementation record predate the completed v12 production census and activation. For current source identity, production results, validation, and remaining acceptance gaps, use the [production release report](PRODUCTION_RELEASE.md). Commercial P0 remains OPEN because buyer coverage and the authenticated production contact UI are unverified.
