import { useEffect, useRef, useState } from 'react'
import { client, OpportunityCohortChangedError, OpportunityNeedUnavailableError, type OpportunityNeedScope, type WorkspaceFilters, type WorkspaceNeed, type WorkspacePage } from '../../api/client'
import { LoginPage } from '../auth/LoginPage'
import { WorkspaceDetail, workspaceTabs, type WorkspaceTab } from './WorkspaceDetail'
import { ResearchView } from '../pursuits/ResearchView'
import { OperationsInbox } from '../operations/OperationsInbox'
import { SignalsBrowse } from '../opportunities/SignalsBrowse'
import { ProjectResults } from './ProjectResults'
import { CanonicalOpportunityKpis, CanonicalOpportunityResults } from './CanonicalOpportunityResults'
import { CustomerAccountsQueue } from './CustomerAccountsQueue'
import { WorkspaceChanges } from './WorkspaceChanges'
import { OpportunityTable } from './OpportunityTable'
import { CanonicalHeader, type CanonicalHeaderDestination } from '../../components/CanonicalHeader'
import { GlobalSearch } from './GlobalSearch'
import { CanonicalOpportunityDetail } from './CanonicalOpportunityDetail'
import '../../styles/workspace.css'
import '../../styles/canonical-workspace.css'
const tabs = workspaceTabs
type Tab = WorkspaceTab
type WorkspaceDetail = import('../../api/client').Opportunity & Partial<Pick<WorkspaceNeed, 'commercial_disposition' | 'commercial_reason' | 'commercial_next_question' | 'commercial_next_action' | 'commercial_organization'>>
const getParams = () => new URLSearchParams(location.search)
function initialFilters(): WorkspaceFilters {
  const p = getParams()
  const rawTier = p.get('tier') ?? p.get('level')
  const tier = rawTier === 'Signals' ? 'Signal' : rawTier === 'Prospects' ? 'Prospect' : rawTier === 'Leads' ? 'Lead' : rawTier
  return { search: p.get('q') ?? '', tier: ['Signal', 'Prospect', 'Lead'].includes(tier || '') ? tier as WorkspaceFilters['tier'] : undefined,
    geography: p.get('geography') ?? '', industry: p.get('industry') ?? p.get('lens') ?? '', industry_group: p.get('industry_group') === 'industrial' ? 'industrial' : undefined, activity: p.get('activity') ?? '',
    timing: p.get('timing') === 'KNOWN' || p.get('timing') === 'UNKNOWN' ? p.get('timing') as 'KNOWN' | 'UNKNOWN' : undefined,
    mw_min: p.get('mw_min') ?? '', mw_max: p.get('mw_max') ?? '', disposition: p.get('disposition') ?? '',
    sort: (p.get('sort') as WorkspaceFilters['sort']) || 'priority', offset: Number(p.get('offset') || 0), cohort_token: p.get('cohort_token') || undefined }
}
function workspaceTabFromParams(params: URLSearchParams): Tab {
  const legacy: Record<string, string> = { evidence: 'evidence', buyers: 'buying-chain', power: 'power-gap', action: 'next-steps' }
  const section = params.get('section') ?? legacy[params.get('mode') ?? '']
  return tabs.find(tab => tab.toLowerCase().replaceAll(' ', '-') === section) ?? 'Overview'
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
type AccountContext = { accountId: string; projectId?: string }
function currentAccountContext(): AccountContext | undefined {
  const params = getParams(), accountId = params.get('account')
  return accountId ? { accountId, projectId: params.get('project') ?? undefined } : undefined
}
function writeUrl(filters: WorkspaceFilters, id: string | null, tab?: Tab, push = false, accountContext?: AccountContext) {
  const signalView = currentView() === 'signals'
  const p = signalView ? getParams() : workspaceParams(filters)
  if (!signalView) for (const key of ['q', 'sector', 'offset', 'cohort_token', 'accountBrowse', 'groupBrowse', 'account', 'project']) { const value = getParams().get(key); if (value) p.set(key, value) }
  if (!signalView && accountContext) { p.set('account', accountContext.accountId); if (accountContext.projectId) p.set('project', accountContext.projectId) }
  if (signalView) { p.set('view', 'signals'); p.delete('need'); p.delete('section') }
  if (id) p.set('need', id)
  if (tab && tab !== 'Overview') p.set('section', tab.toLowerCase().replaceAll(' ', '-'))
  const url = `/${p.size ? `?${p}` : ''}`
  if (push) history.pushState({ ...history.state, workspaceSnapshot: null, workspaceDetail: Boolean(id), workspaceTabSteps: 0, workspaceDirectEntry: false }, '', url); else history.replaceState(history.state, '', url)
}
export function WorkspaceHome() {
  const [view, setView] = useState(currentView)
  const [navigationPanel, setNavigationPanel] = useState<CanonicalHeaderDestination | null>(null)
  const [signalScope, setSignalScope] = useState<OpportunityNeedScope | null>(null)
  const signalScopeRef = useRef<OpportunityNeedScope | null>(null)
  function updateSignalScope(scope: OpportunityNeedScope | null) {
    signalScopeRef.current = scope
    setSignalScope(scope)
  }
  const [authenticated, setAuthenticated] = useState<boolean | null>(null)
  const [filters, setFilters] = useState<WorkspaceFilters>(() => currentView() === 'opportunities' ? initialFilters() : { sort: 'priority', offset: 0 })
  const [page, setPage] = useState<WorkspacePage | null>(null)
  const [pageIdentity, setPageIdentity] = useState<{ request: string; revision: number } | null>(null)
  const [selected, setSelected] = useState<WorkspaceDetail | null>(null)
  const [pendingNeedId, setPendingNeedId] = useState<string | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [detailIdentity, setDetailIdentity] = useState<{ id: string; revision: number } | null>(null)
  const [accountAssociationNotice, setAccountAssociationNotice] = useState('')
  const [tab, setTab] = useState<Tab>(() => workspaceTabFromParams(getParams()))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [detailNavigation, setDetailNavigation] = useState(0)
  const [signalsRevision, setSignalsRevision] = useState(0)
  const selectionSequence = useRef(0)
  const selectedNeedContext = useRef<{ needId: string | null; generation: number }>({ needId: null, generation: 0 })
  function updateSelectedNeedContext(needId: string | null) {
    if (selectedNeedContext.current.needId !== needId) {
      selectedNeedContext.current = { needId, generation: selectedNeedContext.current.generation + 1 }
    }
  }
  const historyFocusSequence = useRef(0)
  const pendingHistoryFocus = useRef<{ id: string; sequence: number; focused: boolean; origin: Element | null } | null>(null)
  const moreMenu = useRef<HTMLDetailsElement>(null)
  const signalParams = useRef<URLSearchParams | null>(currentView() === 'signals' ? getParams() : null)
  const lastSelected = useRef<string | null>(null)
  const pageRef = useRef<{ page: WorkspacePage; request: string; revision: number } | null>(null)
  const requestKey = workspaceRequestKey(filters)
  const accountBrowse = getParams().get('accountBrowse') === '1'
  const groupBrowse = getParams().get('groupBrowse') === '1'
  const pageCurrent = Boolean(page && pageIdentity?.request === requestKey && pageIdentity.revision === revision && !loading && !error)
  const detailCurrent = Boolean(selected && detailIdentity?.id === selected.id && detailIdentity.revision === revision && !detailLoading && !detailError)
  useEffect(() => {
    if (!detailCurrent || !selected) return
    const params = getParams(), expectedAccount = params.get('account')
    if (!expectedAccount) { setAccountAssociationNotice(''); return }
    const association = selected.associated_account
    if (association?.support_status === 'current' && association.company_identity_id === expectedAccount) { setAccountAssociationNotice(''); return }
    params.delete('account'); params.delete('project')
    history.replaceState(history.state, '', `/${params.size ? `?${params}` : ''}`)
    setAccountAssociationNotice(association
      ? `The saved account link was cleared. Current evidence associates this need with ${association.name}.`
      : 'The saved account link was cleared because current evidence does not support an account association for this need.')
  }, [detailCurrent, selected?.id, selected?.associated_account?.company_identity_id, selected?.associated_account?.support_status])
  let detailItem: WorkspaceDetail | null = null
  if (detailCurrent && selected) {
    detailItem = pageCurrent || !accountBrowse ? selected : { ...selected, ...commercialPreview(undefined), next_action: 'Recommendation unavailable while the current opportunity cohort is unavailable.' }
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
  useEffect(() => {
    const restore = pendingRestore.current
    if (!restore || accountBrowse || view !== 'opportunities' || selected || pendingNeedId) return
    const restoreFocus = () => {
      if (pendingRestore.current !== restore || getParams().has('need')) return
      const target = restore.focus ? document.querySelector<HTMLButtonElement>(`button[data-need-row="${CSS.escape(restore.focus)}"]`) : null
      if (restore.focus && (!target || target.disabled)) return
      const disclosure = target?.closest('details')
      if (disclosure) disclosure.open = true
      target?.focus({ preventScroll: true })
      window.scrollTo(0, restore.window)
      pendingRestore.current = null
      observer.disconnect()
    }
    const observer = new MutationObserver(restoreFocus)
    observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['disabled'] })
    const frame = requestAnimationFrame(restoreFocus)
    return () => { observer.disconnect(); cancelAnimationFrame(frame) }
  }, [accountBrowse, view, selected?.id, pendingNeedId, detailNavigation])
  useEffect(() => {
    const focusBack = () => {
      const pending = pendingHistoryFocus.current
      if (!pending || (selected?.id ?? pendingNeedId) !== pending.id || view !== 'opportunities' || !window.matchMedia('(max-width: 1050px)').matches) return
      if (getParams().get('need') !== pending.id) return
      const sequence = pending.sequence
      requestAnimationFrame(() => {
        const current = pendingHistoryFocus.current
        if (!current || current.sequence !== sequence || (selected?.id ?? pendingNeedId) !== pending.id || getParams().get('need') !== pending.id) return
        const isCurrent = detailCurrent
        if (!isCurrent && current.focused) return
        const active = document.activeElement
        if (!current.focused && active !== current.origin && active !== document.body && active instanceof HTMLElement && active.isConnected) {
          pendingHistoryFocus.current = null
          return
        }
        if (isCurrent && current.focused && active !== document.body && active instanceof HTMLElement && active.isConnected) {
          pendingHistoryFocus.current = null
          return
        }
        const back = document.querySelector<HTMLElement>('.cod-back, .wh-back')
        back?.focus({ preventScroll: true })
        if (document.activeElement === back) {
          pendingHistoryFocus.current = isCurrent ? null : { ...current, focused: true }
        }
      })
    }
    focusBack()
    window.addEventListener('resize', focusBack)
    return () => window.removeEventListener('resize', focusBack)
  }, [detailCurrent, detailNavigation, pendingNeedId, selected?.id, view])
  useEffect(() => { void client.session().then(value => setAuthenticated(value.authenticated)).catch(() => setAuthenticated(false)) }, [])
  // Account browsing remains available as an explicit secondary route. Ordinary
  // opportunities use the project projection in ProjectResults.
  useEffect(() => {
    if (!authenticated || view !== 'opportunities' || !accountBrowse) return
    const controller = new AbortController(); setLoading(true); setError('')
    client.workspace(filters, controller.signal).then(value => {
      if (controller.signal.aborted) return
      pageRef.current = { page: value, request: workspaceRequestKey(filters), revision }
      setPage(value); setPageIdentity({ request: workspaceRequestKey(filters), revision }); setLoading(false)
    }).catch((cause: Error) => { if (!controller.signal.aborted) { setLoading(false); if (cause instanceof OpportunityCohortChangedError && (filters.offset || filters.cohort_token)) { const next = { ...filters, offset: 0, cohort_token: undefined }; setFilters(next); setPageIdentity(null); setError('The opportunity list changed. Reloaded from the first page.'); const params = getParams(); params.set('offset', '0'); params.delete('cohort_token'); history.replaceState(history.state, '', `/?${params}`) } else { setError(cause.message); if (/session ended/i.test(cause.message)) setAuthenticated(false) } } })
    return () => controller.abort()
  }, [authenticated, view, accountBrowse, JSON.stringify(filters), revision])
  useEffect(() => {
    const onPop = () => {
      const p = getParams(); let id = p.get('need')
      pendingHistoryFocus.current = null
      ++selectionSequence.current; setDetailNavigation(value => value + 1)
      setView(currentView())
      try { id ||= decodeURIComponent(location.hash.slice(1) || '') } catch { setDetailError('The selected power need link is malformed.'); id = '' }
      updateSelectedNeedContext(id || null)
      const next = currentView() === 'opportunities' ? initialFilters() : filters; pendingRestore.current = null; if (currentView() === 'opportunities') setFilters(next); if (currentView() === 'signals') signalParams.current = getParams()
      setTab(workspaceTabFromParams(p))
      setDetailIdentity(null)
      if (!id) { ++selectionSequence.current; setDetailLoading(false); setSelected(null); setPendingNeedId(null); if (currentView() === 'opportunities') { const snapshot = history.state?.workspaceSnapshot ?? { ...savedScroll.current, focus: lastSelected.current }; pendingRestore.current = { ...snapshot, key: workspaceRequestKey(next) } } else requestAnimationFrame(() => { if (lastSelected.current) document.querySelector<HTMLElement>(`[data-opportunity-id="${CSS.escape(lastSelected.current)}"]`)?.focus() }); return }
      if (currentView() === 'opportunities' && window.matchMedia('(max-width: 1050px)').matches) pendingHistoryFocus.current = { id, sequence: ++historyFocusSequence.current, focused: false, origin: document.activeElement }
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
      setSelected(accountBrowse && row ? { ...value, ...commercialPreview(row) } : value)
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
  const select = (item: WorkspaceNeed | null, targetTab: Tab = 'Overview', accountContext?: AccountContext) => {
    if (!item && history.state?.workspaceDetail && !history.state?.workspaceDirectEntry) { history.go(-((history.state.workspaceTabSteps ?? 0) + 1)); return }
    updateSelectedNeedContext(item?.id ?? null)
    if (!item) { ++selectionSequence.current; setDetailLoading(false); setDetailError('') }
    if (item) { lastSelected.current = item.id; snapshotList(item.id); pendingRestore.current = null }
    if (item && selected?.id === item.id && detailCurrent) {
      setTab(targetTab); writeUrl(filters, item.id, targetTab, true, accountContext); return
    }
    const sameNeedNeedsReadback = Boolean(item && selected?.id === item.id)
    setDetailIdentity(null); setPendingNeedId(null); setSelected(item); setTab(targetTab); writeUrl(filters, item?.id ?? null, item ? targetTab : undefined, true, accountContext)
    if (sameNeedNeedsReadback) setRevision(value => value + 1)
    if (item && window.matchMedia('(max-width: 1050px)').matches) { window.scrollTo(0, 0); requestAnimationFrame(() => document.querySelector<HTMLElement>('.cod-back, .wh-back')?.focus()) }
    if (!item) requestAnimationFrame(() => { const list = document.querySelector('.wh-list'); if (list && window.matchMedia('(min-width: 1051px)').matches) list.scrollTop = savedScroll.current.list; else window.scrollTo(0, savedScroll.current.window); const focus = document.querySelector<HTMLElement>(`[data-need-row="${selected?.id ?? ''}"]`); focus?.focus() })
  }
  const navigate = (nextView: 'opportunities' | 'pursuits' | 'ingestion' | 'signals') => {
    moreMenu.current?.removeAttribute('open')
    if (nextView === 'ingestion' && view === 'ingestion') return
    if (nextView === 'opportunities' && view === 'opportunities') return
    if (nextView === 'signals' && view === 'signals') { updateSelectedNeedContext(null); ++selectionSequence.current; setSelected(null); setPendingNeedId(null); setDetailIdentity(null); setDetailLoading(false); setDetailError(''); dispatchEvent(new Event('gridlens:signals-reset')); return }
    if (nextView !== view) { updateSelectedNeedContext(null); ++selectionSequence.current; setSelected(null); setPendingNeedId(null); setDetailIdentity(null); setDetailLoading(false); setDetailError('') }
    setView(nextView)
    if (view === 'signals') signalParams.current = getParams()
    const currentBrowse = getParams()
    const savedBrowse: Record<string, string> = view === 'opportunities'
      ? Object.fromEntries(['q', 'sector', 'offset', 'cohort_token', 'groupBrowse'].flatMap(key => currentBrowse.has(key) ? [[key, currentBrowse.get(key)!]] : []))
      : (history.state?.workspaceBrowse as Record<string, string> | undefined) ?? {}
    const params = nextView === 'opportunities' ? workspaceParams(filters)
      : nextView === 'signals' ? new URLSearchParams(signalParams.current ?? { view: 'signals', tier: 'Signals' })
      : new URLSearchParams({ view: nextView })
    if (nextView === 'opportunities') for (const [key, value] of Object.entries(savedBrowse)) params.set(key, value)
    if (nextView === 'signals') { params.set('view', 'signals'); params.delete('need'); params.delete('section') }
    history.pushState({ ...history.state, workspaceBrowse: savedBrowse }, '', `/?${params}`)
  }
  const openActiveNeed = (need: { id: string }, accountContext?: AccountContext) => {
    lastSelected.current = need.id
    const row = visiblePage?.items.find(item => item.id === need.id)
    if (row) { select(row, 'Overview', accountContext); return }
    snapshotList(need.id)
    updateSelectedNeedContext(need.id)
    setDetailIdentity(null); setSelected(null); setPendingNeedId(need.id); setTab('Overview'); writeUrl(filters, need.id, undefined, true, accountContext)
    if (window.matchMedia('(max-width: 1050px)').matches) {
      window.scrollTo(0, 0)
      requestAnimationFrame(() => document.querySelector<HTMLElement>('.cod-back, .wh-back')?.focus())
    }
  }
  if (authenticated === null) return <div className="workspace-home"><div inert><CanonicalHeader onNavigate={() => {}}/></div><main className="loading" aria-live="polite" aria-busy="true">Loading your private workspace…</main></div>
  if (!authenticated) return <LoginPage onLogin={async password => { await client.login(password); updateSelectedNeedContext(null); setPage(null); setError(''); setSelected(null); setAuthenticated(true) }}/>
  const header = <CanonicalHeader
    activeDestination={navigationPanel ?? (view === 'pursuits' ? 'intelligence' : 'opportunities')}
    onNavigate={destination => {
      if (destination === 'opportunities' || destination === 'intelligence') { setNavigationPanel(null); navigate(destination === 'intelligence' ? 'pursuits' : 'opportunities') }
      else { setNavigationPanel(destination); navigate('opportunities') }
    }}
    search={<GlobalSearch onNeed={id => { setNavigationPanel(null); navigate('opportunities'); openActiveNeed({ id }) }} onCompany={id => { const params = new URLSearchParams({ view: 'workspace', accountBrowse: '1', account: id }); location.assign(`/?${params}`) }}/>}
    profile={<details ref={moreMenu} className="wh-account"><summary aria-label="Account menu"><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="7" r="3"/><path d="M4 17a6 6 0 0 1 12 0"/></svg></summary><div><span>Private workspace</span><button onClick={() => { setNavigationPanel(null); navigate('pursuits') }}>Research</button><button onClick={() => { setNavigationPanel(null); navigate('signals') }}>Signals</button><button onClick={() => { setNavigationPanel(null); navigate('ingestion') }}>Technical diagnostics</button><button className="wh-signout" onClick={() => void client.logout().then(() => location.reload())}>Sign out</button></div></details>}/>
  const researchHost = <main className="wh-single-view" hidden={view !== 'pursuits'}>{view === 'pursuits' && <ResearchView/>}</main>
  if (view === 'pursuits') return <div className="workspace-home">{header}{researchHost}</div>
  if (view === 'ingestion') return <div className="workspace-home">{header}{researchHost}<main className="wh-single-view"><OperationsInbox/></main></div>
  if (view === 'signals') return <div className="workspace-home">{header}{researchHost}<main className="wh-main"><div className="wh-layout wh-signal-layout"><SignalsBrowse refreshKey={signalsRevision} onSelect={item => openActiveNeed(item)} onScope={scope => { updateSignalScope(scope); if (!scope && !getParams().get('need') && !location.hash) { updateSelectedNeedContext(null); ++selectionSequence.current; setSelected(null); setPendingNeedId(null); setDetailIdentity(null); setDetailLoading(false) } }}/><WorkspaceDetail item={detailItem} pending={Boolean(pendingNeedId)} loading={detailLoading || Boolean(selected && !detailCurrent)} error={detailError} tab={tab} associationNotice={accountAssociationNotice} onTab={next => { setTab(next); if (selected) writeUrl(filters, selected.id, next) }} onBack={() => select(null)} onRetry={() => setRevision(value => value + 1)}/></div></main></div>
  if (accountBrowse) {
    const setLegacyFilter = (key: keyof WorkspaceFilters, value: string) => { const next = { ...filters, [key]: value || undefined, offset: 0, cohort_token: undefined }; if (key === 'industry_group') next.industry = undefined; if (key === 'industry' && value.trim()) next.industry_group = undefined; setFilters(next); setPageIdentity(null); const params = workspaceParams(next); params.set('accountBrowse', '1'); const account = getParams().get('account'); if (account) params.set('account', account); history.pushState(history.state, '', `/?${params}`) }
    const setLegacyPage = (offset: number, cohort_token: string | undefined) => { snapshotList(); const next = { ...filters, offset, cohort_token }; setFilters(next); setPageIdentity(null); const params = workspaceParams(next); params.set('accountBrowse', '1'); const account = getParams().get('account'); if (account) params.set('account', account); history.pushState(history.state, '', `/?${params}`) }
    return <div className="workspace-home">{header}{researchHost}<main className="wh-main"><div className="wh-layout wh-opportunity-layout"><section className="wh-list" aria-label={visiblePage?.count_unit === 'company accounts' ? 'Account results' : 'Secondary opportunity list'}>
      <h1>{visiblePage?.count_unit === 'company accounts' ? 'Customer accounts' : 'Opportunities'}</h1>
      <div className="wh-table-toolbar"><label className="wh-opportunity-search">Search workspace<input aria-label="Search workspace" placeholder="Company, project or location" value={filters.search ?? ''} onChange={event => setLegacyFilter('search', event.target.value)}/></label><nav className="wh-disposition-tabs" aria-label="Filter opportunities by category">{([{label:'All',value:''},{label:'Data centers',value:'data_center'},{label:'Industrial',value:'industrial'}] as const).map(({label,value}) => { const active = value === 'industrial' ? filters.industry_group === 'industrial' : value ? !filters.industry_group && filters.industry === value : !filters.industry_group && !filters.industry; return <button type="button" key={label} aria-pressed={active} onClick={() => value === 'industrial' ? setLegacyFilter('industry_group', value) : setLegacyFilter('industry', value)}>{label}</button> })}</nav></div>
      <div className="wh-queue-heading"><span>{pageCurrent ? `${visiblePage?.total ?? 0} ${visiblePage?.count_unit === 'company accounts' ? 'customer accounts' : 'opportunities'}` : loading ? 'Refreshing opportunities…' : 'Opportunity results unavailable'}</span><label className="wh-sort"><span>Sort</span><select aria-label="Sort" value={filters.sort ?? 'priority'} onChange={event => setLegacyFilter('sort', event.target.value)}><option value="priority">Priority (High → Low)</option><option value="project">Project name</option><option value="mw">Power need</option><option value="start">Start window</option><option value="updated">Recently updated</option></select></label><details className="wh-tools"><summary>Tools</summary><div className="wh-tool-content"><details className="wh-change-disclosure"><summary>Recent changes</summary><WorkspaceChanges onSelectActiveNeed={openActiveNeed}/></details><details className="wh-filter-disclosure"><summary>More filters</summary><div className="wh-filters"><select aria-label="Tier" value={filters.tier ?? ''} onChange={event => setLegacyFilter('tier', event.target.value)}><option value="">All qualifications</option><option>Signal</option><option>Prospect</option><option>Lead</option></select><select aria-label="Commercial disposition" value={filters.disposition ?? ''} onChange={event => setLegacyFilter('disposition', event.target.value)}><option value="">All dispositions</option><option>ACTION NOW</option><option>RESEARCH</option><option>WATCH</option><option>REJECT</option></select><input aria-label="Geography (exact match)" placeholder="Exact geography" value={filters.geography ?? ''} onChange={event => setLegacyFilter('geography', event.target.value)}/><input aria-label="Industry (exact match)" placeholder="Exact industry" value={filters.industry ?? ''} onChange={event => setLegacyFilter('industry', event.target.value)}/><input aria-label="Activity (exact match)" placeholder="Exact activity" value={filters.activity ?? ''} onChange={event => setLegacyFilter('activity', event.target.value)}/><select aria-label="Timing" value={filters.timing ?? ''} onChange={event => setLegacyFilter('timing', event.target.value)}><option value="">Any timing</option><option>KNOWN</option><option>UNKNOWN</option></select><input aria-label="Minimum MW" placeholder="Min MW" value={filters.mw_min ?? ''} onChange={event => setLegacyFilter('mw_min', event.target.value)}/><input aria-label="Maximum MW" placeholder="Max MW" value={filters.mw_max ?? ''} onChange={event => setLegacyFilter('mw_max', event.target.value)}/></div></details></div></details></div>
      {error && <div role="alert" className="wh-error">{error} <button onClick={() => setRevision(value => value + 1)}>Retry</button></div>}
      {loading && <p role="status">Loading current power needs…</p>}
      {pageCurrent && visiblePage?.count_unit === 'company accounts' && <CustomerAccountsQueue page={visiblePage} filters={filters} onNeed={(id, context) => openActiveNeed({ id }, context ?? currentAccountContext())} pagingAvailable onPage={setLegacyPage}/>}
      {pageCurrent && visiblePage?.count_unit === 'power needs' && <OpportunityTable items={visiblePage.items} selectedId={selected?.id} onSelect={item => select(item)} onAccount={item => { const params = getParams(); if (item.company_identity_id) params.set('account', item.company_identity_id); params.set('accountBrowse', '1'); history.pushState(history.state, '', `/?${params}`); dispatchEvent(new PopStateEvent('popstate')) }}/>}
      <footer className="wh-paging"><span>{pageCurrent ? `Showing ${visiblePage?.items.length ? (visiblePage?.offset ?? 0) + 1 : 0}–${(visiblePage?.offset ?? 0) + (visiblePage?.items.length ?? 0)} of ${visiblePage?.total ?? 0}` : 'Results unavailable'}</span><button disabled={!pageCurrent || !visiblePage?.offset} onClick={() => visiblePage && setLegacyPage(Math.max(0, visiblePage.offset - 25), visiblePage.cohort_token)}>Previous</button><button disabled={!pageCurrent || visiblePage?.next_offset == null} onClick={() => visiblePage && visiblePage.next_offset != null && setLegacyPage(visiblePage.next_offset, visiblePage.cohort_token)}>Next</button></footer>
    </section><WorkspaceDetail item={detailItem} pending={Boolean(pendingNeedId)} loading={detailLoading || Boolean(selected && !detailCurrent)} error={detailError} tab={tab} associationNotice={accountAssociationNotice} onTab={next => { setTab(next); if (selected) { const steps = history.state?.workspaceTabSteps ?? 0; const directEntry = history.state?.workspaceDirectEntry || !history.state?.workspaceDetail; writeUrl(filters, selected.id, next, true, currentAccountContext()); history.replaceState({ ...history.state, workspaceTabSteps: steps + 1, workspaceDirectEntry: directEntry }, '', location.href) } }} onBack={() => select(null)} onRetry={() => setRevision(value => value + 1)}/></div></main></div>
  }
  const ResultsView = groupBrowse ? ProjectResults : CanonicalOpportunityResults
  const DetailView = groupBrowse ? WorkspaceDetail : CanonicalOpportunityDetail
  return <div className="workspace-home">
    {header}
    {researchHost}
    {navigationPanel && <section className="canonical-navigation-panel" aria-label={navigationPanel === 'developers' ? 'Developers' : navigationPanel === 'reports' ? 'Reports' : 'Power Supply'}>
      <button aria-label="Close navigation panel" onClick={() => setNavigationPanel(null)}>Close</button>
      <h1>{navigationPanel === 'developers' ? 'Developers' : navigationPanel === 'reports' ? 'Reports' : 'Power Supply'}</h1>
      {navigationPanel === 'developers' ? <><p>Explore evidenced operator and customer relationships, projects, and published business contacts.</p><a href="/?view=workspace&accountBrowse=1">Browse customer accounts</a><span> · </span><a href="/?view=workspace&groupBrowse=1">Browse operator and customer groups</a></> : navigationPanel === 'reports' ? <><p>Export the current results with the table's Export action. Recent source-backed changes appear below.</p><WorkspaceChanges onSelectActiveNeed={need => { setNavigationPanel(null); openActiveNeed(need) }}/></> : <><p>Select a project to inspect its activity-specific requirement, available supply, and supported residual power gap.</p>{selected && <button onClick={() => { setNavigationPanel(null); setTab('Power gap') }}>View selected project power supply</button>}</>}
    </section>}
    <main className={`wh-main project-first-main ${groupBrowse ? "" : "canonical-workspace-main"}`}>
      <div className={`wh-layout wh-opportunity-layout project-first-layout ${selected || pendingNeedId ? 'project-detail-open' : ''}`}>
        {!groupBrowse && <CanonicalOpportunityKpis/>}
        <ResultsView selectedNeedId={selected?.id ?? pendingNeedId ?? undefined} onNeed={openActiveNeed} onBrowseChange={() => select(null)}/>
        {(!groupBrowse || selected || pendingNeedId) && <DetailView item={detailItem} pending={Boolean(pendingNeedId)} loading={detailLoading || Boolean(selected && !detailCurrent)} error={detailError} tab={tab} associationNotice={accountAssociationNotice} projectFirst={!accountBrowse} onTab={next => { setTab(next); if (selected) { const steps = history.state?.workspaceTabSteps ?? 0; const directEntry = history.state?.workspaceDirectEntry || !history.state?.workspaceDetail; writeUrl(filters, selected.id, next, true, currentAccountContext()); history.replaceState({ ...history.state, workspaceTabSteps: steps + 1, workspaceDirectEntry: directEntry }, '', location.href) } }} onBack={() => select(null)} onRetry={() => setRevision(value => value + 1)}/>}
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
