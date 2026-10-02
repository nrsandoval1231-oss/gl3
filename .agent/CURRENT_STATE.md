# Current state

GL3-027 LOCAL ACCEPTED on `feat/gl3-027-priority-flare-intake`, base `94cba4e13197701bde52178e6ece6acd4c485296` (GL3-026 draft PR16, unmerged). Owner priorities are recorded in PRD, vertical strategy and decisions: Dallas, Austin, Houston, El Paso, California; data-center construction, commissioning, then oil and gas. Other sources remain enabled. Packet: `packets/GL3-027.md`.

Independent Sol PASS on manifest `850efc765dbf26f42f16e060af16b36cfe5c90db2deb5e4c704a4dad74060ba1`; all local gates passed, including 559 backend tests/one existing skip and 18 browser tests. Real official SWR 32 ingestion retained 38 applications; final replay preserved seven tables exactly. The authenticated local app shows the flare source in Ingestion and retains 1,167 visible Signals. See `docs/validation/gl3-027-priority-flare-intake.md` and `artifacts/GL3-027/REVIEW.json`.

Runtime uses preserved clone `gl3_027_accept`, API8023/web5193. Original databases, local edits and credentials remain preserved. Automatic refresh is off. California enabled coverage, flare detail/site enrichment and historical backfill remain gaps. No unsupported gas-to-power, rental or authority claims. Parent launch remains OPEN. Next direction: push the accepted branch and deliver a draft PR against main with its PR16 dependency; no merge or cloud deployment.
