# Opportunity ranking weights

Requirement 27: rank active needs by timing, recent material change, evidence strength, product fit and purchasing accessibility; publish the weights; show the principal reasons; never rank solely by campus MW or tier.

Version `ranking-v2-regional-geography` applies the owner's October 22 TX/OK/NM geographic ordering to the weights approved October 14; all six factor weights remain unchanged from `ranking-v1` (`backend/src/gridlens/domain/ranking.py`). Score is 0–100 points. It orders attention. It is not a probability or a confidence, and it never changes a tier.

| Factor | Points | How points are earned |
|---|---:|---|
| Product fit | 25 | Owner priority order: DC commissioning with phase evidence 100% · DC construction phase 95% · explicit temporary/construction/bridge scope 90% · DC commissioning evidence 80% · DC construction evidence 75% · producing O&G asset 70% · DC, phase unknown 60% · O&G activity 50% · other 30% |
| Timing | 20 | Supported start window 100% · construction or commissioning phase 70% · derived lifecycle window 40% · unknown 10% |
| Evidence strength | 20 | Lead 100% · Prospect 70% · Signal 40% · source status needs review 25% · unresolved conflict 10% |
| Recent change | 15 | Evidence dated within 30 days 100% · within 90 days 50% · older 0% |
| Buyer access | 10 | Direct responsible party in the buying chain (owner, GC, EPC, electrical, commissioning, procurement, operator) 100% · project company known 50% · unknown 0% |
| Geography | 10 | Evidence-supported TX project 100% (10 points) · OK 66.67% (6.67 points) · NM 33.33% (3.33 points) · other/unknown/conflicted 0% |

Each opportunity shows its score and up to three largest contributing reasons.

## How rank is used

- Each opportunity shows its score and principal reasons.
- The home view features the highest-ranked loaded record.
- Lists default to rank order, highest first. Equal or missing ranks keep most-recently-updated order.
- `GET /api/opportunities?sort=rank` ranks the whole filtered cohort on the server before paging, so the map's bounded pages are the highest-ranked records. Ranks come from the same detail projection the page displays, computed in batches of 50, so the score shown is the score used for ordering. A rank cohort token also works for group and record drill-downs, which check cohort membership only. The default API order (`sort=updated`) is unchanged for other callers.
- Weights change only by editing this table and `WEIGHTS` together, with a new version.

The October 22 regional mandate supersedes the prior metro/California geography component. Territory comes from the versioned regional policy in the source registry; ranking never grants geographic eligibility or changes qualification. The final score rounds the sum of all six components.
