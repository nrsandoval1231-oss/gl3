import { useEffect, useRef, useState } from 'react'
import { client, OpportunityCohortChangedError, type Opportunity, type OpportunityPage } from '../../api/client'
import { projectTitle } from '../opportunities/projectCards'

// Browsing is independently paged; the bounded map never limits record access.
export function BrowseRecords({ tier, lens, search, offset, onPage, onSelect }: {
  tier: string; lens: string; search: string; offset: number
  onPage: (offset: number) => void; onSelect: (item: Opportunity) => void
}) {
  const [result, setResult] = useState<{ key: string; page?: OpportunityPage; error?: string }>({ key: '' })
  const [revision, setRevision] = useState(0)
  const cohort = useRef<{ key: string; token: string } | null>(null)
  const filterKey = JSON.stringify([tier, lens, search])
  const key = `${filterKey}:${offset}:${revision}`
  useEffect(() => {
    const controller = new AbortController()
    void (async () => {
      try {
        let first: OpportunityPage | undefined
        if (offset === 0 || cohort.current?.key !== filterKey) {
          first = await client.opportunityPage(tier.slice(0, -1), search, 'ALL', 50, 0, undefined, { industry: lens }, controller.signal, 'rank')
          if (controller.signal.aborted) return
          cohort.current = { key: filterKey, token: first.cohortToken }
        }
        const page = offset === 0 && first ? first : await client.opportunityPage(tier.slice(0, -1), search, 'ALL', 50, offset, cohort.current?.token, { industry: lens }, controller.signal, 'rank')
        if (!controller.signal.aborted) setResult({ key, page })
      } catch (cause) {
        if (!controller.signal.aborted) setResult({ key, error: cause instanceof OpportunityCohortChangedError
          ? 'Matching records changed. Return to the first page to refresh this list.'
          : cause instanceof Error ? cause.message : 'Records could not be loaded.' })
      }
    })()
    return () => controller.abort()
  }, [key])
  const ready = result.key === key
  const page = ready ? result.page : undefined
  return <section data-context-loading={!ready}>
    <p className="env-eyebrow">All matching records · national scope</p>
    <h1 tabIndex={-1}>Browse {tier.toLowerCase()}</h1>
    <p className="env-lede">The current tier, lens and search apply to this list. Every matching page is available; map counts remain a separate loaded subset.</p>
    {!ready && <p role="status">Loading records…</p>}
    {ready && result.error && <p role="alert">{result.error} <button onClick={() => setRevision((value) => value + 1)}>Retry records</button></p>}
    {page && <>
      <p>{page.items.length ? `${offset + 1}–${offset + page.items.length}` : '0'} of {page.totalCount} matching records</p>
      {page.items.length ? <ul className="env-list" data-context-scroll="browse-records">{page.items.map((item) => <li key={item.id}>
        <button type="button" data-context-key={`browse:${item.id}`} onClick={() => onSelect(item)}><strong>{projectTitle(item)}</strong><span>{item.location ?? 'Location unknown'} · {item.activity.replaceAll('-', ' ')} · {item.tier}</span></button>
      </li>)}</ul> : <p>No matching records on this page.</p>}
    </>}
    <nav className="env-pagination" aria-label="Record pages">
      <button disabled={!offset} onClick={() => onPage(0)}>First records</button>
      <button disabled={!offset || !ready} onClick={() => onPage(Math.max(0, offset - 50))}>Previous records</button>
      <button disabled={!page || page.nextOffset === null} onClick={() => { if (page?.nextOffset != null) onPage(page.nextOffset) }}>Next records</button>
    </nav>
  </section>
}
