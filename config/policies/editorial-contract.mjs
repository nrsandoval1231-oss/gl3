/** 2g-editorial/1 consumer boundary. Fail closed; no network or publication actions. */
const FIELDS = 'id origin title sourceUrl publisher sourceType publishedAt firstSeenAt lastMaterialChangeAt publicationEligibility geography industry eventClassification whatChanged verifiedFacts unknowns interpretations hypotheses commercialSignificance technicalImplications editorialAngles whyNow recommendedArticleType evidenceQuality confidence evidence score'.split(' ')
const TEXT = 'id title publisher sourceType geography industry eventClassification whatChanged commercialSignificance technicalImplications whyNow recommendedArticleType evidenceQuality confidence'.split(' ')
function assert(ok, reason) { if (!ok) throw new Error(`Invalid editorial feed: ${reason}`) }
function keys(obj, allowed) { assert(obj && typeof obj === 'object' && !Array.isArray(obj) && Object.keys(obj).every(k => allowed.includes(k)), 'unknown fields') }
function text(s) { return typeof s === 'string' && s.trim().length > 0 && s.length <= 1200 }
function day(s) { return typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s) && new Date(s).toISOString().slice(0,10) === s }
function instant(s) { return typeof s === 'string' && /T.*(?:Z|[+-]\d\d:\d\d)$/.test(s) && Number.isFinite(Date.parse(s)) }
export function canonicalUrl(s) {
  const u = new URL(s)
  assert(u.protocol === 'https:' && !u.username && !u.password && !u.port && !u.hostname.endsWith('.local') && u.hostname.includes('.') && !/^[\d.]+$/.test(u.hostname), 'source URL')
  assert(![...u.searchParams.keys()].some(k=>/^(token|access_token|api_key|apikey|password|signature)$/i.test(k)), 'credential-bearing source URL')
  u.hash = ''
  for (const k of [...u.searchParams.keys()]) if (/^utm_|^(fbclid|gclid)$/i.test(k)) u.searchParams.delete(k)
  u.searchParams.sort()
  u.pathname = u.pathname.replace(/\/$/, '') || '/'
  return u.href
}
export function validateFeed(feed, now = new Date()) {
  keys(feed, ['version','generatedAt','items','rejected'])
  assert(feed.version === '2g-editorial/1', 'version')
  assert(instant(feed.generatedAt) && Date.parse(feed.generatedAt) <= now.getTime() + 300000, 'export date')
  assert(Array.isArray(feed.items) && feed.items.length <= 3, 'candidate limit')
  const ids = new Set(), urls = new Set()
  for (const c of feed.items) {
    keys(c, FIELDS)
    assert(FIELDS.every(k => Object.hasOwn(c,k)), 'missing field')
    assert(TEXT.every(k => text(c[k])), 'text')
    assert(c.origin === 'gridlens' && c.id.startsWith('gridlens:'), 'origin')
    assert(c.publicationEligibility === 'approved-public', 'publication restriction')
    assert(day(c.publishedAt) && instant(c.firstSeenAt), 'source dates')
    assert(c.lastMaterialChangeAt === null, 'unsupported material-change date')
    const age = Math.floor(now.getTime()/86400000) - Date.parse(c.publishedAt)/86400000
    assert(age >= 0 && age <= 30 && Date.parse(c.firstSeenAt) <= now.getTime(), 'stale or future source')
    const url = canonicalUrl(c.sourceUrl)
    assert(!ids.has(c.id) && !urls.has(url), 'duplicate')
    ids.add(c.id); urls.add(url)
    assert(c.geography.startsWith('United States'), 'market')
    assert(['primary','reported'].includes(c.evidenceQuality) && ['medium','high'].includes(c.confidence), 'quality')
    assert(Number.isInteger(c.score) && c.score >= 14 && c.score <= 21, 'score')
    for (const field of ['unknowns','interpretations','hypotheses','editorialAngles']) {
      assert(Array.isArray(c[field]) && c[field].length <= 12 && c[field].every(text), field)
    }
    assert(c.unknowns.length > 0 && c.editorialAngles.length > 0, 'context')
    assert(Array.isArray(c.evidence) && c.evidence.length === 1, 'evidence')
    const e = c.evidence[0]
    keys(e, ['id','url','contentHash','publishedAt'])
    assert(text(e.id) && canonicalUrl(e.url) === url && /^[a-f0-9]{64}$/.test(e.contentHash) && e.publishedAt === c.publishedAt, 'provenance')
    assert(Array.isArray(c.verifiedFacts) && c.verifiedFacts.length > 0 && c.verifiedFacts.length <= 8, 'facts')
    for (const fact of c.verifiedFacts) {
      keys(fact, ['text','evidenceIds','status'])
      assert(text(fact.text) && fact.status === 'source-reported' && Array.isArray(fact.evidenceIds) && fact.evidenceIds.length === 1 && fact.evidenceIds[0] === e.id, 'fact citation')
    }
  }
  if (feed.rejected !== undefined) {
    assert(Array.isArray(feed.rejected) && feed.rejected.length <= 200, 'rejections')
    for (const r of feed.rejected) { keys(r,['id','reason']); assert(text(r.id) && text(r.reason),'rejection') }
  }
  return feed
}

export function researchBrief(c) {
  const list = rows => rows.map(s => `- ${s}`).join('\n')
  return `# ${c.title}\n\nSource: ${c.publisher} · ${c.publishedAt}\n${c.sourceUrl}\n\n## What changed\n${c.whatChanged}\n\n## Source-reported facts\n${list(c.verifiedFacts.map(f=>f.text))}\n\n## Analytical interpretations\n${list(c.interpretations)}\n\n## Hypotheses — not established\n${list(c.hypotheses)}\n\n## Evidence gaps\n${list(c.unknowns)}\n\n## Technical implications\n${c.technicalImplications}\n\n## Commercial implications\n${c.commercialSignificance}\n\n## Potential thesis\n${list(c.editorialAngles)}\n\nRecommended type: ${c.recommendedArticleType}\n`
}
export function draftOutline(c) {
  return `NOT APPROVED FOR PUBLICATION — RESEARCH OUTLINE\n\n${researchBrief(c)}\n## Original reporting to develop\nExplain the mechanism, test the thesis, seek contrary evidence, and add useful analysis beyond the source.\n\n## Editorial review\nConfirm every factual claim against its original evidence; separate inference; check dates, equipment claims, conflicts and originality.\n\n## Publication approval\nPending human approval. This file is outside the published content tree.\n`
}
