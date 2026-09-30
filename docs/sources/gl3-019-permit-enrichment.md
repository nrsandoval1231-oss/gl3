# GL3-019: useful permit-derived enrichment

Documentation updated before implementation, from remote main `7f24174`.

Priority is data-center construction temporary power, then commissioning temporary power, then O&G temporary power. Drilling permits are valid early production Signals without proven rental demand or a power gap. Upstream wells retain an asset-specific lifecycle; production dates, load and fuel suitability remain unknown unless evidenced. Existing Prospect/Lead gates remain authoritative. News is supplemental.

The bounded target is to make retained official permits useful through the existing project enrichment action and detail UI. Reuse evidence, claims and runs; no research framework or queue. Extract only attributable site/identity, permit scope/type/dates and supported organization/person/contact fields. Project-to-organization, organization-to-person and person-to-project remain distinct. A contractor name is not a person or proof of buying authority.

Source feasibility, final implementation limits and live validation will be recorded here. No national coverage, full application coverage, commissioning feed or all-drilling-permit ingestion is claimed. No outreach or deployment.

## Authorized acquisition continuation

Extend Austin commercial collection to electrical permits and a bounded initial
2026 data-center backfill, retaining exact contractor/applicant organizations,
permit-listed names and business-contact fields. These fields do not establish
current employment, personal telephone ownership or buying authority. Verify
Dallas, Houston and El Paso official routes as requested; historical or incomplete
datasets must not be presented as current complete acquisition. Validate the RRC
current file's framing, amendments, stable identity, freshness and rollover before
enabling ingestion. Current-file retrieval alone is not statewide history.

The original acceptance below is superseded for acquisition by the continuation
validation. Houston now collects the four latest linked official XLSX reports;
it does not manufacture missing status, organizations or contacts.

## Original Chicago / Georgia boundary

The original candidate had 13 enabled sources; the continuation has 14. Chicago acquisition now retains the
full address, application-start date and permit milestone alongside scope,
parcel and the exact 15 named-party slots. Georgia retains a bounded, exact
front-page draft identity excerpt in the accepted parent evidence, versioned
with its extraction metadata. Neither change enlarges existing network bounds.

The existing enrichment action reads Chicago field pairs without another fetch,
extracts explicitly named Georgia construction proponents and legally styled
facility names from draft permits, and persists them through existing immutable
buying-chain evidence/claims/runs. It does not infer ownership from a facility
name. The detail UI exposes permit facts even before enrichment, exact field
quotes, source roles, dates and draft PDF links. Unrecognized named parties stay
visible as permit facts rather than acquiring invented employer relationships.
Optional user-supplied role sources retain the existing bounded research path.

Two freshness repairs preserve the accepted source binding: native permit fields
are not invalidated by differently formatted earlier JSON research, and identical
excerpt text with a changed accepted source hash gets its own enrichment evidence
version. Older evidence and claims remain inspectable. Missing employers, current
roles, assignments, business contacts and buying authority remain UNKNOWN.

Georgia claims cite the accepted parent listing evidence; the extraction location
names the draft PDF page, and the permit summary links to the exact draft PDF.
Narrative proponent extraction is deliberately narrow; unrecognized prose is not
a guessed organization. At most four accepted evidence records feed enrichment.
This is still a bounded project action, not automatic general-purpose research.

## Remaining acquisition gaps

- **Commissioning:** no dedicated commissioning, load-bank or utility milestone
  connector was added. Construction/MEP and standby-generator permits can reveal
  relevant projects, but these examples do not establish a commissioning rental
  package, date, load or power gap.
- **Drilling:** current official `daf420.dat` download was verified twice with
  identical SHA-256 `4bf8b0f65a6e3f077802d9e95ea33bd184c6b0d3ca452efa49129915ea895fc3`
  (2,623,180 bytes). Retrieval is permitted, not denied. Full ingestion remains
  disabled: OGA049M documents 510-byte tape records, while the current download
  has variable-length segments (type 01: 212 bytes, type 02: 510, type 08 mostly
  87) and 57 CRLF fragments without a documented record prefix. Root-only parsing
  finds 966 permit/status-sequence records and 949 permit numbers, including
  original issue dates from 2013. Full transport framing, amendment ordering,
  rollover/archive recovery and independent completeness are not yet validated.
  Silently discarding unknown fragments or treating the file as new permits only
  would lose evidence. No RRC connector or all-Texas-history claim is enabled.
- **Dallas:** official reports page returned HTTP 401 and DallasNow Accela 403.
  The old Dallas Open Data Building Permits dataset explicitly says it is no
  longer updated. Current reliable retrieval is blocked at the tested routes;
  other routes remain unverified. No bypass or stale feed enabled.
- **El Paso:** official city planning page and Accela building search returned
  HTTP 403. No supported current retrieval verified and no connector enabled.
- **Houston:** latest official linked report ends September 14 on September 30.
  Four report snapshots cover August 17–September 14: 1,543 distinct rows after
  two exact duplicate rows. Footer text is validated, conflicting duplicates fail.
  Permit status and all party/contact fields are absent. Existing Signal gates
  reject unknown status; these records remain attributable ingestion evidence,
  not fabricated Signals. This route is limited published-report acquisition,
  not complete or real-time sold-permit/electrical/commissioning coverage.
- **Georgia:** all 19 current application-link fields remained empty. Full air
  applications and comprehensive public contact acquisition remain unproven.
- No BidBuy bypass, generic procurement expansion, outreach or deployment.

See [live acceptance and validation](../validation/gl3-019-validation.md) for
measured examples, exact code hashes, before/after results and source limits.
