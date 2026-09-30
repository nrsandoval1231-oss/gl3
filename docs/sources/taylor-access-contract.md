# Taylor CivicPlus access contract

**Decision:** GO for a bounded adapter implementation using the observed official HTML surfaces, with fail-closed enumeration and replay checks. This is not source activation, production coverage, or proof of an atomic upstream snapshot.

## Observed surfaces

- Development News category 30: `GET https://taylortx.gov/m/NewsFlash?cat=30`.
- Development Notices category 31: `GET https://taylortx.gov/m/NewsFlash?cat=31`.
- Category roots render linked detail pages as `/m/NewsFlash/Home/Detail/{numeric-id}`. Each response is ordinary HTML; follow only links parsed from the official category response. Preserve root and article response hashes.
- Archive root: `GET https://taylortx.gov/m/NewsFlash/Archive`. The rendered controls expose category/item mode (`archCc`), inclusive start and end date inputs, row counts 10/25/50, and offset (`skip`) pagination. Archive result rows expose publication date, archived date, and detail paths `/m/NewsFlash/Archive/Item/{article-id}?arcId={revision-id}`.
- Archived category links are also exposed from the archive root, for example `/m/NewsFlash/Archive/Category/31?arcId=41`. That view describes category archive metadata; it is not a substitute for item revision enumeration.

## Reproducible bounded completeness procedure

For the declared archive interval 2026-08-01 through 2026-09-28, the observed request was:

```text
GET /m/NewsFlash/Archive?archCc=2&startDate=2026-08-01&endDate=2026-09-28&count=10&skip=0
```

`archCc=2` selects items, as shown in the archive page's own controls. The dates bound archive activity: the returned records' Archived Date values fell in the interval, including items whose Published Date predates it. Store publication, event, archived, and retrieval dates separately; do not conflate them.

The first page reported **1–10 of 13**. Requesting `skip=10` returned **11–13 of 13**, with Next Page and Last Page disabled. Thus, a bounded sweep can enumerate the selected interval by incrementing `skip` by `count`, requiring consistent total and contiguous page ranges, and stopping only when the final displayed range reaches that total and the UI marks Next Page disabled. Preserve and hash every original response, and verify the final set of `(article_id, arcId)` identities on a repeat sweep or first-page re-fetch. If totals/ranges/identity sets change, or parsing fails, mark incomplete/UNKNOWN and restart the fixed interval; never emit a complete result from a partial page walk.

The archive filter returns items across categories, so inspect each archived item response's rendered category label before associating it with categories 30/31. Category roots supply current published items; archive enumeration supplies archived changes. Do not claim the category root alone is complete history.

No server snapshot token was observed. The procedure establishes complete client-side enumeration only while the result set remains stable across the sweep and replay check. A concurrent archive update may change the set; detect visible drift and fail closed. No guarantee of atomic consistency is available from this evidence.

## Identity and replay

Use the numeric article ID as source article identity and `arcId` as the archived revision identity. The observed article 2079 has archive revisions 3434 and 3442. Both direct pages return 200; arcId 3434 has a non-WITHDRAWN title and arcId 3442 adds WITHDRAWN. Keep each revision; do not overwrite the earlier evidence or infer project cancellation from the notice disposition. The archived item page supplies the Development Notices label.

For a repeated retrieval of the same `(article_id, arcId)`, identical SHA-256 over retained response bytes is identical replay; changed bytes under that pair must be retained as changed evidence and surfaced for review. A changed `arcId` is a new source revision even if content later looks similar. No ETag or Last-Modified contract was validated, so do not use either as authoritative version identity.

## Access limits

The proof used only public, unauthenticated HTTPS GETs to official Taylor pages. No credentials, paid API, POST, or hidden route was used. Successful retrieval does not establish rights for bulk republication; this work makes no determination about copyright, terms, or robots rules. Keep any future use to attributable factual evidence and obtain review before wider republication or materially increased collection. Request cost, service rate limits, retention, and update latency remain unpublished/UNKNOWN.

The bounded access check covered the category roots, two archive pages, one archive category, and one archived article revision. The retained article fixtures used by parser tests are in `backend/tests/fixtures/`.
