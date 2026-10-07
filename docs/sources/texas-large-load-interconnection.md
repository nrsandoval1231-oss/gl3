# Texas large-load interconnection — narrow §25.194 mapping

Inspected main: `94c3acb7b36c6d5d04a77a0ec445e793e05120a4` on October 7, 2026.
Main already has immutable Evidence, mutable current Observation envelopes,
accepted Interpretation JSON, project lifecycle events, and separate activity
PowerNeeds. It does not have typed agreement, study, allocation-report, or
financial-security state. This change reuses those evidence primitives and adds
a read-only request projection; it requires no migration.

## Source facts versus interpretation

Primary source: [Texas Register, October 2 adopted Title 16 rules](https://www.sos.texas.gov/texreg/archive/October22026/Adopted%20Rules/16.ECONOMIC%20REGULATION.html),
Project 58481, TRD-202604027. Publication is October 2; effective date is October 8,
2026. Rule provenance is stored separately from project evidence.

The adopted text provides these mapping anchors:

- Subsections (a), (b), and (c)(14): ERCOT and single-site non-coincident demand;
  new requests at least 75 MW, first threshold-crossing expansions, expansions
  of existing large loads by at least 75 MW, and generation co-location.
- Subsection (d): intermediate agreement execution and funding precede study inclusion.
- Subsection (d)(2)(B): intermediate security uses requested demand for new
  requests and the incremental addition for expansions, at the 2026 $50,000/MW rate.
- Subsection (f): execution and funding of SLLIA are due within 60 days of
  ERCOT issuing the allocating study report. Notification and publication dates
  are different dates. SLLIA security may exceed its per-MW floor.
- Subsections (h) and (i): pending requests have transition provisions, not a
  blanket exemption. Batch-zero financial treatment needs separate review.

The code's applicability, baseline and deadline calculations are **advisory
interpretations**, not project source facts or legal compliance determinations.
Financial amounts observed in a project document remain reported amounts;
calculated baselines never become proof that security was posted. No deadline
calculation infers cancellation, forfeiture, funding, energization, available
supply, a power gap, rental demand, or a commercial tier.

## Existing storage and minimal additions

| Concern | Representation |
|---|---|
| Project/site identity | Reuse `Project.id` and `identity_key`; preserve site matching upstream. |
| Source provenance | Reuse `Source`, `Observation`, and immutable `Evidence`: publisher, URL, hash, publication/event/retrieval dates and extraction location. |
| Request identity | Required `request_id` inside `Interpretation.assessment.large_load_interconnection`; distinct requests never share calculations. Use the source request serial or a reviewed site/request-specific identifier. |
| Scope | Typed facts `ercot_region`, `energized_as_of_effective_date`, `request_kind`, `expected_site_peak_mw`, `existing_site_peak_mw`, `colocated_generation`, `batch_zero`. |
| Agreement and study state | Separate reported intermediate execution/funding dates, study state, and SLLIA execution/funding dates. No sequential state is inferred from another milestone. |
| Allocation timing | `allocating_study_report_issued_on` and `allocated_mw`; an explicit zero allocation is retained. No deadline anchor is synthesized from notice/retrieval/publication dates. |
| Financial evidence | Reported security USD, form and stage; study fee paid USD. Security baseline is calculated separately and excludes known batch-zero treatment; unknown transition status is flagged. |
| API projection | Existing `/api/projects/{project_id}/state` dictionary gains `state.large_load_interconnection` with rule provenance and per-request facts/interpretation/limitations. |
| Lifecycle and qualification | Existing lifecycle and activity PowerNeed fields are unchanged; campus demand never becomes construction/commissioning/rental MW. |

Each fact has a field, typed value and exact quote from retained `Evidence.abstract`.
Admission requires an already accepted, current, hash-bound interpretation for
the same project. The nested payload repeats version, project identity, evidence
ID and hash; readers verify both outer and nested bindings. Undated or future
publications, absent quotes, invalid values and future occurrence dates are
rejected. Conflicting current values remain CONFLICT, with both sources retained.
No last-write-wins selection is used to erase a disagreement.

An energized-as-of-effective-date fact must explicitly support that cutoff;
do not infer ERCOT membership from Texas geography or apply the threshold to
nameplate generation, IT load estimates, regional totals or rental scope.
Unknown co-location cannot establish an exemption for a small expansion.

## Reviewed retained-evidence path

`gridlens.intelligence.interconnection.attach_interconnection_facts` is the
internal transaction-scoped entry point for reviewed facts from an existing
accepted project Evidence record. It does not fetch sources or admit a project.
It serializes project/interpretation writes, preserves all existing assessment
keys, and treats an identical replay as a no-op. A different payload cannot
overwrite accepted facts at the same evidence version; submit corrected content
through the normal evidence/version path. Rejected or superseded observations
are excluded from the current projection without deleting historical Evidence.

Example call, with actual retained IDs supplied by the caller:

```python
attach_interconnection_facts(
    session, project_id, evidence_id,
    request_id=source_request_serial,
    facts=[{
        "field": "allocating_study_report_issued_on",
        "value": report_issue_date,
        "quote": exact_retained_quote,
    }],
    today=as_of_date,
)
```

The runtime reads the rule clock in America/Chicago. The 2026 security baseline
is not extrapolated from 2032, when the rule schedules adjustment. The rule's
SLLIA clock is anchored only to a supported report issue date. Missing execution
or funding after a derived deadline produces a request to check evidence, not
a finding that the customer violated the rule. Unknown allocation MW stays unknown.

## Coverage and limits

There is no new automated Texas Register, ERCOT queue or agreement feed, no
enabled registry entry, no live customer backfill, and no claim that confidential
commitments are public. General rulemaking material cannot create site-specific
Signals. Existing jobs/source health remain unchanged. This is a usable retained
evidence contract and project-state projection, not automatic document extraction.

Interconnection changes are not added to the morning material-change feed in
this slice. Existing immutable Evidence and accepted assessment bindings provide
provenance, but a regulatory notification workflow would be a separate extension.

Targeted tests cover thresholds, first crossings and incremental security,
ERCOT/energization applicability, co-location uncertainty, effective-date gating,
batch-zero review, report-date deadlines, zero allocation, separate execution and
funding, malformed/contradictory claims, source/project/version binding, replay,
history protection and the real project-state projection. All fixtures are synthetic.
