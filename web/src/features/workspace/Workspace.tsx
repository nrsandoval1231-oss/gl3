import { useEffect, useMemo, useRef, useState } from 'react'
import { client, OpportunityCohortChangedError, OpportunityNeedUnavailableError, type OpportunityNeedScope, type WorkspaceFilters, type WorkspaceNeed, type WorkspacePage } from '../../api/client'
import { LoginPage } from '../auth/LoginPage'
import { projectTitle } from '../opportunities/projectCards'
import { WorkspaceDetail, workspaceTabs, type WorkspaceTab } from './WorkspaceDetail'
import { WorkspaceChanges } from './WorkspaceChanges'
import { CommercialPursuits, type CommercialNavigation, defaultCommercialNavigation } from '../pursuits/CommercialPursuits'
import { OperationsInbox } from '../operations/OperationsInbox'
import { SignalsBrowse } from '../opportunities/SignalsBrowse'
import '../../styles/workspace.css'

const tabs = workspaceTabs
type Tab = WorkspaceTab
type WorkspaceDetail = import('../../api/client').Opportunity & Partial<Pick<WorkspaceNeed, 'commercial_disposition' | 'commercial_reason' | 'commercial_next_question' | 'commercial_next_action' | 'commercial_organization'>>
const getParams = () => new URLSearchParams(location.search)
function commercialFromUrl(): CommercialNavigation {
  const p = getParams(), value = p.get('disposition')
  const disposition = (['ACTION NOW', 'RESEARCH', 'WATCH', 'REJECT'] as const).find(item => item === value) ?? defaultCommercialNavigation.disposition
  const offset = Number(p.get('pursuitPage') ?? 0)
  return { ...defaultCommercialNavigation, needId: p.get('pursuitNeed'), query: p.get('pursuitQuery') ?? '', disposition, offset: Number.isInteger(offset) && offset >= 0 ? offset : 0 }
}
function writeCommercial(params: URLSearchParams, next: CommercialNavigation) {
  if (next.needId) params.set('pursuitNeed', next.needId); else params.delete('pursuitNeed')
  if (next.offset) params.set('pursuitPage', String(next.offset)); else params.delete('pursuitPage')
  if (next.query) params.set('pursuitQuery', next.query); else params.delete('pursuitQuery')
  params.set('disposition', next.disposition)
}
function initialFilters(): WorkspaceFilters {
  const p = getParams()
  const rawTier = p.get('tier') ?? p.get('level')
  const tier = rawTier === 'Signals' ? 'Signal' : rawTier === 'Prospects' ? 'Prospect' : rawTier === 'Leads' ? 'Lead' : rawTier
  return { search: p.get('q') ?? '', tier: ['Signal', 'Prospect', 'Lead'].includes(tier || '') ? tier as WorkspaceFilters['tier'] : undefined,
    geography: p.get('geography') ?? '', industry: p.get('industry') ?? p.get('lens') ?? '', activity: p.get('activity') ?? '',
    timing: p.get('timing') === 'KNOWN' || p.get('timing') === 'UNKNOWN' ? p.get('timing') as 'KNOWN' | 'UNKNOWN' : undefined,
    mw_min: p.get('mw_min') ?? '', mw_max: p.get('mw_max') ?? '', disposition: p.get('disposition') ?? '',
    sort: (p.get('sort') as WorkspaceFilters['sort']) || 'priority', offset: Number(p.get('offset') || 0), cohort_token: p.get('cohort_token') || undefined }
}
function workspaceTabFromParams(params: URLSearchParams): Tab {
  const legacy: Record<string, string> = { evidence: 'evidence', buyers: 'buying-chain', power: 'power-gap', action: 'next-steps' }
  const section = params.get('section') ?? legacy[params.get('mode') ?? '']
  return tabs.find(tab => tab.toLowerCase().replaceAll(' ', '-') === section) ?? 'Evidence'
}
function currentView(): 'opportunities' | 'pursuits' | 'ingestion' | 'signals' {
  const params = getParams(), view = params.get('view')
  if (location.pathname === '/environment' || view === 'environment') return params.get('mode') === 'pursuits' ? 'pursuits' : params.get('mode') === 'browse' ? 'signals' : 'opportunities'
  if (view === 'pursuits') return 'pursuits'
  if (view === 'ingestion') return 'ingestion'
  if (view === 'signals') return 'signals'
  if (view === 'workspace') return 'opportunities'
  return ['Signal', 'Signals', 'Prospect', 'Prospects', 'Lead', 'Leads'].includes(params.get('tier') ?? '') ? 'signals' : 'opportunities'
}
function workspaceRequestKey(filters: WorkspaceFilters) {
  const params = new URLSearchParams({ limit: '25' })
  for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== '') params.set(key, String(value))
  return params.toString()
}
function workspaceParams(filters: WorkspaceFilters) {
  const params = new URLSearchParams({ view: 'workspace' })
  for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== '') params.set(key === 'search' ? 'q' : key, String(value))
  return params
}
function writeUrl(filters: WorkspaceFilters, id: string | null, tab?: Tab, push = false) {
  const signalView = currentView() === 'signals'
  const p = signalView ? getParams() : workspaceParams(filters)
  if (signalView) { p.set('view', 'signals'); p.delete('need'); p.delete('section') }
  if (id) p.set('need', id)
  if (tab && tab !== 'Overview') p.set('section', tab.toLowerCase().replaceAll(' ', '-'))
  const url = `/${p.size ? `?${p}` : ''}`
  if (push) history.pushState({ ...history.state, workspaceSnapshot: null, workspaceDetail: Boolean(id) }, '', url); else history.replaceState(history.state, '', url)
}
export function WorkspaceHome() {
  const [view, setView] = useState(currentView)
  const [researchMounted, setResearchMounted] = useState(() => currentView() === 'pursuits')
  const [signalScope, setSignalScope] = useState<OpportunityNeedScope | null>(null)
  const signalScopeRef = useRef<OpportunityNeedScope | null>(null)
  function updateSignalScope(scope: OpportunityNeedScope | null) {
    signalScopeRef.current = scope
    setSignalScope(scope)
  }
  const [commercialNavigation, setCommercialNavigation] = useState<CommercialNavigation>(() => currentView() === 'pursuits' ? commercialFromUrl() : defaultCommercialNavigation)
  const [authenticated, setAuthenticated] = useState<boolean | null>(null)
  const [filters, setFilters] = useState<WorkspaceFilters>(() => currentView() === 'opportunities' ? initialFilters() : { sort: 'priority', offset: 0 })
  const [page, setPage] = useState<WorkspacePage | null>(null)
  const [pageIdentity, setPageIdentity] = useState<{ request: string; revision: number } | null>(null)
  const [selected, setSelected] = useState<WorkspaceDetail | null>(null)
  const [pendingNeedId, setPendingNeedId] = useState<string | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [detailIdentity, setDetailIdentity] = useState<{ id: string; revision: number } | null>(null)
  const [correctionOutcome, setCorrectionOutcome] = useState<{ needId: string; message: string } | null>(null)
  const [tab, setTab] = useState<Tab>(() => workspaceTabFromParams(getParams()))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [detailNavigation, setDetailNavigation] = useState(0)
  const [changesRevision, setChangesRevision] = useState(0)
  const [signalsRevision, setSignalsRevision] = useState(0)
  const selectionSequence = useRef(0)
  const selectedNeedContext = useRef<{ needId: string | null; generation: number }>({ needId: null, generation: 0 })
  function updateSelectedNeedContext(needId: string | null) {
    if (selectedNeedContext.current.needId !== needId) {
      selectedNeedContext.current = { needId, generation: selectedNeedContext.current.generation + 1 }
    }
  }
  const researchFocus = useRef<HTMLElement | null>(null)
  const signalParams = useRef<URLSearchParams | null>(currentView() === 'signals' ? getParams() : null)
  const lastSelected = useRef<string | null>(null)
  const listSequence = useRef(0)
  const pageRef = useRef<{ page: WorkspacePage; request: string; revision: number } | null>(null)
  const requestKey = workspaceRequestKey(filters)
  const pageCurrent = Boolean(page && pageIdentity?.request === requestKey && pageIdentity.revision === revision && !loading && !error)
  const detailCurrent = Boolean(selected && detailIdentity?.id === selected.id && detailIdentity.revision === revision && !detailLoading && !detailError)
  let detailItem: WorkspaceDetail | null = null
  if (detailCurrent && selected) {
    detailItem = pageCurrent ? selected : { ...selected, ...commercialPreview(undefined) }
  }
  const savedScroll = useRef({ list: 0, window: 0 })
  const pendingRestore = useRef<{ key: string; list: number; window: number; focus: string | null } | null>(null)
  const snapshotList = (focus = (document.activeElement as HTMLElement | null)?.closest<HTMLElement>('[data-need-row]')?.dataset.needRow ?? lastSelected.current) => {
    const list = document.querySelector('.wh-list')
    const snapshot = { list: list?.scrollTop ?? 0, window: window.scrollY, focus }
    savedScroll.current = snapshot
    history.replaceState({ ...history.state, workspaceSnapshot: snapshot }, '', location.href)
  }
  useEffect(() => {
    const restore = pendingRestore.current
    if (!restore || view !== 'opportunities' || !pageCurrent || restore.key !== requestKey) return
    pendingRestore.current = null
    const frame = requestAnimationFrame(() => {
      if (workspaceRequestKey(initialFilters()) !== restore.key || currentView() !== 'opportunities') return
      const list = document.querySelector('.wh-list')
      if (restore.focus) document.querySelector<HTMLElement>(`[data-need-row="${CSS.escape(restore.focus)}"]`)?.focus({ preventScroll: true })
      if (list && window.matchMedia('(min-width: 1051px)').matches) list.scrollTop = restore.list
      else window.scrollTo(0, restore.window)
    })
    return () => cancelAnimationFrame(frame)
  }, [pageCurrent, requestKey, view, detailNavigation])
  useEffect(() => { void client.session().then(value => setAuthenticated(value.authenticated)).catch(() => setAuthenticated(false)) }, [])
  useEffect(() => {
    if (!authenticated || view !== 'opportunities') return
    const sequence = ++listSequence.current, c = new AbortController(); setLoading(true); setError('')
    client.workspace(filters, c.signal).then((value) => {
      if (c.signal.aborted || sequence !== listSequence.current) return
      const successfulRequest = workspaceRequestKey(filters)
      pageRef.current = { page: value, request: successfulRequest, revision }
      setPage(value)
      setPageIdentity({ request: successfulRequest, revision })
      setSelected(previous => {
        const row = previous && value.items.find(item => item.id === previous.id)
        if (previous) return { ...previous, ...commercialPreview(row) }
        return previous
      })
      setLoading(false)
    }).catch((e: Error) => { if (!c.signal.aborted && sequence === listSequence.current) { setLoading(false); if (/cohort/i.test(e.message) && (filters.offset || filters.cohort_token)) { const next = { ...filters, offset: 0, cohort_token: undefined }; setFilters(next); writeUrl(next, selected?.id ?? null); setError('The opportunity list changed. Reloaded from the first page.') } else { setError(e.message); if (/session ended/i.test(e.message)) setAuthenticated(false) } } })
    return () => c.abort()
  }, [JSON.stringify(filters), revision, authenticated, view])
  useEffect(() => {
    const onPop = () => {
      const p = getParams(); let id = p.get('need')
      ++selectionSequence.current; setDetailNavigation(value => value + 1)
      setView(currentView())
      if (currentView() === 'pursuits') { setResearchMounted(true); setCommercialNavigation(commercialFromUrl()); requestAnimationFrame(() => researchFocus.current?.focus()) }
      try { id ||= decodeURIComponent(location.hash.slice(1) || '') } catch { setDetailError('The selected power need link is malformed.'); id = '' }
      updateSelectedNeedContext(id || null)
      const next = currentView() === 'opportunities' ? initialFilters() : filters; pendingRestore.current = null; if (currentView() === 'opportunities') setFilters(next); if (currentView() === 'signals') signalParams.current = getParams()
      setTab(workspaceTabFromParams(p))
      setDetailIdentity(null)
      if (!id) { ++selectionSequence.current; setDetailLoading(false); setSelected(null); setPendingNeedId(null); if (currentView() === 'opportunities') { const snapshot = history.state?.workspaceSnapshot ?? { ...savedScroll.current, focus: lastSelected.current }; pendingRestore.current = { ...snapshot, key: workspaceRequestKey(next) } } else requestAnimationFrame(() => { if (lastSelected.current) document.querySelector<HTMLElement>(`[data-opportunity-id="${CSS.escape(lastSelected.current)}"]`)?.focus() }); return }
      const row = page?.items.find(item => item.id === id)
      setSelected(row ?? null); setPendingNeedId(row ? null : id)
      // A history navigation can reselect the same Need while its selected ID
      // stays unchanged. Refresh identity so a cleared detailIdentity cannot
      // leave the detail panel loading forever.
      setRevision(value => value + 1)
    }
    addEventListener('popstate', onPop)
    let initialId = getParams().get('need'); try { initialId ||= decodeURIComponent(location.hash.slice(1) || '') } catch { setDetailError('The selected power need link is malformed.') }
    if (initialId && !selected && !pendingNeedId) { updateSelectedNeedContext(initialId); const row = page?.items.find(item => item.id === initialId); setSelected(row ?? null); setPendingNeedId(row ? null : initialId) }
    return () => removeEventListener('popstate', onPop)
  }, [page?.cohort_token])
  const activeNeedId = selected?.id ?? pendingNeedId
  useEffect(() => {
    const needId = activeNeedId
    if (!needId || !authenticated || (view === 'signals' && !signalScope)) return
    const sequence = ++selectionSequence.current, controller = new AbortController()
    setDetailLoading(true); setDetailError('')
    void client.opportunityNeed(needId, view === 'signals' ? signalScope ?? undefined : undefined, controller.signal).then(value => {
      if (controller.signal.aborted || sequence !== selectionSequence.current) return
      const currentPageRef = pageRef.current
      const row = currentPageRef?.request === workspaceRequestKey(filters) && currentPageRef.revision === revision
        ? currentPageRef.page.items?.find(item => item.id === value.id)
        : undefined
      setSelected({ ...value, ...commercialPreview(row) })
      setDetailIdentity({ id: value.id, revision })
      setPendingNeedId(null)
      setDetailLoading(false)
    }).catch((error: Error) => { if (!controller.signal.aborted && sequence === selectionSequence.current) {
      if (error instanceof OpportunityCohortChangedError && view === 'signals') {
        setDetailIdentity(null); setSelected(null); setPendingNeedId(needId); updateSignalScope(null); setSignalsRevision(value => value + 1)
        setDetailError('The Signal cohort changed. Refreshing the current results before reopening this need.')
      } else {
        if (error instanceof OpportunityNeedUnavailableError) { setSelected(null); setPendingNeedId(null); writeUrl(filters, null) }
        setDetailError(error.message)
      }
      setDetailLoading(false)
    } })
    return () => controller.abort()
  }, [activeNeedId, authenticated, revision, view, signalScope, detailNavigation])
  const visiblePage = pageCurrent ? page : null
  const items = visiblePage?.items ?? []
  const change = (key: keyof WorkspaceFilters, value: string) => { snapshotList(); pendingRestore.current = null; const next = { ...filters, [key]: value || undefined, offset: 0, cohort_token: undefined }; setFilters(next); writeUrl(next, selected?.id ?? null, undefined, true) }
  const select = (item: WorkspaceNeed | null, targetTab: Tab = 'Evidence') => {
    if (!item && history.state?.workspaceDetail) { history.back(); return }
    updateSelectedNeedContext(item?.id ?? null)
    if (!item) { ++selectionSequence.current; setDetailLoading(false); setDetailError('') }
    if (item) { lastSelected.current = item.id; snapshotList(item.id); pendingRestore.current = null }
    if (!item || (correctionOutcome && correctionOutcome.needId !== item.id)) setCorrectionOutcome(null)
    if (item && selected?.id === item.id && detailCurrent) {
      setTab(targetTab); writeUrl(filters, item.id, targetTab, true); return
    }
    const sameNeedNeedsReadback = Boolean(item && selected?.id === item.id)
    setDetailIdentity(null); setPendingNeedId(null); setSelected(item); setTab(targetTab); writeUrl(filters, item?.id ?? null, item ? targetTab : undefined, true)
    if (sameNeedNeedsReadback) setRevision(value => value + 1)
    if (item && window.matchMedia('(max-width: 1050px)').matches) { window.scrollTo(0, 0); requestAnimationFrame(() => document.querySelector<HTMLElement>('.wh-back')?.focus()) }
    if (!item) requestAnimationFrame(() => { const list = document.querySelector('.wh-list'); if (list && window.matchMedia('(min-width: 1051px)').matches) list.scrollTop = savedScroll.current.list; else window.scrollTo(0, savedScroll.current.window); const focus = document.querySelector<HTMLElement>(`[data-need-row="${selected?.id ?? ''}"]`); focus?.focus() })
  }
  const update = (next: WorkspaceFilters) => { snapshotList(); pendingRestore.current = null; setFilters(next); writeUrl(next, selected?.id ?? null, undefined, true) }
  const navigate = (nextView: 'opportunities' | 'pursuits' | 'ingestion' | 'signals') => {
    if (nextView === 'ingestion' && view === 'ingestion') return
    if (nextView === 'opportunities' && view === 'opportunities') return
    if (nextView === 'signals' && view === 'signals') { updateSelectedNeedContext(null); ++selectionSequence.current; setSelected(null); setPendingNeedId(null); setDetailIdentity(null); setDetailLoading(false); setDetailError(''); dispatchEvent(new Event('gridlens:signals-reset')); return }
    const researchNeed = nextView === 'pursuits' ? selected?.id ?? pendingNeedId ?? commercialNavigation.needId : null
    if (nextView !== view) { updateSelectedNeedContext(null); ++selectionSequence.current; setSelected(null); setPendingNeedId(null); setDetailIdentity(null); setDetailLoading(false); setDetailError('') }
    setView(nextView)
    if (view === 'signals') signalParams.current = getParams()
    const params = nextView === 'opportunities' ? workspaceParams(filters)
      : nextView === 'signals' ? new URLSearchParams(signalParams.current ?? { view: 'signals', tier: 'Signals' })
      : new URLSearchParams({ view: nextView })
    if (nextView === 'signals') { params.set('view', 'signals'); params.delete('need'); params.delete('section') }
    if (nextView === 'pursuits') {
      setResearchMounted(true)
      setCommercialNavigation(previous => ({ ...previous, needId: researchNeed }))
      writeCommercial(params, { ...commercialNavigation, needId: researchNeed })
    }
    history.pushState(null, '', `/?${params}`)
  }
  const openActiveNeed = (need: { id: string }) => {
    lastSelected.current = need.id
    const row = visiblePage?.items.find(item => item.id === need.id)
    if (row) { select(row); return }
    updateSelectedNeedContext(need.id)
    setDetailIdentity(null); setSelected(null); setPendingNeedId(need.id); setTab('Overview'); writeUrl(filters, need.id, undefined, true)
  }
  const readbackNeedId = selected?.id ?? null
  const readbackGeneration = selectedNeedContext.current.generation
  const readbackSignalScope = signalScopeRef.current
  const handleReadback = (notice?: string) => {
    if (!readbackNeedId || selected?.id !== readbackNeedId
      || selectedNeedContext.current.needId !== readbackNeedId
      || selectedNeedContext.current.generation !== readbackGeneration
      || (view === 'signals' && signalScopeRef.current !== readbackSignalScope)) return
    if (notice) setCorrectionOutcome({ needId: readbackNeedId, message: notice })
    if (view === 'signals') {
      updateSignalScope(null)
      setSignalsRevision(value => value + 1)
    }
    setDetailIdentity(null); setSelected(null); setPendingNeedId(readbackNeedId)
    setRevision(value => value + 1); setChangesRevision(value => value + 1)
  }
  const position = useMemo(() => (page?.offset ?? 0) + items.length, [page, items])
  if (authenticated === null) return <main className="loading" aria-live="polite">Loading your private workspace…</main>
  if (!authenticated) return <LoginPage onLogin={async password => { await client.login(password); updateSelectedNeedContext(null); setPage(null); setError(''); setSelected(null); setAuthenticated(true) }}/>
  const header = <header className="wh-header"><a href="/?view=workspace" aria-label="GridLens home"><img src="/brand/lockup-horizontal-white.svg" alt="GridLens"/></a><nav aria-label="Primary navigation"><button aria-current={view === 'opportunities' ? 'page' : undefined} className={view === 'opportunities' ? 'active' : ''} onClick={() => navigate('opportunities')}>Opportunities</button><button aria-current={view === 'pursuits' ? 'page' : undefined} className={view === 'pursuits' ? 'active' : ''} onClick={() => navigate('pursuits')}>Research</button><button aria-current={view === 'signals' ? 'page' : undefined} className={view === 'signals' ? 'active' : ''} onClick={() => navigate('signals')}>Signals</button><button aria-current={view === 'ingestion' ? 'page' : undefined} className={view === 'ingestion' ? 'active' : ''} onClick={() => navigate('ingestion')}>Operations</button></nav>{view === 'opportunities' && <label className="wh-header-search"><span aria-hidden="true">Search</span><input aria-label="Search workspace" placeholder="Search opportunities" value={filters.search ?? ''} onChange={e => change('search', e.target.value)}/></label>}<button className="wh-notifications" aria-label="Notifications" onClick={() => { const open = () => { const tools = document.querySelector<HTMLDetailsElement>('.wh-tools'); const changes = document.querySelector<HTMLDetailsElement>('.wh-change-disclosure'); if (tools) tools.open = true; if (changes) { changes.open = true; changes.querySelector('summary')?.focus() } }; if (view !== 'opportunities') { navigate('opportunities'); window.setTimeout(open, 100); return } open() }}><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M15 7a5 5 0 0 0-10 0c0 6-2 6-2 8h14c0-2-2-2-2-8M8 17h4"/></svg></button><details className="wh-account"><summary><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="7" r="3"/><path d="M4 17a6 6 0 0 1 12 0"/></svg><span>Account</span></summary><div><span>Private workspace</span><button className="wh-signout" onClick={() => void client.logout().then(() => location.reload())}>Sign out</button></div></details></header>
  const updateCommercial = (next: CommercialNavigation, push = true) => { if (JSON.stringify(next) === JSON.stringify(commercialNavigation)) return; setCommercialNavigation(next); const params = new URLSearchParams(getParams()); params.set('view', 'pursuits'); writeCommercial(params, next); if (push) history.pushState(history.state, '', `/?${params}`); else history.replaceState(history.state, '', `/?${params}`) }
  const researchHost = <main className="wh-single-view" hidden={view !== 'pursuits'}>{researchMounted && <><label>Search this page <input aria-label="Search commercial pursuits on this page" value={commercialNavigation.query} onChange={event => updateCommercial({ ...commercialNavigation, query: event.target.value }, false)}/></label><CommercialPursuits navigation={commercialNavigation} onNavigate={updateCommercial} onInvestigate={id => { researchFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; updateSelectedNeedContext(id); const params = workspaceParams(filters); params.set('need', id); history.pushState({ ...history.state, workspaceDetail: true }, '', `/?${params}`); setView('opportunities'); setDetailIdentity(null); setSelected(null); setPendingNeedId(id); setTab('Overview') }}/></>}</main>
  if (view === 'pursuits') return <div className="workspace-home">{header}{researchHost}</div>
  if (view === 'ingestion') return <div className="workspace-home">{header}{researchHost}<main className="wh-single-view"><OperationsInbox/></main></div>
  if (view === 'signals') return <div className="workspace-home">{header}{researchHost}<main className="wh-main"><div className="wh-layout wh-signal-layout"><SignalsBrowse refreshKey={signalsRevision} onSelect={item => openActiveNeed(item)} onScope={scope => { updateSignalScope(scope); if (!scope && !getParams().get('need') && !location.hash) { updateSelectedNeedContext(null); ++selectionSequence.current; setSelected(null); setPendingNeedId(null); setDetailIdentity(null); setDetailLoading(false) } }}/><WorkspaceDetail item={detailItem} pending={Boolean(pendingNeedId)} loading={detailLoading || Boolean(selected && !detailCurrent)} error={detailError} tab={tab} correctionNotice={correctionOutcome?.needId === (selected?.id ?? pendingNeedId) ? correctionOutcome.message : undefined} onTab={next => { setTab(next); if (selected) writeUrl(filters, selected.id, next) }} onBack={() => select(null)} onRetry={() => setRevision(value => value + 1)} onReadback={handleReadback} onTitleReady={() => setRevision(value => value + 1)}/></div></main></div>
  return <div className="workspace-home">
    {header}
    {researchHost}
    <main className="wh-main">
      <div className="wh-layout wh-opportunity-layout">
      <section className={`wh-list ${selected ? 'wh-list-muted' : ''}`} aria-label="Opportunities">
        <div className="wh-list-intro"><h1>Opportunity Intelligence</h1><p>Real signals. Real infrastructure. Real opportunity.</p></div>
        <label className="wh-list-search"><span className="wh-search-icon" aria-hidden="true"><svg viewBox="0 0 20 20"><circle cx="8.5" cy="8.5" r="5.75"/><path d="m13 13 4 4"/></svg></span><input aria-label="Search opportunities" placeholder="Search opportunities…" value={filters.search ?? ''} onChange={e => change('search', e.target.value)}/></label>
        <nav className="wh-disposition-tabs" aria-label="Filter opportunities by category">{([{ label: 'All', value: '' }, { label: 'Data centers', value: 'data_center' }, { label: 'Industrial', value: 'industrial' }] as const).map(({ label, value }) => <button type="button" key={label} aria-pressed={(filters.industry ?? '') === value} className={(filters.industry ?? '') === value ? 'selected' : ''} onClick={() => change('industry', value)}>{label}</button>)}</nav>
        <div className="wh-queue-heading"><span>{pageCurrent ? `${visiblePage?.total ?? 0} opportunities` : loading ? 'Refreshing opportunities…' : 'Opportunity results unavailable'}</span><label className="wh-sort"><span>Sort</span><select aria-label="Sort" value={filters.sort ?? 'priority'} onChange={e => change('sort', e.target.value)}><option value="priority">Priority (High → Low)</option><option value="project">Project name</option><option value="mw">Power need</option><option value="start">Start window</option><option value="updated">Recently updated</option></select></label><details className="wh-tools"><summary>Tools</summary><div className="wh-tool-content"><p className="wh-briefing-scope">Disposition filters affect visible opportunities; aggregate briefing counts ignore the selected disposition.</p>
          <details className="wh-change-disclosure"><summary>Recent changes</summary><WorkspaceChanges onSelectActiveNeed={openActiveNeed} revision={changesRevision}/></details>
          <details className="wh-filter-disclosure"><summary>More filters</summary><div className="wh-filters"><select aria-label="Tier" value={filters.tier ?? ''} onChange={e => change('tier', e.target.value)}><option value="">All qualifications</option><option>Signal</option><option>Prospect</option><option>Lead</option></select><select aria-label="Commercial disposition" value={filters.disposition ?? ''} onChange={e => change('disposition', e.target.value)}><option value="">All dispositions</option><option>ACTION NOW</option><option>RESEARCH</option><option>WATCH</option><option>REJECT</option></select><input aria-label="Geography (exact match)" title="Exact stored geography, for example Austin, TX" placeholder="Exact geography" value={filters.geography ?? ''} onChange={e => change('geography', e.target.value)}/><input aria-label="Industry (exact match)" title="Exact stored industry value" placeholder="Exact industry" value={filters.industry ?? ''} onChange={e => change('industry', e.target.value)}/><input aria-label="Activity (exact match)" title="Exact stored activity value" placeholder="Exact activity" value={filters.activity ?? ''} onChange={e => change('activity', e.target.value)}/><select aria-label="Timing" value={filters.timing ?? ''} onChange={e => change('timing', e.target.value)}><option value="">Any timing</option><option>KNOWN</option><option>UNKNOWN</option></select><input aria-label="Minimum MW" placeholder="Min MW" value={filters.mw_min ?? ''} onChange={e => change('mw_min', e.target.value)}/><input aria-label="Maximum MW" placeholder="Max MW" value={filters.mw_max ?? ''} onChange={e => change('mw_max', e.target.value)}/><select aria-label="Sort" value={filters.sort ?? 'priority'} onChange={e => change('sort', e.target.value)}><option value="priority">Priority</option><option value="project">Project</option><option value="mw">MW</option><option value="start">Start (source text)</option><option value="updated">Updated</option></select></div></details>
          <details className="wh-export"><summary>Download CSV by qualification</summary><div>{(['Signal','Prospect','Lead'] as const).map(tier => <a key={tier} href={client.opportunityExportUrl(tier, filters.search ?? '', 'ALL', undefined, { geography: filters.geography ?? '', industry: filters.industry ?? '', activity: filters.activity ?? '', timing: filters.timing ?? '', mwMin: filters.mw_min ?? '', mwMax: filters.mw_max ?? '' })} download>{tier} CSV</a>)}</div></details>
        </div></details></div>
        {error && <div role="alert" className="wh-error">{error} <button onClick={() => setRevision(x => x + 1)}>Retry</button></div>}
        {loading && <p role="status">Loading current power needs…</p>}
        {!loading && !error && items.length === 0 && <p className="wh-empty">No power needs match these filters.</p>}
        <div className="wh-queue-list">{items.map(item => { const title = projectTitle(item); const identity = item.commercial_organization || title; const monogram = identity.split(/\s+/).filter(Boolean).slice(0, 2).map(word => word[0]).join('').toUpperCase(); return <article className={`wh-queue-item ${selected?.id === item.id ? 'selected' : ''}`} key={item.id}><button aria-current={selected?.id === item.id ? 'true' : undefined} className="wh-queue-main" data-need-row={item.id} onClick={() => select(item)}><span className="wh-queue-monogram" aria-hidden="true">{monogram}</span><span className="wh-queue-copy"><strong>{title}</strong><span className="wh-queue-meta"><span>{item.location ?? 'Location unknown'}</span><b>{item.tier}</b><span className="wh-queue-disposition">{item.commercial_disposition ?? 'Disposition unavailable'}</span></span></span></button></article> })}</div>
        <footer className="wh-paging"><span>Showing {items.length ? (visiblePage?.offset ?? 0) + 1 : 0}–{pageCurrent ? position : '—'} of {pageCurrent ? visiblePage?.total ?? '—' : '—'}</span><button disabled={!pageCurrent || !visiblePage?.offset} onClick={() => { if (visiblePage) update({ ...filters, offset: Math.max(0, visiblePage.offset - 25), cohort_token: visiblePage.cohort_token }) }}>Previous</button><button disabled={!pageCurrent || visiblePage?.next_offset == null} onClick={() => { if (visiblePage) update({ ...filters, offset: visiblePage.next_offset ?? 0, cohort_token: visiblePage.cohort_token }) }}>Next</button></footer>
      </section>
      <WorkspaceDetail item={detailItem} pending={Boolean(pendingNeedId)} loading={detailLoading || Boolean(selected && !detailCurrent)} error={detailError} tab={tab} correctionNotice={correctionOutcome?.needId === (selected?.id ?? pendingNeedId) ? correctionOutcome.message : undefined} onTab={next => { setTab(next); if (selected) writeUrl(filters, selected.id, next) }} onBack={() => select(null)} onRetry={() => setRevision(value => value + 1)} onReadback={handleReadback} onTitleReady={() => setRevision(value => value + 1)}/>
      </div>
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
