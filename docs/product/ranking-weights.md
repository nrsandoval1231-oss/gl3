# Opportunity ranking weights — DRAFT, pending Nick's approval

Requirement 27: rank active needs by timing, recent material change, evidence strength, product fit and purchasing accessibility; publish the weights; show the principal reasons; never rank solely by campus MW or tier.

Version `ranking-draft-v1` (`backend/src/gridlens/domain/ranking.py`). Score is 0–100 points. It orders attention. It is not a probability or a confidence, and it never changes a tier.

| Factor | Points | How points are earned |
|---|---:|---|
| Product fit | 25 | Owner priority order: DC commissioning with phase evidence 100% · DC construction phase 95% · explicit temporary/construction/bridge scope 90% · DC commissioning evidence 80% · DC construction evidence 75% · producing O&G asset 70% · DC, phase unknown 60% · O&G activity 50% · other 30% |
| Timing | 20 | Supported start window 100% · construction or commissioning phase 70% · derived lifecycle window 40% · unknown 10% |
| Evidence strength | 20 | Lead 100% · Prospect 70% · Signal 40% · source status needs review 25% · unresolved conflict 10% |
| Recent change | 15 | Evidence dated within 30 days 100% · within 90 days 50% · older 0% |
| Buyer access | 10 | Direct responsible party in the buying chain (owner, GC, EPC, electrical, commissioning, procurement, operator) 100% · project company known 50% · unknown 0% |
| Geography | 10 | DFW, Austin, Houston, El Paso or California 100% · elsewhere in Texas 50% · other 0% |

Each opportunity shows its score and up to three largest contributing reasons.

## What changes on approval

- Today the score and reasons are shown, and the home view features the highest-ranked loaded record. The list order is still most-recently-updated.
- After approval: the default list order switches to rank, the version becomes `ranking-v1`, and this file drops "DRAFT".
- Weights change only by editing this table and `WEIGHTS` together, with a new version.

## Open questions for Nick

1. Is product fit at 25 right, or should timing lead?
2. Should a DFW record outrank an otherwise equal Houston record (today they tie)?
3. Should O&G producing assets sit above data centers whose phase is unknown (today 70% vs 60%)?
