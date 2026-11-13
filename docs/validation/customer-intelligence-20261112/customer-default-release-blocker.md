# Customer default policy: unresolved release blocker

The retained-source runtime evaluation traversed native ingestion, enrichment, canonical project-scoped identity links and saved-browse publication, then called both customer endpoints. It created no reference company/project IDs and used no external provider.

| Read | Observed result |
| --- | ---: |
| Account queue | 2 WATCH accounts |
| Ordinary `customer_results.groups(shortlist=False)` | 2 groups: DataBank and CyrusOne |
| Current default `groups(shortlist=True)` | 0 groups |
| Open DataBank from ordinary groups | Succeeded |

The exact receipt is [native-runtime-replay-operational-final-20261113.json](../../../eval/customer-commercial-v1/runtime/native-runtime-replay-operational-final-20261113.json). Both companies have zero eligible needs under the existing opportunity-shortlist policy. Their commissioning/rental demand is unknown; creating fictional demand to qualify them would be incorrect.

The primary customer workspace still defaults to Shortlist. The existing `web/tests/default_browse_mode.spec.ts:53` explicitly asserts the Shortlist button is pressed; line60 also requires a `shortlist=true` request. Those checks encode the earlier product policy. They pass as written but contradict the requested customer-first default for these real retained sources.

The proposed change is to default Customers to ordinary canonical account browsing, retain the explicit Shortlist control, and preserve qualified/need-scoped Pursuits eligibility, evidence restrictions, filters, cohort fencing, authentication and privacy. Its regression should require the ordinary request and visible customer groups, while preserving the existing data, navigation, selection and Pursuits assertions. It must also retain an explicit Shortlist regression.

The owner's instruction requires existing tests to remain unmodified and says to stop and explain before changing one. An asynchronous question requests a specific exception for the affected default-policy tests. No exception has been received; neither the default nor those assertions has been changed. The current candidate therefore cannot be called commercially accepted or production-ready even if CI is green. This is not missing public information or a browser timing issue.
