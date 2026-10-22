# Visual comparison and remaining differences

The [side-by-side](desktop-side-by-side.png) and [50% overlay](desktop-overlay.png) compare the exact owner JPEG, resized from 1280 × 720 to 1648 × 928, with the running application. Reference landmarks are approximate image measurements. No pixel-similarity percentage is claimed: records and fonts differ.

| Primary landmark | Reference, approximately | Synthetic API | Historical ACS API |
|---|---:|---:|---:|
| Header height | 58 px | 58 px | 58 px |
| Sidebar width | 412 px / 25% | 412 px | 412 px |
| Identity top / height | 108 / 134 px | 108.3 / 134 px | 108.3 / 134 px |
| Metrics top / height | 251 / 115 px | 250.3 / 117.9 px | 250.3 / 117.9 px |
| Central area top / height | 377 / 374 px | 378.2 / 374 px | 378.2 / 390.1 px |
| Why / next-action height | 218 / 146 px | 218 / 146 px | 218 / 163.1 px |
| Evidence tabs top | 766 px | 762.2 px | 778.3 px |
| Evidence table top | 855 px | 860.6 px | 876.8 px |

Metric columns retain the measured native width ratio 164:192:172:187:194 with a 5px primary gutter. Main content starts at x429.3 versus about x431 in the reference and is about 9px wider. These small geometry differences remain visible in the overlay. Header/canvas use exact Navy/Ice, borders use Mist and selection uses restrained Signal Blue.

The ACS action text and disabled-research reason require 17px more height than the illustrative action list, moving its table about 22px below the reference. At 1440/1280, longer names, organizations, missing-metric explanations and actual next actions cause further growth. The synthetic 1280 dashboard is 474.6px high, with table y922.2; the historical dashboard is 390.7px high, with table y838.2. Desktop retains its sidebar, five metrics, three information columns and detail scrolling. These are explicit density differences, not native-width pixel parity.

At 768, selected detail replaces the queue until Back; the header uses two rows and sections reflow. At 390, identity/metrics precede contacts, supported project disclosures and the next action; a workflow control stays reachable. No horizontal page overflow was observed. Keyboard Back restores row focus.

Expected content differences:

- Actual API records replace illustrative Microsoft figures, dates and contacts. Missing company logos use monograms.
- Four real application routes replace six illustrative destinations. Account identity is generic because the session exposes no named profile. Actions use the existing persisted workflow.
- Unsupported metrics remain unestablished. Qualification, source roles and supported-fields/total completeness remain explicit; no commercial confidence score is invented.
- Evidence controls use actual retained entries/source filters, rather than invented category counts. Diagnostics and title enrichment remain available after the table.

**Unresolved brand difference:** ABC Diatype binaries and the official wordmark master are absent. Browser headings use Arial; existing Aperture/wordmark exports are retained, with the wordmark documented as an approximation. Exact typography/full visual acceptance remain blocked. Proper fonts may change wrapping; repeat this matrix and overlay after integration.

The mechanical Impeccable detector returned one warning for an existing 3px call-preparation accent border in workspace.css. The generic recommendation does not override the approved selective-accent treatment or preserved workflow. [Raw output](impeccable-detector.json) is retained; this is a classified warning, not a clean detector pass.
