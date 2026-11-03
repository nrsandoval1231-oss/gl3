# Commercial proof — full accessible population (2026-11-03)

**Scope:** evidence from one disposable-database ingest of every enabled registry source reachable from the build sandbox, then `scripts/commercial_proof.py` (read-only transaction, resumable, no sample or top-N cutoff). No production data, credentials or paid providers were used. This is a dated observation, not production evidence, and says nothing about sustained scheduled operation.

**Harness notes:** HTTP clients were forced to honor the sandbox egress proxy by a shim in a scratch script outside the repo (no repository code changed). Postgres was 16 (repo targets 18.6). Evaluator rules are evaluator rules, not product behavior.

## Population and completeness
| Measure | Value |
|---|---|
| Enabled sources attempted | 29 |
| Sources that returned data | 18 |
| Sources failed (`network_error` in the worker path in this sandbox) | 11: albuquerque-building-permits, oklahoma-deq-public-review, spp-thermal-interconnection, texas-ercot-large-load-status, texas-jeti-agreements, texas-puct-large-load-{dockets,filings}, texas-tceq-{construction-noi,egu-registrations,nsr-pending,temporary-batch-plants} |
| Records in population / evaluated / unprocessed / evaluation failures | 4,886 / 4,886 / 0 / 0 |
| Unique projects | 1,063 |
| Unique organizations (normalized name, count only; nothing merged) | 251 (140 appear on more than one project) |

The 11 failed sources are an accessible-population limit of this environment. The ERCOT adapter succeeded standalone with the proxy shim but failed in the worker path, and the cause was not isolated. The failures must not be read as source defects, and the sources remain unevaluated. The interconnection, utility-filing and TCEQ sources, which are the highest-value early signals, are in that unevaluated set.

## Classification
| Class | Records |
|---|---|
| Commercial Hit | 3 |
| Investigation Candidate | 1,191 |
| Rejected | 3,692 |

Reason codes (a record may carry several): no_organization 3,652; no_power_evidence 4,501; buyer_not_identified_contractor_or_unknown_role 624; triage_watch 420; no_project_site 147.

## Coverage and yield
Provenance URL 100%; organization named 25.3%; owner/operator role 8.7%; any power evidence 7.6% (quantified 0.5%); eligible project site 21.8%; next action 21.8%. Hits are 0.1% of records and 0.3% of unique projects.

## Verification of hits
Two rule defects were found in the first pass and corrected before these numbers: contractors were counted as buyers (three Austin permits), and two permits for one address were counted as two opportunities. The three remaining hits were checked against the live TDLR TABS pages: Beacon Point Data Center (Robstown, $399M, 657,130 sq ft), DAL130 Data Center (Westlake, $83M, Circle T Owner LP), and EG AI Rice Campus (Rice, $5M, 8,599 sq ft, EG AI Corp). Each is a real project with a source-stated owner.

## Findings that set engineering priorities
1. **Buyer identification is the binding constraint, not scoring.** 75% of records have no organization, and most named organizations are contractors or drilling operators with no power evidence.
2. **Next action is generic.** All hits recommend "call the cited public project contact", which in TDLR records is the accessibility-specialist form filer, not the owner's power decision-maker. The owner contact is in the same record for some projects.
3. **Evidence-only named applicants are discarded.** JETI applications supply 39 real named industrial applicants and no site; with no power evidence they are Rejected under the evaluator's rule. This is a rule-sensitivity point (owner decision), not a measured defect.
4. **Power demand is almost never stated** (0.5% quantified), so electrical-demand work depends on acquiring engineering documents, not on a better calculator.
5. **Facility dedupe.** Permit-level records for one address need a facility key; location normalization yields 143 distinct strings against 1,063 projects and is not a reliable facility key for county-level oil and gas locations.
6. **Source reachability** of the 11 failed sources needs observation from an environment with direct egress.

## Limitations
No independent human review beyond the three hit checks; Investigation Candidates are unreviewed. Austin permit and RRC drilling volumes dominate the population. Results do not generalize to production data.
