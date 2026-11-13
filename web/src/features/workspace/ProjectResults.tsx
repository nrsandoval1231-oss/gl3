import { useEffect, useRef, useState } from 'react'
import { browseUpdatingNotice, client, OpportunityBrowsePendingError, OpportunityCohortChangedError, OpportunityGroupUnavailableError, type CommercialCustomerIntelligence, type CustomerRollupFilters, type CustomerRollupSort, type OpportunityGroup, type OpportunityGroupsPage, type ProjectResult, type ProjectResultsPage } from '../../api/client'
import { clearProjectBrowseCache, invalidateProjectBrowseCache, projectBrowseCacheKey, projectBrowseCacheVersion, readProjectBrowseCache, writeProjectBrowseCache, type ProjectBrowseRoute } from '../../state/projectBrowseCache'
import { AddToPursuit } from '../pursuits/AddToPursuit'
import { downloadProjectPage } from './opportunityExport'
import { bestProjectContactRoutes, CompanyView, generalCompanyContactRoutes, safeContactSourceUrl, selectAccountContactProject, verifiedContactPeople } from '../companies/CompanyView'

type Props = { selectedNeedId?: string; accountContextStatus?: 'valid' | 'pending' | 'unavailable'; onNeed: (need: { id: string }, context?: { accountId: string; projectId?: string }) => void; onBrowseChange?: () => void }
function commercialIntel(group: OpportunityGroup): CommercialCustomerIntelligence | null { return group.commercial_intelligence ?? null }
function intelLabel(value: unknown): string { if (typeof value === 'string' || typeof value === 'number') return String(value); if (!value || typeof value !== 'object') return ''; const row = value as Record<string, unknown>; const display = row.display_label; if (typeof display === 'string') return display; return [row.summary, row.title, row.name, row.label, row.value, row.text, row.date, row.precision].filter((item): item is string | number => typeof item === 'string' || typeof item === 'number').join(' · ') }
function capacityBasis(value: string) { const labels: Record<string,string> = { campus_development:'Campus development', it_load:'IT load', utility_service:'Utility service', generation:'Generation', individual_phase:'Individual phase' }; return labels[value] ?? value.replaceAll('_',' ') }
function capacityPrefix(qualifier: string | undefined, status: string) { if (qualifier === 'up_to' || status === 'upper_bound') return 'Up to '; if (qualifier === 'approximate') return 'Approximately '; if (qualifier === 'more_than') return 'More than '; if (qualifier === 'at_least' || status === 'lower_bound') return 'At least '; return '' }
function CustomerIntelSummary({ group }: { group: OpportunityGroup }) {
  const intel = commercialIntel(group)
  const totals = intel?.capacity?.totals?.filter(item => item.value_mw != null && item.status !== 'unknown') ?? []
  const scenario = intel?.commissioning
  const construction = intelLabel(intel?.timelines?.construction_start)
  const energization = intelLabel(intel?.timelines?.expected_energization)
  const capacity = totals.map(item => { const detail = item as typeof item & { qualifier?: string; complete?: boolean }; return `${capacityPrefix(detail.qualifier,item.status)}${item.value_mw} MW ${capacityBasis(item.basis ?? 'capacity')}${detail.complete === false ? ' · partial coverage' : ''}` }).join(' · ')
  const capacityCoverage = intel?.capacity?.coverage ? `${String(intel.capacity.coverage.projects_with_capacity ?? 0)} of ${String(intel.capacity.coverage.projects_total ?? '?')} projects with supported capacity` : ''
  const scenarioText = scenario && [scenario.low_mw, scenario.base_mw, scenario.high_mw].some(value => value != null)
    ? `Engineering scenario · ${scenario.low_mw ?? scenario.base_mw ?? '—'}–${scenario.high_mw ?? scenario.base_mw ?? '—'} MW`
    : ''
  const development = (intel?.recent_developments ?? []).map(intelLabel).find(Boolean)
  const nextAction = intelLabel(intel?.recommended_next_action)
  return <div className="premium-intelligence-summary" aria-label="Commercial intelligence">
    <span><strong>Build capacity</strong>{capacity || 'Not available from supported evidence'}{capacityCoverage && <small>{capacityCoverage}</small>}</span>
    <span><strong>Timing</strong><small><b>Construction start</b> · {construction || 'Not established'}</small><small><b>Expected energization</b> · {energization || 'Not established'}</small></span>
    <span><strong>Commissioning</strong>{scenarioText || 'Insufficient data for an engineering scenario'}</span>
    {development && <span className="premium-intelligence-development"><strong>Recent development</strong>{development}</span>}
    {nextAction && <span className="premium-intelligence-action"><strong>Next action</strong>{nextAction}</span>}
  </div>
}
const MAX_PENDING_RETRIES = 3
const PENDING_EXHAUSTED_MESSAGE = 'Accounts are still being prepared. Please try again shortly.'
const SEARCH_DEBOUNCE_MS = 300
const projectSpecificMatch = (group: OpportunityGroup, query: string) => {
  if (!group.matched_project_id || !group.matched_need_id || !query.trim()) return false
  const words = (value: string) => value.toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []
  const accountWords = new Set(words(group.name))
  return words(query).some(word => !accountWords.has(word))
}
const browseKey = (route: ProjectBrowseRoute) => projectBrowseCacheKey({ ...route, shortlist: route.shortlist ?? new URLSearchParams(location.search).get('shortlist') !== '0' })
function waitForRetry(delayMs: number, signal: AbortSignal): Promise<boolean> {
  if (signal.aborted) return Promise.resolve(false)
  return new Promise(resolve => {
    let timer: ReturnType<typeof setTimeout>
    const finish = (completed: boolean) => {
      clearTimeout(timer)
      signal.removeEventListener('abort', onAbort)
      resolve(completed)
    }
    const onAbort = () => finish(false)
    signal.addEventListener('abort', onAbort, { once: true })
    timer = setTimeout(() => finish(true), delayMs)
  })
}
function browsePageIsValid(page: { valid_until?: string } | null): boolean {
  if (!page || page.valid_until === undefined) return Boolean(page)
  const validUntil = Date.parse(page.valid_until)
  return Number.isFinite(validUntil) && Date.now() < validUntil
}

export function ProjectResults({ selectedNeedId, accountContextStatus = 'valid', onNeed, onBrowseChange }: Props) {
  const readRoute = () => { const route = new URLSearchParams(location.search); const rawOffset = Number(route.get('offset') ?? 0); const rawSort = route.get('sort'); return { search: route.get('q') ?? '', sector: (route.get('sector') === 'oil_gas' || route.get('sector') === 'data_centers' ? route.get('sector') : 'all') as 'all' | 'oil_gas' | 'data_centers', offset: Number.isSafeInteger(rawOffset) && rawOffset >= 0 ? rawOffset : 0, region: route.get('region') ?? '', stage: route.get('stage') ?? '', priority: (route.get('priority') === 'ranked' || route.get('priority') === 'unranked' ? route.get('priority') : '') as CustomerRollupFilters['priority'], sort: (rawSort === 'priority_asc' || rawSort === 'company' || rawSort === 'updated' ? rawSort : 'priority') as CustomerRollupSort, shortlist: route.get('shortlist') !== '0', accountId: route.get('account') ?? '' } }
  const [initialRoute] = useState(readRoute)
  const [initialCache] = useState(() => initialRoute.shortlist ? readProjectBrowseCache(initialRoute) : null)
  const [search, setSearch] = useState(initialRoute.search)
  const [searchDraft, setSearchDraft] = useState(initialRoute.search)
  const [sector, setSector] = useState(initialRoute.sector)
  const [region, setRegion] = useState(initialRoute.region)
  const [stage, setStage] = useState(initialRoute.stage)
  const [priority, setPriority] = useState<CustomerRollupFilters['priority']>(initialRoute.priority)
  const [sort, setSort] = useState<CustomerRollupSort>(initialRoute.sort)
  const [shortlist, setShortlist] = useState(initialRoute.shortlist)
  const [accountId, setAccountId] = useState(initialRoute.accountId)
  const [page, setPage] = useState<OpportunityGroupsPage | null>(initialCache?.page ?? null)
  const [pageKey, setPageKey] = useState(browseKey(initialRoute))
  const [expanded, setExpanded] = useState<Record<string, boolean>>(initialCache?.expanded ?? {})
  const [children, setChildren] = useState<Record<string, ProjectResultsPage | null>>(initialCache?.children ?? {})
  const [childErrors, setChildErrors] = useState<Record<string, string>>({})
  const [childLoading, setChildLoading] = useState<Record<string, boolean>>({})
  const [childNotices, setChildNotices] = useState<Record<string, string>>({})
  const [childOffsets, setChildOffsets] = useState<Record<string, number>>(initialCache?.childOffsets ?? {})
  const [groupParentTokens, setGroupParentTokens] = useState<Record<string, string>>(initialCache?.groupParentTokens ?? {})
  const [openedGroups, setOpenedGroups] = useState<Record<string, OpportunityGroup>>(initialCache?.openedGroups ?? {})
  const [offset, setOffset] = useState(initialRoute.offset)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(true)
  const [retryKey, setRetryKey] = useState(0)
  const childRequests = useRef(new Map<string, AbortController>())
  const childEpoch = useRef(0)
  const parentReloadNotice = useRef(false)
  const pendingScrollRestore = useRef<number | null>(initialCache?.scrollY ?? null)
  const fetchedAt = useRef<number>(initialCache?.savedAt ?? 0)
  const resetChildRequests = () => { childEpoch.current += 1; childRequests.current.forEach(request => request.abort()); childRequests.current.clear(); setExpanded({}); setChildren({}); setChildErrors({}); setChildLoading({}); setChildNotices({}); setChildOffsets({}); setGroupParentTokens({}); setOpenedGroups({}) }
  useEffect(() => () => {
    childEpoch.current += 1
    childRequests.current.forEach(request => request.abort())
    childRequests.current.clear()
  }, [])
  useEffect(() => {
    const onSessionCleared = () => {
      setPage(null); setExpanded({}); setChildren({}); setChildErrors({}); setChildLoading({}); setChildNotices({}); setChildOffsets({}); setGroupParentTokens({}); setOpenedGroups({}); setError('Your session ended. Sign in again.'); setLoading(false)
    }
    window.addEventListener('gl3-clear-continuity', onSessionCleared)
    return () => window.removeEventListener('gl3-clear-continuity', onSessionCleared)
  }, [])
  useEffect(() => {
    const onPop = () => { parentReloadNotice.current = false; const route = readRoute(); setSearch(route.search); setSearchDraft(route.search); setSector(route.sector); setOffset(route.offset); setRegion(route.region); setStage(route.stage); setPriority(route.priority); setSort(route.sort); setShortlist(route.shortlist); setAccountId(route.accountId) }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  useEffect(() => {
    const syncAccountRoute = () => setAccountId(new URLSearchParams(location.search).get('account') ?? '')
    window.addEventListener('gl3-account-route', syncAccountRoute)
    return () => window.removeEventListener('gl3-account-route', syncAccountRoute)
  }, [])
  const browseChangeRef = useRef(onBrowseChange)
  browseChangeRef.current = onBrowseChange
  useEffect(() => {
    if (searchDraft === search) return
    const timer = setTimeout(() => {
      parentReloadNotice.current = false
      if (selectedNeedId) browseChangeRef.current?.()
      setSearch(searchDraft); setOffset(0); updateUrl(searchDraft, sector)
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [searchDraft, search, sector, selectedNeedId])
  useEffect(() => {
    childEpoch.current += 1; childRequests.current.forEach(request => request.abort()); childRequests.current.clear()
    const route = { search, sector, offset, region, stage, priority, sort, shortlist }
    const key = browseKey(route)
    const cached = readProjectBrowseCache(route)
    if (pageKey !== key) {
      if (cached) {
        setPage(cached.page); setPageKey(key); setExpanded(cached.expanded); setChildren(cached.children); setChildOffsets(cached.childOffsets); setGroupParentTokens(cached.groupParentTokens); setOpenedGroups(cached.openedGroups); pendingScrollRestore.current = cached.scrollY; fetchedAt.current = cached.savedAt
      } else {
        setExpanded({}); setChildren({}); setChildOffsets({}); setGroupParentTokens({}); setOpenedGroups({}); fetchedAt.current = 0
      }
    }
    const controller = new AbortController(); setLoading(true); setError(''); if (!parentReloadNotice.current) setNotice(''); setChildErrors({}); setChildLoading({}); setChildNotices({})
    const cohort = new URLSearchParams(location.search).get('cohort_token') ?? undefined
    const loadGroups = async () => {
      for (let attempt = 0; attempt <= MAX_PENDING_RETRIES; attempt += 1) {
        try {
          const value = await client.opportunityGroups({ search, sector, limit: 25, offset, cohort_token: cohort, sort, region, stage, priority, shortlist }, controller.signal)
          if (controller.signal.aborted) return
          const previousCohort = pageKey === key ? page?.cohort_token : cached?.page.cohort_token
          const cohortChanged = Boolean(previousCohort && previousCohort !== value.cohort_token)
          setPage(value); setPageKey(key); fetchedAt.current = Date.now(); setLoading(false)
          if (cohortChanged) { setExpanded({}); setChildren({}); setChildOffsets({}); setGroupParentTokens({}); setOpenedGroups({}) }
          if (parentReloadNotice.current) {
            parentReloadNotice.current = false
            setNotice(['Results changed. Reloaded from the first page.', browseUpdatingNotice(value)].filter(Boolean).join(' '))
          } else setNotice(browseUpdatingNotice(value))
          return
        } catch (e) {
          if (controller.signal.aborted) return
          if (e instanceof OpportunityBrowsePendingError && attempt < MAX_PENDING_RETRIES) {
            setNotice('Results are still being prepared. Retrying automatically…')
            setExpanded({}); setChildren({}); setChildOffsets({}); setGroupParentTokens({}); setOpenedGroups({})
            if (await waitForRetry(e.retryAfterMs, controller.signal)) continue
            return
          }
          if (e instanceof OpportunityCohortChangedError) {
            clearProjectBrowseCache()
            setPage(null); setPageKey(key)
            setExpanded({}); setChildren({}); setChildOffsets({}); setGroupParentTokens({}); setOpenedGroups({})
            parentReloadNotice.current = true
            setNotice('Results changed. Reloaded from the first page.')
            updateUrl(search, sector)
            setOffset(0)
            if (offset === 0) setRetryKey(value => value + 1)
          } else {
            clearProjectBrowseCache()
            parentReloadNotice.current = false
            setNotice('')
            setPage(null); setPageKey(key)
            setExpanded({}); setChildren({}); setChildOffsets({}); setGroupParentTokens({}); setOpenedGroups({})
            setError(e instanceof OpportunityBrowsePendingError ? PENDING_EXHAUSTED_MESSAGE : e instanceof Error && /session ended/i.test(e.message) ? e.message : 'Could not load accounts. Please try again.')
          }
          setLoading(false)
          return
        }
      }
    }
    void loadGroups()
    return () => controller.abort()
  }, [search, sector, offset, region, stage, priority, sort, shortlist, retryKey])
  useEffect(() => {
    if (!page || pageKey !== browseKey({ search, sector, offset, region, stage, priority, sort, shortlist })) return
    const route = { search, sector, offset, region, stage, priority, sort, shortlist }
    const version = projectBrowseCacheVersion()
    const save = () => writeProjectBrowseCache(browseKey(route), { savedAt: fetchedAt.current || Date.now(), page, expanded, children, childOffsets, groupParentTokens, openedGroups, scrollY: window.scrollY }, version)
    save()
    window.addEventListener('scroll', save, { passive: true })
    return () => { save(); window.removeEventListener('scroll', save) }
  }, [page, pageKey, search, sector, offset, region, stage, priority, sort, shortlist, expanded, children, childOffsets, groupParentTokens, openedGroups])
  useEffect(() => {
    if (!page || pageKey !== browseKey({ search, sector, offset, region, stage, priority, sort, shortlist }) || pendingScrollRestore.current == null) return
    const scrollY = pendingScrollRestore.current; pendingScrollRestore.current = null
    const frame = requestAnimationFrame(() => window.scrollTo(0, scrollY))
    return () => cancelAnimationFrame(frame)
  }, [page, pageKey, search, sector, offset, region, stage, priority, sort, shortlist])
  const updateUrl = (nextSearch: string, nextSector: string, nextOffset = 0, cohort?: string, nextRegion = region, nextStage = stage, nextPriority = priority, nextSort = sort, nextShortlist = shortlist) => {
    if (new URLSearchParams(location.search).has('panel')) return
    const next = new URLSearchParams({ view: 'workspace' }); if (new URLSearchParams(location.search).get('groupBrowse') === '1') next.set('groupBrowse', '1'); next.set('shortlist', nextShortlist ? '1' : '0'); if (nextSearch) next.set('q', nextSearch); if (nextSector !== 'all') next.set('sector', nextSector); if (nextOffset) next.set('offset', String(nextOffset)); if (cohort) next.set('cohort_token', cohort); if (nextRegion) next.set('region', nextRegion); if (nextStage) next.set('stage', nextStage); if (nextPriority) next.set('priority', nextPriority); if (nextSort !== 'priority') next.set('sort', nextSort)
    history.replaceState(history.state, '', `/?${next}`)
  }
  useEffect(() => {
    const params = new URLSearchParams(location.search)
    const rawOffset = params.get('offset'), rawSort = params.get('sort'), rawPriority = params.get('priority')
    const parsedOffset = Number(rawOffset ?? 0)
    let changed = false
    if (rawOffset !== null && (!Number.isSafeInteger(parsedOffset) || parsedOffset < 0)) { params.delete('offset'); changed = true }
    if (rawSort !== null && !['priority', 'priority_asc', 'company', 'updated'].includes(rawSort)) { params.delete('sort'); changed = true }
    if (rawPriority !== null && !['ranked', 'unranked'].includes(rawPriority)) { params.delete('priority'); changed = true }
    if (changed) history.replaceState(history.state, '', `/?${params}`)
  }, [])
  const setFilter = (q: string, s: 'all' | 'oil_gas' | 'data_centers', r = region, st = stage, p = priority, so = sort) => { parentReloadNotice.current = false; resetChildRequests(); if (selectedNeedId) onBrowseChange?.(); if (s !== sector) window.dispatchEvent(new CustomEvent('gl3-demand-sector-change', { detail: s })); setNotice(''); setSearchDraft(q); setSearch(q); setSector(s); setRegion(r); setStage(st); setPriority(p); setSort(so); setOffset(0); updateUrl(q, s, 0, undefined, r, st, p, so) }
  const requestedKey = browseKey({ search, sector, offset, region, stage, priority, sort, shortlist })
  const currentPage = pageKey === requestedKey && browsePageIsValid(page) ? page : null
  const previousPage = pageKey !== requestedKey && browsePageIsValid(page) ? page : null
  const searchDraftChanged = searchDraft !== search
  const requestedPageLoading = pageKey !== requestedKey || loading
  const busy = requestedPageLoading || searchDraftChanged
  const canUseChildren = pageKey === requestedKey && searchDraft === search && !loading && !error && !notice.toLowerCase().includes('still being prepared')
  const canInteract = !busy && !error && pageKey === requestedKey && searchDraft === search
  const groups = !searchDraftChanged ? currentPage?.items ?? [] : []
  const resultsStatus = busy
    ? notice || (searchDraftChanged ? 'Updating account search…' : currentPage ? 'Refreshing accounts…' : previousPage ? 'Refreshing accounts; previous results are hidden.' : 'Loading accounts…')
    : currentPage ? `${currentPage.total.toLocaleString()} ${currentPage.total === 1 ? 'account' : 'accounts'}` : error ? 'Accounts unavailable' : 'No accounts available'
  useEffect(() => {
    if (!currentPage?.valid_until) return
    const validUntil = Date.parse(currentPage.valid_until)
    if (!Number.isFinite(validUntil)) return
    const expire = () => {
      invalidateProjectBrowseCache({ search, sector, offset, region, stage, priority, sort })
      setPage(null); setExpanded({}); setChildren({}); setChildOffsets({}); setGroupParentTokens({}); setOpenedGroups({}); setLoading(true); setNotice('Refreshing expired results…'); setRetryKey(value => value + 1)
    }
    const delay = validUntil - Date.now()
    if (delay <= 0) { expire(); return }
    const timer = setTimeout(expire, delay)
    return () => clearTimeout(timer)
  }, [currentPage?.valid_until, pageKey, search, sector, offset, region, stage, priority, sort])
  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = []
    const expireGroups = (groupIds: string[]) => {
      const expired = new Set(groupIds)
      setChildren(current => { const next = { ...current }; for (const id of expired) next[id] = null; return next })
      setExpanded(current => { const next = { ...current }; for (const id of expired) if (!childLoading[id]) next[id] = false; return next })
      setChildOffsets(current => { const next = { ...current }; for (const id of expired) delete next[id]; return next })
      setGroupParentTokens(current => { const next = { ...current }; for (const id of expired) delete next[id]; return next })
      setOpenedGroups(current => { const next = { ...current }; for (const id of expired) delete next[id]; return next })
    }
    const expiredNow: string[] = []
    for (const [groupId, childPage] of Object.entries(children)) {
      if (!childPage || childPage.valid_until === undefined) continue
      const validUntil = Date.parse(childPage.valid_until)
      if (!Number.isFinite(validUntil) || validUntil <= Date.now()) expiredNow.push(groupId)
      else timers.push(setTimeout(() => expireGroups([groupId]), validUntil - Date.now()))
    }
    if (expiredNow.length) expireGroups(expiredNow)
    return () => timers.forEach(clearTimeout)
  }, [children, childLoading])
  const loadGroupProjects = (group: OpportunityGroup, childOffset: number, cohortToken?: string) => {
    const requestSearch = search
    const requestSector = sector
    const requestRegion = region
    const requestStage = stage
    const requestPriority = priority
    const requestSort = sort
    const requestShortlist = shortlist
    const requestPage = page
    const requestOffset = offset
    setChildLoading(current => ({ ...current, [group.id]: true })); setChildErrors(current => ({ ...current, [group.id]: '' })); setChildNotices(current => ({ ...current, [group.id]: '' }))
    childRequests.current.get(group.id)?.abort()
    const controller = new AbortController(); childRequests.current.set(group.id, controller)
    const epoch = childEpoch.current
    const requestIsCurrent = () => !controller.signal.aborted && epoch === childEpoch.current && requestSearch === search && requestSector === sector && requestOffset === offset && requestRegion === region && requestStage === stage && requestPriority === priority && requestSort === sort && requestShortlist === shortlist
    const openFreshGroup = async (firstRetryDelayMs = 0) => {
      let retryDelayMs = firstRetryDelayMs
      for (let attempt = 0; attempt <= MAX_PENDING_RETRIES; attempt += 1) {
        if (retryDelayMs > 0 && !(await waitForRetry(retryDelayMs, controller.signal))) return
        if (!requestIsCurrent()) return
        try {
          const opened = await client.openOpportunityGroup(group.id, { search: requestSearch, sector: requestSector, limit: 25, sort, region, stage, priority, shortlist }, controller.signal)
          if (!requestIsCurrent()) return
          if (opened.group.id !== group.id) throw new Error('The refreshed operator/customer group did not match the requested group.')
          setOpenedGroups(current => ({ ...current, [group.id]: opened.group }))
          setChildren(current => ({ ...current, [group.id]: opened.projects }))
          setChildOffsets(current => ({ ...current, [group.id]: 0 }))
          setGroupParentTokens(current => ({ ...current, [group.id]: opened.parent_cohort_token }))
          setChildLoading(current => ({ ...current, [group.id]: false }))
          setChildErrors(current => ({ ...current, [group.id]: '' }))
          setChildNotices(current => ({ ...current, [group.id]: '' }))
          return
        } catch (refreshError) {
          if (!requestIsCurrent()) return
          if (refreshError instanceof OpportunityBrowsePendingError && attempt < MAX_PENDING_RETRIES) {
            retryDelayMs = refreshError.retryAfterMs
            setChildNotices(current => ({ ...current, [group.id]: 'Project results are still being prepared. Retrying this group automatically…' }))
            continue
          }
          if (refreshError instanceof OpportunityGroupUnavailableError) {
            setExpanded(current => ({ ...current, [group.id]: false }))
            setChildren(current => ({ ...current, [group.id]: null }))
            setChildOffsets(current => ({ ...current, [group.id]: 0 }))
            setGroupParentTokens(current => { const next = { ...current }; delete next[group.id]; return next })
            setOpenedGroups(current => { const next = { ...current }; delete next[group.id]; return next })
            setNotice(refreshError.message)
          }
          setChildNotices(current => ({ ...current, [group.id]: '' }))
          setChildErrors(current => ({ ...current, [group.id]: refreshError instanceof OpportunityBrowsePendingError ? PENDING_EXHAUSTED_MESSAGE : refreshError instanceof Error ? refreshError.message : 'Could not load projects.' }))
          setChildLoading(current => ({ ...current, [group.id]: false }))
          return
        }
      }
    }
    const wasPagination = childOffset > 0 || Boolean(cohortToken)
    const recoverGroup = (retryDelayMs = 0) => {
      setChildren(current => ({ ...current, [group.id]: null }))
      setChildOffsets(current => ({ ...current, [group.id]: 0 }))
      if (retryDelayMs > 0) setChildNotices(current => ({ ...current, [group.id]: 'Project results are still being prepared. Retrying this group automatically…' }))
      else if (wasPagination) setNotice('Project results changed. Reloaded this operator/customer group.')
      void openFreshGroup(retryDelayMs)
    }
    client.groupProjects(group.id, { search: requestSearch, sector: requestSector, limit: 25, offset: childOffset, cohort_token: cohortToken, parent_cohort_token: groupParentTokens[group.id] ?? requestPage?.cohort_token, sort, region, stage, priority, shortlist }, controller.signal).then(value => {
      if (!requestIsCurrent()) return
      setChildren(current => ({ ...current, [group.id]: value })); setChildOffsets(current => ({ ...current, [group.id]: childOffset })); setChildLoading(current => ({ ...current, [group.id]: false }))
    }).catch((e: Error) => {
      if (!requestIsCurrent()) return
      if (e instanceof OpportunityCohortChangedError) {
        recoverGroup()
      } else if (e instanceof OpportunityBrowsePendingError) {
        recoverGroup(e.retryAfterMs)
      } else {
        setChildNotices(current => ({ ...current, [group.id]: '' }))
        setChildErrors(current => ({ ...current, [group.id]: e.message }))
        setChildLoading(current => ({ ...current, [group.id]: false }))
      }
    })
  }
  const openAccount = (id: string, matchedProjectId?: string | null, matchedNeedId?: string | null) => { const params = new URLSearchParams(location.search); params.set('view', 'workspace'); params.set('groupBrowse', '1'); params.set('account', id); if (matchedProjectId) params.set('project', matchedProjectId); else params.delete('project'); if (matchedNeedId) params.set('matchedNeed', matchedNeedId); else params.delete('matchedNeed'); params.delete('need'); params.delete('section'); history.pushState({ ...history.state, accountOpened: true }, '', `/?${params}`); setAccountId(id); window.scrollTo(0, 0) }
  const closeAccount = () => { if (history.state?.accountOpened) { history.back(); return } const params = new URLSearchParams(location.search); params.delete('account'); history.pushState(history.state, '', `/?${params}`); setAccountId('') }
  if (accountId) { const params = new URLSearchParams(location.search); const selectedAccount = currentPage?.items.find(group => group.id === accountId); return <CompanyView groupId={accountId} summary={selectedAccount} onBack={closeAccount} onNeed={(id, projectId) => onNeed({ id }, { accountId, projectId })} backLabel="Back to accounts" shortlist={shortlist} search={search} sector={sector} region={region} stage={stage} priority={priority} sort={sort} matchedProjectId={params.get('project')} matchedNeedId={params.get('matchedNeed')} accountContextStatus={params.has('need') ? accountContextStatus : 'valid'} /> }
  return <section className="project-results" aria-label="Project opportunities" aria-busy={busy}>
    <header className="project-results-header"><div className="project-results-title"><h1>Customers</h1><button type="button" aria-label="Refresh customer accounts" disabled={loading} onClick={() => { window.dispatchEvent(new Event('gl3-demand-refresh')); setRetryKey(value => value + 1) }}>Refresh</button></div>
      <label><span className="project-search-label">Search accounts and projects</span><input aria-label="Search accounts and projects" placeholder="Account, project or location" value={searchDraft} onChange={e => { setSearchDraft(e.target.value); updateUrl(e.target.value, sector) }}/></label>
    </header>
    <nav className="project-sector-tabs" aria-label="Project type">{([['all','All'],['oil_gas','Oil & Gas'],['data_centers','Data Centers']] as const).map(([value,label]) => <button key={value} type="button" aria-pressed={sector === value} onClick={() => setFilter(searchDraft, value, '', '', priority)}>{label}</button>)}</nav>
    <nav className="project-sector-tabs" aria-label="Opportunity scope"><button type="button" aria-pressed={shortlist} onClick={() => { clearProjectBrowseCache(); setShortlist(true); setOffset(0); resetChildRequests(); updateUrl(search, sector, 0, undefined, region, stage, priority, sort, true) }}>Shortlist</button><button type="button" aria-pressed={!shortlist} onClick={() => { clearProjectBrowseCache(); setShortlist(false); setOffset(0); resetChildRequests(); updateUrl(search, sector, 0, undefined, region, stage, priority, sort, false) }}>All Projects</button></nav>
    <button type="button" disabled={!currentPage || busy || error !== '' || !groups.some(group => group.featured_project)} onClick={() => downloadProjectPage(groups.flatMap(group => group.featured_project ? [{ ...group.featured_project, company: group.name }] : []), undefined, 'Current account page — featured project per account')}>Export featured projects on this page</button>
    <details className="customer-rollup-controls"><summary>More filters and sorting</summary><div>
      <label>Region<select aria-label="Region" value={region} onChange={event => setFilter(searchDraft, sector, event.target.value)}><option value="">All regions</option>{region && !((currentPage ?? previousPage)?.facets?.regions ?? []).includes(region) && <option value={region}>{region}</option>}{((currentPage ?? previousPage)?.facets?.regions ?? []).map(value => <option key={value} value={value}>{value}</option>)}</select></label>
      <label>Stage<select aria-label="Stage" value={stage} onChange={event => setFilter(searchDraft, sector, region, event.target.value)}><option value="">All stages</option>{stage && !((currentPage ?? previousPage)?.facets?.stages ?? []).includes(stage) && <option value={stage}>{stage}</option>}{((currentPage ?? previousPage)?.facets?.stages ?? []).map(value => <option key={value} value={value}>{value}</option>)}</select></label>
      <label>Priority<select aria-label="Priority" value={priority} onChange={event => setFilter(searchDraft, sector, region, stage, event.target.value as CustomerRollupFilters['priority'])}><option value="">All priorities</option><option value="ranked">Ranked</option><option value="unranked">Unranked</option></select></label>
      <label>Sort opportunities<select aria-label="Sort opportunities" value={sort} onChange={event => setFilter(searchDraft, sector, region, stage, priority, event.target.value as CustomerRollupSort)}><option value="company">Company</option><option value="priority">Priority</option><option value="priority_asc">Priority (ascending)</option><option value="updated">Recently updated</option></select></label>
    </div></details>
    <div className="project-results-count" aria-live="polite" role={busy ? 'status' : undefined}>{resultsStatus}</div>
    {!busy && notice && <p role="status" className="project-results-notice">{notice}</p>}
    {error && pageKey === requestedKey && <p role="alert">{error} <button onClick={() => setRetryKey(value => value + 1)}>Retry</button></p>}
    {!busy && !error && currentPage && !groups.length && <p className="project-empty">{search ? 'No accounts match this search.' : 'No accounts are available in this scope.'}</p>}
    {!error && currentPage && !searchDraftChanged && <div className="customer-group-list">{groups.map(group => { const childPageCurrent = !children[group.id] || browsePageIsValid(children[group.id]); const displayedGroup = canUseChildren && childPageCurrent ? openedGroups[group.id] ?? group : group; const unconfirmedNameGroup = displayedGroup.group_kind === 'same_name_unconfirmed'; const featuredProject = displayedGroup.featured_project ?? null; const accountContactProject = displayedGroup.group_kind === 'resolved_identity' ? selectAccountContactProject(displayedGroup, featuredProject) : featuredProject; return <section key={displayedGroup.id} className="customer-group" aria-label={`${displayedGroup.name} ${unconfirmedNameGroup ? 'name group' : 'customer group'}`}>
      <h2 className="customer-group-heading"><button className="customer-group-toggle" type="button" disabled={!canInteract} aria-expanded={false} onClick={() => openAccount(group.id, group.matched_project_id, group.matched_need_id)}>
        <span><strong className="customer-group-name">{displayedGroup.name}</strong>{unconfirmedNameGroup ? <><small className="customer-group-kind">Name group</small><small>Same source-reported name; company identities are not linked.</small>{displayedGroup.identity_count !== undefined && <small>{displayedGroup.identity_count} separate company identities</small>}</> : <><small>{displayedGroup.featured_project?.location || displayedGroup.sectors.length ? [displayedGroup.featured_project?.location, ...displayedGroup.sectors.map(value => value === 'oil_gas' ? 'Oil & Gas' : value === 'data_centers' ? 'Data Centers' : value.replaceAll('_', ' '))].filter(Boolean).join(' · ') : displayedGroup.role === 'operator' ? 'Operator' : displayedGroup.role === 'customer' ? 'Customer' : 'Operator/customer unresolved'}</small>{displayedGroup.role === 'unresolved' && <small>Operator/customer unresolved</small>}</>}</span>
        <span className="customer-group-count">{displayedGroup.project_count} {displayedGroup.project_count === 1 ? 'project' : 'projects'}</span>
        <svg className="customer-group-chevron" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m9 18 6-6-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
      </button></h2>
      <div className="customer-group-featured"><CustomerIntelSummary group={displayedGroup}/>{displayedGroup.featured_project && <><p>{displayedGroup.featured_project.name}</p>{displayedGroup.featured_project.commercial_brief ? <CommercialBriefSummary project={displayedGroup.featured_project}/> : <>{displayedGroup.featured_project.event?.date && <small>Evidence event · {displayedGroup.featured_project.event.date}</small>}{displayedGroup.featured_project.shortlist_assessment?.why_now && <p>{displayedGroup.featured_project.shortlist_assessment.why_now}</p>}{displayedGroup.featured_project.shortlist_assessment?.next_step && <p>{displayedGroup.featured_project.shortlist_assessment.next_step}</p>}<FeaturedContact project={displayedGroup.featured_project} contactProject={accountContactProject}/></>}{group.pursued_eligible_need_count != null && group.eligible_need_count != null && group.pursued_eligible_need_count > 0 && <small>{group.pursued_eligible_need_count === group.eligible_need_count ? `All ${group.eligible_need_count} opportunities in Pursuits` : `${group.pursued_eligible_need_count} of ${group.eligible_need_count} opportunities in Pursuits`}</small>}{group.eligible_need_count === 1 && displayedGroup.featured_project.representative_need_id && <AddToPursuit key={displayedGroup.featured_project.representative_need_id} needId={displayedGroup.featured_project.representative_need_id} deferLookup>for {displayedGroup.featured_project.name}</AddToPursuit>}{projectSpecificMatch(group, search) && <button type="button" onClick={() => openAccount(group.id, group.matched_project_id, group.matched_need_id)}>View account with matching opportunity</button>}<button type="button" onClick={() => openAccount(group.id, projectSpecificMatch(group, search) ? group.matched_project_id : null, projectSpecificMatch(group, search) ? group.matched_need_id : null)}>{(group.eligible_need_count ?? 0) > 1 ? `Choose opportunity` : `View account details`}</button></>}</div>
      {canUseChildren && childPageCurrent && expanded[group.id] && <div className="customer-group-projects">
        {childNotices[group.id] && <p role="status" className="project-results-notice">{childNotices[group.id]}</p>}
        {childErrors[group.id] && <p role="alert">{childErrors[group.id]} <button type="button" onClick={() => loadGroupProjects(group, 0)}>Reload projects</button></p>}
        {childLoading[group.id] && <p role="status">Loading projects…</p>}
        {!childLoading[group.id] && !childErrors[group.id] && children[group.id] && <>
          <div className="project-card-list">{children[group.id]!.items.map(project => <ProjectCard key={project.id} project={project} selectedNeedId={selectedNeedId} onNeed={onNeed} nested/>)}</div>
          {children[group.id]!.total > children[group.id]!.limit && <footer className="project-paging"><span>{(childOffsets[group.id] ?? 0) + 1}–{(childOffsets[group.id] ?? 0) + children[group.id]!.items.length} of {children[group.id]!.total} projects</span><button disabled={childLoading[group.id] || (childOffsets[group.id] ?? 0) === 0} onClick={() => loadGroupProjects(group, Math.max(0, (childOffsets[group.id] ?? 0) - 25), children[group.id]?.cohort_token)}>Previous</button><button disabled={childLoading[group.id] || (childOffsets[group.id] ?? 0) + children[group.id]!.items.length >= children[group.id]!.total} onClick={() => loadGroupProjects(group, (childOffsets[group.id] ?? 0) + 25, children[group.id]?.cohort_token)}>Next</button></footer>}
        </>}
      </div>}
    </section>})}</div>}
    {currentPage && currentPage.total > currentPage.limit && <footer className="project-paging"><span>{!busy && !error ? `${currentPage.offset + (groups.length ? 1 : 0)}–${currentPage.offset + groups.length} of ${currentPage.total} accounts` : ''}</span><button disabled={!canInteract || currentPage.offset === 0} onClick={() => { const n = Math.max(0, currentPage.offset - 25); setOffset(n); updateUrl(search, sector, n, currentPage.cohort_token) }}>Previous</button><button disabled={!canInteract || currentPage.offset + groups.length >= currentPage.total} onClick={() => { const n = currentPage.offset + 25; setOffset(n); updateUrl(search, sector, n, currentPage.cohort_token) }}>Next</button></footer>}
  </section>
}
function ProjectCard({ project, selectedNeedId, onNeed, nested = false }: { project: ProjectResult; selectedNeedId?: string; onNeed: Props['onNeed']; nested?: boolean }) {
  const primary = project.representative_need_id ?? project.needs[0]?.id
  const contacts = project.contact.filter(contact => /^(tel:|mailto:)/i.test(contact.href ?? ''))
  const displayName = project.company && project.name.startsWith(`${project.company} · `) ? project.name.slice(project.company.length + 3) : project.name
  const assessment = project.shortlist_assessment
  const eventUrl = /^https?:\/\//i.test(project.event?.source ?? '') ? project.event?.source : null
  return <article className="project-card" aria-current={selectedNeedId && project.needs.some(need => need.id === selectedNeedId) ? 'true' : undefined}>
    <div className="project-card-top"><span>{project.asset_type?.replaceAll('_', ' ') ?? 'Project'}</span>{project.sector && <span>{project.sector === 'oil_gas' ? 'Oil & Gas' : 'Data Centers'}</span>}</div>
    {nested ? <h3>{displayName}</h3> : <h2>{displayName}</h2>}{(project.company || project.location) && <p className="project-company">{[project.company, project.location].filter(Boolean).join(' · ')}</p>}
    {project.commercial_brief ? <CommercialBriefSummary project={project}/> : <>
      {assessment?.why_now && <p className="project-next">{assessment.why_now}</p>}
      {assessment?.next_step && <p>{assessment.next_step}</p>}
    </>}
    <div className="project-card-actions">{project.commercial_brief ? null : contacts.map((contact, index) => <a key={`${contact.kind}-${contact.href}-${index}`} href={contact.href!}>{contact.label}</a>)}{!project.commercial_brief && contacts.length === 0 && <span>Contact method not verified</span>}{primary && <><button type="button" onClick={() => onNeed({ id: primary })}>Project details</button><AddToPursuit key={primary} needId={primary} deferLookup/></>}</div>
    {project.need_count > 1 && <details className="project-needs"><summary>Related power needs ({project.need_count})</summary><ul>{project.needs.map(need => <li key={need.id}><button type="button" onClick={() => onNeed({ id: need.id })}>{String(need.activity ?? need.browse_title ?? 'Related project detail')}{need.location ? ` · ${String(need.location)}` : ''}</button></li>)}</ul></details>}
    {(assessment?.evidence_refs.length || eventUrl) ? <details className="project-needs"><summary>Sources</summary>{eventUrl && <p><a href={eventUrl} target="_blank" rel="noreferrer">{project.event?.label ?? 'Open source'}</a></p>}{assessment?.evidence_refs.length && <><p>Supporting evidence is available in project detail.</p>{primary && <button type="button" onClick={() => onNeed({ id: primary })}>Open project evidence</button>}</>}</details> : null}
  </article>
}

function FeaturedContact({ project, contactProject }: { project: ProjectResult; contactProject: ProjectResult | null }) {
  if (!contactProject) return null
  const contacts = bestProjectContactRoutes(contactProject.contact)
  const general = generalCompanyContactRoutes(contactProject.contact, contacts)
  const people = verifiedContactPeople(contactProject)
  if (!contacts.length && !general.length) return <div className="customer-group-contact" aria-label="Best contact"><strong>Best contact</strong>{people.length ? <>{people.map((person, index) => <span key={`${person.person_identity_id ?? person.name}:${index}`}><strong>{person.name}</strong>{person.title && ` · ${person.title}`}{person.role && ` · ${person.role}`}<small>Verified {person.responsibility?.replace('Verified ', '').toLowerCase()} · Professional contact details unavailable.</small>{safeContactSourceUrl(person.source_url) && <a href={safeContactSourceUrl(person.source_url)!} target="_blank" rel="noreferrer">Contact source</a>}</span>)}<small>Research a permitted business route before outreach.</small></> : <small>No verified business contact is currently available. Contact research is needed.</small>}</div>
  const best = contacts[0]?.contact ?? general[0].contact
  const companyLine = best.route_kind === 'company_route'
  const contactSource = safeContactSourceUrl(best.source_url)
  return <div className="customer-group-contact">{contactProject.project_id !== project.project_id && <small>Contact associated with {contactProject.name}</small>}<strong>{best.name ?? best.company ?? 'Business contact'}</strong>{best.title && <span> · {best.title}</span>}{best.responsibility && <small>{best.responsibility}. Authority needs confirmation.</small>}{companyLine && <span> · General company route</span>}{contacts.length > 0 && <span>{contacts.map(({ contact, href }) => <a key={`${contact.kind}:${href}`} href={href}>{/^mailto:/i.test(href) ? 'Email' : 'Call'} {contact.name ?? (contact.route_kind === 'company_route' ? 'company' : 'contact')}</a>)}</span>}{general.length > 0 && <span>General company route · {general.map(({ contact, href }) => <a key={`general:${contact.kind}:${href}`} href={href}>{/^mailto:/i.test(href) ? 'Email' : 'Call'} company</a>)}</span>}{contactSource && <details><summary>Contact source</summary><a href={contactSource} target="_blank" rel="noreferrer">Open source</a></details>}</div>
}

function CommercialBriefSummary({ project }: { project: ProjectResult }) {
  const brief = project.commercial_brief
  if (!brief) return null
  const representativeNeeds = project.needs.filter(need => need.id === project.representative_need_id)
  const representativeNeedBrief = representativeNeeds.length === 1 ? representativeNeeds[0].commercial_brief : null
  const contactCandidate = brief.best_contact ?? representativeNeedBrief?.best_contact ?? null
  const contactHref = contactCandidate?.href ? safeBriefHref(contactCandidate.kind, contactCandidate.href) : null
  const best = contactHref ? contactCandidate : null
  const powerLimitations = meaningfulPowerLimitations(brief.power_need.limitations)
  const hasDocumentedAmount = brief.power_need.amount_class !== 'unknown' && Boolean(brief.power_need.value)
  const hasUsefulUnknownScope = !hasDocumentedAmount && Boolean(brief.power_need.scope?.trim()) && powerLimitations.length > 0
  const showPowerNeed = hasDocumentedAmount || hasUsefulUnknownScope
  const powerText = hasDocumentedAmount
    ? `${briefPowerAmount(brief.power_need.value!, brief.power_need.unit)}${brief.power_need.scope ? ` · ${brief.power_need.scope}` : ''}`
    : brief.power_need.scope ?? ''
  const whySources = brief.why_now.sources ?? []
  const sourceRows = new Map<string, { title: string; url: string; date: string | null }>()
  for (const source of [...brief.sources, ...whySources, ...(brief.next_action.source ? [brief.next_action.source] : []), ...(best?.sources ?? [])]) {
    const url = safeContactSourceUrl(source.url)
    const title = source.title?.trim()
    if (!url || !title) continue
    sourceRows.set(`${url}:${source.evidence_id ?? source.date ?? title}`, { title, url, date: source.date })
  }
  return <div className="customer-commercial-brief">
    <div className="customer-brief-claim"><strong>Why now</strong><p>{brief.why_now.text ?? 'Why now is not established from current evidence.'}</p></div>
    {showPowerNeed && <div className="customer-brief-claim"><strong>Power need</strong><p>{powerText}</p>{hasDocumentedAmount && <small>{humanizeBriefStatus(brief.power_need.amount_class)}</small>}{powerLimitations.map((limitation, index) => <small key={`${index}:${limitation}`}>{limitation}</small>)}</div>}
    {best && <div className="customer-group-contact" role="group" aria-label="Best contact"><strong>Best contact</strong>{contactHref && <a href={contactHref} target={best.kind === 'contact' ? '_blank' : undefined} rel={best.kind === 'contact' ? 'noreferrer' : undefined}>{best.kind === 'call' ? 'Call' : best.kind === 'email' ? 'Email' : 'Contact'} {best.contact}</a>}</div>}
    <div className="customer-brief-claim"><strong>Next action</strong><p>{brief.next_action.text}</p></div>
    <details className="customer-brief-sources"><summary>Sources</summary>{best?.authority && <p>Contact authority: {best.authority}</p>}{best?.deliverability && <p>Contact deliverability: {best.deliverability}</p>}{sourceRows.size ? [...sourceRows.values()].map(source => <p key={`${source.url}:${source.title}`}><a href={source.url} target="_blank" rel="noreferrer">{source.title}</a>{source.date ? ` · ${source.date}` : ''}</p>) : <p>No current source citations are available.</p>}</details>
  </div>
}

function meaningfulPowerLimitations(values: string[]): string[] {
  return values.flatMap(value => value.split(/;\s*/).map(part => part.trim()).filter(part => part && !/^(?:(?:activity-specific )?(?:power )?(?:need|amount)(?: for [^.]*)? is unknown\.?|unknown is not zero\.?|unknown does not mean zero\.?)$/i.test(part)))
}

function safeBriefHref(kind: string, value: string): string | null {
  const href = value.trim()
  if (kind === 'call' && /^tel:\+?[0-9]{7,15}$/i.test(href)) return href
  if (kind === 'email' && href.toLowerCase().startsWith('mailto:') && /^[A-Za-z0-9._+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,63}$/.test(href.slice(7))) return `mailto:${href.slice(7)}`
  if (kind === 'contact') return safeContactSourceUrl(href)
  return null
}

function briefPowerAmount(value: string, unit: string | null): string {
  const amount = value.trim()
  return unit && !new RegExp(`\\b${unit}\\s*$`, 'i').test(amount) ? `${amount} ${unit}` : amount
}

function humanizeBriefStatus(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b[a-z]/g, character => character.toUpperCase())
}
