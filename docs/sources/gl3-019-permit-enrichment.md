# GL3-019: useful permit-derived enrichment

Documentation updated before implementation, from remote main `7f24174`.

Priority is data-center construction temporary power, then commissioning temporary power, then O&G temporary power. Drilling permits are valid early production Signals without proven rental demand or a power gap. Upstream wells retain an asset-specific lifecycle; production dates, load and fuel suitability remain unknown unless evidenced. Existing Prospect/Lead gates remain authoritative. News is supplemental.

The bounded target is to make retained official permits useful through the existing project enrichment action and detail UI. Reuse evidence, claims and runs; no research framework or queue. Extract only attributable site/identity, permit scope/type/dates and supported organization/person/contact fields. Project-to-organization, organization-to-person and person-to-project remain distinct. A contractor name is not a person or proof of buying authority.

Source feasibility, final implementation limits and live validation will be recorded here. No national coverage, full application coverage, commissioning feed or all-drilling-permit ingestion is claimed. No outreach or deployment.

## Shipped boundary

The registry still has 13 enabled sources. Chicago acquisition now retains the
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
- **Drilling:** the official RRC download index and its linked daily GoDrive page
  returned HTTP 200 in this cloud executor. The index describes a current-month
  cumulative daily file. The portal showed 3,248 files with a 250-row first page;
  that is a file listing, not permit coverage. Current-file download, stateful
  pagination, parsing and complete ingestion were not verified. There is no new
  RRC connector and no claim that all drilling permits are ingested. Access was
  not denied; reliable current retrieval remains unfinished lower-priority work.
- **Georgia:** all 19 current application-link fields remained empty. Full air
  applications and comprehensive public contact acquisition remain unproven.
- No BidBuy bypass, generic procurement expansion, outreach or deployment.

See [live acceptance and validation](../validation/gl3-019-validation.md) for
measured examples, exact code hashes, before/after results and source limits.
