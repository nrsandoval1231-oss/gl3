import { useEffect, useRef, useState } from 'react'
import { client, OpportunityCohortChangedError, type OpportunityGroup, type OpportunityGroupsPage } from '../../api/client'
import { onPursuitDataEnded } from '../../state/sessionState'
import { CompanyView } from './CompanyView'
import { groupDescription } from './groupKind'
import './companies.css'

type Sector = 'all' | 'oil_gas' | 'data_centers'
const SECTORS: { value: Sector; label: string }[] = [{ value: 'all', label: 'All' }, { value: 'oil_gas', label: 'Oil & Gas' }, { value: 'data_centers', label: 'Data Centers' }]
const PAGE = 25
const readUrl = () => {
  const p = new URLSearchParams(location.search), s = p.get('cs')
  const offset = Number(p.get('co') ?? 0)
  return { search: p.get('cq') ?? '', sector: (SECTORS.some(item => item.value === s) ? s : 'all') as Sector, company: p.get('company') ?? '', offset: Number.isSafeInteger(offset) && offset >= 0 ? offset : 0 }
}
const sectorLabel = (value: string) => value === 'oil_gas' ? 'Oil & Gas' : value === 'data_centers' ? 'Data Centers' : value.replaceAll('_', ' ')
const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`

/** Browse company groups and open the associated opportunity detail. */
export function CompaniesPanel({ onNeed }: { onNeed: (needId: string) => void }) {
  const initial = readUrl()
  const [search, setSearch] = useState(initial.search)
  const [query, setQuery] = useState(initial.search)
  const [sector, setSector] = useState<Sector>(initial.sector)
  const [company, setCompany] = useState(initial.company)
  const [offset, setOffset] = useState(initial.offset)
  const [page, setPage] = useState<OpportunityGroupsPage | null>(null)
  const [projectTotal, setProjectTotal] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [retry, setRetry] = useState(0)
  const [ended, setEnded] = useState(false)
  const endedRef = useRef(false)
  const queryRef = useRef(initial.search)
  const cohort = useRef<{ key: string; token: string } | null>(null)
  const knownGroups = useRef(new Map<string, OpportunityGroup>())
  const scrollY = useRef(0)
  const listRef = useRef<HTMLDivElement>(null)
  const lastOpened = useRef('')

  useEffect(() => {
    const t = setTimeout(() => {
      const next = search.trim()
      // Only a real search change restarts paging; otherwise an early Next click would be undone.
      if (next !== queryRef.current) { queryRef.current = next; setQuery(next); setOffset(0) }
    }, 250)
    return () => clearTimeout(t)
  }, [search])
  useEffect(() => {
    // popstate covers Back/Forward; gl3-panel-route covers the header 'Companies' item, which pushes without popstate.
    const sync = () => { const next = readUrl(); queryRef.current = next.search; setSearch(next.search); setQuery(next.search); setSector(next.sector); setOffset(next.offset); setCompany(next.company); cohort.current = null }
    const onEnded = () => {
      endedRef.current = true
      knownGroups.current.clear(); cohort.current = null
      setPage(null); setProjectTotal(null); setCompany(''); setError(''); setLoading(false); setEnded(true)
    }
    addEventListener('popstate', sync); addEventListener('gl3-panel-route', sync)
    const offEnded = onPursuitDataEnded(onEnded)
    return () => { removeEventListener('popstate', sync); removeEventListener('gl3-panel-route', sync); offEnded() }
  }, [])
  // Keep the directory filters in the URL so reload and panel switches keep context.
  useEffect(() => {
    const p = new URLSearchParams(location.search)
    if (query) p.set('cq', query); else p.delete('cq')
    if (sector !== 'all') p.set('cs', sector); else p.delete('cs')
    if (offset) p.set('co', String(offset)); else p.delete('co')
    const next = `/?${p}`
    if (next !== `${location.pathname}${location.search}`) history.replaceState(history.state, '', next)
  }, [query, sector, offset])
  useEffect(() => {
    if (ended) return
    const controller = new AbortController()
    const key = JSON.stringify([query, sector])
    setLoading(true); setError('')
    void (async () => {
      let token = cohort.current?.key === key ? cohort.current.token : undefined
      if (offset > 0 && !token) { const first = await client.opportunityGroups({ search: query, sector, limit: PAGE, shortlist: false }, controller.signal); token = first.cohort_token }
      const value = await client.opportunityGroups({ search: query, sector, limit: PAGE, offset, cohort_token: offset > 0 ? token : undefined, shortlist: false }, controller.signal)
      if (controller.signal.aborted || endedRef.current) return
      cohort.current = { key, token: value.cohort_token }
      for (const item of value.items) knownGroups.current.set(item.id, item)
      setPage(value); setLoading(false)
    })().catch((cause: unknown) => {
      if (controller.signal.aborted || endedRef.current) return
      if (cause instanceof OpportunityCohortChangedError && offset > 0) { cohort.current = null; setOffset(0); return }
      setPage(null); setLoading(false); setError(cause instanceof Error ? cause.message : 'Companies are unavailable.')
    })
    return () => controller.abort()
  }, [query, sector, offset, retry, ended])
  useEffect(() => {
    // Match the directory's all-project cohort, including Signals, so this number
    // describes the same projects represented by the company groups below.
    const controller = new AbortController()
    setProjectTotal(null)
    if (query || ended) return () => controller.abort()
    client.projectResults({ sector, limit: 1, include_signals: true, shortlist: false }, controller.signal).then(value => { if (!controller.signal.aborted && !endedRef.current) setProjectTotal(value.total) }).catch(() => {})
    return () => controller.abort()
  }, [query, sector, retry, ended])
  // Restore list scroll and focus after returning from a company.
  useEffect(() => {
    if (company) { lastOpened.current = company; return }
    if (lastOpened.current) {
      const id = lastOpened.current; lastOpened.current = ''
      requestAnimationFrame(() => { window.scrollTo(0, scrollY.current); listRef.current?.querySelector<HTMLElement>(`[data-company-id="${CSS.escape(id)}"]`)?.focus({ preventScroll: true }) })
    }
  }, [company])

  function openCompany(id: string) {
    scrollY.current = window.scrollY
    const p = new URLSearchParams(location.search); p.set('company', id)
    history.pushState({ ...history.state, companyOpened: true }, '', `/?${p}`)
    setCompany(id); window.scrollTo(0, 0)
  }
  function closeCompany() {
    if (history.state?.companyOpened) { history.back(); return }
    const p = new URLSearchParams(location.search); p.delete('company')
    history.pushState({ ...history.state }, '', `/?${p}`); setCompany('')
  }
  const items = page?.items ?? []
  if (ended) return <div className="cmp"><p role="alert" className="cmp-error">Your session ended. Sign in again.</p></div>
  const subtitle = loading && !page ? 'Loading companies…' : page ? `${plural(page.total, 'operator/customer group')}${projectTotal !== null ? ` · ${plural(projectTotal, 'project')}` : ''}${query ? ' matching search' : ''}` : 'Group count unavailable'

  return <div className="cmp">
    {company && <CompanyView groupId={company} summary={knownGroups.current.get(company)} onBack={closeCompany} onNeed={onNeed} search={query} shortlist={false}/>}
    <div className="cmp-list" hidden={Boolean(company)} ref={listRef}>
      <h1>Companies</h1>
      <p className="cmp-sub" role="status">{subtitle}</p>
      {page && <p className="cmp-note">Groups include one group per unresolved project and same-name groups, so this is not a count of confirmed companies.</p>}
      <div className="cmp-tools">
        <label className="cmp-search"><span className="cmp-sr">Search companies</span><input type="search" aria-label="Search companies" placeholder="Search companies" value={search} onChange={event => setSearch(event.target.value)}/></label>
        <div className="cmp-chips" role="group" aria-label="Filter companies by vertical">{SECTORS.map(item => <button type="button" key={item.value} aria-pressed={sector === item.value} onClick={() => { setSector(item.value); setOffset(0) }}>{item.label}</button>)}</div>
      </div>
      {error && <p role="alert" className="cmp-error">{error} <button type="button" onClick={() => setRetry(value => value + 1)}>Retry</button></p>}
      {!error && <div className="cmp-table" role="table" aria-label="Companies" aria-busy={loading}>
        <div role="row" className="cmp-row cmp-head"><span role="columnheader">Company</span><span role="columnheader">Projects</span><span role="columnheader" className="cmp-sr">Open</span></div>
        {items.map(item => { const info = groupDescription(item); return <div role="row" className="cmp-row cmp-body" key={item.id} onClick={() => openCompany(item.id)}>
          <span role="cell" className="cmp-name"><button type="button" data-company-id={item.id} aria-label={`Open ${item.name}${info.kind ? ' name group' : ''}`} onClick={event => { event.stopPropagation(); openCompany(item.id) }}>{item.name}</button>{info.kind && <small className="cmp-kind">{info.kind}</small>}<small>{info.text}{item.sectors.length ? ` · ${item.sectors.map(sectorLabel).join(', ')}` : ''}</small>{info.identities && <small>{info.identities}</small>}</span>
          <span role="cell" data-label="Projects">{item.project_count.toLocaleString()}</span>
          <span role="cell" className="cmp-chevron" aria-hidden="true">›</span>
        </div> })}
      </div>}
      {!error && !loading && items.length === 0 && <p className="cmp-empty">{query ? 'No groups match this search.' : 'No operator/customer groups are available in the current results.'}</p>}
      {!error && page && <footer className="cmp-paging"><span>Showing {items.length ? page.offset + 1 : 0}–{page.offset + items.length} of {page.total}</span><button type="button" disabled={loading || page.offset === 0} onClick={() => setOffset(Math.max(0, page.offset - PAGE))}>Previous</button><button type="button" disabled={loading || page.offset + items.length >= page.total} onClick={() => setOffset(page.offset + PAGE)}>Next</button></footer>}
      <p className="cmp-note">Total MW and linked pursuits are not part of the company list, so they are not shown here. Open a company to see project power as reported and its linked pursuits.</p>
      <p className="cmp-links"><a href="/?view=workspace">Back to Opportunities</a></p>
    </div>
  </div>
}
