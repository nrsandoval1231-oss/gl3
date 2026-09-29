# GL3-015 current-source Signal review

This was the **pre-repair read-only selector review**. The final ordinary-worker, persisted-card and withdrawal review is [GL3-015 persisted Signal card review](gl3-015-persisted-signal-review.md); its findings supersede this document's activation assessment.

Read-only run on 2026-09-29 from `feat/gl3-015`: loaded the configured Taylor source and called `taylor_newsflash.retrieve`, then `interpret_taylor_planning` on every returned row. This made bounded public GETs only. No application database, production-like records, or fixture rows were written. Command shape:

```powershell
$env:PYTHONPATH=(Resolve-Path 'backend/src').Path
uv run --directory backend python -c "from gridlens.ingestion.registry import load_registry; from gridlens.ingestion.adapters.taylor_newsflash import retrieve; from gridlens.domain.taylor_planning import interpret_taylor_planning; s=next(x for x in load_registry() if x['id']=='taylor-development-newsflash'); rows=retrieve(s); print(len(rows)); print([(r['document_number'],r['title']) for r in rows if interpret_taylor_planning(r)])"
```

The current official sweep returned **25 observation versions**, of which **two** passed the current deterministic Taylor Signal selector. These are adapter candidates, **not persisted current Signal cards**. Source freshness is limited by Taylor's published items: the selected notices were dated 2026-04-21 and 2026-08-07, not new events on the run date. No statistically meaningful precision, lead-time or duplicate rate follows from this small local sample.

| Candidate | Event and authority | Identity, relevance and evidence | Quality judgment |
|---|---|---|---|
| Project Comal | Taylor Development News article `2032`, 2026-04-21, Employment Center Plan at 1051 CR 401. [Official item](https://taylortx.gov/m/newsflash/home/detail/2032) | Named project, site and planning action; credible early physical-project evidence. Future electrical demand is worth investigating; MW, service timing and temporary need UNKNOWN. | Worth showing as a dated planning Signal, with clear original event date. It is not proof of construction start. |
| Project Mustang | Taylor Development Notices archived article `2079:arcId=3434`, 2026-08-07, PZ 2026-2715 Employment Center Plan. [Official archive](https://taylortx.gov/m/NewsFlash/Archive/Item/2079?arcId=3434) | Named proposed campus and planning case; source also returns later `2079:arcId=3442` labeled **WITHDRAWN** on 2026-09-04. | **Weak as a current active card.** The selector recognizes the old notice and suppresses the withdrawn revision, but first-time ingestion can still create a Signal from the prior revision. History should retain both, while current display must foreground withdrawal. Do not activate until verified. |

The other 23 versions include routine planning items (for example a Chick-fil-A SUP, general development-code amendments), other project types, and archive revisions. They are useful retained observations but do not justify a data-center Signal. The two selected versions have distinct article/case identities; no project duplicate was proven in this read-only run. That is not a database-level project-matching test. The earlier isolated Taylor persistence test retained 25 observations with unchanged replay, but did not prove today's end-to-end card state.

**What is missing:** current electrical/temporary-service records, air application breadth, utility large-load project records, upstream completion-to-production, fixed O&G facility events, and wider pre-permit geography. The Taylor registry entry is enabled locally, but the next narrow implementation should make superseding Taylor dispositions prominent on the same project and prove a clean current isolated persisted-card replay before treating it as end-to-end accepted. Unknown relationship between Project Mustang's withdrawn zoning application and overall campus viability must remain UNKNOWN.
