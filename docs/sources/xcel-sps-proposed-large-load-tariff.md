# SPS Texas large-load tariff proposal — Docket 60332

Reviewed 2026-10-07 against GL3 main `94c3acb7b36c6d5d04a77a0ec445e793e05120a4`.

## Smallest useful representation

`config/tariffs/xcel-sps-tx-60332.json` is a manually reviewed, utility-level
proposal record. `gridlens.domain.utility_tariff_proposals` validates and reads
it. Keep it separate from the enabled ingestion source registry: this is not an
active feed. The CLI emits validated JSON without network or database access:

```bash
PYTHONPATH=backend/src python -m gridlens.domain.utility_tariff_proposals \
  config/tariffs/xcel-sps-tx-60332.json
```

Current main already has Observation raw payloads, immutable Evidence versions
and Interpretation assessment JSON. No schema migration is warranted for this
bounded representation. This change intentionally does not create a project,
attach the general tariff to a need, or extend the existing project-state API.
There is no supported project/utility-service association in this source itself.
PR29 (§25.194) and PR30 (public ERCOT RFI) remain independent draft work.

## Primary sources and date discrepancy

- [Application, item 2](https://interchange.puc.texas.gov/Documents/60332_2_1687520.PDF):
  receipt and proposed notice date September 25, 2026. Attachment A contains
  the actual proposed revisions to LGS-T, Sheet IV-108, revision 17.
- [Order No. 1, item 9](https://interchange.puc.texas.gov/Documents/60332_9_1689557.PDF):
  October 2; requests staff recommendations on completeness, notice and schedule
  by October 9. It does not approve the tariff. Its description calls the petition
  September 30; this conflicts with the application receipt and is retained as a
  limitation rather than used to rewrite that receipt.
- [Xcel announcement](https://newsroom.xcelenergy.com/news/xcel-energy-proposal-protects-texas-customers-from-higher-bills-as-electric-demand-from-data-centers-grows):
  September 28. It describes the proposal and explicitly reserves PUCT approval.
- [Docket listing](https://interchange.puc.texas.gov/search/filings/?ControlNumber=60332):
  nine items visible at review, through Order No. 1.

The requested October 30 effective date is only `proposed_effective_date`.
Neither passage of time nor a procedural order makes this record operative.
Subsequent approval, amendment, withdrawal or rejection requires source review
and a separate contract; this proposal-only schema cannot represent an approved tariff.

## Verified scope, not an automatic eligibility rule

Attachment A verifies an inclusive 75 MW threshold for aggregated peak
contracted load or qualifying peak contracted load growth. It is SPS Texas
retail LGS-T service at 69 kV or above, not a statewide ERCOT requirement and
not New Mexico. Aggregation uses delivery points within 2.5 miles under common
ultimate ownership/control, with an exception for noncontrolling interests below
50%. Off-Peak Alternate Rider delivery points do not count. Standby,
supplementary, resale and shared service are excluded. Growth is an increase
of at least 75 MW after September 25, 2026. The full conditions accompany the
numeric field; this change provides no simplistic `project_mw >= 75` matcher.

## Economics and commitments

Each term carries a source and section locator. Attachment A supports the
15-year full-load term plus any elected ramp period, possible existing-service
credit, 80% contracted-load minimum-bill basis, application/study fees, security,
termination and renewal terms. Detailed conditions remain text because billing
and contract adjudication are outside this slice.

Do not collapse three different statements:

1. **Proposed direct interconnection terms:** customer-funded CIAC in advance.
2. **Proposed dedicated generation terms:** customer responsibility for incremental
   generation and associated facilities/operating costs, subject to utility and
   separate SPP processes. These do not guarantee backup or generation access.
3. **Future rate-case intent:** allocation of incremental generation/transmission
   costs via a later proposed cost test, anticipated for the second half of 2027.
   This application says it does not change customer rates.

The broad announcement about transmission, substations, upgrades and new
generation remains labeled announcement content. It is not substituted for
these more specific filing terms.

## Interpretation and acquisition boundaries

These are reported proposal facts, not legal conclusions. Potential commercial
relevance is a research hypothesis: customers may evaluate power alternatives
when commitments and upfront costs affect project economics. No delay, power gap,
executed ESA, financial commitment, purchasing authority, tier or priority follows
from this utility proposal alone.

Validate later incoming records before consumption. A provenance citation is a
reviewed attribution, not cryptographic proof that its text supports a claim;
source-kind validation does not replace human/source-content verification.
If later ingested, reuse Observation/Evidence hash and version binding, preserve
prior claims, and keep this metadata outside project qualification until explicit
project-specific evidence exists. No parser, source scheduling, ingestion writer,
UI, production backfill, database mutation or deployment is delivered here.
