# Customer-commercial reference input contract v2

Status: proposed review contract. This is an additive context layer over
`eval/customer-commercial-v1`; it does not replace v1 gold, sources, scores or
the existing evaluation path. No v1 file is edited by this proposal.

## Purpose

V1 stores useful display labels and source-supported capacity/timeline
assertions, but it does not consistently show whether a label is literally
named in the assigned excerpt, which text names the physical project, or
whether a quantity refers to a building, campus, phase, regional portfolio,
adjacent energy asset or AI compute cluster. A display label is not itself
source proof of physical identity.

V2 therefore adds `source-context-annotations.json`. Every v1 organization
record remains present. Every capacity and timeline assertion is referenced
by its original record ID and JSON Pointer and is protected by a canonical
assertion hash. Each contextual quote binds to an exact source bundle field,
source file hash, text hash, quote, and half-open Unicode-code-point span.
Offsets are measured in the exact decoded JSON string before normalization;
quotes are copied verbatim and are not whitespace-normalized.

## Required annotation dimensions

For each organization record, v2 separates:

1. The unchanged v1 display label (`company`, `project`, `location`) and an
   explicit statement of whether that label is literal, compositional,
   title-only, ambiguous, or unsupported by the assigned source.
2. The exact source phrase for the physical subject, with status
   `explicit_named_subject`, `explicit_descriptive_subject`,
   `multi_site_subject`, `title_only_subject`, `ambiguous_subject`, or
   `unsupported_subject`. A derived normalized name is never presented as a
   source quote.
3. Source-supported site aliases, kept separate from nearby places, customer
   names, energy partners, corporate portfolios, and AI clusters.
4. Asset scope: `single_facility`, `campus`, `phase`, `building`, `multisite`,
   `regional`, `adjacent_generation`, `ai_cluster`, `mixed_or_ambiguous`, or
   `unknown`, plus evidence refs and a support status.
5. Location relation: same project/site, host campus, adjacent asset, region
   only, title-only, unsupported, or unknown.
6. Organization role and owner proof. Developer, operator, planned developer,
   customer, EPC contractor, and energy partner are distinct. A role quote does
   not establish legal ownership. `owner_proof.status` remains
   `not_established` unless the assigned text explicitly names ownership of
   this exact physical subject.
7. A subject-binding disposition for every original assertion: `same_subject`,
   `nested_subject`, `regional_or_portfolio`, `other_site`,
   `adjacent_generation`, `cluster_not_physical_site`, `nonphysical_measure`,
   `ambiguous`, or `unsupported_by_assigned_source`. An assertion is never
   deleted to make a denominator smaller. Each disposition has a reason and
   exact source-context evidence references.
8. The unchanged V1 scoring-denominator decision, separately from subject
   binding. A subject-bound compute figure, utility supply, or announced event
   can still be ineligible for a particular physical-capacity or operational
   milestone metric. A conflicting date can remain bound to the same project
   while its temporal value is unresolved. V1 r2 contains 34 capacity and 30
   timeline assertions (64 total), of which 32 capacity and all 30 timeline
   assertions are in its physical-capacity-plus-timeline scoring denominator.
   The QTS approximately 4.5MW lease with unspecified basis and Fervo's
   contracted 900MW offtake remain in the source-context set but are excluded
   from V1's physical-capacity denominator.

## Optional evaluation mode

V1 raw extraction, V1 reference scoring, source-context binding, and native
end-to-end publication are separate results. A future v2 evaluator may report:

- **Context coverage:** counts of all retained assertions by disposition,
  with unresolved, excluded, and source-unsupported counts shown explicitly.
- **Context-bound extraction:** extraction results against assertions whose
  assigned text supports the same subject or an explicitly nested phase,
  building, or component. This is conditional recall and must be labelled as
  such; it cannot replace the all-v1 reference denominator.
- **Extraction missingness:** source-present, subject-bound assertions with no
  corresponding raw extraction, separated from ambiguous or unsupported
  context.
- **Native end-to-end:** retained-source admission, current Evidence/Need,
  project-scoped role, saved customer membership, and rendered-card output.
  This is reported independently; labels from reference annotations never
  create runtime aliases, identities, or memberships.

The mandatory context-coverage invariant for every mode is:

`all v1 assertions = context-bound + context-excluded + context-unresolved`.

The independent historical V1 scoring invariant remains:

`64 source assertions = 62 V1-scored assertions + 2 V1 capacity exclusions`.

These are distinct partitions. Context-bound does not imply that the
measurement basis qualifies for a particular physical metric.

The v1 evaluator and retained outputs remain byte-for-byte the historical
baseline. V2 does not change parser inputs, gold values, matching rules, source
selection, or production behavior. No v2 metric should be published until all
20 annotations, classification denominators, and exclusion reasons receive
independent review.

## V2 artifact contents

`source-context-annotations.json` is a versioned overlay. It contains the v1
gold file hash, a manifest of all 114 pre-v2 files under the v1 tree,
20 organization annotations, exact source spans, and per-assertion pointers
and hashes. The accompanying unit test validates file preservation, exact span
reconstruction, 20/20 record coverage, and the all-assertions denominator
invariant. It does not claim that the provisional annotations are correct; an
independent review is required before any optional v2 score is treated as
accepted.
