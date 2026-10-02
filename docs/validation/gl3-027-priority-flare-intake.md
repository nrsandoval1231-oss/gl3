# GL3-027: acquisition priorities and flare/vent applications

Branch `feat/gl3-027-priority-flare-intake` starts at `94cba4e13197701bde52178e6ece6acd4c485296`, the unmerged GL3-026 draft PR16. It records the owner's priority geographies (Dallas, Austin, Houston, El Paso, California) and commercial order (data-center construction, data-center commissioning, oil and gas), without disabling other sources or claiming a new runtime ranking algorithm.

The twentieth enabled source is the official Texas RRC SWR 32 public query. Its ordinary anonymous form and JSF paginator retrieve a count-checked three-day Texas-calendar submittal window. The first page-size experiment and an incomplete paginator request were rejected before persistence; publisher JavaScript established the normal `_skipChildren` and `_encodeFeature` parameters and AJAX headers. No authentication or access control was bypassed. Detailed application retrieval did not establish a usable selected-record route; no details or attachments are claimed.

## Actual acquisition, persistence and replay

The current app database was backed up and cloned to isolated UTF8 `gl3_027_accept`, preserving `gl3_026_app` and the original recovery databases. The ordinary worker ingested 38 unique filings submitted September 29–October 1, 2026, at 2026-10-02 00:37 UTC (October 1 in Texas). It saved 38 observations and evidence versions, with no manufactured physical projects or Signals. Filing number anchors identity; submittal and authorization dates remain distinct and publication date remains unknown.

Immediate ordinary-worker replay retrieved all 38 unchanged, with zero new or changed records. All seven inspected tables were exactly equal: observations (16,921), evidence (16,960), projects (1,168), power needs (1,168), need-observation links (1,170), buying-chain claims (49), and interpretations (16,921). Row-level snapshots are retained locally; the public count/parity receipts are in `.agent/artifacts/GL3-027`. Existing 1,167 visible Signal records remain unchanged.

Real examples retained include DIAMONDBACK E&P LLC filing 35895 and CONTINENTAL RESOURCES, INC. filing 35906 (a renewal/amendment). Each retains operator number, property label, district, original query URL and filing locator. These are operator roles, not verified buying authority. No person or public business contact is present in the acquired list fields. Gas flow, composition, power fit, MW, rental need and exact physical flare/well location remain unknown.

The task-local API and worker were restarted on the validated clone; the authenticated Ingestion screen shows the new source under Oil & gas, 38 retained records, source citations, dates and the evidence-only explanation. Screenshot `ui/flare-ingestion.png` was visually inspected. This is local runtime verification, not a cloud deployment; automatic refresh remains off.

## Scope and remaining gaps

The adapter checks 10-row pages up to 50 pages/500 records, with a 2 MB response and 20 MB run bound. Malformed/incomplete acquisition fails before persistence; ordinary jobs retain retry/fencing and last-good behavior. Status changes within the overlapping window create new evidence under the same filing identity. Older filings outside the window are not rechecked; historical backfill and detail enrichment remain gaps. The official historical count of 21,470 is not ingested coverage.

Existing Dallas monthly, Austin issued/modified, Houston weekly sold/detail and El Paso NewCommercial feeds remain enabled with their documented limits. Firecrawl discovered official CEC, San Jose and CalGEM routes for California; no California feed is enabled by this slice. Backup-generation capacity is not temporary construction/commissioning load, and general well permits are not flare authorizations.

## Validation

The first full run passed Ruff, 559 pytest tests (one existing skip), frontend typecheck/build, clean/repeated migrations, migration drift check, 18 relevant browser tests and diff check. Mypy found six BeautifulSoup attribute narrowing errors, repaired with validated string attributes and nullable-tag checks. The final full run passed every gate, including mypy across 59 source files, 559 pytest tests (one existing skip) and 18 browser tests. No tests or admission requirements were weakened. Four prior historical-corpus browser exclusions remain unchanged and are recorded in the exact command receipt.

The final repaired code also completed another live 38-row unchanged replay with exact seven-table parity. An intervening queued check was claimed and completed by the existing background worker before the controller could claim it; its retained receipt has `ran=false`, `status=succeeded`. The controller stopped only its owned worker, performed the final scoped check itself, and restarted the local API and worker. No lease, retry or scheduling rule was changed to force success.

Changed implementation surfaces: the new RRC adapter and unit tests; adapter routing, registry validation/configuration, ingestion permit dispatch and permit interpretation. Documentation updates cover README, adapter ownership, owner priorities and source coverage. No migrations, frontend redesign, outreach or CRM changes.

Parent launch, national completeness and qualified Lead acceptance remain open. No merge or cloud deployment is claimed.

Independent Sol review returned PASS for the exact 317-file manifest `850efc765dbf26f42f16e060af16b36cfe5c90db2deb5e4c704a4dad74060ba1`. Review verified every manifest byte, source/evidence boundaries, controller gate receipts and actual UI pixels. No material findings. Acceptance is limited to this local slice.
