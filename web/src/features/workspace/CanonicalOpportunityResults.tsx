import { Zap, ChartNoAxesColumnIncreasing, FileText, Download } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { client, OpportunityBrowsePendingError, OpportunityCohortChangedError, type DemandSummary, type ProjectResult, type ProjectResultsPage, type ProjectResultsSort } from '../../api/client'
import './canonical-opportunity-results.css'

type Props = { selectedNeedId?: string; onNeed: (need: { id: string }) => void; onBrowseChange?: () => void }
type Sector = 'all' | 'oil_gas' | 'data_centers'
type Sort = Exclude<ProjectResultsSort, 'updated'>
type CacheEntry = { page: ProjectResultsPage; savedAt: number }
const cache = new Map<string, CacheEntry>()
const CACHE_TTL = 60_000
let cacheGeneration = 0
if (typeof window !== 'undefined') window.addEventListener('gl3-clear-continuity', () => { cacheGeneration += 1; cache.clear() })
const EMPTY_PROJECTS: ProjectResult[] = []
const cacheKey = (search: string, sector: Sector, offset: number, sort: Sort) => JSON.stringify([search, sector, offset, sort])
function pageIsCurrent(page: ProjectResultsPage | null) {
  if (!page || !Array.isArray(page.items) || !Number.isSafeInteger(page.total) || page.total < 0 || !Number.isSafeInteger(page.limit) || page.limit <= 0 || !Number.isSafeInteger(page.offset) || page.offset < 0 || typeof page.cohort_token !== 'string') return false
  if (page.items.some(item => !item || typeof item.id !== 'string' || typeof item.name !== 'string' || !Array.isArray(item.needs))) return false
  if (page.qualification_state && page.qualification_state !== 'current') return false
  if (page.refresh_state && page.refresh_state !== 'current') return false
  if (!page.valid_until) return true
  const expires = Date.parse(page.valid_until)
  return Number.isFinite(expires) && Date.now() < expires
}
function readRoute() {
  const params = new URLSearchParams(location.search)
  return { search: params.get('q') ?? '', sector: (['oil_gas', 'data_centers'].includes(params.get('sector') ?? '') ? params.get('sector') : 'all') as Sector, offset: Math.max(0, Number(params.get('offset') ?? 0) || 0), sort: (['priority_asc', 'company', 'project'].includes(params.get('sort') ?? '') ? params.get('sort') : 'priority') as Sort }
}
function updateUrl(search: string, sector: Sector, offset: number, sort: Sort, cohort?: string, push = false) {
  const params = new URLSearchParams({ view: 'workspace' })
  if (new URLSearchParams(location.search).get('projectBrowse') === '1') params.set('projectBrowse', '1')
  if (search) params.set('q', search)
  if (sector !== 'all') params.set('sector', sector)
  if (offset) params.set('offset', String(offset))
  if (sort !== 'priority') params.set('sort', sort)
  if (cohort) params.set('cohort_token', cohort)
  if (push) history.pushState(history.state, '', `/?${params}`)
  else history.replaceState(history.state, '', `/?${params}`)
}
function displayProjectName(project: ProjectResult) {
  return project.company && project.name.startsWith(`${project.company} · `) ? project.name.slice(project.company.length + 3) : project.name
}
function gapValue(project: ProjectResult) {
  if (project.power_summary_kind !== 'supported_gap' || !project.power_summary) return 'Unavailable'
  return project.power_summary
}
function safeCsvCell(value: string) {
  const safe = /^[\s\t]*[=+@\-]/.test(value) ? `'${value}` : value
  return `"${safe.replaceAll('"', '""')}"`
}

export function CanonicalOpportunityResults({ selectedNeedId, onNeed, onBrowseChange }: Props) {
  const initial = useRef(readRoute()).current
  const [searchDraft, setSearchDraft] = useState(initial.search)
  const [search, setSearch] = useState(initial.search)
  const [sector, setSector] = useState<Sector>(initial.sector)
  const [offset, setOffset] = useState(initial.offset)
  const [sort, setSort] = useState<Sort>(initial.sort)
  const [page, setPage] = useState<ProjectResultsPage | null>(() => {
    const entry = cache.get(cacheKey(initial.search, initial.sector, initial.offset, initial.sort))
    return entry && Date.now() - entry.savedAt < CACHE_TTL && pageIsCurrent(entry.page) ? entry.page : null
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [selectedRows, setSelectedRows] = useState<string[]>([])
  const [region, setRegion] = useState('')
  const [stage, setStage] = useState('')
  const [priority, setPriority] = useState('')
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onBrowseChangeRef = useRef(onBrowseChange)
  onBrowseChangeRef.current = onBrowseChange
  const requestGeneration = useRef(0)
  const requestAbort = useRef<AbortController | null>(null)
  const [pageKey, setPageKey] = useState(() => cacheKey(initial.search, initial.sector, initial.offset, initial.sort))
  const cohortResetUsed = useRef(false)
  const [retryKey, setRetryKey] = useState(0)
  const [pageErrorNotice, setPageErrorNotice] = useState('')

  useEffect(() => {
    const onPop = () => { const route = readRoute(); setSearchDraft(route.search); setSearch(route.search); setSector(route.sector); setOffset(route.offset); setSort(route.sort); cohortResetUsed.current = false }
    const onClear = () => { requestGeneration.current += 1; requestAbort.current?.abort(); if (retryTimer.current) clearTimeout(retryTimer.current); cacheGeneration += 1; cache.clear(); setPage(null); setError('Your session ended. Sign in again.'); setLoading(false) }
    window.addEventListener('popstate', onPop)
    window.addEventListener('gl3-clear-continuity', onClear)
    return () => { window.removeEventListener('popstate', onPop); window.removeEventListener('gl3-clear-continuity', onClear) }
  }, [])
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchDraft !== search) {
        setSearch(searchDraft); setOffset(0); setSelectedRows([]); setRegion(''); setStage(''); setPriority(''); onBrowseChangeRef.current?.(); updateUrl(searchDraft, sector, 0, sort)
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [searchDraft, search, sector, sort])
  useEffect(() => {
    const key = cacheKey(search, sector, offset, sort)
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
        const value = await client.projectResults({ search, sector, limit: 25, offset, cohort_token: new URLSearchParams(location.search).get('cohort_token') ?? undefined, sort, include_signals: true }, controller.signal)
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
          updateUrl(search, sector, 0, sort)
          if (offset) { cohortResetUsed.current = false; setOffset(0); return }
          if (!cohortResetUsed.current) { cohortResetUsed.current = true; setRetryKey(value => value + 1); return }
          setError('Results changed again while reloading. Refresh to try once more.'); return
        }
        setError(cause instanceof Error ? cause.message : 'Could not load opportunities.'); setPage(null); setLoading(false)
      }
    }
    void load()
    return () => { active = false; controller.abort(); if (requestAbort.current === controller) requestAbort.current = null; if (retryTimer.current) clearTimeout(retryTimer.current) }
  }, [search, sector, offset, sort, retryKey])
  useEffect(() => {
    if (!page?.valid_until) return
    const expires = Date.parse(page.valid_until)
    if (!Number.isFinite(expires)) return
    const delay = expires - Date.now()
    if (delay <= 0) { setPage(null); setRetryKey(value => value + 1); return }
    const timer = setTimeout(() => { cache.delete(cacheKey(search, sector, offset, sort)); setPage(null); setRetryKey(value => value + 1) }, delay)
    return () => clearTimeout(timer)
  }, [page?.valid_until, search, sector, offset, sort])

  const requestedPageKey = cacheKey(search, sector, offset, sort)
  const visiblePage = pageKey === requestedPageKey && pageIsCurrent(page) ? page : null
  const canInteract = Boolean(visiblePage) && !loading && !error && searchDraft === search
  const items = visiblePage?.items ?? EMPTY_PROJECTS
  const regions = [...new Set(items.map(item => item.location).filter((value): value is string => Boolean(value)))].sort()
  const stages = [...new Set(items.map(item => item.event?.kind).filter((value): value is string => Boolean(value)))].sort()
  const visible = useMemo(() => items.filter(item =>
    (!region || item.location === region) && (!stage || item.event?.kind === stage) &&
    (!priority || (priority === 'ranked' ? item.priority_score != null : item.priority_score == null))
  ), [items, region, stage, priority])
  useEffect(() => { setSelectedRows(current => { const next = current.filter(id => visible.some(item => item.id === id)); return next.length === current.length && next.every((id, index) => id === current[index]) ? current : next }) }, [visible])
  const exportRows = () => {
    const rows = [['Company', 'Project', 'Region', 'Power gap', 'Timing', 'Lifecycle event', 'Qualification', 'Priority score']]
    for (const item of visible) rows.push([item.company ?? 'Unavailable', displayProjectName(item), item.location ?? 'Unavailable', gapValue(item), item.event?.date ?? 'Unavailable', item.event?.label ?? 'Unavailable', item.needs.find(need => need.id === item.representative_need_id)?.tier ?? 'Unavailable', item.priority_score == null ? 'Unavailable' : String(item.priority_score)])
    const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([rows.map(row => row.map(safeCsvCell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' })); link.download = 'gridlens-opportunities.csv'; link.click(); URL.revokeObjectURL(link.href)
  }
  const selectSector = (value: Sector) => { if (value === sector) return; onBrowseChangeRef.current?.(); setSector(value); window.dispatchEvent(new CustomEvent('gl3-demand-sector-change', { detail: value })); setOffset(0); setRegion(''); setStage(''); setPriority(''); setSelectedRows([]); updateUrl(search, value, 0, sort) }
  const clearFilters = () => { onBrowseChangeRef.current?.(); setSearchDraft(''); setSearch(''); setRegion(''); setStage(''); setPriority(''); setSector('all'); window.dispatchEvent(new CustomEvent('gl3-demand-sector-change', { detail: 'all' })); setOffset(0); setSelectedRows([]); updateUrl('', 'all', 0, sort) }
  const selectSort = (value: Sort) => { if (value === sort) return; onBrowseChangeRef.current?.(); cohortResetUsed.current = false; setSort(value); setOffset(0); setSelectedRows([]); updateUrl(search, sector, 0, value, undefined, true) }
  const selectAll = (checked: boolean) => setSelectedRows(checked ? visible.map(item => item.id) : [])
  return <section className="canonical-flat-results" aria-label="Project opportunities" aria-busy={loading || searchDraft !== search}>
    <header className="cfr-heading"><div><h1>Opportunities</h1><p>Commercial projects with material power demand in constrained markets.</p></div><div><span>{visiblePage ? `${visiblePage.total} ${visiblePage.count_unit} · ${visiblePage.results_scope === 'discovery' ? 'Signals included' : 'Qualified projects'}` : 'Unavailable'}<small className="cfr-filter-scope" title="Region, stage and priority filter the current page. Search and project type cover all results.">Page filters</small></span><label className="cfr-sort-label">Sort<select aria-label="Sort opportunities" disabled={!canInteract} value={sort} onChange={event => selectSort(event.target.value as Sort)}><option value="priority">Priority</option><option value="priority_asc">Priority (ascending)</option><option value="company">Company</option><option value="project">Project</option></select></label><button type="button" onClick={exportRows} disabled={!visible.length || !canInteract}><Download size={13} aria-hidden="true"/> Export</button></div></header>
    <div className="cfr-filters" aria-describedby="canonical-filter-scope"><input aria-label="Search opportunities" placeholder="Search opportunities…" value={searchDraft} onChange={event => setSearchDraft(event.target.value)}/><select aria-label="Region" value={region} onChange={event => setRegion(event.target.value)}><option value="">All Regions</option>{regions.map(value => <option key={value}>{value}</option>)}</select><select aria-label="Project type" value={sector} onChange={event => selectSector(event.target.value as Sector)}><option value="all">All Project Types</option><option value="oil_gas">Oil &amp; Gas</option><option value="data_centers">Data Centers</option></select><select aria-label="Stage" value={stage} onChange={event => setStage(event.target.value)}><option value="">All Stages</option>{stages.map(value => <option key={value}>{value}</option>)}</select><select aria-label="Priority" value={priority} onChange={event => setPriority(event.target.value)}><option value="">All Priorities</option><option value="ranked">Ranked</option><option value="unranked">Unranked</option></select><button type="button" onClick={clearFilters}>Clear</button></div>
    <p className="cfr-scope" id="canonical-filter-scope">Region, stage and priority filter this page · Search and project type cover all results</p>
    {pageErrorNotice && <p role="status">{pageErrorNotice}</p>}{error && <p role="alert">{error} <button type="button" onClick={() => setRetryKey(value => value + 1)}>Retry</button></p>}
    {loading && !page && !error && <p role="status">Loading current opportunities…</p>}
    {!loading && visiblePage && !visible.length && <p>No projects match these page filters.</p>}
    {visiblePage && <div className="cfr-table-wrap"><table className="cfr-table"><thead><tr><th><input type="checkbox" aria-label="Select all visible projects" disabled={!canInteract} checked={visible.length > 0 && visible.every(item => selectedRows.includes(item.id))} onChange={event => selectAll(event.target.checked)}/></th><th>Company / Project</th><th>Region</th><th>Est. Power<br/>Need (MW)</th><th>Est. Power<br/>Gap (MW)</th><th>Timing</th><th>Stage</th><th aria-sort={sort === 'priority_asc' ? 'ascending' : sort === 'priority' ? 'descending' : 'none'}><button type="button" disabled={!canInteract} onClick={() => selectSort(sort === 'priority' ? 'priority_asc' : 'priority')}>Priority {sort === 'priority_asc' ? '↑' : sort === 'priority' ? '↓' : '↕'}</button></th><th /></tr></thead><tbody>{visible.map(item => {
      const primaryNeedId = item.representative_need_id ?? item.needs[0]?.id
      const primary = item.needs.find(need => need.id === primaryNeedId) ?? item.needs[0]
      const selected = selectedNeedId && item.needs.some(need => need.id === selectedNeedId)
      const demand = item.power_summary_kind === 'activity_requirement' || item.power_summary_kind === 'facility_demand' ? item.power_summary : 'Unavailable'
      return <tr key={item.id} className={selected ? 'cfr-selected' : undefined}>
        <td><input type="checkbox" aria-label={`Select ${displayProjectName(item)}`} disabled={!canInteract} checked={selectedRows.includes(item.id)} onChange={event => setSelectedRows(current => event.target.checked ? [...current, item.id] : current.filter(id => id !== item.id))}/></td>
        <td><span className="cfr-company-project"><strong>{item.company ?? 'Company unavailable'}</strong><button type="button" data-need-row={primaryNeedId} onClick={() => primaryNeedId && onNeed({ id: primaryNeedId })} disabled={!canInteract || !primaryNeedId}>{displayProjectName(item)}</button>{item.need_count > 1 && <details><summary>{item.need_count} related power needs</summary>{item.needs.filter(need => need.id !== primaryNeedId).map(need => <button type="button" data-need-row={need.id} key={need.id} disabled={!canInteract} onClick={() => onNeed({ id: need.id })}>{need.activity ?? need.browse_title ?? 'Related project detail'}</button>)}</details>}</span></td>
        <td>{item.location ?? 'Unavailable'}</td><td className="cfr-power" title={demand ?? undefined}>{demand === 'Unavailable' ? 'Unknown' : demand}</td><td className="cfr-power" title={gapValue(item)}>{gapValue(item) === 'Unavailable' ? 'Unknown' : gapValue(item)}</td>
        <td>{item.event?.date ? `${item.event.label} · ${item.event.date}` : 'Unavailable'}</td><td><span className="cfr-stage">{item.event?.label ?? 'Unknown'}</span>{primary?.tier && <small className="cfr-qualification"><span className="sr-only">Qualification: </span>{primary.tier}</small>}</td>
        <td title="Server priority rank score; not a qualification or confidence rating">{item.priority_score == null ? '—' : item.priority_score}</td><td><button type="button" className="cfr-open" aria-label={`Open ${displayProjectName(item)}`} onClick={() => primaryNeedId && onNeed({ id: primaryNeedId })} disabled={!canInteract || !primaryNeedId}>›</button></td>
      </tr>
    })}</tbody></table></div>}
    {visiblePage && <footer className="cfr-paging"><span>{visiblePage.items.length ? `${visiblePage.offset + 1}–${visiblePage.offset + visiblePage.items.length} of ${visiblePage.total} projects` : visiblePage.total ? `0 projects on this page · ${visiblePage.total} projects total` : '0 projects'}{(region || stage || priority) && ` · ${visible.length} of ${visiblePage.items.length} projects on this page match filters`}</span><button type="button" disabled={!canInteract || offset === 0} onClick={() => { const next = Math.max(0, offset - visiblePage.limit); setOffset(next); setSelectedRows([]); updateUrl(search, sector, next, sort, visiblePage.cohort_token) }}>Previous</button><button type="button" disabled={!canInteract || offset + visiblePage.items.length >= visiblePage.total} onClick={() => { const next = offset + visiblePage.limit; setOffset(next); setSelectedRows([]); updateUrl(search, sector, next, sort, visiblePage.cohort_token) }}>Next</button></footer>}
  </section>
}

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
  return <div className="cfr-kpis" aria-label="Opportunity summary"><article><Zap aria-hidden="true"/><strong aria-label={loading ? 'Loading' : error || !ready || !knownClass ? 'Unavailable' : `${format(classes![knownClass].mw)} MW ${knownClass}`}>{loading ? '…' : knownClass && classes ? `${format(classes[knownClass].mw)} MW` : '—'}</strong><span>Identified Power Demand (MW)</span><small>{loading || error || !ready ? <>{statusText}{error && <> <button type="button" onClick={() => setRetry(value => value + 1)}>Retry</button></>}</> : <><b className="cfr-kpi-scope">Additional equipment only</b> · Bounded supported equipment records; not total portfolio demand. {knownClass ? `${knownClass[0].toUpperCase()}${knownClass.slice(1)} class.` : 'No known class amount.'} {classSummary}. {countsText} {sectorLabel}{asOfLabel ? ` · Updated ${asOfLabel}` : ''}.</>}</small>{coverageDisclosure}</article><article><ChartNoAxesColumnIncreasing aria-hidden="true"/><strong>—</strong><span>High Priority</span><small>Priority classification unavailable</small></article><article><FileText aria-hidden="true"/><strong>—</strong><span>New This Week</span><small>Creation date unavailable</small></article></div>
}
