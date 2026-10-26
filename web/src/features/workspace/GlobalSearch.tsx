import { useEffect, useRef, useState } from 'react'
import { client, type GlobalSearchResult } from '../../api/client'
import './global-search.css'

type SearchHit = { id?: string; need_id?: string; project_id?: string; company_identity_id?: string; name?: string; title?: string; organization?: string; location?: string | null; region_state?: string | null; tier?: string; updated_at?: string | null; verification_status?: string; confidence?: string; methods?: { kind: string; value: string }[]; aliases?: string[]; project_count?: number; need_count?: number; required_mw?: string | null; start_window?: string | null; rank_score?: number | null; sources?: unknown[] }
const list = (value: unknown): SearchHit[] => Array.isArray(value) ? value.filter((item): item is SearchHit => Boolean(item && typeof item === 'object')) : []
const label = (hit: SearchHit) => hit.name || hit.title || hit.organization || 'Unnamed result'

export function GlobalSearch({ onNeed, onCompany }: { onNeed: (needId: string) => void; onCompany: (companyId: string, companyName: string) => void }) {
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<GlobalSearchResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(false)
  const searchRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const value = query.trim()
    if (value.length < 2) { setResult(null); setError(''); setLoading(false); return }
    setResult(null)
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setLoading(true); setError('')
      void client.search(value, controller.signal).then(data => {
        if (!controller.signal.aborted) setResult(data)
      }).catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Search is unavailable.')
      }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    }, 180)
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [query])
  useEffect(() => {
    const close = (event: PointerEvent) => { if (event.target instanceof Node && !searchRef.current?.contains(event.target)) setOpen(false) }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [])

  const currentResult = result?.query === query.trim() ? result : null
  const companies = list(currentResult?.companies)
  const projects = list(currentResult?.projects)
  const contacts = list(currentResult?.contacts)
  const opportunities = list(currentResult?.opportunities)
  const select = (hit: SearchHit, group: string) => {
    const needId = hit.need_id ?? (group === 'Opportunity intelligence' ? hit.id : undefined)
    if (needId) { setOpen(false); onNeed(needId); return }
    if (hit.company_identity_id) { setOpen(false); onCompany(hit.company_identity_id, label(hit)) }
  }
  const groups: [string, SearchHit[]][] = [['Projects', projects], ['Companies', companies], ['Contacts', contacts], ['Opportunity intelligence', opportunities]]

  return <div className="global-search" ref={searchRef}>
    <label><span aria-hidden="true">Search</span><input type="search" aria-label="Search companies, projects, contacts and opportunities" placeholder="Companies, projects, contacts…" value={query} onFocus={() => setOpen(true)} onChange={event => { setQuery(event.target.value); setOpen(true) }}/></label>
    {open && query.trim().length >= 2 && <section className="global-search-results" aria-label="Search results" aria-live="polite">
      {loading && <p role="status">Searching current intelligence…</p>}{error && <p role="alert">{error}</p>}
      {!loading && !error && currentResult && !groups.some(([, items]) => items.length) && currentResult.companies_status !== 'qualification_pending' && currentResult.opportunities_status !== 'qualification_pending' && <p>No current companies, projects, contacts or opportunities match this search.</p>}
      {!loading && currentResult?.companies_status === 'qualification_pending' && <p role="status">Company matches are waiting for the current opportunity qualification snapshot.</p>}
      {!loading && currentResult?.opportunities_status === 'qualification_pending' && <p role="status">Opportunity matches are waiting for the current qualification snapshot.</p>}
      {groups.map(([group, hits]) => hits.length > 0 && <section key={group} aria-label={group}><h2>{group}</h2><ul>{hits.map((hit, index) => <li key={`${group}:${hit.need_id ?? hit.company_identity_id ?? hit.project_id ?? hit.id ?? index}`}><button type="button" onClick={() => select(hit, group)} disabled={!hit.need_id && !(group === 'Opportunity intelligence' && hit.id) && !hit.company_identity_id}><strong>{label(hit)}</strong><span>{hit.organization && hit.name ? hit.organization : ''}{hit.location ? `${hit.organization && hit.name ? ' · ' : ''}${hit.location}` : ''}{hit.region_state ? ` · ${hit.region_state}` : ''}{hit.tier ? ` · ${hit.tier}` : ''}</span>{hit.verification_status && <small>{hit.verification_status}</small>}{hit.confidence && <small>Contact confidence: {hit.confidence}</small>}{hit.project_count != null && <small>{hit.project_count} project{hit.project_count === 1 ? '' : 's'} · {hit.need_count ?? 'Unknown'} power needs</small>}{hit.required_mw && <small>Power need: {hit.required_mw}</small>}{hit.start_window && <small>Timing: {hit.start_window}</small>}{hit.rank_score != null && <small>Priority: {hit.rank_score}</small>}{hit.methods?.length ? <small>{hit.methods.map(method => `${method.kind}: ${method.value}`).join(' · ')}</small> : null}</button></li>)}</ul></section>)}
    </section>}
  </div>
}
