# Customer scope gap — bounded diagnostic, November 13, 2026

The retained 20-organization evaluation has **17 raw capacity candidates and seven raw timeline candidates, but zero scoped claims**. A read-only diagnostic reproduced the rejection of each of those 24 assertions using the actual `scope_customer_facts` function and the exact supplied project name/location stored in the result. **All 24 fail the first named-subject gate**; none reaches the later electrical-predicate checks. All 26 retained supporting-quote variants likewise fail that first gate. This explains the measured cohort's zero publication coverage without asserting that production overall has zero facts.

Evidence: `eval/customer-commercial-v1/results/scoped-candidate-1de298af-reference-r2.json`, SHA-256 `42445efbd6b3fd4e8c5ec0b80ad00e62ff8bf8ce73c5269c07eae433ab811040`. Its four measured source modules were hash-checked against the current files before diagnosis; they match backend repair `1de298af047f09a32e9a0349f41410a55bc1791e`. No gold, source, runner, metric, or application code was edited for this diagnostic; no database or external source was queried.

## Observed rejection path

| First gate result | Capacity candidates | Timeline candidates |
| --- | ---: | ---: |
| No admitted exact named subject | 17 | 7 |
| Admitted subject reaching later predicate checks | 0 | 0 |

`intelligence/customer_intelligence.py:128` calls `_subject_predicate(quote, [project_name])`. The helper at `domain/project_research.py:89` admits only reference strings with at least two normalized words, then requires the **whole clause to begin with the exact reference** (`re.fullmatch`, line 97). One candidate has the supplied one-word name `Frontier`, so that name is excluded from the helper's eligible references. The other 23 assertions fail the literal sentence-leading subject requirement with their supplied project labels. The optional exact `project_name at project_location` form at integration lines 129–142 does not rescue any of these 24 clauses; a city or county cannot substitute for the project name.

At integration lines143–146 a missing predicate is immediately discarded. Later checks reject coordinated/comparative predicates and restrict the local electrical/timing grammar (lines147–174). Those later checks exist, but **were not the observed rejection stage here**.

## Three retained examples

1. **Applied Digital; supplied project `Ellendale campus`.** Exact retained candidate quote: “Applied Digital’s Ellendale campus is designed to host 400 MW of critical IT load.” The quote begins with the company's possessive, not the exact supplied project label. `_subject_predicate` returns `None`. This demonstrates an evidence-presentation/subject-span coverage limitation even where the owner and project appear explicitly in the clause. It does not establish that broadening the name match alone would pass the later predicate gate.

2. **CyrusOne; supplied project `New CyrusOne facility adjacent to Thad Hill Energy Center`.** Exact retained quote: “The deal secures power, grid connection, and land to support a new state of the art facility that is currently under construction and expected to be operational by the fourth quarter of 2026.” Its subject is “The deal”; the fixture's descriptive project label is not an exact leading subject. The correctly matched raw operational deadline remains withheld. Resolving that anaphora safely requires evidence-bound source/project context; this fixture did not invoke canonical project matching.

3. **Compass; supplied project `Meridian campus`.** Exact retained quote: “This 200 MW campus, located 30 miles west of Chicago in Hoffman Estates, is strategically positioned to support growing demand for capacity in the Midwest.” The first subject gate rejects it. This is necessary withholding: the retained markets page discusses several physical sites, and this amount belongs to Chicago, not Meridian. Admitting any sentence mentioning the same company would introduce a real cross-site error.

## What this does and does not establish

The runner supplies independently labeled project names/locations and `fixture-project:*` keys (`scripts/evaluate_customer_commercial.py:214,244`). These are targeted-extraction inputs, **not resolved runtime canonical identities**. Runtime uses the stored `Project.name` and `Project.location` at integration line312; the actual stored names and full discovery/identity path were not exercised by this cohort. A fixture label can therefore differ from a source-native or stored project name. The diagnostic neither certifies those supplied names as database identities nor measures end-to-end identity accuracy.

The evaluator marks these official-company sources `primary`; runtime maps non-`.gov` hosts to `unknown` (integration line291). That is a separate confidence/source-priority limitation. The scope function does not inspect authority when rejecting these clauses, so this mismatch is **not the cause of their first-gate rejection**. Contact acquisition and verification were not invoked and are not explained by this diagnostic.

## Safest reuse path

Keep the existing accepted-current-evidence admission, observation/evidence hash checks, project identity binding and immutable provenance (`intelligence/customer_intelligence.py:80–92,255–277,320–327`). Extend that same path to retain evidence-bound project/phase subject spans or source context for admitted claims, rather than treating a whole multi-project page as a single site's electrical evidence. Require real-source positives through actual stored canonical project identities and counterexamples for other sites, phases, acquisitions and comparisons before broadening grammar. Do not substitute a loose city match, corporate alias, guessed source name or a fixture-only synonym for physical-project proof.

The practical blocker remains coverage: the safe publication path withholds every candidate in this bounded real-source cohort. Improving it must preserve the necessary cross-site refusals illustrated above. No release, commercial-usefulness or production-readiness acceptance follows from this diagnosis.
