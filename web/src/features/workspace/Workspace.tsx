import { useEffect, useMemo, useRef, useState } from 'react'
import { client, type WorkspaceFilters, type WorkspaceNeed, type WorkspacePage } from '../../api/client'
import { LoginPage } from '../auth/LoginPage'
import { projectTitle } from '../opportunities/projectCards'
import { WorkspaceDetail, workspaceTabs, type WorkspaceTab } from './WorkspaceDetail'
import { WorkspaceChanges } from './WorkspaceChanges'
import '../../styles/workspace.css'

const tabs = workspaceTabs
type Tab = WorkspaceTab
type WorkspaceDetail = import('../../api/client').Opportunity & Partial<Pick<WorkspaceNeed, 'commercial_disposition' | 'commercial_reason' | 'commercial_next_question' | 'commercial_next_action' | 'commercial_organization'>>
const getParams = () => new URLSearchParams(location.search)
function legacyUrl(view: string) { const p = getParams(); p.set('view', view); const need = p.get('need'); p.delete('need'); if (view === 'pursuits' && need) p.set('pursuitNeed', need); p.delete('section'); p.delete('offset'); return `/?${p}` }
function initialFilters(): WorkspaceFilters {
  const p = getParams()
  const tier = p.get('tier')
  return { search: p.get('q') ?? '', tier: ['Signal', 'Prospect', 'Lead'].includes(tier || '') ? tier as WorkspaceFilters['tier'] : undefined,
    geography: p.get('geography') ?? '', industry: p.get('industry') ?? '', activity: p.get('activity') ?? '',
    timing: p.get('timing') === 'KNOWN' || p.get('timing') === 'UNKNOWN' ? p.get('timing') as 'KNOWN' | 'UNKNOWN' : undefined,
    mw_min: p.get('mw_min') ?? '', mw_max: p.get('mw_max') ?? '', disposition: p.get('disposition') ?? '',
    sort: (p.get('sort') as WorkspaceFilters['sort']) || 'priority', offset: Number(p.get('offset') || 0), cohort_token: p.get('cohort_token') || undefined }
}
function workspaceRequestKey(filters: WorkspaceFilters) {
  const params = new URLSearchParams({ limit: '25' })
  for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== '') params.set(key, String(value))
  return params.toString()
}
function writeUrl(filters: WorkspaceFilters, id: string | null, tab?: Tab, push = false) {
  const p = new URLSearchParams({ view: 'workspace' })
  for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== '') p.set(key === 'search' ? 'q' : key, String(value))
  if (id) p.set('need', id)
  if (tab && tab !== 'Overview') p.set('section', tab.toLowerCase().replaceAll(' ', '-'))
  const url = `${location.pathname}${p.size ? `?${p}` : ''}`
  if (push) history.pushState(null, '', url); else history.replaceState(null, '', url)
}
export function WorkspaceHome() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null)
  const [filters, setFilters] = useState<WorkspaceFilters>(initialFilters)
  const [page, setPage] = useState<WorkspacePage | null>(null)
  const [pageIdentity, setPageIdentity] = useState<{ request: string; revision: number } | null>(null)
  const [selected, setSelected] = useState<WorkspaceDetail | null>(null)
  const [pendingNeedId, setPendingNeedId] = useState<string | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [detailIdentity, setDetailIdentity] = useState<{ id: string; revision: number } | null>(null)
  const [tab, setTab] = useState<Tab>(() => tabs.find(t => t.toLowerCase().replaceAll(' ', '-') === getParams().get('section')) ?? 'Overview')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const selectionSequence = useRef(0)
  const listSequence = useRef(0)
  const pageRef = useRef<{ page: WorkspacePage; request: string; revision: number } | null>(null)
  const requestKey = workspaceRequestKey(filters)
  const pageCurrent = Boolean(page && pageIdentity?.request === requestKey && pageIdentity.revision === revision && !loading && !error)
  const detailCurrent = Boolean(selected && detailIdentity?.id === selected.id && detailIdentity.revision === revision && !detailLoading && !detailError)
  const savedScroll = useRef({ list: 0, window: 0 })
  useEffect(() => { void client.session().then(value => setAuthenticated(value.authenticated)).catch(() => setAuthenticated(false)) }, [])
  useEffect(() => {
    if (!authenticated) return
    const sequence = ++listSequence.current, c = new AbortController(); setLoading(true); setError('')
    client.workspace(filters, c.signal).then((value) => {
      if (c.signal.aborted || sequence !== listSequence.current) return
      const successfulRequest = workspaceRequestKey(filters)
      pageRef.current = { page: value, request: successfulRequest, revision }
      setPage(value)
      setPageIdentity({ request: successfulRequest, revision })
      setSelected(previous => {
        const row = previous && value.items.find(item => item.id === previous.id)
        return previous ? { ...previous, ...commercialPreview(row) } : previous
      })
      setLoading(false)
    }).catch((e: Error) => { if (!c.signal.aborted && sequence === listSequence.current) { setLoading(false); if (/cohort/i.test(e.message) && (filters.offset || filters.cohort_token)) { const next = { ...filters, offset: 0, cohort_token: undefined }; setFilters(next); writeUrl(next, selected?.id ?? null); setError('The opportunity list changed. Reloaded from the first page.') } else { setError(e.message); if (/session ended/i.test(e.message)) setAuthenticated(false) } } })
    return () => c.abort()
  }, [JSON.stringify(filters), revision, authenticated])
  useEffect(() => {
    const onPop = () => {
      const p = getParams(); let id = p.get('need')
      try { id ||= decodeURIComponent(location.hash.slice(1) || '') } catch { setDetailError('The selected power need link is malformed.'); id = '' }
      const next = initialFilters(); setFilters(next)
      setTab(tabs.find(t => t.toLowerCase().replaceAll(' ', '-') === p.get('section')) ?? 'Overview')
      setDetailIdentity(null)
      if (!id) { setSelected(null); setPendingNeedId(null); requestAnimationFrame(() => { const list = document.querySelector('.wh-list'); if (list && window.matchMedia('(min-width: 761px)').matches) list.scrollTop = savedScroll.current.list; else window.scrollTo(0, savedScroll.current.window) }); return }
      const row = page?.items.find(item => item.id === id)
      setSelected(row ?? null); setPendingNeedId(row ? null : id)
    }
    addEventListener('popstate', onPop)
    let initialId = getParams().get('need'); try { initialId ||= decodeURIComponent(location.hash.slice(1) || '') } catch { setDetailError('The selected power need link is malformed.') }
    if (initialId && !selected && !pendingNeedId) { const row = page?.items.find(item => item.id === initialId); setSelected(row ?? null); setPendingNeedId(row ? null : initialId) }
    return () => removeEventListener('popstate', onPop)
  }, [page?.cohort_token])
  useEffect(() => {
    const needId = selected?.id ?? pendingNeedId
    if (!needId || !authenticated) return
    const sequence = ++selectionSequence.current, controller = new AbortController()
    setDetailLoading(true); setDetailError('')
    void client.opportunityNeed(needId, undefined, controller.signal).then(value => {
      if (sequence !== selectionSequence.current) return
      const currentPageRef = pageRef.current
      const row = currentPageRef?.request === workspaceRequestKey(filters) && currentPageRef.revision === revision
        ? currentPageRef.page.items.find(item => item.id === value.id)
        : undefined
      setSelected({ ...value, ...commercialPreview(row) })
      setDetailIdentity({ id: value.id, revision })
      setPendingNeedId(null)
      setDetailLoading(false)
    }).catch((error: Error) => { if (!controller.signal.aborted && sequence === selectionSequence.current) { setDetailError(error.message); setDetailLoading(false) } })
    return () => controller.abort()
  }, [selected?.id, pendingNeedId, authenticated, revision])
  const visiblePage = pageCurrent ? page : null
  const items = visiblePage?.items ?? []
  const change = (key: keyof WorkspaceFilters, value: string) => { const next = { ...filters, [key]: value || undefined, offset: 0, cohort_token: undefined }; setFilters(next); writeUrl(next, selected?.id ?? null) }
  const select = (item: WorkspaceNeed | null, targetTab: Tab = 'Overview') => {
    if (item) { const list = document.querySelector('.wh-list'); savedScroll.current = { list: list?.scrollTop ?? 0, window: window.scrollY } }
    if (item && selected?.id === item.id && detailCurrent) {
      setTab(targetTab); writeUrl(filters, item.id, targetTab, true); return
    }
    const sameNeedNeedsReadback = Boolean(item && selected?.id === item.id)
    setDetailIdentity(null); setPendingNeedId(null); setSelected(item); setTab(targetTab); writeUrl(filters, item?.id ?? null, item ? targetTab : undefined, true)
    if (sameNeedNeedsReadback) setRevision(value => value + 1)
    if (item && window.matchMedia('(max-width: 760px)').matches) { window.scrollTo(0, 0); requestAnimationFrame(() => document.querySelector<HTMLElement>('.wh-back')?.focus()) }
    if (!item) requestAnimationFrame(() => { const list = document.querySelector('.wh-list'); if (list && window.matchMedia('(min-width: 761px)').matches) list.scrollTop = savedScroll.current.list; else window.scrollTo(0, savedScroll.current.window); const focus = document.querySelector<HTMLElement>(`[data-need-row="${selected?.id ?? ''}"]`); focus?.focus() })
  }
  const update = (next: WorkspaceFilters) => { setFilters(next); writeUrl(next, selected?.id ?? null) }
  const openActiveNeed = (need: { id: string }) => {
    const row = visiblePage?.items.find(item => item.id === need.id)
    if (row) { select(row); return }
    setDetailIdentity(null); setSelected(null); setPendingNeedId(need.id); setTab('Overview'); writeUrl(filters, need.id, undefined, true)
  }
  const position = useMemo(() => (page?.offset ?? 0) + items.length, [page, items])
  if (authenticated === null) return <main className="loading" aria-live="polite">Loading your private workspace…</main>
  if (!authenticated) return <LoginPage onLogin={async password => { await client.login(password); setPage(null); setError(''); setSelected(null); setAuthenticated(true) }}/>
  return <div className="workspace-home">
    <header className="wh-header"><a href="/?view=workspace" aria-label="GridLens home"><img src="/brand/lockup-horizontal-navy.svg" alt="GridLens"/></a><nav aria-label="Primary navigation"><a className="active" href="/?view=workspace">Opportunities</a><a href={legacyUrl('pursuits')}>Research</a><a href="/?view=workspace&amp;tier=Signal">Signals</a><a href={legacyUrl('ingestion')}>Operations</a></nav><label className="wh-global-search"><span>Search</span><input aria-label="Search opportunities" value={filters.search ?? ''} onChange={e => change('search', e.target.value)}/></label><button className="wh-signout" onClick={() => void client.logout().then(() => location.reload())}>Sign out</button></header>
    <section className="wh-briefbar"><h1>Power needs</h1><span>{pageCurrent ? `${visiblePage?.total ?? 0} filtered power needs` : 'Current results unavailable'}</span><small>Disposition counts ignore this filter · review counts appear in Material changes.</small>{(['action_now','research','watch','reject'] as const).map(v => <button key={v} className={filters.disposition === v.toUpperCase().replace('_',' ') ? 'chosen' : ''} onClick={() => change('disposition', filters.disposition === v.toUpperCase().replace('_',' ') ? '' : v.toUpperCase().replace('_',' '))}><strong>{pageCurrent ? visiblePage?.counts[v] ?? '—' : '—'}</strong> {v.replace('_',' ')}</button>)}</section>
    <WorkspaceChanges onSelectActiveNeed={openActiveNeed}/>
    <main className="wh-layout">
      <section className={`wh-list ${selected ? 'wh-list-muted' : ''}`} aria-label="Opportunities">
        <div className="wh-filters"><select aria-label="Tier" value={filters.tier ?? ''} onChange={e => change('tier', e.target.value)}><option value="">All tiers</option><option>Signal</option><option>Prospect</option><option>Lead</option></select><input aria-label="Geography (exact match)" title="Exact stored geography, for example Austin, TX" placeholder="Exact geography" value={filters.geography ?? ''} onChange={e => change('geography', e.target.value)}/><input aria-label="Industry (exact match)" title="Exact stored industry value" placeholder="Exact industry" value={filters.industry ?? ''} onChange={e => change('industry', e.target.value)}/><input aria-label="Activity (exact match)" title="Exact stored activity value" placeholder="Exact activity" value={filters.activity ?? ''} onChange={e => change('activity', e.target.value)}/><select aria-label="Timing" value={filters.timing ?? ''} onChange={e => change('timing', e.target.value)}><option value="">Timing</option><option>KNOWN</option><option>UNKNOWN</option></select><input aria-label="Minimum MW" placeholder="Min MW" value={filters.mw_min ?? ''} onChange={e => change('mw_min', e.target.value)}/><input aria-label="Maximum MW" placeholder="Max MW" value={filters.mw_max ?? ''} onChange={e => change('mw_max', e.target.value)}/><select aria-label="Sort" value={filters.sort ?? 'priority'} onChange={e => change('sort', e.target.value)}><option value="priority">Priority</option><option value="project">Project</option><option value="mw">MW</option><option value="start">Start (source text)</option><option value="updated">Updated</option></select></div>
        {error && <div role="alert" className="wh-error">{error} <button onClick={() => setRevision(x => x + 1)}>Retry</button></div>}
        {loading && <p role="status">Loading current power needs…</p>}
        {!loading && !error && items.length === 0 && <p className="wh-empty">No power needs match these filters.</p>}
        <div className="wh-table-wrap"><table className="wh-table"><thead><tr><th>Project / location</th><th>MW</th><th>Application</th><th>Start · duration</th><th>Disposition</th><th>Next action</th></tr></thead><tbody>{items.map(item => { const title = projectTitle(item); return <tr key={item.id} className={selected?.id === item.id ? 'selected' : ''}><td data-label="Project / location"><button className="wh-project" data-need-row={item.id} onClick={() => select(item)}><strong>{title}</strong>{title !== item.name && <small>Source record: {item.name}</small>}<span>{item.location ?? 'Location unknown'} · {item.tier}</span>{item.rank_score != null && <small>Priority {item.rank_score}{item.rank_reasons?.length ? ` · ${item.rank_reasons.join('; ')}` : ''}</small>}</button></td><td data-label="MW">{item.required_mw ?? 'Unknown'}</td><td data-label="Application">{item.activity.replaceAll('-', ' ')}</td><td data-label="Start · duration">{item.start_window ?? 'Unknown'} · {item.duration ?? 'Unknown'}</td><td data-label="Disposition">{item.commercial_disposition}</td><td data-label="Next action"><button className="wh-action" title={item.commercial_next_action || item.commercial_next_question || 'Review evidence'} onClick={() => select(item, 'Next steps')}>{item.commercial_next_action || item.commercial_next_question || 'Review evidence'}</button></td></tr> })}</tbody></table></div>
        <footer className="wh-paging"><span>Showing {items.length ? (visiblePage?.offset ?? 0) + 1 : 0}–{pageCurrent ? position : '—'} of {pageCurrent ? visiblePage?.total ?? '—' : '—'}</span><button disabled={!pageCurrent || !visiblePage?.offset} onClick={() => { if (visiblePage) update({ ...filters, offset: Math.max(0, visiblePage.offset - 25), cohort_token: visiblePage.cohort_token }) }}>Previous</button><button disabled={!pageCurrent || visiblePage?.next_offset == null} onClick={() => { if (visiblePage) update({ ...filters, offset: visiblePage.next_offset ?? 0, cohort_token: visiblePage.cohort_token }) }}>Next</button></footer>
      </section>
      <WorkspaceDetail item={detailCurrent ? selected : null} pending={Boolean(pendingNeedId)} loading={detailLoading || Boolean(selected && !detailCurrent)} error={detailError} tab={tab} onTab={next => { setTab(next); if (selected) writeUrl(filters, selected.id, next) }} onBack={() => select(null)} onRetry={() => setRevision(value => value + 1)} onReadback={() => { setDetailIdentity(null); setSelected(null); setPendingNeedId(selected?.id ?? null); setRevision(value => value + 1) }} onTitleReady={() => setRevision(value => value + 1)}/>
    </main>
  </div>
}

function commercialPreview(row: WorkspaceNeed | null | undefined) {
  return {
    commercial_disposition: row?.commercial_disposition,
    commercial_reason: row?.commercial_reason,
    commercial_next_question: row?.commercial_next_question,
    commercial_next_action: row?.commercial_next_action,
    commercial_organization: row?.commercial_organization,
  }
}
