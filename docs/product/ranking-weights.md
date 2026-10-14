# Opportunity ranking weights

Requirement 27: rank active needs by timing, recent material change, evidence strength, product fit and purchasing accessibility; publish the weights; show the principal reasons; never rank solely by campus MW or tier.

Version `ranking-v1`, approved by Nick on 2026-10-14 with the weights unchanged from `ranking-draft-v1` (`backend/src/gridlens/domain/ranking.py`). Score is 0–100 points. It orders attention. It is not a probability or a confidence, and it never changes a tier.

| Factor | Points | How points are earned |
|---|---:|---|
| Product fit | 25 | Owner priority order: DC commissioning with phase evidence 100% · DC construction phase 95% · explicit temporary/construction/bridge scope 90% · DC commissioning evidence 80% · DC construction evidence 75% · producing O&G asset 70% · DC, phase unknown 60% · O&G activity 50% · other 30% |
| Timing | 20 | Supported start window 100% · construction or commissioning phase 70% · derived lifecycle window 40% · unknown 10% |
| Evidence strength | 20 | Lead 100% · Prospect 70% · Signal 40% · source status needs review 25% · unresolved conflict 10% |
| Recent change | 15 | Evidence dated within 30 days 100% · within 90 days 50% · older 0% |
| Buyer access | 10 | Direct responsible party in the buying chain (owner, GC, EPC, electrical, commissioning, procurement, operator) 100% · project company known 50% · unknown 0% |
| Geography | 10 | DFW, Austin, Houston, El Paso or California 100% · elsewhere in Texas 50% · other 0% |

Each opportunity shows its score and up to three largest contributing reasons.

## How rank is used

- Each opportunity shows its score and principal reasons.
- The home view features the highest-ranked loaded record.
- Lists default to rank order, highest first. Equal or missing ranks keep most-recently-updated order.
- Rank orders the records already loaded (the most recently updated, up to 200). It does not re-query the full archive by rank.
- Weights change only by editing this table and `WEIGHTS` together, with a new version.
