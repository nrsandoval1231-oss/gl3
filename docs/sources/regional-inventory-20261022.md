# Regional source inventory — October 22, 2026

All 29 registered sources were inspected against immutable base `0f876440a1375c502534cc1dd3c08ceff38c7349`. Status below means registry policy, not verified runtime success. A = Texas, B = Oklahoma/New Mexico, C = national with regional relevance, D = out of region. National feeds are filtered by physical project location at backend admission and queries. Original definitions/evidence/history remain retained.

| Source | Physical coverage | Category | Previous policy / observed health | New policy | Reason |
|---|---|---|---|---|---|
| texas-rrc-flare-vent-exceptions | Texas | A | Enabled / Updated | Enabled | Existing TX acquisition |
| boston-building-permits | Boston, Massachusetts | D | Enabled / Partial | Disabled | Outside exclusive TX/OK/NM territory |
| texas-rrc-drilling-permits | Texas | A | Enabled / Updated | Enabled | Existing TX acquisition |
| dallas-monthly-permits | Dallas, Texas | A | Enabled / Checked—No Change | Enabled | Existing TX acquisition |
| el-paso-new-commercial-permits | El Paso, Texas | A | Enabled / Checked—No Change | Enabled | Existing TX acquisition |
| houston-weekly-permits | Houston, Texas | A | Enabled / Failed | Enabled | Existing TX acquisition |
| austin-building-permits | Austin, Texas | A | Enabled / Partial | Enabled | Existing TX acquisition |
| seattle-building-permits | Seattle, Washington | D | Enabled / Partial | Disabled | Outside exclusive TX/OK/NM territory |
| chicago-building-permits | Chicago, Illinois | D | Enabled / Partial | Disabled | Outside exclusive TX/OK/NM territory |
| georgia-air-draft-title-v | Georgia | D | Enabled / Failed | Disabled | Outside exclusive TX/OK/NM territory |
| federal-register-eis | United States | C | Enabled / Updated | Enabled | National upstream evidence; physical-project region required |
| nc-commerce | North Carolina | D | Enabled / Checked—No Change | Disabled | Outside exclusive TX/OK/NM territory |
| dcd-news | Global, including US and international coverage | C | Enabled / Checked—No Change | Enabled | National upstream evidence; physical-project region required |
| utility-dive-news | US-focused with international coverage | C | Enabled / Checked—No Change | Enabled | National upstream evidence; physical-project region required |
| manufacturing-dive-news | US-focused with international coverage | C | Enabled / Checked—No Change | Enabled | National upstream evidence; physical-project region required |
| construction-dive-news | US-focused with international coverage | C | Enabled / Checked—No Change | Enabled | National upstream evidence; physical-project region required |
| ogj-exploration-news | Global, including US and international coverage | C | Enabled / Checked—No Change | Enabled | National upstream evidence; physical-project region required |
| taylor-development-newsflash | Taylor, Texas | A | Enabled / Updated | Enabled | Existing TX acquisition |
| mjbizdaily-news | US-focused with international coverage | C | Enabled / Updated | Enabled | National upstream evidence; physical-project region required |
| ma-ccc-cultivation-applications | Massachusetts | D | Enabled / Failed | Disabled | Outside exclusive TX/OK/NM territory |
| texas-tceq-nsr-pending | Texas | A | Enabled / Checked—No Change | Enabled | Existing TX acquisition |
| texas-tceq-temporary-batch-plants | Texas | A | Enabled / Checked—No Change | Enabled | Existing TX acquisition |
| california-ceqanet-data-centers | California | D | Enabled / Checked—No Change | Disabled | Outside exclusive TX/OK/NM territory |
| fort-worth-development-permits | Fort Worth, Texas | A | Enabled / Checked—No Change | Enabled | Existing TX acquisition |
| san-antonio-development-permits | San Antonio, Texas | A | Enabled / Checked—No Change | Enabled | Existing TX acquisition |
| texas-tdlr-tabs-data-centers | Texas | A | Disabled / Overdue | Disabled | Preserve pre-existing disabled/manual status |
| f17-stack-city-claim | Santa Clara, California | D | Disabled / Overdue | Disabled | Preserve pre-existing disabled/manual status |
| f17-stack-cec-filing | Santa Clara, California | D | Disabled / Overdue | Disabled | Preserve pre-existing disabled/manual status |
| f17-crusoe-impact | Abilene, Texas | A | Disabled / Overdue | Disabled | Preserve pre-existing disabled/manual status |

There are **no dedicated OK or NM sources** in the registry. OCC/DEQ, OCD/NMED/PRC, ERCOT, PUCT, FERC, EIA, EPA and SEC are examples to assess for future coverage, not implemented integrations in this registry. TCEQ and both RRC routes exist. Federal Register is the implemented national regulatory adapter; six publisher RSS feeds supplement it. No new integrations are added.

The three `retained-document` entries are manual evidence sources rather than automated adapter dispatch. TDLR is implemented but was already disabled; its source-readiness decision is preserved. Existing disabled entries are not portrayed as failures. Current per-source execution/freshness and concrete blockers belong in the [engineering report](../operations/regional-stabilization-20261022.md); enabled policy alone is never source health proof.

Previous observed health is the read-only production snapshot captured at `2026-10-22T19:43:17.713011+00:00`; it is dated baseline evidence, not a present availability claim. Operator enablement and registry enablement are separate. A disabled/manual registry entry may have had an old persisted Overdue health value; the regional candidate must report it as intentionally disabled.
