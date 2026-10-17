/** Canonical server-only transport. Copy byte-for-byte to consumers with the v1 validator.
 * Only configured origins; no browser-supplied targets, credentials or redirects.
 */
import { validateFeed } from './editorial-contract.mjs'
export function gridlensConnection({ origin, password, fetcher = fetch }) {
  const base = new URL(origin)
  if (
    base.username ||
    base.password ||
    base.pathname !== '/' ||
    base.search ||
    base.hash ||
    (base.protocol !== 'https:' &&
      !(
        base.protocol === 'http:' &&
        ['127.0.0.1', 'localhost'].includes(base.hostname)
      ))
  )
    throw new Error('Invalid GridLens origin')
  let cookie = '',
    loginPending
  async function bounded(response) {
    if (!response.ok || !response.body)
      throw new Error('GridLens unavailable or clearance withdrawn')
    const reader = response.body.getReader()
    const chunks = []
    let size = 0
    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        size += value.byteLength
        if (size > 1_000_000) throw new Error('Response exceeds limit')
        chunks.push(value)
      }
    } finally {
      await reader.cancel()
    }
    return JSON.parse(Buffer.concat(chunks).toString('utf8'))
  }
  async function login() {
    if (!password) throw new Error('GridLens connection is not configured')
    const r = await fetcher(new URL('/api/auth/login', base), {
      method: 'POST',
      redirect: 'error',
      signal: AbortSignal.timeout(10000),
      headers: { 'Content-Type': 'application/json', Origin: base.origin },
      body: JSON.stringify({ password }),
    })
    await bounded(r)
    const token = /(?:^|;\s*)gridlens_session=([^;]+)/.exec(
      r.headers.get('set-cookie') || '',
    )?.[1]
    if (!token || !/^[A-Za-z0-9_-]{20,128}$/.test(token))
      throw new Error('GridLens authentication failed')
    cookie = 'gridlens_session=' + token
  }
  async function request(path, retry = true) {
    if (!cookie) {
      loginPending ||= login().finally(() => {
        loginPending = undefined
      })
      await loginPending
    }
    const r = await fetcher(new URL(path, base), {
      method: 'GET',
      redirect: 'error',
      signal: AbortSignal.timeout(10000),
      headers: { Cookie: cookie, Accept: 'application/json' },
    })
    if (r.status === 401 && retry) {
      cookie = ''
      return request(path, false)
    }
    const document = await bounded(r)
    if (document.version !== '2g-editorial-sync/1' || !document.clearances)
      throw new Error('Unsupported clearance envelope')
    validateFeed(document.feed)
    for (const c of document.feed.items) {
      const clearance = document.clearances[c.id]
      if (
        !clearance ||
        clearance.status !== 'approved' ||
        clearance.evidenceVersion !== c.evidence[0].contentHash ||
        !Number.isFinite(Date.parse(clearance.reviewedAt))
      )
        throw new Error('Unbound clearance')
    }
    return document
  }
  return {
    sync: () => request('/api/editorial/sync'),
    async resolve(id, version) {
      if (
        !/^gridlens:[a-f0-9-]{36}$/.test(id) ||
        !/^[a-f0-9]{64}$/.test(version)
      )
        throw new Error('Invalid candidate identity')
      const document = await request('/api/editorial/clearance/' + id.slice(9))
      const candidate = document.feed.items.find(
        (c) => c.id === id && c.evidence[0].contentHash === version,
      )
      if (!candidate)
        throw new Error(
          'Evidence changed or approval withdrawn; synchronize again',
        )
      return candidate
    },
  }
}

export function validatePublications(document, now = new Date()) {
  if (
    document?.version !== 'pgr-publications/1' ||
    !Array.isArray(document.items) ||
    document.items.length > 500
  )
    throw new Error('Invalid publication history')
  const seen = new Set()
  return {
    version: document.version,
    items: document.items.map((item) => {
      const url = new URL(item.url)
      if (
        url.origin !== 'https://thepowergapreport.com' ||
        !/^\/reports\/[a-z0-9-]+$/.test(url.pathname) ||
        url.pathname.includes('/dispatch-') ||
        url.search ||
        url.hash ||
        seen.has(url.href) ||
        typeof item.title !== 'string' ||
        !item.title ||
        item.title.length > 1200 ||
        !/^\d{4}-\d{2}-\d{2}$/.test(item.publishedAt) ||
        !Number.isFinite(Date.parse(item.publishedAt)) ||
        new Date(item.publishedAt).toISOString().slice(0, 10) !==
          item.publishedAt ||
        Date.parse(item.publishedAt) > now.getTime()
      )
        throw new Error('Invalid published issue')
      seen.add(url.href)
      if (
        !Array.isArray(item.topics) ||
        item.topics.some((x) => typeof x !== 'string' || x.length > 1200) ||
        !Array.isArray(item.candidateIds) ||
        item.candidateIds.some((x) => !/^gridlens:[a-f0-9-]{36}$/.test(x))
      )
        throw new Error('Invalid coverage metadata')
      return {
        title: item.title,
        url: url.href,
        publishedAt: item.publishedAt,
        topics: item.topics,
        candidateIds: item.candidateIds,
      }
    }),
  }
}
export function publishedRssMetadata(xml) {
  // Compatibility with the publication's existing structured RSS, not page scraping.
  if (
    xml.length > 1_000_000 ||
    /<!DOCTYPE|<!ENTITY/i.test(xml) ||
    !xml.includes('</rss>')
  )
    throw new Error('Invalid publication RSS')
  const decode = (s) =>
    s.replace(
      /&(?:amp|lt|gt|quot|apos|#39);/g,
      (e) =>
        ({
          '&amp;': '&',
          '&lt;': '<',
          '&gt;': '>',
          '&quot;': '"',
          '&apos;': "'",
          '&#39;': "'",
        })[e],
    )
  const items = []
  for (const match of xml.matchAll(/<item>([\s\S]*?)<\/item>/g)) {
    const value = (tag) =>
      decode(
        new RegExp('<' + tag + '>([\\s\\S]*?)</' + tag + '>')
          .exec(match[1])?.[1]
          ?.trim() || '',
      )
    const url = value('link')
    if (
      !/^https:\/\/thepowergapreport\.com\/reports\/[a-z0-9-]+$/.test(url) ||
      url.includes('/dispatch-')
    )
      continue
    const date = new Date(value('pubDate'))
    if (!Number.isFinite(date.getTime()) || date > Date.now()) continue
    items.push({
      title: value('title'),
      url,
      publishedAt: date.toISOString().slice(0, 10),
      topics: [value('category')].filter(Boolean),
      candidateIds: [],
    })
  }
  return {
    ...validatePublications({ version: 'pgr-publications/1', items }),
    metadataSource: 'published-rss',
    candidateLinkage: 'unavailable',
  }
}
export async function publicationHistory(fetcher = fetch) {
  const options = {
    redirect: 'error',
    signal: AbortSignal.timeout(8000),
    headers: { Accept: 'application/json, application/rss+xml' },
  }
  let r = await fetcher(
    'https://thepowergapreport.com/editorial-publications.json',
    options,
  )
  const legacy = r.status === 404
  if (legacy)
    r = await fetcher('https://thepowergapreport.com/rss.xml', {
      ...options,
      signal: AbortSignal.timeout(8000),
    })
  if (!r.ok || !r.body) throw new Error('Publication history unavailable')
  const reader = r.body.getReader(),
    chunks = []
  let size = 0
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      size += value.byteLength
      if (size > 1_000_000) throw new Error('Publication history exceeds limit')
      chunks.push(value)
    }
  } finally {
    await reader.cancel()
  }
  const raw = Buffer.concat(chunks).toString('utf8')
  return legacy
    ? publishedRssMetadata(raw)
    : {
        ...validatePublications(JSON.parse(raw)),
        metadataSource: 'published-manifest',
        candidateLinkage: 'explicit-only',
      }
}
