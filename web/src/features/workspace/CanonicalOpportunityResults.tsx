import { Zap, Download } from 'lucide-react'
import { downloadProjectPage } from './opportunityExport'
import { useEffect, useMemo, useRef, useState } from 'react'
import { client, OpportunityBrowsePendingError, OpportunityCohortChangedError, type DemandSummary, type ProjectResult, type ProjectResultsPage, type ProjectResultsSort } from '../../api/client'
import './canonical-opportunity-results.css'
import { AddToPursuit } from '../pursuits/AddToPursuit'

type Props = { selectedNeedId?: string; onNeed: (need: { id: string }) => void; onBrowseChange?: () => void }
type Sector = 'all' | 'oil_gas' | 'data_centers'
type Sort = Exclude<ProjectResultsSort, 'updated'>
type CacheEntry = { page: ProjectResultsPage; savedAt: number }
const cache = new Map<string, CacheEntry>()
const CACHE_TTL = 60_000
let cacheGeneration = 0
if (typeof window !== 'undefined') window.addEventListener('gl3-clear-continuity', () => { cacheGeneration += 1; cache.clear() })
const EMPTY_PROJECTS: ProjectResult[] = []
const cacheKey = (search: string, sector: Sector, offset: number, sort: Sort, shortlist: boolean) => JSON.stringify([search, sector, offset, sort, shortlist])
/** Reject malformed or expired cached result pages before presenting them. */
function pageIsCurrent(page: ProjectResultsPage | null) {
  if (!page || !Array.isArray(page.items) || !Number.isSafeInteger(page.total) || page.total < 0 || !Number.isSafeInteger(page.limit) || page.limit <= 0 || !Number.isSafeInteger(page.offset) || page.offset < 0 || typeof page.cohort_token !== 'string') return false
  if (page.items.some(item => !item || typeof item.id !== 'string' || typeof item.name !== 'string' || !Array.isArray(item.needs))) return false
  if (page.qualification_state && page.qualification_state !== 'current') return false
  if (page.refresh_state && page.refresh_state !== 'current') return false
  if (!page.valid_until) return true
  const expires = Date.parse(page.valid_until)
  return Number.isFinite(expires) && Date.now() < expires
}
/** Reads the supported workspace view and filter state from the current URL. */
function readRoute() {
  const params = new URLSearchParams(location.search)
  const priority = params.get('priority')
  const shortlist = params.get('shortlist') !== '0'
  return { region: params.get('region') ?? '', stage: params.get('stage') ?? '', priority: !shortlist && (priority === 'ranked' || priority === 'unranked') ? priority : '', search: params.get('q') ?? '', sector: (['oil_gas', 'data_centers'].includes(params.get('sector') ?? '') ? params.get('sector') : 'all') as Sector, offset: Math.max(0, Number(params.get('offset') ?? 0) || 0), sort: (['priority_asc', 'company', 'project'].includes(params.get('sort') ?? '') ? params.get('sort') : 'priority') as Sort, shortlist }
}
type PageFilters = { region: string; stage: string; priority: string }
const NO_FILTERS: PageFilters = { region: '', stage: '', priority: '' }
/** Writes the current project cohort and visible page filters to the URL. */
/** Persist browse filters and page state in the shareable workspace URL. */
function updateUrl(search: string, sector: Sector, offset: number, sort: Sort, shortlist: boolean, cohort?: string, push = false, filters: PageFilters = NO_FILTERS) {
  const params = new URLSearchParams({ view: 'workspace' })
  if (new URLSearchParams(location.search).get('projectBrowse') === '1') params.set('projectBrowse', '1')
  params.set('shortlist', shortlist ? '1' : '0')
  if (search) params.set('q', search)
  if (sector !== 'all') params.set('sector', sector)
  if (offset) params.set('offset', String(offset))
  if (sort !== 'priority') params.set('sort', sort)
  if (filters.region) params.set('region', filters.region)
  if (filters.stage) params.set('stage', filters.stage)
  if (filters.priority) params.set('priority', filters.priority)
  if (cohort) params.set('cohort_token', cohort)
  if (push) history.pushState(history.state, '', `/?${params}`)
  else history.replaceState(history.state, '', `/?${params}`)
}
// Page-local filters change in place so an open selection (`need`, `section`) is kept.
/** Update one optional project filter while preserving the current route. */
function setFilterParam(key: keyof PageFilters, value: string) {
  const params = new URLSearchParams(location.search)
  if (value) params.set(key, value); else params.delete(key)
  history.replaceState(history.state, '', `/?${params}`)
}
/** Choose the best available source-backed name for display. */
function displayProjectName(project: ProjectResult) {
  return project.company && project.name.startsWith(`${project.company} · `) ? project.name.slice(project.company.length + 3) : project.name
}
/** Chooses a human-readable project subject while avoiding unsupported identities. */
/** Build the compact name shown on an opportunity card. */
function cardProjectName(project: ProjectResult) {
  const subject = project.shortlist_assessment?.source_subject?.trim()
  if (subject && !/^\d+$/.test(subject) && !/\b(?:contractor|applicant)\b/i.test(subject)) return subject
  const name = displayProjectName(project).trim()
  return name && !/\b(?:contractor|applicant)\b/i.test(name) ? name : 'Project name not established'
}
/** Format a project total without changing its underlying count. */
function projectCount(value: number) {
  return `${value} project${value === 1 ? '' : 's'}`
}
/** Render a normalized lifecycle stage as readable UI text. */
function stageLabel(value: string) {
  const known: Record<string, string> = {
    permit_issued: 'Permit issued', building_permit_issued: 'Building permit issued', electrical_permit_issued: 'Electrical permit issued',
    construction_started: 'Construction started', site_selected: 'Site selected', planning: 'Planning', reclassified: 'Reclassified', reopened: 'Reopened',
  }
  return known[value] ?? value.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase())
}
/** Renders the current project cohort with source-backed filters and non-qualifying priority rank. */
export function CanonicalOpportunityResults({ selectedNeedId, onNeed, onBrowseChange }: Props) {
  const initial = useRef(readRoute()).current
  const [shortlist, setShortlist] = useState(initial.shortlist)
  const [searchDraft, setSearchDraft] = useState(initial.search)
  const [search, setSearch] = useState(initial.search)
  const [sector, setSector] = useState<Sector>(initial.sector)
  const [offset, setOffset] = useState(initial.offset)
  const [sort, setSort] = useState<Sort>(initial.sort)
  const [page, setPage] = useState<ProjectResultsPage | null>(() => {
    const entry = cache.get(cacheKey(initial.search, initial.sector, initial.offset, initial.sort, initial.shortlist))
    return entry && Date.now() - entry.savedAt < CACHE_TTL && pageIsCurrent(entry.page) ? entry.page : null
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [region, setRegion] = useState(initial.region)
  const [stage, setStage] = useState(initial.stage)
  const [priority, setPriority] = useState(initial.priority)
  const filtersRef = useRef<PageFilters>({ region: initial.region, stage: initial.stage, priority: initial.priority })
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onBrowseChangeRef = useRef(onBrowseChange)
  onBrowseChangeRef.current = onBrowseChange
  const requestGeneration = useRef(0)
  const requestAbort = useRef<AbortController | null>(null)
  const [pageKey, setPageKey] = useState(() => cacheKey(initial.search, initial.sector, initial.offset, initial.sort, initial.shortlist))
  const cohortResetUsed = useRef(false)
  const [retryKey, setRetryKey] = useState(0)
  const [pageErrorNotice, setPageErrorNotice] = useState('')

  useEffect(() => {
    // Unsupported sort values (for example the legacy `updated`) fall back to priority; drop them from the URL.
    const params = new URLSearchParams(location.search), raw = params.get('sort')
    if ((raw !== null && readRoute().sort === 'priority') || (params.has('priority') && readRoute().shortlist)) { if (readRoute().sort === 'priority') params.delete('sort'); if (readRoute().shortlist) params.delete('priority'); history.replaceState(history.state, '', `/?${params}`) }
  }, [])
  useEffect(() => {
    const onPop = () => { const route = readRoute(); setSearchDraft(route.search); setSearch(route.search); setSector(route.sector); setOffset(route.offset); setSort(route.sort); setShortlist(route.shortlist); setRegion(route.region); setStage(route.stage); setPriority(route.priority); cohortResetUsed.current = false }
    const onClear = () => { requestGeneration.current += 1; requestAbort.current?.abort(); if (retryTimer.current) clearTimeout(retryTimer.current); cacheGeneration += 1; cache.clear(); setPage(null); setError('Your session ended. Sign in again.'); setLoading(false) }
    window.addEventListener('popstate', onPop)
    window.addEventListener('gl3-clear-continuity', onClear)
    return () => { window.removeEventListener('popstate', onPop); window.removeEventListener('gl3-clear-continuity', onClear) }
  }, [])
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchDraft !== search) {
        setSearch(searchDraft); setOffset(0); setRegion(''); setStage(''); setPriority(''); onBrowseChangeRef.current?.(); updateUrl(searchDraft, sector, 0, sort, shortlist)
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [searchDraft, search, sector, sort, shortlist])
  useEffect(() => {
    const key = cacheKey(search, sector, offset, sort, shortlist)
    const cached = cache.get(key)
    if (cached && Date.now() - cached.savedAt < CACHE_TTL && pageIsCurrent(cached.page)) setPage(cached.page)
    else setPage(null)
    const controller = new AbortController()
    requestAbort.current?.abort(); requestAbort.current = controller
    const generation = ++requestGeneration.current
    const cacheGenerationAtStart = cacheGeneration
    setPageKey(key)
    setLoading(true); setError(''); setPageErrorNotice('')
    let active = true
    let retries = 0
    const load = async () => {
      try {
        const value = await client.projectResults({ search, sector, limit: 25, offset, cohort_token: new URLSearchParams(location.search).get('cohort_token') ?? undefined, sort, include_signals: true, shortlist }, controller.signal)
        if (!active || controller.signal.aborted || generation !== requestGeneration.current || cacheGenerationAtStart !== cacheGeneration) return
        if (!pageIsCurrent(value)) throw new Error('Current project results could not be confirmed. Refresh to retry.')
        cache.delete(key); cache.set(key, { page: value, savedAt: Date.now() }); while (cache.size > 5) cache.delete(cache.keys().next().value!)
        setPage(value); setLoading(false)
      } catch (cause) {
        if (!active || controller.signal.aborted || generation !== requestGeneration.current || cacheGenerationAtStart !== cacheGeneration) return
        if (cause instanceof OpportunityBrowsePendingError && retries++ < 2) {
          setPageErrorNotice('Results are being prepared. Retrying shortly…')
          retryTimer.current = setTimeout(() => void load(), cause.retryAfterMs)
          return
        }
        if (cause instanceof OpportunityCohortChangedError) {
          cache.clear(); setPage(null); setLoading(false); setPageErrorNotice('Results changed. Reloaded from the first page.')
          onBrowseChangeRef.current?.(); updateUrl(search, sector, 0, sort, shortlist, undefined, false, filtersRef.current)
          if (offset) { cohortResetUsed.current = false; setOffset(0); return }
          if (!cohortResetUsed.current) { cohortResetUsed.current = true; setRetryKey(value => value + 1); return }
          setError('Results changed again while reloading. Refresh to try once more.'); return
        }
        setError(cause instanceof Error ? cause.message : 'Could not load opportunities.'); setPage(null); setLoading(false)
      }
    }
    void load()
    return () => { active = false; controller.abort(); if (requestAbort.current === controller) requestAbort.current = null; if (retryTimer.current) clearTimeout(retryTimer.current) }
  }, [search, sector, offset, sort, shortlist, retryKey])
  useEffect(() => {
    if (!page?.valid_until) return
    const expires = Date.parse(page.valid_until)
    if (!Number.isFinite(expires)) return
    const delay = expires - Date.now()
    if (delay <= 0) { setPage(null); setRetryKey(value => value + 1); return }
    const timer = setTimeout(() => { cache.delete(cacheKey(search, sector, offset, sort, shortlist)); setPage(null); setRetryKey(value => value + 1) }, delay)
    return () => clearTimeout(timer)
  }, [page?.valid_until, search, sector, offset, sort, shortlist])

  filtersRef.current = { region, stage, priority }
  const requestedPageKey = cacheKey(search, sector, offset, sort, shortlist)
  const visiblePage = pageKey === requestedPageKey && pageIsCurrent(page) ? page : null
  const canInteract = Boolean(visiblePage) && !loading && !error && searchDraft === search
  const items = visiblePage?.items ?? EMPTY_PROJECTS
  const regions = [...new Set(items.map(item => item.location).filter((value): value is string => Boolean(value)))].sort()
  const stages = [...new Set(items.map(item => item.event?.kind).filter((value): value is string => Boolean(value)))].sort()
  // A bookmarked filter value absent from this page stays selectable/visible so the control reflects the URL.
  const regionOptions = region && !regions.includes(region) ? [...regions, region].sort() : regions
  const stageOptions = stage && !stages.includes(stage) ? [...stages, stage].sort() : stages
  const visible = useMemo(() => items.filter(item =>
    (!region || item.location === region) && (!stage || item.event?.kind === stage) &&
    (shortlist || !priority || (priority === 'ranked' ? item.priority_score != null : item.priority_score == null))
  ), [items, region, stage, priority, shortlist])
  /** Exports the visible page, omitting the shortlist ordering value from score fields. */
  const exportRows = () => {
    downloadProjectPage(visible)
  }
  const selectSector = (value: Sector) => { if (value === sector) return; onBrowseChangeRef.current?.(); setSector(value); window.dispatchEvent(new CustomEvent('gl3-demand-sector-change', { detail: value })); setOffset(0); setRegion(''); setStage(''); setPriority(''); updateUrl(search, value, 0, sort, shortlist) }
  const clearFilters = () => { onBrowseChangeRef.current?.(); setSearchDraft(''); setSearch(''); setRegion(''); setStage(''); setPriority(''); setSector('all'); window.dispatchEvent(new CustomEvent('gl3-demand-sector-change', { detail: 'all' })); setOffset(0); updateUrl('', 'all', 0, sort, shortlist) }
  const selectSort = (value: Sort) => { if (value === sort) return; onBrowseChangeRef.current?.(); cohortResetUsed.current = false; setSort(value); setOffset(0); updateUrl(search, sector, 0, value, shortlist, undefined, true, { region, stage, priority }) }
  /** Switches project views and clears page filters that do not carry across cohorts. */
  const selectShortlist = (value: boolean) => { if (value === shortlist) return; onBrowseChangeRef.current?.(); setShortlist(value); setOffset(0); setRegion(''); setStage(''); setPriority(''); updateUrl(search, sector, 0, sort, value, undefined, true) }
  return <section className="canonical-flat-results" aria-label="Project opportunities" aria-busy={loading || searchDraft !== search}>
    <header className="cfr-heading"><div><h1>Opportunities</h1><p>{shortlist ? 'Source-backed development and power activity for review.' : 'All source-backed project records, including Signals.'}</p></div><div><span>{visiblePage ? `${projectCount(visiblePage.total)} · ${shortlist ? 'Shortlist' : visiblePage.results_scope === 'discovery' ? 'All projects · Signals included' : 'All qualified projects'}` : 'Unavailable'}<small className="cfr-filter-scope" title="Region, stage and priority filter the current page. Search and project type cover all results.">Page filters</small></span><label className="cfr-sort-label">Sort<select aria-label="Sort opportunities" disabled={!canInteract} value={sort} onChange={event => selectSort(event.target.value as Sort)}><option value="priority">Priority</option><option value="priority_asc">Priority (ascending)</option><option value="company">Company</option><option value="project">Project</option></select></label><button type="button" onClick={exportRows} disabled={!visible.length || !canInteract}><Download size={13} aria-hidden="true"/> Export current page</button></div></header>
    <div className="cfr-filters" aria-describedby="canonical-filter-scope"><div className="cfr-view-switch" role="group" aria-label="Opportunity view"><button type="button" aria-pressed={shortlist} onClick={() => selectShortlist(true)}>Shortlist</button><button type="button" aria-pressed={!shortlist} onClick={() => selectShortlist(false)}>All Projects</button></div><input aria-label="Search opportunities" placeholder="Search opportunities…" value={searchDraft} onChange={event => setSearchDraft(event.target.value)}/><select aria-label="Region" value={region} onChange={event => { setRegion(event.target.value); setFilterParam('region', event.target.value) }}><option value="">All Regions</option>{regionOptions.map(value => <option key={value}>{value}</option>)}</select><select aria-label="Project type" value={sector} onChange={event => selectSector(event.target.value as Sector)}><option value="all">All Project Types</option><option value="oil_gas">Oil &amp; Gas</option><option value="data_centers">Data Centers</option></select><select aria-label="Stage" value={stage} onChange={event => { setStage(event.target.value); setFilterParam('stage', event.target.value) }}><option value="">All Stages</option>{stageOptions.map(value => <option key={value} value={value}>{stageLabel(value)}</option>)}</select>{!shortlist && <select aria-label="Priority" value={priority} onChange={event => { setPriority(event.target.value); setFilterParam('priority', event.target.value) }}><option value="">All Priorities</option><option value="ranked">Ranked</option><option value="unranked">Unranked</option></select>}<button type="button" onClick={clearFilters}>Clear</button></div>
    <p className="cfr-scope" id="canonical-filter-scope">Region and stage filter this page · Search and project type cover all results{!shortlist && ' · Priority filters this page'}</p>
    {pageErrorNotice && <p role="status">{pageErrorNotice}</p>}{error && <p role="alert">{error} <button type="button" onClick={() => setRetryKey(value => value + 1)}>Retry</button></p>}
    {loading && !page && !error && <p role="status">Loading current opportunities…</p>}
    {!loading && visiblePage && !visible.length && (shortlist && visiblePage.total === 0
      ? <p role="status">No projects meet the shortlist evidence rules for this search. <button type="button" onClick={() => selectShortlist(false)}>Explore All Projects for unresolved records</button>.</p>
      : visiblePage.total > 0 ? <p>No projects match these page filters.</p> : <p>No projects are available for this search in All Projects.</p>)}
    {visiblePage && <div className="cfr-table-wrap"><table className="cfr-table" role="table"><thead className="cfr-thead"><tr role="row"><th>What</th><th>Why now</th><th>Power need</th><th>Next step</th><th>Actions</th></tr></thead><tbody>{visible.map(item => {
      const primaryNeedId = item.representative_need_id ?? item.needs[0]?.id
      const selected = selectedNeedId && item.needs.some(need => need.id === selectedNeedId)
      const brief = item.commercial_brief ?? item.needs.find(need => need.id === primaryNeedId)?.commercial_brief ?? null
      const powerKind = item.power_summary_kind ?? 'unknown'
      const powerText = item.power_summary?.trim()
      const briefPower = brief?.power_need
      const powerLabel = brief
        ? briefPower?.amount_class !== 'unknown' && briefPower?.value?.trim()
          ? `${briefPower.value}${briefPower.unit ? ` ${briefPower.unit}` : ''}${briefPower.scope ? ` · ${briefPower.scope}` : ''}`
          : 'Power need unknown'
        : powerText && (powerKind === 'facility_demand' || powerKind === 'activity_requirement')
          ? `${powerKind === 'facility_demand' ? 'Facility demand' : 'Power need'} · ${powerText}`
          : 'Power need unknown'
      const assessment = item.shortlist_assessment
      return <tr role="row" key={item.id} aria-selected={selected ? true : undefined} className={selected ? 'cfr-selected' : undefined}>
        <td role="cell" data-label="What" className="cfr-c-project"><span className="cfr-company-project">{item.company && <strong>{item.company}</strong>}<button type="button" data-need-row={primaryNeedId} onClick={() => primaryNeedId && onNeed({ id: primaryNeedId })} disabled={!canInteract || !primaryNeedId}>{cardProjectName(item)}</button>{item.location && <small>{item.location}</small>}</span></td>
        <td role="cell" data-label="Why now" className="cfr-card-why">{brief?.why_now.text ?? assessment?.why_now ?? (item.event?.date && item.event.label ? `${item.event.label} · ${item.event.date}` : 'No dated development established.')}{brief?.why_now.scope && <small>Scope: {brief.why_now.scope}</small>}{brief?.why_now.source_date && <small>Source date: {brief.why_now.source_date}</small>}</td>
        <td role="cell" data-label="Power need" className="cfr-power">{powerLabel}{briefPower && <small>{briefPower.amount_class === 'unknown' ? 'Amount unknown' : `${briefPower.amount_class} · ${briefPower.status}`}{briefPower.limitations.length > 0 && ` · ${briefPower.limitations.join('; ')}`}</small>}</td>
        <td role="cell" data-label="Next step" className="cfr-card-next">{brief?.next_action.text ?? assessment?.next_step ?? (!shortlist ? item.next_action : null) ?? 'Confirm project scope and timing from sources.'}{brief?.freshness.status && <small>{brief.freshness.status}{brief.freshness.source_date ? ` · source date ${brief.freshness.source_date}` : ''}</small>}</td>
        <td role="cell" className="cfr-card-action">{brief?.best_contact && safeBriefContactHref(brief.best_contact.kind, brief.best_contact.contact) && <a className="cfr-contact-route" aria-label={`Best contact ${brief.best_contact.contact}. Authority: ${brief.best_contact.authority}. Deliverability: ${brief.best_contact.deliverability}.`} href={safeBriefContactHref(brief.best_contact.kind, brief.best_contact.contact)!}>Best contact · {brief.best_contact.contact}<small>Authority: {brief.best_contact.authority} · Deliverability: {brief.best_contact.deliverability}</small></a>}{primaryNeedId && <AddToPursuit key={primaryNeedId} needId={primaryNeedId} disabled={!canInteract} deferLookup/>}</td>
      </tr>
    })}</tbody></table></div>}
    {visiblePage && <footer className="cfr-paging"><span>{visiblePage.items.length ? `${visiblePage.offset + 1}–${visiblePage.offset + visiblePage.items.length} of ${projectCount(visiblePage.total)}` : visiblePage.total ? `0 projects on this page · ${projectCount(visiblePage.total)} total` : '0 projects'}{(region || stage || priority) && ` · ${visible.length} of ${visiblePage.items.length} projects on this page match filters`}</span><button type="button" disabled={!canInteract || offset === 0} onClick={() => { const next = Math.max(0, offset - visiblePage.limit); onBrowseChangeRef.current?.(); setOffset(next); updateUrl(search, sector, next, sort, shortlist, visiblePage.cohort_token, false, { region, stage, priority }) }}>Previous</button><button type="button" disabled={!canInteract || offset + visiblePage.items.length >= visiblePage.total} onClick={() => { const next = offset + visiblePage.limit; onBrowseChangeRef.current?.(); setOffset(next); updateUrl(search, sector, next, sort, shortlist, visiblePage.cohort_token, false, { region, stage, priority }) }}>Next</button></footer>}
  </section>
}

const STRICT_EMAIL = /^[A-Za-z0-9._+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,63}$/
function safeBriefContactHref(kind: string, value: string): string | null {
  const contact = value.trim()
  if (kind === 'call' && /^[+()\d][\d\s().-]{5,}$/.test(contact) && (contact.match(/\d/g)?.length ?? 0) >= 7) return `tel:${contact.replace(/[^+\d]/g, '')}`
  if (kind === 'email' && STRICT_EMAIL.test(contact)) return `mailto:${contact}`
  if (kind === 'contact') {
    try { const url = new URL(contact); return ['https:', 'http:'].includes(url.protocol) ? url.href : null } catch { return null }
  }
  return null
}

/** Show the sector demand summary while preserving unknown and unavailable states. */
export function CanonicalOpportunityKpis() {
  const [sector, setSector] = useState<Sector>(() => readRoute().sector)
  const [summary, setSummary] = useState<DemandSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [retry, setRetry] = useState(0)
  const [refreshRevision, setRefreshRevision] = useState(0)
  const activeRequest = useRef<AbortController | null>(null)
  const sessionCleared = useRef(false)
  const lastFetchedAt = useRef(0)
  useEffect(() => {
    const syncRoute = () => setSector(readRoute().sector)
    const syncSector = (event: Event) => setSector((event as CustomEvent<Sector>).detail)
    const refresh = () => setRefreshRevision(value => value + 1)
    const refreshOnFocus = () => { if (document.visibilityState === 'visible' && Date.now() - lastFetchedAt.current >= 60_000) refresh() }
    const clear = () => { sessionCleared.current = true; activeRequest.current?.abort(); activeRequest.current = null; setSummary(null); setError(false); setLoading(false) }
    window.addEventListener('popstate', syncRoute)
    window.addEventListener('gl3-demand-sector-change', syncSector)
    window.addEventListener('gl3-demand-refresh', refresh)
    window.addEventListener('focus', refreshOnFocus)
    document.addEventListener('visibilitychange', refreshOnFocus)
    window.addEventListener('gl3-clear-continuity', clear)
    return () => { window.removeEventListener('popstate', syncRoute); window.removeEventListener('gl3-demand-sector-change', syncSector); window.removeEventListener('gl3-demand-refresh', refresh); window.removeEventListener('focus', refreshOnFocus); document.removeEventListener('visibilitychange', refreshOnFocus); window.removeEventListener('gl3-clear-continuity', clear) }
  }, [])
  useEffect(() => {
    if (sessionCleared.current) return
    const controller = new AbortController()
    activeRequest.current = controller
    let active = true
    setLoading(true); setError(false); setSummary(null)
    client.demandSummary(sector, controller.signal).then(value => {
      if (!active || controller.signal.aborted) return
      lastFetchedAt.current = Date.now()
      setSummary(value); setLoading(false)
    }).catch(() => { if (active && !controller.signal.aborted) { setSummary(null); setError(true); setLoading(false) } })
    return () => { active = false; controller.abort(); if (activeRequest.current === controller) activeRequest.current = null }
  }, [sector, retry, refreshRevision])
  useEffect(() => {
    const timer = window.setTimeout(() => setRefreshRevision(value => value + 1), 60_000)
    return () => window.clearTimeout(timer)
  }, [refreshRevision])
  const format = (value: number | null) => value == null || !Number.isFinite(value) ? 'Unavailable' : new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value)
  const ready = !loading && !error && summary?.availability === 'available'
  const classes = summary?.classes
  const sectorLabel = sector === 'all' ? 'All sectors' : sector === 'oil_gas' ? 'Oil & Gas' : 'Data Centers'
  const provenance = summary?.provenance
  const knownClass = ready && classes ? (['documented', 'calculated', 'estimated'] as const).find(kind => classes[kind].mw != null && classes[kind].record_count > 0) : undefined
  const classSummary = ready && classes ? `Documented ${format(classes.documented.mw)} MW (${classes.documented.record_count}) · Calculated ${format(classes.calculated.mw)} MW (${classes.calculated.record_count}) · Estimated ${format(classes.estimated.mw)} MW (${classes.estimated.record_count})` : null
  const countsText = summary && summary.counts_complete !== false ? `${summary.totals.identified_records} identified records · ${summary.totals.known_mw_records} with MW · ${summary.totals.unknown_records} unknown · ${summary.totals.conflicted_records} conflicted.` : 'Record counts unavailable.'
  const statusText = loading ? 'Loading demand summary…' : error ? 'Demand summary unavailable.' : !summary ? 'Demand summary unavailable; record counts are unavailable.' : `${countsText} Demand total unavailable; unknown is not zero.`
  const asOfLabel = summary?.as_of && Number.isFinite(Date.parse(summary.as_of)) ? new Date(summary.as_of).toLocaleString() : null
  const coverageDisclosure = summary ? <details className="cfr-demand-provenance"><summary>Coverage and limitations</summary><p>{provenance?.source_count ?? 0} contributing sources · {sectorLabel}{provenance?.latest_evidence_at ? ` · Latest evidence ${new Date(provenance.latest_evidence_at).toLocaleString()}` : ''}</p>{summary.limitations.length > 0 ? <ul>{summary.limitations.map((limitation, index) => <li key={`${index}-${limitation}`}>{limitation}</li>)}</ul> : <p>Coverage is limited to supported, safely aggregated equipment records.</p>}</details> : null
  return <div className="cfr-kpis" aria-label="Opportunity summary"><article><Zap aria-hidden="true"/><strong aria-label={loading ? 'Loading' : error || !ready || !knownClass ? 'Unavailable' : `${format(classes![knownClass].mw)} MW ${knownClass}`}>{loading ? '…' : knownClass && classes ? `${format(classes[knownClass].mw)} MW` : '—'}</strong><span>Identified Power Demand (MW)</span><small>{loading || error || !ready ? <>{statusText}{error && <> <button type="button" onClick={() => setRetry(value => value + 1)}>Retry</button></>}</> : <><b className="cfr-kpi-scope">Additional equipment only</b> · Bounded supported equipment records; not total portfolio demand. {knownClass ? `${knownClass[0].toUpperCase()}${knownClass.slice(1)} class.` : 'No known class amount.'} {classSummary}. {countsText} {sectorLabel}{asOfLabel ? ` · Updated ${asOfLabel}` : ''}.</>}</small>{coverageDisclosure}</article></div>
}
