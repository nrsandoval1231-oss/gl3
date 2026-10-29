import { useEffect, useRef, useState } from 'react'
import { client, OpportunityBrowsePendingError, OpportunityCohortChangedError, OpportunityGroupUnavailableError, type OpportunityGroup, type OpportunityGroupsPage, type ProjectResult, type ProjectResultsPage } from '../../api/client'
import { clearProjectBrowseCache, invalidateProjectBrowseCache, projectBrowseCacheKey, projectBrowseCacheVersion, readProjectBrowseCache, writeProjectBrowseCache, type ProjectBrowseRoute } from '../../state/projectBrowseCache'

type Props = { selectedNeedId?: string; onNeed: (need: { id: string }) => void; onBrowseChange?: () => void }
const MAX_PENDING_RETRIES = 3
const PENDING_EXHAUSTED_MESSAGE = 'Results are still being prepared. Please try again shortly.'
const SEARCH_DEBOUNCE_MS = 300
const browseKey = (route: ProjectBrowseRoute) => projectBrowseCacheKey(route)
function pageKeyContext(key: string): string {
  try {
    const [search, sector, offset] = JSON.parse(key) as [string, ProjectBrowseRoute['sector'], number]
    const sectorName = sector === 'oil_gas' ? 'Oil & Gas' : sector === 'data_centers' ? 'Data Centers' : 'All'
    return `${sectorName}${search ? ` search “${search}”` : ''}, groups ${offset + 1}–${offset + 25}`
  } catch { return 'the previous browse context' }
}

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

export function ProjectResults({ selectedNeedId, onNeed, onBrowseChange }: Props) {
  const readRoute = () => { const route = new URLSearchParams(location.search); return { search: route.get('q') ?? '', sector: (route.get('sector') === 'oil_gas' || route.get('sector') === 'data_centers' ? route.get('sector') : 'all') as 'all' | 'oil_gas' | 'data_centers', offset: Number(route.get('offset') ?? 0) } }
  const [initialRoute] = useState(readRoute)
  const [initialCache] = useState(() => readProjectBrowseCache(initialRoute))
  const [search, setSearch] = useState(initialRoute.search)
  const [searchDraft, setSearchDraft] = useState(initialRoute.search)
  const [sector, setSector] = useState(initialRoute.sector)
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
    const onPop = () => { parentReloadNotice.current = false; const route = readRoute(); setSearch(route.search); setSearchDraft(route.search); setSector(route.sector); setOffset(route.offset) }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
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
    const key = browseKey({ search, sector, offset })
    const cached = readProjectBrowseCache({ search, sector, offset })
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
          const value = await client.opportunityGroups({ search, sector, limit: 25, offset, cohort_token: cohort, sort: 'priority' }, controller.signal)
          if (controller.signal.aborted) return
          const previousCohort = pageKey === key ? page?.cohort_token : cached?.page.cohort_token
          const cohortChanged = Boolean(previousCohort && previousCohort !== value.cohort_token)
          setPage(value); setPageKey(key); fetchedAt.current = Date.now(); setLoading(false)
          if (cohortChanged) { setExpanded({}); setChildren({}); setChildOffsets({}); setGroupParentTokens({}); setOpenedGroups({}) }
          if (parentReloadNotice.current) {
            parentReloadNotice.current = false
            setNotice('Results changed. Reloaded from the first page.')
          } else setNotice('')
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
            setError(e instanceof OpportunityBrowsePendingError ? PENDING_EXHAUSTED_MESSAGE : e instanceof Error ? e.message : 'Could not load operator/customer groups.')
          }
          setLoading(false)
          return
        }
      }
    }
    void loadGroups()
    return () => controller.abort()
  }, [search, sector, offset, retryKey])
  useEffect(() => {
    if (!page || pageKey !== browseKey({ search, sector, offset })) return
    const route = { search, sector, offset }
    const version = projectBrowseCacheVersion()
    const save = () => writeProjectBrowseCache(browseKey(route), { savedAt: fetchedAt.current || Date.now(), page, expanded, children, childOffsets, groupParentTokens, openedGroups, scrollY: window.scrollY }, version)
    save()
    window.addEventListener('scroll', save, { passive: true })
    return () => { save(); window.removeEventListener('scroll', save) }
  }, [page, pageKey, search, sector, offset, expanded, children, childOffsets, groupParentTokens, openedGroups])
  useEffect(() => {
    if (!page || pageKey !== browseKey({ search, sector, offset }) || pendingScrollRestore.current == null) return
    const scrollY = pendingScrollRestore.current; pendingScrollRestore.current = null
    const frame = requestAnimationFrame(() => window.scrollTo(0, scrollY))
    return () => cancelAnimationFrame(frame)
  }, [page, pageKey, search, sector, offset])
  const updateUrl = (nextSearch: string, nextSector: string, nextOffset = 0, cohort?: string) => {
    const next = new URLSearchParams({ view: 'workspace' }); if (new URLSearchParams(location.search).get('groupBrowse') === '1') next.set('groupBrowse', '1'); if (nextSearch) next.set('q', nextSearch); if (nextSector !== 'all') next.set('sector', nextSector); if (nextOffset) next.set('offset', String(nextOffset)); if (cohort) next.set('cohort_token', cohort)
    history.replaceState(history.state, '', `/?${next}`)
  }
  const setFilter = (q: string, s: 'all' | 'oil_gas' | 'data_centers') => { parentReloadNotice.current = false; resetChildRequests(); if (selectedNeedId) onBrowseChange?.(); setNotice(''); setSearchDraft(q); setSearch(q); setSector(s); setOffset(0); updateUrl(q, s) }
  const requestedKey = browseKey({ search, sector, offset })
  const currentPage = pageKey === requestedKey && browsePageIsValid(page) ? page : null
  const previousPage = pageKey !== requestedKey && browsePageIsValid(page) ? page : null
  const busy = loading || searchDraft !== search
  const canUseChildren = pageKey === requestedKey && searchDraft === search && !loading && !error && !notice.toLowerCase().includes('still being prepared')
  const canInteract = !busy && !error && pageKey === requestedKey && searchDraft === search
  const groups = (currentPage ?? previousPage)?.items ?? []
  useEffect(() => {
    if (!currentPage?.valid_until) return
    const validUntil = Date.parse(currentPage.valid_until)
    if (!Number.isFinite(validUntil)) return
    const expire = () => {
      invalidateProjectBrowseCache({ search, sector, offset })
      setPage(null); setExpanded({}); setChildren({}); setChildOffsets({}); setGroupParentTokens({}); setOpenedGroups({}); setLoading(true); setNotice('Refreshing expired results…'); setRetryKey(value => value + 1)
    }
    const delay = validUntil - Date.now()
    if (delay <= 0) { expire(); return }
    const timer = setTimeout(expire, delay)
    return () => clearTimeout(timer)
  }, [currentPage?.valid_until, pageKey, search, sector, offset])
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
  const toggleGroup = (group: OpportunityGroup) => {
    if (expanded[group.id]) {
      childRequests.current.get(group.id)?.abort(); childRequests.current.delete(group.id)
      setExpanded(current => ({ ...current, [group.id]: false }))
      setChildLoading(current => ({ ...current, [group.id]: false }))
      setChildNotices(current => { const next = { ...current }; delete next[group.id]; return next })
      setChildren(current => ({ ...current, [group.id]: null }))
      setChildOffsets(current => ({ ...current, [group.id]: 0 }))
      setGroupParentTokens(current => { const next = { ...current }; delete next[group.id]; return next })
      setOpenedGroups(current => { const next = { ...current }; delete next[group.id]; return next })
      return
    }
    setExpanded(current => ({ ...current, [group.id]: true }))
    if (children[group.id] || childLoading[group.id]) return
    loadGroupProjects(group, 0)
  }
  const loadGroupProjects = (group: OpportunityGroup, childOffset: number, cohortToken?: string) => {
    const requestSearch = search
    const requestSector = sector
    const requestPage = page
    const requestOffset = offset
    setChildLoading(current => ({ ...current, [group.id]: true })); setChildErrors(current => ({ ...current, [group.id]: '' })); setChildNotices(current => ({ ...current, [group.id]: '' }))
    childRequests.current.get(group.id)?.abort()
    const controller = new AbortController(); childRequests.current.set(group.id, controller)
    const epoch = childEpoch.current
    const requestIsCurrent = () => !controller.signal.aborted && epoch === childEpoch.current && requestSearch === search && requestSector === sector && requestOffset === offset
    const openFreshGroup = async (firstRetryDelayMs = 0) => {
      let retryDelayMs = firstRetryDelayMs
      for (let attempt = 0; attempt <= MAX_PENDING_RETRIES; attempt += 1) {
        if (retryDelayMs > 0 && !(await waitForRetry(retryDelayMs, controller.signal))) return
        if (!requestIsCurrent()) return
        try {
          const opened = await client.openOpportunityGroup(group.id, { search: requestSearch, sector: requestSector, limit: 25, sort: 'priority' }, controller.signal)
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
    client.groupProjects(group.id, { search: requestSearch, sector: requestSector, limit: 25, offset: childOffset, cohort_token: cohortToken, parent_cohort_token: groupParentTokens[group.id] ?? requestPage?.cohort_token, sort: 'priority' }, controller.signal).then(value => {
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
  const previousContext = previousPage ? `Showing prior operator/customer summaries for ${pageKeyContext(pageKey)} while the requested view loads. Expansion and project details are paused.${notice.toLowerCase().includes('still being prepared') ? ' The current cohort is still being prepared.' : ''}` : ''
  return <section className="project-results" aria-label="Project opportunities" aria-busy={busy}>
    <header className="project-results-header"><div className="project-results-title"><h1>Search opportunities</h1><button type="button" aria-label="Refresh project results" disabled={loading} onClick={() => setRetryKey(value => value + 1)}>Refresh</button></div>
      <label><span className="project-search-label">Search opportunities</span><input aria-label="Search opportunities" placeholder="Project, operator, well or location" value={searchDraft} onChange={e => { setSearchDraft(e.target.value); updateUrl(e.target.value, sector) }}/></label>
    </header>
    <nav className="project-sector-tabs" aria-label="Project type">{([['all','All'],['oil_gas','Oil & Gas'],['data_centers','Data Centers']] as const).map(([value,label]) => <button key={value} type="button" aria-pressed={sector === value} onClick={() => setFilter(searchDraft, value)}>{label}</button>)}</nav>
    <div className="project-results-count" aria-live="polite" role={busy ? 'status' : undefined}>{busy ? searchDraft !== search && currentPage ? `Updating search. Previous results for ${pageKeyContext(pageKey)} are still shown while this search settles; expansion and details are paused.` : currentPage ? `${notice && !notice.toLowerCase().includes('still being prepared') ? `${notice} ` : ''}Updating results. ${currentPage.as_of ? `Showing results last prepared ${new Date(currentPage.as_of).toLocaleString()}; qualification may have changed.` : 'Showing previously loaded results while the current cohort is checked.'}` : previousContext || (notice && !notice.toLowerCase().includes('still being prepared') ? `${notice} Loading operator/customer groups…` : page && !browsePageIsValid(page) ? 'Refreshing expired results; the previous generation is no longer shown.' : searchDraft !== search ? 'Updating search…' : notice.toLowerCase().includes('still being prepared') ? 'Results are still being prepared. Retrying automatically…' : 'Loading operator/customer groups…') : currentPage ? `${currentPage.total} operator/customer ${currentPage.total === 1 ? 'group' : 'groups'}` : error ? 'Operator/customer groups unavailable' : 'No operator/customer groups'}</div>
    {!busy && notice && <p role="status" className="project-results-notice">{notice}</p>}
    {error && <p role="alert">{error} <button onClick={() => setRetryKey(value => value + 1)}>Retry</button></p>}
    {!busy && !error && currentPage && !groups.length && <p className="project-empty">No operator/customer groups match this search.</p>}
    {!error && (currentPage || previousPage) && <div className="customer-group-list">{groups.map(group => { const childPageCurrent = !children[group.id] || browsePageIsValid(children[group.id]); const displayedGroup = canUseChildren && childPageCurrent ? openedGroups[group.id] ?? group : group; return <section key={group.id} className="customer-group" aria-label={`${displayedGroup.name} customer group`}>
      <h2 className="customer-group-heading"><button className="customer-group-toggle" type="button" disabled={!canInteract} aria-expanded={canUseChildren && Boolean(expanded[group.id])} onClick={() => toggleGroup(group)}>
        <span><strong className="customer-group-name">{displayedGroup.name}</strong><small>{displayedGroup.role === 'operator' ? 'Operator' : displayedGroup.role === 'customer' ? 'Customer' : 'Operator/customer unresolved'}{displayedGroup.operator_number ? ` · Operator ${displayedGroup.operator_number}` : ''}</small></span>
        <span className="customer-group-count">{displayedGroup.project_count} {displayedGroup.project_count === 1 ? 'project' : 'projects'}</span>
        <svg className="customer-group-chevron" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m9 18 6-6-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
      </button></h2>
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
    {currentPage && currentPage.total > currentPage.limit && <footer className="project-paging"><span>{!busy && !error ? `${currentPage.offset + (groups.length ? 1 : 0)}–${currentPage.offset + groups.length} of ${currentPage.total} operator/customer groups` : ''}</span><button disabled={!canInteract || currentPage.offset === 0} onClick={() => { const n = Math.max(0, currentPage.offset - 25); setOffset(n); updateUrl(search, sector, n, currentPage.cohort_token) }}>Previous</button><button disabled={!canInteract || currentPage.offset + groups.length >= currentPage.total} onClick={() => { const n = currentPage.offset + 25; setOffset(n); updateUrl(search, sector, n, currentPage.cohort_token) }}>Next</button></footer>}
  </section>
}
function ProjectCard({ project, selectedNeedId, onNeed, nested = false }: { project: ProjectResult; selectedNeedId?: string; onNeed: Props['onNeed']; nested?: boolean }) {
  const primary = project.representative_need_id ?? project.needs[0]?.id
  const representative = project.needs.find(need => need.id === primary) ?? project.needs[0]
  const disposition = representative?.commercial_preview?.disposition
  const contacts = project.contact.filter(contact => /^(tel:|mailto:|https?:\/\/)/i.test(contact.href ?? ''))
  const people = project.contact_people ?? []
  const eventLabel = project.event?.label && project.event.date ? `${project.event.label} · ${project.event.date}` : project.event?.label
  const displayName = project.company && project.name.startsWith(`${project.company} · `) ? project.name.slice(project.company.length + 3) : project.name
  const call = contacts.find(contact => contact.kind === 'call' || contact.kind === 'phone' || contact.kind === 'tel')
  const nextAction = representative?.tier === 'Signal' && disposition === 'WATCH'
    ? 'Monitoring for verified power demand.'
    : representative?.tier === 'Signal' && disposition === 'ACTION NOW'
      ? call && (call.company || project.company) ? `Discuss project power plans with ${call.company || project.company}.` : 'Discovery call · Power need unconfirmed'
      : project.next_action
  const showPowerSummary = Boolean(project.power_summary && project.power_summary_kind !== 'unknown')
  return <article className="project-card" aria-current={selectedNeedId && project.needs.some(need => need.id === selectedNeedId) ? 'true' : undefined}>
    <div className="project-card-top"><span>{project.asset_type?.replaceAll('_', ' ') ?? (project.sector === 'oil_gas' ? 'Oil & Gas project' : project.sector === 'data_centers' ? 'Data center project' : 'Project')}</span>{project.sector && <span>{project.sector === 'oil_gas' ? 'Oil & Gas' : 'Data Centers'}</span>}</div>
    {representative?.tier && <div className="project-qualification"><span className="project-tier">{representative.tier}</span>{representative.tier === 'Signal' && disposition === 'ACTION NOW' && <span>Discovery call · Power need unconfirmed</span>}</div>}
    {nested ? <h3>{displayName}</h3> : <h2>{displayName}</h2>}{(project.company || project.location) && <p className="project-company">{[project.company, project.location].filter(Boolean).join(' · ')}</p>}
    {eventLabel && <p className="project-event">{eventLabel}</p>}
    {showPowerSummary && <p>{project.power_summary}</p>}
    {nextAction && <p className="project-next">{nextAction}</p>}
    {people.length > 0 && <div className="project-contact-people" aria-label="Source-supported project contacts">{people.map((person, index) => { const sourceUrl = /^https?:\/\//i.test(person.source_url ?? '') ? person.source_url : null; const role = (person.role ?? '').toLowerCase().replaceAll('_', ' '); const label = person.title?.trim() || (role === 'owner developer' || role === 'owner/developer' ? 'Listed owner contact' : 'Source-listed project contact'); return <div key={`${person.person_identity_id ?? person.name}-${index}`}><p><strong>{person.name}</strong>{` · ${label}`}{person.company ? ` · ${person.company}` : ''}</p>{person.responsibility && <p>{person.responsibility}</p>}<span>No verified direct method</span>{sourceUrl && <a href={sourceUrl} target="_blank" rel="noreferrer">Source</a>}</div> })}</div>}
    <div className="project-card-actions">{contacts.map((contact, index) => <a key={`${contact.kind}-${contact.href}-${index}`} href={contact.href!}>{contact.label}</a>)}{contacts.length === 0 && people.length === 0 && <span>Contact not yet verified</span>}{primary && <button type="button" onClick={() => onNeed({ id: primary })}>View project details</button>}</div>
    {project.need_count > 1 && <details className="project-needs"><summary>{project.need_count} related power needs</summary><ul>{project.needs.map(need => <li key={need.id}><button type="button" onClick={() => onNeed({ id: need.id })}>{String(need.activity ?? need.browse_title ?? 'Related project detail')}{need.location ? ` · ${String(need.location)}` : ''}</button></li>)}</ul></details>}
  </article>
}
