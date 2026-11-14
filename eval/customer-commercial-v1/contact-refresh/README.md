# Current customer contact refresh

Observation date: **2026-11-13**. This is a read-only research dataset for the same 20 organizations in `../reference-customers-r2.json`. It records observed first-party roles with currentness limits without editing the reference fixture or its existing source excerpts.

## Files

- `contact-refresh.json` contains one row per reference organization, relevant names and roles, the exact supporting quote, source IDs, currentness scope, project-assignment limits, and any published organizational contact channel found in the captured page footer.
- `source-manifest.json` lists captured source URLs, observation date, source text byte/character counts, explicit publisher publication dates, separate SEC filing dates, and SHA-256 hashes.
- `company-identity-evidence.json` contains SEC name/EIN/website excerpts with exact byte offsets and source-file hashes for review. It distinguishes proof from mismatch/hold cases.
- `raw/` retains complete Firecrawl-rendered Markdown for the retrieved company pages. SEC filing pages used for issuer/domain review are retained as full Markdown `.md` files; the smaller SEC index pages are retained as JSON captures. Any SEC source captured only as excerpts is labeled as such in the manifest.
- `build_manifest.py` and `build_identity_evidence.py` reproduce the offline manifests/quote offsets from the captured files. They make no network calls.

## Reading the records

Leadership pages are first-party sources. A name on an undated page means it appeared on that company roster when retrieved; the page does not establish the precise start date or prove continued employment after observation. The company-wide leadership names are not assigned to the referenced construction project unless the source explicitly says so.

The dataset includes 36 names across the 20 rows. Some rows are deliberately empty or historical-only:

- **Vantage:** an older page fragment still presents Jeff Tench as President, North America, but his global EVP biography explicitly says that role was previous; Dana Adams is listed as President, North America. Effective dates are not stated. Samuel Huckaby is listed as VP, Construction in an undated retained block, so current employment is not independently verified.
- **Google:** the official careers page exposed only first names beside several role labels, so no full named person is asserted.
- **Amazon Web Services:** Roger Wehner appears only in the January 25, 2024 project announcement. The record makes no current-employment claim.
- **Microsoft:** Noelle Walsh is supported by a June 22, 2026 Microsoft datacenter article as President, Cloud Operations and Innovation, overseeing physical cloud infrastructure and operations. The source does not assign her to Fairwater.
- **Compass:** the text calls the Chief Delivery Officer Tamara Yang while the headshot alt text says Tammy Yang; the source variation is retained.
- **STACK:** Omar Muhialdin is listed for APAC and is flagged as out of region for U.S. project SVY01 unless a project assignment is separately evidenced.
- **QTS:** the current page footer says QTS Realty Trust, LLC. This is retained as a brand-level association and is not bound to a historical Inc. legal form.
- **Dominion:** Emil Avram is specifically listed with Dominion Energy Virginia. The page does not establish a parent-level employment relationship or a CVOW assignment.
- **Meta:** the reference project page has no current full named relevant leader in the captured text.

## Identity evidence and limits

The source pages establish public company/role associations, not native GridLens UUIDs. The SEC filings provide clear company-name, EIN, and official-domain evidence for Applied Digital, Equinix, and Microsoft; the corresponding customer source hosts are subdomains of the filing-stated domains. This is not project assignment evidence.

Other identity cases remain constrained:

- Meta's filing names `investor.atmeta.com` and `meta.com/news`; it does not explicitly bind the reference project host `datacenters.atmeta.com`.
- The Digital Realty filing excerpt lists both Digital Realty Trust, Inc. and Digital Realty Trust, L.P. with separate EINs. The identity is held rather than resolved by dropping the legal form.
- Amazon's SEC issuer is Amazon.com, Inc.; that alone does not establish the reference entity Amazon Web Services or bind the `aboutamazon.com` host.
- Dominion's supporting source is an SEC-hosted annual report filed as ARS. The captured index says it was filed March 19, 2026; the publisher publication date was not established. It is not a completed same-10-K parser proof.

No named-person email or phone was inferred. Organizational channels are included only where the company page itself exposed a shared inbox or official contact page. No outreach, paid contact provider, source activation, production write, or credentials were used.
